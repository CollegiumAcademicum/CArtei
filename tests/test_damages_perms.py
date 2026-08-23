import uuid
from datetime import date, timedelta

import pytest

from app import damages
from app.models import (
    Building, WG, Room, Tenant, RoomDamage, WGDamage,
    RoomDamageLine, WGDamageLine, DamageSize, TenantRoomAssignment,
)


@pytest.mark.django_db
def test_room_damage_round_trip():
    b = Building.objects.create(name="Altbau")
    wg = WG.objects.create(building=b, name="WG 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm="12.50")
    t = Tenant.objects.create(
        first_name="Da", last_name="Mage",
        intranet_username="dmage", intranet_uuid=uuid.uuid4(),
    )
    d = RoomDamage.objects.create(
        room=room, line=RoomDamageLine.WAND_LOECHER, size=DamageSize.LT1,
        note="x", created_at="2026-08-22T00:00:00Z", created_by=t,
    )
    assert d.fixed_at is None
    assert d.is_open
    assert RoomDamage.objects.get(pk=d.pk).line == RoomDamageLine.WAND_LOECHER


@pytest.mark.django_db
def test_wg_damage_round_trip():
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="WG 2")
    t = Tenant.objects.create(
        first_name="Fi", last_name="Xer",
        intranet_username="fixer", intranet_uuid=uuid.uuid4(),
    )
    d = WGDamage.objects.create(
        wg=wg, line=WGDamageLine.KUECHE_LOCH, size=DamageSize.MID,
        note="y", created_at="2026-08-22T00:00:00Z", created_by=t,
    )
    assert d.is_open
    assert WGDamage.objects.get(pk=d.pk).line == WGDamageLine.KUECHE_LOCH


def test_role_gates():
    assert damages.can_view_damages({"werkstatt"})
    assert damages.can_view_damages({"mietverwaltung"})
    assert damages.can_view_damages({"admin"})
    assert not damages.can_view_damages({"belegium"})
    assert not damages.can_view_damages({"public"})
    assert damages.can_fix_damage({"admin"})
    assert not damages.can_fix_damage({"werkstatt", "belegium"} - {"werkstatt"})


@pytest.mark.django_db
def test_resident_scoping():
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm="12.00")
    other = Room.objects.create(wg=wg, name="1.02", size_sqm="12.00")
    t = Tenant.objects.create(first_name="R", last_name="es", intranet_username="res", intranet_uuid=uuid.uuid4())
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2026, 1, 1))
    today = date(2026, 8, 22)
    assert damages.is_room_resident(t, room.id, today)
    assert not damages.is_room_resident(t, other.id, today)
    assert damages.is_wg_resident(t, wg.id, today)


@pytest.mark.django_db
def test_future_move_in_not_resident():
    """A tenant with a future move-in must NOT count as a current resident."""
    b = Building.objects.create(name="C")
    wg = WG.objects.create(building=b, name="W2")
    room = Room.objects.create(wg=wg, name="2.01", size_sqm="14.00")
    t = Tenant.objects.create(first_name="F", last_name="ut", intranet_username="fut", intranet_uuid=uuid.uuid4())
    today = date(2026, 8, 24)
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=today + timedelta(days=30))
    assert not damages.is_room_resident(t, room.id, today)
    assert not damages.is_wg_resident(t, wg.id, today)


