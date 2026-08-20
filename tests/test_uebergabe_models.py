import datetime
import uuid
import pytest
from app.models import (
    Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll,
    UebergabeProtokollDamage, WG, DamageLine, UebergabeProtokollType,
)

@pytest.mark.django_db
def test_protocol_mirror_round_trips():
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="ab", intranet_uuid=uuid.uuid4())
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))
    p = UebergabeProtokoll.objects.create(
        assignment=a, protocol_type=UebergabeProtokollType.EINZUG,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    d = UebergabeProtokollDamage.objects.create(protocol=p, line=DamageLine.BODEN_FLECKEN, count_lt1=1)
    assert d.count_mid == 0
    assert p.damages.first().line == DamageLine.BODEN_FLECKEN
