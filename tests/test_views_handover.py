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


_DEFAULT = object()


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    t = Tenant.objects.create(first_name="Res", last_name="Ident",
                              intranet_username="res_ident", intranet_uuid=uuid.uuid4())
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2026, 1, 1))
    return {"wg": wg, "room": room, "tenant": t, "assignment": a}


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


def _start(client, world, outgoing=_DEFAULT, incoming=None):
    """POST the start form for world's room. Defaults outgoing to world's
    assignment so most tests get a valid handover; pass outgoing=None to omit."""
    out_a = world["assignment"] if outgoing is _DEFAULT else outgoing
    data = {}
    if out_a is not None:
        data["outgoing_assignment"] = out_a.id
    if incoming is not None:
        data["incoming_assignment"] = incoming.id
    return client.post(f"/uebergabe/start/?room={world['room'].id}", data)


def test_helper_can_start(client, world):
    _login(client, "helper", "cartei_helfer_mietverwaltung")
    r = _start(client, world)
    assert r.status_code == 302
    u = Uebergabe.objects.get()
    assert u.room_id == world["room"].id
    assert u.outgoing_assignment_id == world["assignment"].id
    assert r.url == f"/uebergabe/{u.id}/step/?step=0"


def test_start_links_both_assignments(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    in_t = Tenant.objects.create(first_name="In", last_name="T",
                                 intranet_username="in_t", intranet_uuid=uuid.uuid4())
    in_a = TenantRoomAssignment.objects.create(tenant=in_t, room=world["room"],
                                               moved_in=date(2026, 7, 1))
    r = _start(client, world, outgoing=world["assignment"], incoming=in_a)
    assert r.status_code == 302
    u = Uebergabe.objects.get()
    assert u.outgoing_assignment_id == world["assignment"].id
    assert u.incoming_assignment_id == in_a.id
    # record-only: no assignment created or moved out
    assert TenantRoomAssignment.objects.count() == 2
    world["assignment"].refresh_from_db()
    assert world["assignment"].moved_out is None


def test_start_incoming_only(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    in_t = Tenant.objects.create(first_name="In", last_name="T",
                                 intranet_username="in_t", intranet_uuid=uuid.uuid4())
    in_a = TenantRoomAssignment.objects.create(tenant=in_t, room=world["room"],
                                               moved_in=date(2026, 7, 1))
    r = _start(client, world, outgoing=None, incoming=in_a)
    assert r.status_code == 302
    u = Uebergabe.objects.get()
    assert u.outgoing_assignment_id is None and u.incoming_assignment_id == in_a.id


def test_start_rejects_neither_side(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    r = _start(client, world, outgoing=None, incoming=None)
    assert r.status_code == 200
    assert Uebergabe.objects.count() == 0


def test_start_rejects_same_assignment_both_sides(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    r = _start(client, world, outgoing=world["assignment"], incoming=world["assignment"])
    assert r.status_code == 200
    assert Uebergabe.objects.count() == 0


def test_start_rejects_foreign_room_assignment(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    other_room = Room.objects.create(wg=world["wg"], name="1.02", size_sqm=12)
    foreign = TenantRoomAssignment.objects.create(
        tenant=world["tenant"], room=other_room, moved_in=date(2026, 1, 1))
    # assignment belongs to another room → not in the scoped queryset → invalid
    r = _start(client, world, outgoing=foreign)
    assert r.status_code == 200
    assert Uebergabe.objects.count() == 0


def test_start_no_room_shows_picker(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    r = client.get("/uebergabe/start/")
    assert r.status_code == 200
    assert Uebergabe.objects.count() == 0


def test_start_get_ignores_bad_room_param(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    for bad in ("", "abc", "99999"):
        r = client.get(f"/uebergabe/start/?room={bad}")
        assert r.status_code == 200


def test_resident_cannot_start(client, world):
    _login(client, "resi")
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
    # step 0 is the whole Zimmer; the client picks the category line
    line = RoomDamageLine.values[0]
    r = client.post(f"/uebergabe/{u.id}/damage/?step=0",
                    {"line": line, "size": "LT1", "note": "Kratzer"})
    # adding stays on the same step so more categories can be recorded
    assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/step/?step=0"
    d = RoomDamage.objects.get()
    assert d.line == line and d.room_id == world["room"].id
    assert d.created_by.intranet_username == "helper"


def test_wizard_add_wg_damage_on_wg_step(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    kind, area, lines = STEPS[1]   # first WG area (Bad)
    assert kind == "wg"
    line = lines[0]
    r = client.post(f"/uebergabe/{u.id}/damage/?step=1", {"line": line})
    assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/step/?step=1"
    d = WGDamage.objects.get()
    assert d.line == line and d.wg_id == world["wg"].id


def test_damage_line_outside_step_area_rejected(client, world):
    _login(client, "mv", "ag.mietverwaltung")
    _start(client, world)
    u = Uebergabe.objects.get()
    # step 0 is the Zimmer; a WG line does not belong here → nothing created
    r = client.post(f"/uebergabe/{u.id}/damage/?step=0",
                    {"line": WGDamageLine.values[0]})
    assert r.status_code == 302 and r.url == f"/uebergabe/{u.id}/step/?step=0"
    assert RoomDamage.objects.count() == 0 and WGDamage.objects.count() == 0


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
                    {"line": RoomDamageLine.values[0],
                     "photo": SimpleUploadedFile("evil.png", b"<html>", content_type="image/png")})
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
    line = RoomDamageLine.values[0]
    RoomDamage.objects.create(room=world["room"], line=line,
                              created_at=tz_now(), created_by=t)           # open
    RoomDamage.objects.create(room=world["room"], line=line,
                              created_at=tz_now(), created_by=t,
                              fixed_at=tz_now(), fixed_by=t)                # fixed
    _start(client, world)
    u = Uebergabe.objects.get()
    r = client.get(f"/uebergabe/{u.id}/step/?step=0")
    assert r.status_code == 200
    # categories: list of (line, label, [open damages]) for the step's area
    open_by_line = {c[0]: c[2] for c in r.context["categories"]}
    assert len(open_by_line[line]) == 1     # only the open one
