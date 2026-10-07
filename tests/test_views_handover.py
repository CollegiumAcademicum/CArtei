import uuid
import pytest
from datetime import date
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import now as tz_now

from app.models import (
    Building, WG, Room, Tenant, TenantRoomAssignment,
    RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, Uebergabe,
)
from app.handover import STEPS

PNG = b"\x89PNG\r\n\x1a\n" + b"rest"


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    return {"wg": wg, "room": room}


def _login(client, username, group=None):
    u = User.objects.create_user(username=username, password="x")
    if group:
        g, _ = Group.objects.get_or_create(name=group)
        u.groups.add(g)
    Tenant.objects.create(first_name=username, last_name="T",
                          email=f"{username}@example.invalid", phone="1",
                          intranet_username=username, intranet_uuid=uuid.uuid4(),
                          profile_setup_completed_at=tz_now())
    client.force_login(u)
    return u


def _start(client, world):
    return client.post(f"/wgs/{world['wg'].id}/rooms/{world['room'].id}/uebergabe/start/")


def test_helper_can_start(client, world):
    _login(client, "helper", "cartei_helfer_mietverwaltung")
    r = _start(client, world)
    assert r.status_code == 302
    u = Uebergabe.objects.get()
    assert u.room_id == world["room"].id
    assert r.url == f"/uebergabe/{u.id}/step/?step=0"


def test_resident_cannot_start(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = _start(client, world)
    assert r.status_code == 403
    assert Uebergabe.objects.count() == 0


def test_belegium_cannot_start(client, world):
    _login(client, "beleg", "gr.belegium")
    assert _start(client, world).status_code == 403


def test_start_room_wg_mismatch_404(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    other = WG.objects.create(building=world["wg"].building, name="OTHER")
    r = client.post(f"/wgs/{other.id}/rooms/{world['room'].id}/uebergabe/start/")
    assert r.status_code == 404
    assert Uebergabe.objects.count() == 0


def test_helper_add_room_damage_through_wizard(client, world):
    _login(client, "helper", "cartei_helfer_mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    # step 0 is the first room line
    kind, line = STEPS[0]
    assert kind == "room"
    r = client.post(f"/uebergabe/{u.id}/damage/?step=0",
                    {"size": "LT1", "note": "Kratzer"})
    assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/step/?step=1"
    d = RoomDamage.objects.get()
    assert d.line == line and d.room_id == world["room"].id
    assert d.created_by.intranet_username == "helper"


def test_wizard_add_wg_damage_on_wg_step(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    wg_step = len(RoomDamageLine.values)  # first wg step
    kind, line = STEPS[wg_step]
    assert kind == "wg"
    client.post(f"/uebergabe/{u.id}/damage/?step={wg_step}", {})
    d = WGDamage.objects.get()
    assert d.line == line and d.wg_id == world["wg"].id


def test_bad_step_redirects_to_recap(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    for bad in ("999", "-1", "abc"):
        r = client.get(f"/uebergabe/{u.id}/step/?step={bad}")
        assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/"


def test_bad_photo_no_damage_stays_on_step(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    r = client.post(f"/uebergabe/{u.id}/damage/?step=0",
                    {"photo": SimpleUploadedFile("evil.png", b"<html>", content_type="image/png")})
    assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/step/?step=0"
    assert RoomDamage.objects.count() == 0


def test_complete_sets_timestamp(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    r = client.post(f"/uebergabe/{u.id}/complete/")
    assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/"
    u.refresh_from_db()
    assert u.completed_at is not None
