from app.handover import CONDUCT_ROLES, STEPS, can_conduct_handover
from app.models import RoomDamageLine, WGDamageLine


def test_conduct_roles():
    assert can_conduct_handover({"mietverwaltung_helfer"})
    assert can_conduct_handover({"admin"})
    assert can_conduct_handover({"mietverwaltung"})
    assert not can_conduct_handover({"belegium"})
    assert not can_conduct_handover(set())


def test_steps_group_by_room_then_wg_areas():
    # 4 walkthrough steps: the whole Zimmer, then each WG area.
    assert len(STEPS) == 4
    kind, label, lines = STEPS[0]
    assert kind == "room" and label == "Zimmer"
    assert lines == list(RoomDamageLine.values)   # all room categories in one step
    wg_steps = STEPS[1:]
    assert [s[0] for s in wg_steps] == ["wg", "wg", "wg"]
    assert [s[1] for s in wg_steps] == ["Bad", "Küche", "Gemeinschaftsfläche"]
    wg_lines = [ln for _, _, step_lines in wg_steps for ln in step_lines]
    assert wg_lines == list(WGDamageLine.values)  # full WG catalog, split by area


def test_uebergabe_has_incoming_tenant_field():
    from app.models import Uebergabe
    f = Uebergabe._meta.get_field("incoming_tenant")
    assert f.null is True
    assert f.column == "incoming_tenant_id"
