"""Room handover (Übergabe): who may conduct one, the ordered catalog the
wizard walks, and the recap damage scoping. The damages themselves live in the
existing RoomDamage/WGDamage tables; this module only orchestrates."""
from app.damages import open_and_fixed
from app.models import RoomDamage, RoomDamageLine, WGDamage, WGDamageLine

# Conducting a handover: Mietverwaltung, admins, and MV helpers. Deliberately
# wider than app.damages (which excludes helpers) — the one place a helper may
# create a damage is inside a handover they conduct.
CONDUCT_ROLES = {"mietverwaltung", "admin", "mietverwaltung_helfer"}

# The wizard walks every room-damage line, then every WG common-area line.
STEPS = (
    [("room", v) for v in RoomDamageLine.values]
    + [("wg", v) for v in WGDamageLine.values]
)


def can_conduct_handover(roles: set[str]) -> bool:
    return bool(CONDUCT_ROLES & roles)


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
