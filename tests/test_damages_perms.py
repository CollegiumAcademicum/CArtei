import uuid

import pytest

from app.models import (
    Building, WG, Room, Tenant, RoomDamage, WGDamage,
    RoomDamageLine, WGDamageLine, DamageSize,
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
