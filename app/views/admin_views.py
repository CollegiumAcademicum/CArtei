import uuid as uuid_module
from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from app import ldap_utils
from app.decorators import require_group
from app.models import EnrollmentProof, EnrollmentType, Tenant
from app.residency import has_active_assignment
from app.tenant_access import RESOURCE_SECTIONS, SECTIONS

_ROLE_LABELS = {
    "public": "Öffentlich",
    "owner": "Bewohner*in selbst",
    "mietverwaltung": "Mietverwaltung",
    "cluster": "Cluster",
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
