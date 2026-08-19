import datetime
from app.residency import assignment_active_on


def _filters_to_sql(q):
    from app.models import TenantRoomAssignment
    return str(TenantRoomAssignment.objects.filter(q).query)


def test_active_on_bounds_both_sides():
    d = datetime.date(2026, 6, 1)
    sql = _filters_to_sql(assignment_active_on(d))
    assert "moved_in" in sql and "moved_out" in sql
