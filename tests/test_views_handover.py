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


def _start(client, world, outgoing=None, incoming=None):
    data = {"room": world["room"].id}
    if outgoing is not None:
        data["outgoing_tenant"] = outgoing.id
    if incoming is not None:
        data["incoming_tenant"] = incoming.id
    return client.post("/uebergabe/start/", data)


def test_helper_can_start(client, world):
    _login(client, "helper", "cartei_helfer_mietverwaltung")
    r = _start(client, world)
    assert r.status_code == 302
    u = Uebergabe.objects.get()
    assert u.room_id == world["room"].id
    assert r.url == f"/uebergabe/{u.id}/step/?step=0"


def test_start_records_incoming_and_outgoing(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    out_t = Tenant.objects.create(first_name="Out", last_name="T",
                                  intranet_username="out_t", intranet_uuid=uuid.uuid4())
    in_t = Tenant.objects.create(first_name="In", last_name="T",
                                 intranet_username="in_t", intranet_uuid=uuid.uuid4())
    a = TenantRoomAssignment.objects.create(tenant=out_t, room=world["room"],
                                             moved_in=date(2026, 1, 1))
    r = _start(client, world, outgoing=out_t, incoming=in_t)
    assert r.status_code == 302
    u = Uebergabe.objects.get()
    assert u.assignment_id == a.id            # outgoing assignment resolved
    assert u.incoming_tenant_id == in_t.id
    # record-only: no assignment was created or moved out
    assert TenantRoomAssignment.objects.count() == 1
    a.refresh_from_db()
    assert a.moved_out is None


def test_start_requires_room(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    r = client.post("/uebergabe/start/", {})
    assert r.status_code == 200          # form re-rendered
    assert Uebergabe.objects.count() == 0


def test_start_rejects_same_tenant(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    t = Tenant.objects.create(first_name="Same", last_name="T",
                              intranet_username="same_t", intranet_uuid=uuid.uuid4())
    r = _start(client, world, outgoing=t, incoming=t)
    assert r.status_code == 200
    assert Uebergabe.objects.count() == 0


def test_start_outgoing_without_assignment_sets_null(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    out_t = Tenant.objects.create(first_name="No", last_name="Assign",
                                  intranet_username="noass", intranet_uuid=uuid.uuid4())
    r = _start(client, world, outgoing=out_t)   # out_t has no assignment on this room
    assert r.status_code == 302
    assert Uebergabe.objects.get().assignment_id is None


def test_start_get_ignores_bad_room_param(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    for bad in ("", "abc", "99999"):
        r = client.get(f"/uebergabe/start/?room={bad}")
        assert r.status_code == 200


def test_resident_cannot_start(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = _start(client, world)
    assert r.status_code == 403
    assert Uebergabe.objects.count() == 0


def test_resident_cannot_open_start(client, world):
    _login(client, "resi")
    assert client.get("/uebergabe/start/").status_code == 403


def test_belegium_cannot_start(client, world):
    _login(client, "beleg", "gr.belegium")
    assert _start(client, world).status_code == 403


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


def test_step_lists_existing_open_damages(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    t = Tenant.objects.get(intranet_username="mv")
    kind, line = STEPS[0]            # first room line
    RoomDamage.objects.create(room=world["room"], line=line,
                              created_at=tz_now(), created_by=t)           # open
    RoomDamage.objects.create(room=world["room"], line=line,
                              created_at=tz_now(), created_by=t,
                              fixed_at=tz_now(), fixed_by=t)                # fixed
    _start(client, world)
    u = Uebergabe.objects.get()
    r = client.get(f"/uebergabe/{u.id}/step/?step=0")
    assert r.status_code == 200
    assert len(r.context["existing"]) == 1     # only the open one
