import uuid as uuid_module
from datetime import date
from itertools import groupby

from django.contrib import messages
from django.contrib.sessions.models import Session
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from app import ldap_utils
from app.decorators import require_group
from app.models import EnrollmentProof, EnrollmentType, Tenant, UserSession
from app.residency import has_active_assignment
from app.tenant_access import RESOURCE_SECTIONS, SECTIONS

_ROLE_LABELS = {
    "public": "Öffentlich",
    "owner": "Bewohner*in selbst",
    "mietverwaltung": "Mietverwaltung",
    "cluster": "Cluster",
    "belegium": "Belegium",
    "finanzierung": "Finanzierung",
    "admin": "Admin",
}


@require_group("admins")
def admin_portal(request):
    total = Tenant.objects.count()
    living = Tenant.objects.filter(has_active_assignment(date.today()))
    current = living.count()
    flinta = living.filter(is_flinta=True).count()
    azubi = living.filter(enrollment_proofs__enrollment_type=EnrollmentType.APPRENTICESHIP).distinct().count()
    return render(request, "app/admin/portal.html", {
        "current_tenants": current,
        "total_tenants": total,
        "flinta_quote": round(flinta / current * 100, 1) if current else 0,
        "azubi_quote": round(azubi / current * 100, 1) if current else 0,
    })


@require_group("admins")
def permission_matrix(request):
    all_sections = list(SECTIONS) + list(RESOURCE_SECTIONS)
    roles = sorted({r for s in all_sections for f in s.fields for r in f.visible_to | f.editable_by})
    sections_data = []
    for section in all_sections:
        rows = []
        for f in section.fields:
            cells = []
            for role in roles:
                can_see = role in f.visible_to
                can_edit = role in f.editable_by
                cells.append(
                    "both" if (can_see and can_edit) else
                    "view" if can_see else
                    "edit" if can_edit else
                    "none"
                )
            rows.append({"label": f.label, "name": f.name, "cells": cells})
        sections_data.append({"title": section.title, "rows": rows})
    return render(request, "app/admin/permission_matrix.html", {
        "sections": sections_data,
        "roles": [{"key": r, "label": _ROLE_LABELS.get(r, r)} for r in roles],
    })


@require_POST
@require_group("admins")
def sync_from_ldap(request):
    """Import new LDAP members as Tenants; never overwrites existing records."""
    members = ldap_utils.get_clearance_members()
    created = 0
    for m in members:
        try:
            intranet_uuid = uuid_module.UUID(m["uuid"]) if m["uuid"] else uuid_module.uuid4()
        except ValueError:
            intranet_uuid = uuid_module.uuid4()
        _, was_created = Tenant.objects.get_or_create(
            intranet_username=m["username"],
            defaults={
                "intranet_uuid": intranet_uuid,
                "first_name": m["first_name"],
                "last_name": m["last_name"],
                "email": m["email"],
            },
        )
        if was_created:
            created += 1
    messages.success(request, f"Sync abgeschlossen: {created} neue Mieter*innen angelegt.")
    return redirect("admin_portal")


@require_POST
@require_group("admins")
def invalidate_all_sessions(request):
    """Log out every user by deleting all session records (including your own)."""
    count = Session.objects.count()
    Session.objects.all().delete()
    UserSession.objects.all().delete()
    messages.success(request, f"{count} Sitzungen ungültig gemacht. Alle Nutzer*innen wurden abgemeldet.")
    return redirect("admin_portal")


@require_group("admins")
def session_management(request):
    """List active web sessions grouped by user, so admins can revoke a single
    device or log a user out everywhere. Only sessions with a live (non-expired)
    Django Session row are shown; orphaned metadata is ignored."""
    live_keys = set(
        Session.objects.filter(expire_date__gte=timezone.now())
        .values_list("session_key", flat=True)
    )
    rows = (
        UserSession.objects.filter(session_key__in=live_keys)
        .order_by("username", "-created_at")
    )
    current_key = request.session.session_key
    users = []
    for username, group in groupby(rows, key=lambda r: r.username):
        users.append({
            "username": username,
            "sessions": [{
                "session_key": r.session_key,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "created_at": r.created_at,
                "is_current": r.session_key == current_key,
            } for r in group],
        })
    return render(request, "app/admin/sessions.html", {"users": users})


@require_POST
@require_group("admins")
def revoke_session(request, session_key):
    """Kill one device's session."""
    Session.objects.filter(session_key=session_key).delete()
    UserSession.objects.filter(session_key=session_key).delete()
    messages.success(request, "Sitzung beendet.")
    return redirect("session_management")


@require_POST
@require_group("admins")
def invalidate_user_sessions(request, username):
    """Log one user out of all their devices."""
    keys = list(
        UserSession.objects.filter(username=username).values_list("session_key", flat=True)
    )
    Session.objects.filter(session_key__in=keys).delete()
    UserSession.objects.filter(username=username).delete()
    messages.success(request, f"Alle Sitzungen von {username} beendet.")
    return redirect("session_management")
