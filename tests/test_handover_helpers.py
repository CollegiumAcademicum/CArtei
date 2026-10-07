from app.handover import CONDUCT_ROLES, STEPS, can_conduct_handover
from app.models import RoomDamageLine, WGDamageLine


def test_conduct_roles():
    assert can_conduct_handover({"mietverwaltung_helfer"})
    assert can_conduct_handover({"admin"})
    assert can_conduct_handover({"mietverwaltung"})
    assert not can_conduct_handover({"belegium"})
    assert not can_conduct_handover(set())


def test_steps_cover_full_catalog_room_then_wg():
    assert len(STEPS) == len(RoomDamageLine.values) + len(WGDamageLine.values)
    assert STEPS[0] == ("room", RoomDamageLine.values[0])
    assert STEPS[len(RoomDamageLine.values)] == ("wg", WGDamageLine.values[0])
    assert {k for k, _ in STEPS} == {"room", "wg"}


def test_uebergabe_has_incoming_tenant_field():
    from app.models import Uebergabe
    f = Uebergabe._meta.get_field("incoming_tenant")
    assert f.null is True
    assert f.column == "incoming_tenant_id"
