"""Central permission + catalog rules for room/WG damages, so views and
templates never re-derive them. Staff (werkstatt/mietverwaltung/admin) manage
all damages; residents may add + view damages on their own room/WG only and may
not mark them fixed; belegium has no access."""
from app.models import Tenant, TenantRoomAssignment, DamageSize
from app.residency import active_assignment_q

STAFF_ROLES = {"werkstatt", "mietverwaltung", "admin"}


def can_view_damages(roles: set[str]) -> bool:
    return bool(STAFF_ROLES & roles)


def can_fix_damage(roles: set[str]) -> bool:
    return bool(STAFF_ROLES & roles)


def author_for(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


def is_room_resident(tenant, room_id, today) -> bool:
    if tenant is None:
        return False
    return (
        TenantRoomAssignment.objects.filter(tenant=tenant, room_id=room_id)
        .filter(active_assignment_q(today)).exists()
    )


def is_wg_resident(tenant, wg_id, today) -> bool:
    if tenant is None:
        return False
    return (
        TenantRoomAssignment.objects.filter(tenant=tenant, room__wg_id=wg_id)
        .filter(active_assignment_q(today)).exists()
    )


def can_add_room_damage(user, roles, room_id, today) -> bool:
    if STAFF_ROLES & roles:
        return True
    return is_room_resident(author_for(user), room_id, today)


def can_add_wg_damage(user, roles, wg_id, today) -> bool:
    if STAFF_ROLES & roles:
        return True
    return is_wg_resident(author_for(user), wg_id, today)


def size_options(line: str) -> list:
    """Holes take only two sizes (<1 cm / >1 cm); stains/sonstiges take all three."""
    if line.endswith("LOECHER") or line.endswith("LOCH"):
        return [DamageSize.LT1, DamageSize.GT]
    return [DamageSize.LT1, DamageSize.MID, DamageSize.GT]
