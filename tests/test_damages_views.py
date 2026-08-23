import uuid
import pytest
from datetime import date
from django.contrib.auth.models import User, Group
from django.utils.timezone import now

from app.models import (
    Building, WG, Room, Tenant, TenantRoomAssignment,
    RoomDamage, WGDamage, RoomDamageLine, WGDamageLine,
)


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
    Tenant.objects.create(first_name=username, last_name="T", intranet_username=username, intranet_uuid=uuid.uuid4())
    client.force_login(u)
    return u


def test_staff_add_room_damage(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.WAND_LOECHER, "size": "LT1", "note": "x", "next": "/"},
    )
    assert r.status_code == 302
    assert RoomDamage.objects.filter(room=world["room"], line=RoomDamageLine.WAND_LOECHER).count() == 1


def test_resident_add_own_room(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/"},
    )
    assert r.status_code == 302
    assert RoomDamage.objects.filter(room=world["room"]).count() == 1


def test_nonresident_add_denied(client, world):
    _login(client, "stranger")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/"},
    )
    assert r.status_code == 403
    assert RoomDamage.objects.count() == 0


def test_belegium_add_denied(client, world):
    _login(client, "beleg", "gr.belegium")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/"},
    )
    assert r.status_code == 403
    assert RoomDamage.objects.count() == 0


def test_invalid_line_rejected(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": "NOT_A_LINE", "next": "/"},
    )
    assert r.status_code == 403
    assert RoomDamage.objects.count() == 0


def test_fix_and_reopen_staff_only(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    d = RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN, created_at=now(), created_by=t,
    )
    # resident cannot fix
    r = client.post(f"/damages/room/{d.id}/fix/", {"next": "/"})
    assert r.status_code == 403
    assert RoomDamage.objects.get(pk=d.id).fixed_at is None
    # staff can fix — use "ag.mietverwaltung" (the real TENANT_ROLE_GROUPS key for mietverwaltung)
    _login(client, "mv_staff", "ag.mietverwaltung")
    client.post(f"/damages/room/{d.id}/fix/", {"next": "/"})
    assert RoomDamage.objects.get(pk=d.id).fixed_at is not None
    # staff can reopen
    client.post(f"/damages/room/{d.id}/fix/", {"next": "/"})
    assert RoomDamage.objects.get(pk=d.id).fixed_at is None


def test_staff_add_wg_damage(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.post(
        f"/wgs/{world['wg'].id}/damages/add/",
        {"line": WGDamageLine.BAD_FLECK, "next": "/"},
    )
    assert r.status_code == 302
    assert WGDamage.objects.filter(wg=world["wg"], line=WGDamageLine.BAD_FLECK).count() == 1


def test_wg_fix_and_reopen_staff_only(client, world):
    resi = _login(client, "wgresi")
    t = Tenant.objects.get(intranet_username="wgresi")
    d = WGDamage.objects.create(
        wg=world["wg"], line=WGDamageLine.BAD_FLECK, created_at=now(), created_by=t,
    )
    # resident cannot fix
    r = client.post(f"/damages/wg/{d.id}/fix/", {"next": "/"})
    assert r.status_code == 403
    assert WGDamage.objects.get(pk=d.id).fixed_at is None
    # staff can fix, then reopen
    _login(client, "mv_staff", "ag.mietverwaltung")
    client.post(f"/damages/wg/{d.id}/fix/", {"next": "/"})
    assert WGDamage.objects.get(pk=d.id).fixed_at is not None
    client.post(f"/damages/wg/{d.id}/fix/", {"next": "/"})
    assert WGDamage.objects.get(pk=d.id).fixed_at is None
