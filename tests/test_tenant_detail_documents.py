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
