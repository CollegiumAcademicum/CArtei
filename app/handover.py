"""Room handover (Übergabe): who may conduct one, the ordered catalog the
wizard walks, and the recap damage scoping. The damages themselves live in the
existing RoomDamage/WGDamage tables; this module only orchestrates."""
from app.damages import open_and_fixed
from app.models import RoomDamage, RoomDamageLine, WGDamage, WGDamageLine

# Conducting a handover: Mietverwaltung, admins, and MV helpers. Deliberately
# wider than app.damages (which excludes helpers) — the one place a helper may
# create a damage is inside a handover they conduct.
CONDUCT_ROLES = {"mietverwaltung", "admin", "mietverwaltung_helfer"}

# The wizard walks one step per physical room/area: the whole Zimmer (all its
# damage categories), then each WG common-area (Bad, Küche, Gemeinschaftsfläche).
# Each step is (kind, area_label, [lines]). WG areas are derived from the enum —
# the area label is the part of the choice label before " – ", so a new WG line
# lands in its area automatically.
def _wg_area_steps():
    labels = dict(WGDamageLine.choices)
    groups, order = {}, []
    for v in WGDamageLine.values:
        area = labels[v].split(" – ")[0]
        if area not in groups:
            groups[area] = []
            order.append(area)
        groups[area].append(v)
    return [("wg", area, groups[area]) for area in order]


STEPS = [("room", "Zimmer", list(RoomDamageLine.values))] + _wg_area_steps()


def can_conduct_handover(roles: set[str]) -> bool:
    return bool(CONDUCT_ROLES & roles)


def existing_open_damages(u, kind, line):
    """Currently-open damages (fixed_at is null) for one catalog line on this
    handover's room/WG, oldest first — shown so the inspector sees what is already
    recorded before adding more. Not window-scoped: the incoming tenant inherits
    the room's present open state. (open == fixed_at NULL, as in
    app.damages.open_and_fixed.)"""
    if kind == "room":
        qs = RoomDamage.objects.filter(room_id=u.room_id, line=line, fixed_at__isnull=True)
    else:
        qs = WGDamage.objects.filter(wg_id=u.room.wg_id, line=line, fixed_at__isnull=True)
    return list(qs.order_by("created_at"))


def recap_damages(u):
    """((room_open, room_fixed), (wg_open, wg_fixed)) for the outgoing tenancy.
    Window = [assignment.moved_in, assignment.moved_out or conducted date]; with
    no outgoing assignment there is no lower bound. Scoped on created_at's date."""
    room, a = u.room, u.assignment
    rq = RoomDamage.objects.filter(room=room)
    wq = WGDamage.objects.filter(wg_id=room.wg_id)
    if a is not None:
        rq = rq.filter(created_at__date__gte=a.moved_in)
        wq = wq.filter(created_at__date__gte=a.moved_in)
    end = a.moved_out if (a and a.moved_out) else u.conducted_at.date()
    rq = rq.filter(created_at__date__lte=end)
    wq = wq.filter(created_at__date__lte=end)
    return open_and_fixed(rq), open_and_fixed(wq)
