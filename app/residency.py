"""Ersteinzug/Auszug and 'currently resident' are derived from room assignments,
not stored on the tenant. Shared so the list scope, dashboard and abfragen agree."""
from django.db.models import Count, Exists, Max, Min, OuterRef, Q

from app.models import TenantRoomAssignment


def active_assignment_q(today):
    """An assignment counts as active while not yet moved out (or moving out later)."""
    return Q(moved_out__isnull=True) | Q(moved_out__gt=today)


def has_active_assignment(today):
    """Exists() subquery: the tenant currently holds a room."""
    return Exists(
        TenantRoomAssignment.objects.filter(tenant_id=OuterRef("pk")).filter(
            active_assignment_q(today)
        )
    )


def set_move_dates(tenant, today):
    """Attach computed .ersteinzug / .auszug to a single tenant instance.

    ersteinzug = earliest moved_in; auszug = latest moved_out, but None while any
    assignment is still open (the tenant hasn't fully moved out)."""
    agg = TenantRoomAssignment.objects.filter(tenant=tenant).aggregate(
        first_in=Min("moved_in"),
        last_out=Max("moved_out"),
        open_count=Count("id", filter=Q(moved_out__isnull=True)),
    )
    tenant.ersteinzug = agg["first_in"]
    tenant.auszug = None if agg["open_count"] else agg["last_out"]
