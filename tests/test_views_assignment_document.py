import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from app.models import (
    Building, MietbedingungenDocument, MietvertragDocument, Room, Tenant,
    TenantRoomAssignment, WG,
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


def _upload_mietbedingungen(client, assignment):
    data = {
        "document_type": "mietbedingungen",
        "signed_at": "2026-08-01",
        "document_file": SimpleUploadedFile("m.pdf", b"%PDF-1.4 m", content_type="application/pdf"),
    }
    return client.post(reverse("assignment_document_upload", args=[assignment.pk]), data)


def test_mv_upload_mietbedingungen(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_mietbedingungen(client, setup["assignment"])
    doc = MietbedingungenDocument.objects.get(assignment=setup["assignment"])
    assert doc.signed_at == datetime.date(2026, 8, 1)
    assert doc.uploaded_by_id == setup["mv"].pk


def test_mv_upload_mietvertrag_with_company_signer(client, setup):
    client.login(username="mv_adoc", password="x")
    data = {
        "document_type": "mietvertrag",
        "renter_signed_at": "2026-08-01",
        "company_signed_at": "2026-08-03",
        "company_signed_by": str(setup["mv"].pk),
        "document_file": SimpleUploadedFile("v.pdf", b"%PDF-1.4 v", content_type="application/pdf"),
    }
    client.post(reverse("assignment_document_upload", args=[setup["assignment"].pk]), data)
    doc = MietvertragDocument.objects.get(assignment=setup["assignment"])
    assert doc.company_signed_by_id == setup["mv"].pk
    assert doc.renter_signed_at == datetime.date(2026, 8, 1)


def test_tenant_cannot_upload(client, setup):
    client.login(username="ten_adoc", password="x")
    resp = _upload_mietbedingungen(client, setup["assignment"])
    assert resp.status_code == 403
    assert not MietbedingungenDocument.objects.exists()


def test_owner_can_download_other_cannot(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_mietbedingungen(client, setup["assignment"])
    doc = MietbedingungenDocument.objects.get(assignment=setup["assignment"])
    url = reverse("assignment_document_download",
                  args=[setup["assignment"].pk, "mietbedingungen", doc.pk])

    client.login(username="ten_adoc", password="x")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4 m"

    client.login(username="oth_adoc", password="x")
    assert client.get(url).status_code == 403


def test_revoke_sets_fields_and_blocks_second(client, setup):
    client.login(username="mv_adoc", password="x")
    _upload_mietbedingungen(client, setup["assignment"])
    doc = MietbedingungenDocument.objects.get(assignment=setup["assignment"])
    url = reverse("assignment_document_revoke",
                  args=[setup["assignment"].pk, "mietbedingungen", doc.pk])
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
    _upload_mietbedingungen(client, setup["assignment"])
    doc = MietbedingungenDocument.objects.get(assignment=setup["assignment"])
    resp = client.post(
        reverse("assignment_document_revoke",
                args=[setup["assignment"].pk, "mietbedingungen", doc.pk]),
        {"revoked_note": "  "},
    )
    assert resp.status_code == 400
    doc.refresh_from_db()
    assert doc.revoked_at is None
