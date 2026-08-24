import uuid
import pytest
from datetime import date
from django.contrib.auth.models import User, Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import now

PNG = b"\x89PNG\r\n\x1a\n" + b"rest-of-image"

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


def _room_damage(world, tenant):
    return RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN, created_at=now(), created_by=tenant,
    )


def test_add_room_damage_with_photo(client, world):
    _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/",
         "photo": SimpleUploadedFile("a.png", PNG, content_type="image/png")},
    )
    assert r.status_code == 302
    d = RoomDamage.objects.get(room=world["room"])
    assert d.photo_name == "a.png" and bytes(d.photo_data) == PNG


def test_add_damage_with_bad_photo_not_created(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/",
         "photo": SimpleUploadedFile("evil.png", b"<html>", content_type="image/png")},
    )
    assert r.status_code == 302  # redirected with an error message
    assert RoomDamage.objects.count() == 0


def test_resident_sets_photo_once(client, world):
    _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    d = _room_damage(world, t)
    r = client.post(
        f"/damages/room/{d.id}/photo/set/",
        {"next": "/", "photo": SimpleUploadedFile("a.png", PNG, content_type="image/png")},
    )
    assert r.status_code == 302
    d.refresh_from_db()
    assert d.photo_name == "a.png" and bytes(d.photo_data) == PNG
    # a photo already exists — no overwrite
    r = client.post(
        f"/damages/room/{d.id}/photo/set/",
        {"next": "/", "photo": SimpleUploadedFile("b.png", PNG, content_type="image/png")},
    )
    assert r.status_code == 400
    d.refresh_from_db()
    assert d.photo_name == "a.png"


def test_photo_bad_type_rejected(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    t = Tenant.objects.get(intranet_username="cartei_werkstatt")
    d = _room_damage(world, t)
    r = client.post(
        f"/damages/room/{d.id}/photo/set/",
        {"next": "/", "photo": SimpleUploadedFile("evil.png", b"<html>", content_type="image/png")},
    )
    assert r.status_code == 302  # redirects with an error message, no save
    d.refresh_from_db()
    assert d.photo_name is None


def test_nonresident_photo_denied(client, world):
    t0 = Tenant.objects.create(first_name="x", last_name="x", intranet_username="ownerx", intranet_uuid=uuid.uuid4())
    d = _room_damage(world, t0)
    _login(client, "stranger")
    r = client.post(
        f"/damages/room/{d.id}/photo/set/",
        {"next": "/", "photo": SimpleUploadedFile("a.png", PNG, content_type="image/png")},
    )
    assert r.status_code == 403
    d.refresh_from_db()
    assert d.photo_name is None


def test_photo_download_serves_bytes(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    t = Tenant.objects.get(intranet_username="cartei_werkstatt")
    d = _room_damage(world, t)
    d.photo_name, d.photo_data = "a.png", PNG
    d.save()
    r = client.get(f"/damages/room/{d.id}/photo/")
    assert r.status_code == 200
    assert r["Content-Type"] == "image/png"
    assert r.content == PNG
