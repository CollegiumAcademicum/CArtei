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
