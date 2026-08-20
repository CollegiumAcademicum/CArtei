import datetime
import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from app.models import (Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll,
                        UebergabeProtokollDocument, WG)

@pytest.fixture
def protocol(db):
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="helper",
                              intranet_uuid=uuid.uuid4())
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))
    return UebergabeProtokoll.objects.create(assignment=a, protocol_type="AUSZUG",
                                             created_at=datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc))

@pytest.fixture
def helper(db):
    u = User.objects.create_user("helper", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    return u

@pytest.mark.django_db
def test_scan_upload_and_download(client, protocol, helper):
    client.force_login(helper)
    f = SimpleUploadedFile("scan.pdf", b"%PDF-1.4 data", content_type="application/pdf")
    resp = client.post(reverse("uebergabe_scan_upload", args=[protocol.pk]), {"document_file": f})
    assert resp.status_code in (302, 200)
    doc = UebergabeProtokollDocument.objects.get(protocol=protocol)
    dl = client.get(reverse("uebergabe_scan_download", args=[protocol.pk, doc.pk]))
    assert dl.status_code == 200 and b"%PDF" in dl.getvalue()


def _upload(client, protocol):
    f = SimpleUploadedFile("scan.pdf", b"%PDF-1.4 data", content_type="application/pdf")
    client.post(reverse("uebergabe_scan_upload", args=[protocol.pk]), {"document_file": f})
    return UebergabeProtokollDocument.objects.get(protocol=protocol)


@pytest.mark.django_db
def test_scan_revoke(client, protocol, helper):
    client.force_login(helper)
    doc = _upload(client, protocol)
    resp = client.post(reverse("uebergabe_scan_revoke", args=[protocol.pk, doc.pk]),
                       {"revoked_note": "Falsch gescannt"})
    assert resp.status_code == 302
    doc.refresh_from_db()
    assert doc.revoked_at is not None and doc.revoked_note == "Falsch gescannt"


@pytest.mark.django_db
def test_scan_revoke_requires_note(client, protocol, helper):
    client.force_login(helper)
    doc = _upload(client, protocol)
    resp = client.post(reverse("uebergabe_scan_revoke", args=[protocol.pk, doc.pk]), {"revoked_note": "  "})
    assert resp.status_code == 302
    doc.refresh_from_db()
    assert doc.revoked_at is None


@pytest.mark.django_db
def test_scan_double_revoke_no_500(client, protocol, helper):
    client.force_login(helper)
    doc = _upload(client, protocol)
    client.post(reverse("uebergabe_scan_revoke", args=[protocol.pk, doc.pk]), {"revoked_note": "erst"})
    resp = client.post(reverse("uebergabe_scan_revoke", args=[protocol.pk, doc.pk]), {"revoked_note": "nochmal"})
    assert resp.status_code == 302


@pytest.mark.django_db
def test_revoke_caller_none_returns_400(client, protocol, db):
    """User with permission but no matching Tenant row must get 400, not 500."""
    u = User.objects.create_user("notenantuser", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung_notenant"))
    # Wire the permission group the view checks by adding the real group name.
    from django.contrib.auth.models import Group as G
    g, _ = G.objects.get_or_create(name="cartei_helfer_mietverwaltung")
    u.groups.add(g)
    client.force_login(u)
    # Upload a doc as the regular helper first (reuse protocol fixture's Tenant).
    from django.contrib.auth.models import User as U
    helper_u = U.objects.create_user("helper", password="x")
    helper_u.groups.add(g)
    client.force_login(helper_u)
    f = SimpleUploadedFile("scan.pdf", b"%PDF-1.4 data", content_type="application/pdf")
    client.post(reverse("uebergabe_scan_upload", args=[protocol.pk]), {"document_file": f})
    doc = UebergabeProtokollDocument.objects.get(protocol=protocol)
    # Now switch to the user with no Tenant row and try to revoke.
    client.force_login(u)
    resp = client.post(reverse("uebergabe_scan_revoke", args=[protocol.pk, doc.pk]),
                       {"revoked_note": "test"})
    assert resp.status_code == 400
