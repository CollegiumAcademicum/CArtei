"""Cross-view helpers shared by the tenant and WG views. Extracted from
tenant.py so rooms.py can reuse them without a circular import."""
from datetime import timedelta

from app.forms import TenantRoomAssignmentForm
from app.models import TenantRoomAssignment

# Statuses that clear the engagement flag: being reported active in an AG.
ACTIVE_STATES = {"AKTIV", "ZU_AKTIV"}

# Belegium may edit an assignment's room data only for future move-ins and the
# first two weeks after move-in (moved_in >= today - 14d); read-only afterwards.
BELEGIUM_EDIT_WINDOW = timedelta(days=14)


def display(tenant):
    return tenant.preferred_name or f"{tenant.first_name} {tenant.last_name}".strip()


def engagement_verdict(results):
    """True = flagged for the Clustersprechende (not meeting engagement). One
    'aktiv'/'zu aktiv' AG clears it; insufficient/inactive/no report flags it."""
    return not any(r.status in ACTIVE_STATES for r in results)


def assignment_editable_by(a, roles, today):
    """Who may edit an assignment's room data. MV/admin: always. Belegium: only
    inside the move-in window. Everyone else (owner): never."""
    if {"mietverwaltung", "admin"} & roles:
        return True
    if "belegium" in roles:
        return a.moved_in >= today - BELEGIUM_EDIT_WINDOW
    return False


def submitted_assignment_forms(request, roles, today, scope_qs):
    """Bind + authorize a TenantRoomAssignmentForm for each submitted
    assignment_id that lives in scope_qs and is editable by roles."""
    forms = []
    for pk_str in request.POST.getlist("assignment_ids"):
        a = scope_qs.filter(pk=pk_str).first()
        if a and assignment_editable_by(a, roles, today):
            forms.append((a, TenantRoomAssignmentForm(request.POST, instance=a, prefix=f"room_{a.pk}")))
    return forms
