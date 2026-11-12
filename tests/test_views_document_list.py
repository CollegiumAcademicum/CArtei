import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils.timezone import make_aware

from app.models import (
    Building, DatenschutzDocument, Room, SepaLastschriftmandatDocument,
    Tenant, TenantRoomAssignment, WG, WohnungsgeberbescheinigungDocument,
)


def _tenant(n, uname):
    return Tenant.objects.create(
        first_name=f"F{n}", last_name=f"L{n}", email=f"{uname}@example.com",
        intranet_username=uname, intranet_uuid=f"00000000-0000-0000-0000-0000000004{n:02d}",
    )


def _user(uname, group=None):
    u = User.objects.create_user(username=uname, password="x")
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


@pytest.fixture
def data(db):
    subject = _tenant(1, "subj_dl")
    _tenant(2, "mv_dl"); _user("mv_dl", "ag.mietverwaltung")
    _tenant(3, "fin_dl"); _user("fin_dl", "cartei_finanzierung")
    _tenant(4, "plain_dl"); _user("plain_dl")
    now = make_aware(datetime.datetime(2026, 8, 1, 12, 0))

    ds = DatenschutzDocument.objects.create(
        tenant=subject, file_name="ds.pdf", file_data=b"x", uploaded_at=now,
        uploaded_by=subject, signed_at=datetime.date(2026, 8, 1),
    )
    sepa = SepaLastschriftmandatDocument.objects.create(
        tenant=subject, file_name="sepa.pdf", file_data=b"x", uploaded_at=now,
        uploaded_by=subject, signed_at=datetime.date(2026, 8, 1),
        mandatsreferenz="M1", kontoinhaber="K", bank_name="B", iban="DE1", bic="BIC",
    )
    # A revoked doc still belongs in the list (client filters it out by default).
    DatenschutzDocument.objects.create(
        tenant=subject, file_name="old.pdf", file_data=b"x", uploaded_at=now,
        uploaded_by=subject, signed_at=datetime.date(2026, 7, 1),
        revoked_at=now, revoked_by=subject, revoked_note="alt",
    )
    b = Building.objects.create(name="NB_DL")
    w = WG.objects.create(building=b, name="9.01")
    r = Room.objects.create(wg=w, name="9.01.1", size_sqm="11.00")
    a = TenantRoomAssignment.objects.create(tenant=subject, room=r, moved_in=datetime.date(2024, 9, 1))
    wgb = WohnungsgeberbescheinigungDocument.objects.create(
        assignment=a, file_name="wgb.pdf", file_data=b"x", uploaded_at=now,
        uploaded_by=subject, signed_at=datetime.date(2026, 8, 1), company_signed_by=subject,
    )
    return {"subject": subject, "ds": ds, "sepa": sepa, "wgb": wgb}


def _rows(client, uname):
    client.login(username=uname, password="x")
    resp = client.get(reverse("document_list"))
    assert resp.status_code == 200
    return resp.context["rows"]


def _types(rows):
    return {r["type_key"] for r in rows}


def test_mv_sees_all_types(client, data):
    types = _types(_rows(client, "mv_dl"))
    assert {"datenschutz", "sepa_lastschriftmandat", "wohnungsgeberbescheinigung"} <= types


def test_finanzierung_sees_only_sepa(client, data):
    assert _types(_rows(client, "fin_dl")) == {"sepa_lastschriftmandat"}


def test_plain_user_sees_nothing(client, data):
    assert _rows(client, "plain_dl") == []


def test_revoked_row_included_and_flagged(client, data):
    rows = [r for r in _rows(client, "mv_dl") if r["type_key"] == "datenschutz"]
    assert {r["revoked"] for r in rows} == {True, False}


def test_common_metadata_present(client, data):
    row = {r["type_key"]: r for r in _rows(client, "mv_dl")}["sepa_lastschriftmandat"]
    assert row["file_name"] == "sepa.pdf"
    assert row["uploaded_by"] == data["subject"]   # tenant object → template links it
    assert row["signed"] == "01.08.2026"


def test_sepa_detail_lists_structured_fields(client, data):
    row = {r["type_key"]: r for r in _rows(client, "fin_dl")}["sepa_lastschriftmandat"]
    assert ("IBAN", "DE1") in row["detail"]
    assert ("Mandatsreferenz", "M1") in row["detail"]


def test_assignment_detail_has_signer(client, data):
    row = {r["type_key"]: r for r in _rows(client, "mv_dl")}["wohnungsgeberbescheinigung"]
    assert ("GmbH-Unterzeichner*in", data["subject"]) in row["detail"]


def test_revoked_row_carries_revocation_fields(client, data):
    revoked = [r for r in _rows(client, "mv_dl")
               if r["type_key"] == "datenschutz" and r["revoked"]][0]
    assert revoked["revoked_note"] == "alt"
    assert revoked["revoked_by"] == data["subject"]
    assert revoked["revoked_at"] == "01.08.2026"


def test_download_url_points_to_download_view(client, data):
    rows = {r["type_key"]: r for r in _rows(client, "mv_dl")}
    assert rows["sepa_lastschriftmandat"]["download_url"] == reverse(
        "document_download",
        args=[data["sepa"].tenant_id, "sepa_lastschriftmandat", data["sepa"].pk],
    )
    assert rows["wohnungsgeberbescheinigung"]["download_url"] == reverse(
        "assignment_document_download",
        args=[data["wgb"].assignment_id, "wohnungsgeberbescheinigung", data["wgb"].pk],
    )


def test_ve_without_grant_is_ausstehend(client, data, django_assert_max_num_queries):
    from app.models import ClearanceAction, ConfidentialityClearanceEvent, VertraulichkeitserklaerungDocument
    now = make_aware(datetime.datetime(2026, 8, 1, 12, 0))

    def ve(name):
        return VertraulichkeitserklaerungDocument.objects.create(
            tenant=data["subject"], file_name=name, file_data=b"x", uploaded_at=now,
            uploaded_by=data["subject"], signed_at=datetime.date(2026, 8, 1),
        )
    pending, approved = ve("pending.pdf"), ve("approved.pdf")
    ConfidentialityClearanceEvent.objects.create(
        tenant=data["subject"], document=approved, action=ClearanceAction.GRANT, created_at=now,
    )
    rows = {r["file_name"]: r for r in _rows(client, "mv_dl")}
    assert rows["pending.pdf"]["pending"] and not rows["approved.pdf"]["pending"]
    assert not rows["ds.pdf"]["pending"]
    html = client.get(reverse("document_list")).content.decode()
    assert html.count(">Ausstehend</span>") == 1
    # One approved-ids query regardless of VE count: adding more VEs adds no queries.
    for i in range(5):
        ve(f"more{i}.pdf")
    with django_assert_max_num_queries(30) as ctx:
        client.get(reverse("document_list"))
    base = len(ctx.captured_queries)
    ve("one_more.pdf")
    with django_assert_max_num_queries(base):
        client.get(reverse("document_list"))
