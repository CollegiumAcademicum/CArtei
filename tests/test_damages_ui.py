import uuid
from datetime import date

import pytest
from django.contrib.auth.models import User, Group
from django.utils import timezone as django_timezone

from app.models import Building, WG, Room, Tenant, RoomDamage, RoomDamageLine, TenantRoomAssignment


def _login(client, username, group=None):
    u = User.objects.create_user(username=username, password="x")
    if group:
        g, _ = Group.objects.get_or_create(name=group)
        u.groups.add(g)
    Tenant.objects.create(first_name=username, last_name="T", email=f"{username}@example.invalid", phone="123", profile_setup_completed_at=django_timezone.now(), intranet_username=username, intranet_uuid=uuid.uuid4())
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


# --- damages on tenant_detail assignment cards (staff + richer rows) ---
from datetime import datetime, timezone
from app.models import WGDamage


def _occupant_with_room(world, username="occ"):
    t = Tenant.objects.create(
        first_name="Occ", last_name="Upant", email="occ@example.invalid", phone="123", profile_setup_completed_at=django_timezone.now(), intranet_username=username, intranet_uuid=uuid.uuid4()
    )
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    return t


def test_staff_sees_damages_and_fix_on_tenant_detail(client, world):
    t = _occupant_with_room(world)
    RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
        created_at=datetime(2026, 8, 15, 12, tzinfo=timezone.utc), created_by=t,
    )
    _login(client, "mvstaff", "ag.mietverwaltung")
    r = client.get(f"/tenants/{t.id}/")
    assert r.status_code == 200
    body = r.content.decode()
    assert f"/rooms/{world['room'].id}/damages/add/" in body   # staff add form present
    assert f"/wgs/{world['wg'].id}/damages/add/" in body
    assert "als behoben markieren" in body                      # staff fix button
    assert "2026-08-15" in body                                 # submission date shown
    assert "Upant" in body                                      # reporter name shown


def test_fixed_damage_collapsed_with_fixer_on_tenant_detail(client, world):
    t = _occupant_with_room(world, "occ2")
    fixer = Tenant.objects.create(
        first_name="Hans", last_name="Fixer", intranet_username="fixer", intranet_uuid=uuid.uuid4()
    )
    RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.WAND_LOECHER,
        created_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc), created_by=t,
        fixed_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc), fixed_by=fixer,
    )
    _login(client, "mvstaff2", "ag.mietverwaltung")
    body = client.get(f"/tenants/{t.id}/").content.decode()
    assert "Behobene Schäden" in body        # collapsed fixed section heading
    assert "Fixer" in body                    # fixer name
    assert "2026-08-10" in body               # fixed date
    assert "wieder öffnen" in body            # staff reopen button


def test_stranger_sees_no_damages_on_tenant_detail(client, world):
    t = _occupant_with_room(world, "occ3")
    RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
        created_at=datetime(2026, 8, 15, 12, tzinfo=timezone.utc), created_by=t,
    )
    _login(client, "stranger", None)
    body = client.get(f"/tenants/{t.id}/").content.decode()
    assert "damages/add" not in body


def test_resident_sees_fixed_section_but_no_buttons(client, world):
    t = _occupant_with_room(world, "selfres")
    RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), created_by=t,
        fixed_at=datetime(2026, 8, 5, tzinfo=timezone.utc), fixed_by=t,
    )
    # log in AS the occupant (owner of the page)
    u = User.objects.create_user(username="selfres_u", password="x")
    # reuse the occupant tenant as the logged-in identity
    t.intranet_username = "selfres_u"
    t.save()
    client.force_login(u)
    body = client.get(f"/tenants/{t.id}/").content.decode()
    assert "Behobene Schäden" in body            # resident sees fixed section
    assert "wieder öffnen" not in body           # but no reopen button
    assert "als behoben markieren" not in body   # and no fix button
