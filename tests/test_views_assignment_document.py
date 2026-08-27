import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from app.models import (
    Building, Room, Tenant, TenantRoomAssignment, WG,
    WohnungsgeberbescheinigungDocument,
)


@pytest.fixture
def setup(db):
    mv = Tenant.objects.create(
        first_name="MV", last_name="Verw", email="mv@example.com",
        intranet_username="mv_adoc", intranet_uuid="00000000-0000-0000-0000-000000000201",
    )
    u = User.objects.create_user(username="mv_adoc", password="x")
    u.groups.add(Group.objects.get_or_create(name="ag.mietverwaltung")[0])

    tenant = Tenant.objects.create(
        first_name="Ten", last_name="Ant", email="ten@example.com",
        intranet_username="ten_adoc", intranet_uuid="00000000-0000-0000-0000-000000000202",
    )
    User.objects.create_user(username="ten_adoc", password="x")

    other = Tenant.objects.create(
        first_name="Oth", last_name="Er", email="oth@example.com",
        intranet_username="oth_adoc", intranet_uuid="00000000-0000-0000-0000-000000000203",
    )
    User.objects.create_user(username="oth_adoc", password="x")

    b = Building.objects.create(name="NB_ADOC")
    w = WG.objects.create(building=b, name="4.03")
    r = Room.objects.create(wg=w, name="4.03.1", size_sqm="11.00")
    a = TenantRoomAssignment.objects.create(
        tenant=tenant, room=r, moved_in=datetime.date(2024, 9, 1)
    )
    return {"mv": mv, "tenant": tenant, "other": other, "assignment": a}


def _upload_wgb(client, setup, **overrides):
    data = {
        "document_type": "wohnungsgeberbescheinigung",
        "signed_at": "2026-08-01",
        "company_signed_by": str(setup["mv"].pk),
        "document_file": SimpleUploadedFile("m.pdf", b"%PDF-1.4 m", content_type="application/pdf"),
    }
    data.update(overrides)
    return client.post(reverse("assignment_document_upload", args=[setup["assignment"].pk]), data)


def test_mv_upload_wohnungsgeberbescheinigung(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_wgb(client, setup)
    doc = WohnungsgeberbescheinigungDocument.objects.get(assignment=setup["assignment"])
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.company_signed_by_id == setup["mv"].pk
    assert doc.uploaded_by_id == setup["mv"].pk


def test_tenant_cannot_upload(client, setup):
    client.login(username="ten_adoc", password="x")
    resp = _upload_wgb(client, setup)
    assert resp.status_code == 403
    assert not WohnungsgeberbescheinigungDocument.objects.exists()


def test_owner_can_download_other_cannot(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_wgb(client, setup)
    doc = WohnungsgeberbescheinigungDocument.objects.get(assignment=setup["assignment"])
    url = reverse("assignment_document_download",
                  args=[setup["assignment"].pk, "wohnungsgeberbescheinigung", doc.pk])

    client.login(username="ten_adoc", password="x")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 m"

    client.login(username="oth_adoc", password="x")
    assert client.get(url).status_code == 403


def test_revoke_sets_fields_and_blocks_second(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_wgb(client, setup)
    doc = WohnungsgeberbescheinigungDocument.objects.get(assignment=setup["assignment"])
    url = reverse("assignment_document_revoke",
                  args=[setup["assignment"].pk, "wohnungsgeberbescheinigung", doc.pk])
    client.post(url, {"revoked_note": "Widerruf"})
    doc.refresh_from_db()
    assert doc.revoked_at is not None
    assert doc.revoked_by_id == setup["mv"].pk
    # Second revoke is a no-op (view guards; DB trigger absent under SQLite).
    client.post(url, {"revoked_note": "nochmal"})
    doc.refresh_from_db()
    assert doc.revoked_note == "Widerruf"


def test_revoke_without_note_rejected(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_wgb(client, setup)
    doc = WohnungsgeberbescheinigungDocument.objects.get(assignment=setup["assignment"])
    resp = client.post(
        reverse("assignment_document_revoke",
                args=[setup["assignment"].pk, "wohnungsgeberbescheinigung", doc.pk]),
        {"revoked_note": "  "},
    )
    assert resp.status_code == 400
    doc.refresh_from_db()
    assert doc.revoked_at is None


def test_upload_honors_safe_next(client, setup):
    client.login(username="mv_adoc", password="x")
    wg_path = reverse("wg_detail", args=[setup["assignment"].room.wg_id])
    resp = _upload_wgb(client, setup, next=wg_path)
    assert resp.status_code == 302
    assert resp["Location"] == wg_path


def test_upload_rejects_offsite_next(client, setup):
    client.login(username="mv_adoc", password="x")
    resp = _upload_wgb(client, setup, next="https://evil.example.com/")
    assert resp.status_code == 302
    assert resp["Location"] == reverse("tenant_detail", args=[setup["tenant"].pk])
