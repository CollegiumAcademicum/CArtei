import uuid
from datetime import date

import pytest
from django.contrib.auth.models import User, Group

from app.models import Building, WG, Room, Tenant, RoomDamage, RoomDamageLine, TenantRoomAssignment


def _login(client, username, group=None):
    u = User.objects.create_user(username=username, password="x")
    if group:
        g, _ = Group.objects.get_or_create(name=group)
        u.groups.add(g)
    Tenant.objects.create(first_name=username, last_name="T", intranet_username=username, intranet_uuid=uuid.uuid4())
    client.force_login(u)
    return u


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    return {"wg": wg, "room": room}


def test_staff_sees_damage_panels(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.get(f"/wgs/{world['wg'].id}/")
    assert r.status_code == 200
    assert b"damages/add" in r.content  # add form rendered for staff


def test_belegium_sees_no_damage_panels(client, world):
    _login(client, "beleg", "gr.belegium")
    r = client.get(f"/wgs/{world['wg'].id}/")
    assert r.status_code == 200
    assert b"damages/add" not in r.content  # no add form action rendered


def test_resident_sees_report_form_on_own_card(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = client.get(f"/tenants/{t.id}/")
    assert r.status_code == 200
    assert f"/rooms/{world['room'].id}/damages/add/".encode() in r.content
    assert f"/wgs/{world['wg'].id}/damages/add/".encode() in r.content


def test_resident_has_no_fix_button(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    dmg = RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
        created_at="2026-08-22T00:00:00Z", created_by=t,
    )
    r = client.get(f"/tenants/{t.id}/")
    # Confirm damage section rendered (if this fails, the whole test is moot)
    assert dmg.get_line_display().encode() in r.content
    # Resident must not see the fix button
    assert b"als behoben markieren" not in r.content
