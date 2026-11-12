import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import DatenschutzDocument, MietvertragDocument, Tenant


@pytest.fixture
def owner(db):
    t = Tenant.objects.create(
        first_name="Owner", last_name="Doc", email="od@example.com",
        intranet_username="owner_dd", intranet_uuid="00000000-0000-0000-0000-000000000020",
    )
    User.objects.create_user(username="owner_dd", password="x")
    return t


def test_detail_lists_document(client, owner):
    DatenschutzDocument.objects.create(
        tenant=owner, file_name="d.pdf",
        file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=owner,
    )
    client.login(username="owner_dd", password="x")
    html = client.get(reverse("tenant_detail", args=[owner.pk])).content.decode()
    assert "Datenschutz" in html
    assert "d.pdf" in html


def test_detail_lists_mietvertrag_in_rechtsdokumente(client, owner):
    # Mietvertrag now lives in the per-tenant Rechtsdokumente section, keyed on
    # the person, and renders its two-party signing info (not a single signed_at).
    MietvertragDocument.objects.create(
        tenant=owner, file_name="v.pdf", file_data=b"x",
        renter_signed_at=datetime.date(2026, 8, 1),
        company_signed_at=datetime.date(2026, 8, 3), company_signed_by=owner,
        uploaded_at=datetime.datetime(2026, 8, 4, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=owner,
    )
    client.login(username="owner_dd", password="x")
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    groups = {g["type"]: g for g in resp.context["document_groups"]}
    assert groups["mietvertrag"]["has_active"] is True
    assert "mietbedingungen" in groups
    html = resp.content.decode()
    assert "v.pdf" in html
    assert "Mieter*in 01.08.2026" in html


def test_detail_shows_missing_type_when_no_active_doc(client, owner):
    # Owner has a Datenschutz doc but no Fotoerlaubnis -> Fotoerlaubnis is missing.
    DatenschutzDocument.objects.create(
        tenant=owner, file_name="d.pdf", file_data=b"x",
        signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=owner,
    )
    client.login(username="owner_dd", password="x")
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    groups = {g["type"]: g for g in resp.context["document_groups"]}
    assert groups["datenschutz"]["has_active"] is True
    assert groups["photoerlaubnis"]["has_active"] is False
    assert "Noch nicht unterschrieben" in resp.content.decode()


def test_header_renders_a_pill_per_document_group(client, owner):
    # The Rechtsdokumente header uses short pills (like the tenants list); every
    # document group must carry a short code and render a pill.
    DatenschutzDocument.objects.create(
        tenant=owner, file_name="d.pdf", file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=datetime.datetime(2026, 8, 2, 9, 0, tzinfo=datetime.timezone.utc),
        uploaded_by=owner,
    )
    client.login(username="owner_dd", password="x")
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    groups = resp.context["document_groups"]
    assert all(g.get("short") for g in groups)
    html = resp.content.decode()
    for g in groups:
        assert f">{g['short']}</span>" in html
    # Datenschutz present -> green pill; a not-yet-signed type -> red pill.
    assert "ca-pill-green" in html
    assert "ca-pill-red" in html


def test_finanzierung_sees_only_sepa_group(client, owner):
    # AG Finanzierung may read SEPA and nothing else — the documents section
    # renders only the SEPA group, no consent/Mietvertrag documents.
    User.objects.create_user(username="fin_dd", password="x").groups.add(
        Group.objects.get_or_create(name="ag.finanzierung")[0]
    )
    client.login(username="fin_dd", password="x")
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    assert resp.context["can_see_documents"] is True
    types = {g["type"] for g in resp.context["document_groups"]}
    assert types == {"sepa_lastschriftmandat"}
    # No upload/revoke controls for a read-only reader.
    assert resp.context.get("can_manage_documents") is False


# --- Vertraulichkeitserklärung / confidentiality_clearance (#65) -------------

from django.utils.timezone import now  # noqa: E402

from app import clearance  # noqa: E402
from app.models import (  # noqa: E402
    ClearanceAction, ConfidentialityClearanceEvent, VertraulichkeitserklaerungDocument,
)


def _grouped_user(username, group):
    Tenant.objects.create(
        first_name=username, last_name="Viewer", email=f"{username}@example.com",
        intranet_username=username, intranet_uuid=f"00000000-0000-0000-0000-0000000{len(username):05d}",
    )
    u = User.objects.create_user(username=username, password="x")
    u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


@pytest.fixture
def granter_user(db):
    return _grouped_user("granter_dd", "cartei_grant_clearance")


@pytest.fixture
def mv_user(db):
    return _grouped_user("mv_dd", "cartei_mietverwaltung")


def _ve(tenant, approved=False):
    doc = VertraulichkeitserklaerungDocument.objects.create(
        tenant=tenant, file_name="ve.pdf", file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=now(), uploaded_by=tenant,
    )
    if approved:
        ConfidentialityClearanceEvent.objects.create(
            tenant=tenant, document=doc, action=ClearanceAction.GRANT, created_at=now()
        )
    return doc


def _html(client, user, tenant):
    client.force_login(user)
    resp = client.get(reverse("tenant_detail", args=[tenant.pk]))
    assert resp.status_code == 200
    return resp.content.decode()


def test_granter_sees_only_ve_card(client, owner, granter_user):
    client.force_login(granter_user)
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    html = resp.content.decode()
    assert 'id="section-documents"' in html
    assert {g["type"] for g in resp.context["document_groups"]} == {"vertraulichkeitserklaerung"}
    section = html.split('id="section-documents"', 1)[1].split("</details>", 1)[0]
    assert "Vertraulichkeitserklärung" in section
    assert "Datenschutz" not in section


@pytest.mark.parametrize("approved, pending, in_group, color", [
    (True, False, True, "green"),
    (False, True, False, "yellow"),
    (True, False, False, "black"),
    (False, False, False, "red"),
])
def test_ve_pill_colours(client, owner, granter_user, monkeypatch, approved, pending, in_group, color):
    monkeypatch.setattr("app.clearance.is_clearance_member", lambda u: in_group)
    if approved or pending:
        _ve(owner, approved=approved)
    html = _html(client, granter_user, owner)
    assert f"ca-pill-{color}" in html
    assert clearance.tooltip(color) in html  # summary pill
    assert 'aria-label="Was bedeuten die Farben?"' in html
    for name, text in clearance.LEGEND:
        assert f"{name}:</strong> {text}" in html


def test_ve_has_active_only_when_approved(client, owner, granter_user):
    _ve(owner)
    client.force_login(granter_user)
    resp = client.get(reverse("tenant_detail", args=[owner.pk]))
    (g,) = resp.context["document_groups"]
    assert g["has_active"] is False
    assert "Ausstehend" in resp.content.decode()


def test_ldap_down_renders_unknown(client, owner, granter_user, monkeypatch):
    monkeypatch.setattr("app.clearance.is_clearance_member", lambda u: None)
    html = _html(client, granter_user, owner)
    assert "ca-pill-unknown" in html


def test_grant_button_only_for_granter(client, owner, granter_user, mv_user):
    _ve(owner)
    html = _html(client, mv_user, owner)
    assert "clearance-dialog" not in html
    html = _html(client, granter_user, owner)
    assert 'id="clearance-dialog"' in html
    assert "data-pip-src" in html
    assert "Bestätigen" in html


def test_grant_button_disabled_without_account(client, granter_user):
    no_account = Tenant.objects.create(first_name="Kein", last_name="Konto", email="kk@example.com")
    _ve(no_account)
    html = _html(client, granter_user, no_account)
    assert "Noch kein Intranet-Account – zuerst provisionieren" in html
    assert "disabled" in html


def test_impersonating_granter_cannot_grant_or_revoke_approved(client, owner, granter_user):
    from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP

    approved, pending = _ve(owner, approved=True), _ve(owner)
    real = _grouped_user("imp_dd", IMPERSONATION_GROUP)
    client.force_login(real)
    session = client.session
    session[IMPERSONATED_USER_SESSION_KEY] = granter_user.pk
    session.save()
    html = client.get(reverse("tenant_detail", args=[owner.pk])).content.decode()
    assert "clearance-dialog" not in html
    revoke = lambda d: reverse("document_revoke", args=[owner.pk, "vertraulichkeitserklaerung", d.pk])  # noqa: E731
    assert revoke(approved) not in html
    assert revoke(pending) in html


def test_approved_ve_revoke_warns_about_group(client, owner, granter_user):
    _ve(owner, approved=True)
    html = _html(client, granter_user, owner)
    from django.conf import settings

    from app.ldap_utils import _dn_to_cn
    assert f"entzieht {_dn_to_cn(settings.LDAP_REQUIRE_GROUP)} und" in html
    assert "allen internen Plattformen (und CArtei)" in html


def test_granter_sees_real_name_on_ve_card(client, granter_user):
    t = Tenant.objects.create(
        first_name="Echter", last_name="Name", preferred_name="Spitzname", email="en@example.com",
        intranet_username="echt_n", intranet_uuid="00000000-0000-0000-0000-000000000077",
    )
    html = _html(client, granter_user, t)
    section = html.split('id="section-documents"', 1)[1].split("</details>", 1)[0]
    assert "Name: Echter Name" in section


def test_non_granter_reader_sees_no_name_line(client, owner):
    _ve(owner)
    mv = _grouped_user("mv_real", "ag.mietverwaltung")
    section = _html(client, mv, owner).split('id="section-documents"', 1)[1]
    assert "Vertraulichkeitserklärung" in section
    assert "Name: Owner Doc" not in section


def test_ve_row_shows_uploader(client, owner, granter_user):
    uploader = Tenant.objects.create(
        first_name="Up", last_name="Loader", preferred_name="Uppi", email="up@example.com",
    )
    VertraulichkeitserklaerungDocument.objects.create(
        tenant=owner, file_name="ve.pdf", file_data=b"x", signed_at=datetime.date(2026, 8, 1),
        uploaded_at=now(), uploaded_by=uploader,
    )
    assert "· hochgeladen von Uppi" in _html(client, granter_user, owner)


def test_grant_dialog_name_is_stripped(client, granter_user):
    t = Tenant.objects.create(
        first_name=" Max ", last_name="Muster  ", email="ws@example.com",
        intranet_username="max_ws_d", intranet_uuid="00000000-0000-0000-0000-000000000078",
    )
    _ve(t)
    html = _html(client, granter_user, t)
    assert 'data-name="Max Muster"' in html
    assert "<strong>Max Muster</strong>" in html
