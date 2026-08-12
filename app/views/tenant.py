from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.forms import TenantForm, TenantRoomAssignmentForm
from app.models import (
    AGAbfrageResult, ClusterNote, EnrollmentProof, Tenant, TenantRoomAssignment,
)
from app.tenant_access import SECTIONS, editable_fields, viewer_roles, visible_fields


def _current_tenant(request):
    return Tenant.objects.filter(intranet_username=request.user.username).first()


def _build_sections(tenant, form, visible, editable):
    out = []
    for section in SECTIONS:
        rows = []
        for f in section.fields:
            if f.name not in visible:
                continue
            rows.append({
                "label": f.label,
                "name": f.name,
                "value": getattr(tenant, f.name),
                "field": form[f.name] if (f.name in editable and f.name in form.fields) else None,
            })
        if rows:
            out.append({"key": section.key, "title": section.title, "rows": rows})
    return out


@login_required
def tenant_detail(request: HttpRequest, pk: int):
    tenant = get_object_or_404(Tenant, pk=pk)
    roles = viewer_roles(request.user, tenant, _current_tenant(request))
    visible = visible_fields(roles)
    editable = editable_fields(roles)
    can_manage_room = bool({"mietverwaltung", "admin"} & roles)

    # Bound room forms from a failed POST — carried into context-building below.
    failed_assignment_forms = None
    failed_new_room_form = None

    if request.method == "POST":
        section_key = request.POST.get("section")
        section_fields = {f.name for s in SECTIONS if s.key == section_key for f in s.fields}
        allowed = editable & section_fields if section_key else editable

        if not allowed:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect("tenant_detail", pk=pk)

        form = TenantForm(request.POST, instance=tenant, allowed_fields=allowed)

        # Build room forms when the housing section is submitted.
        a_forms = []
        new_rf = None
        if section_key == "housing" and can_manage_room:
            for pk_str in request.POST.getlist("assignment_ids"):
                a = TenantRoomAssignment.objects.filter(pk=pk_str, tenant=tenant).first()
                if a:
                    rf = TenantRoomAssignmentForm(request.POST, instance=a, prefix=f"room_{a.pk}")
                    a_forms.append((a, rf))
            new_rf = TenantRoomAssignmentForm(request.POST, prefix="new_room")

        new_room_selected = bool(new_rf and request.POST.get("new_room-room"))
        new_rf_ok = not new_room_selected or new_rf.is_valid()

        if form.is_valid() and all(rf.is_valid() for _, rf in a_forms) and new_rf_ok:
            form.save()
            for _, rf in a_forms:
                rf.save()
            if new_room_selected:
                obj = new_rf.save(commit=False)
                obj.tenant = tenant
                obj.save()
            messages.success(request, "Gespeichert.")
            return redirect("tenant_detail", pk=pk)

        failed_assignment_forms = a_forms
        failed_new_room_form = new_rf
    else:
        form = TenantForm(instance=tenant, allowed_fields=editable)

    display_name = tenant.preferred_name or f"{tenant.first_name} {tenant.last_name}".strip()

    ctx = {
        "tenant": tenant,
        "display_name": display_name,
        "sections": _build_sections(tenant, form, visible, editable),
        "can_edit": bool(editable),
        "roles": roles,
        "can_manage_room": can_manage_room,
    }

    # Room assignments — fetch for owners, mietverwaltung, admins.
    if {"owner", "mietverwaltung", "admin"} & roles:
        assignments = list(
            TenantRoomAssignment.objects.filter(tenant=tenant)
            .select_related("room__wg__building")
            .order_by("-moved_in")
        )
        today = date.today()
        active_assignments = [a for a in assignments if not a.moved_out or a.moved_out > today]
        ctx["past_assignments"] = [a for a in assignments if a.moved_out and a.moved_out <= today]
    else:
        active_assignments = []
        ctx["past_assignments"] = []

    if can_manage_room:
        if failed_assignment_forms is not None:
            ctx["active_assignment_forms"] = failed_assignment_forms
            ctx["new_room_form"] = failed_new_room_form or TenantRoomAssignmentForm(prefix="new_room")
        else:
            ctx["active_assignment_forms"] = [
                (a, TenantRoomAssignmentForm(instance=a, prefix=f"room_{a.pk}"))
                for a in active_assignments
            ]
            ctx["new_room_form"] = TenantRoomAssignmentForm(prefix="new_room")
    else:
        ctx["active_assignment_forms"] = []
    ctx["active_assignments"] = active_assignments

    if {"owner", "mietverwaltung", "admin"} & roles:
        ctx["enrollment_proofs"] = list(EnrollmentProof.objects.filter(tenant=tenant))
    else:
        ctx["enrollment_proofs"] = []
    if {"owner", "cluster", "admin"} & roles:
        ctx["engagement"] = list(
            AGAbfrageResult.objects.filter(tenant=tenant).select_related("abfrage")
        )
    else:
        ctx["engagement"] = []
    if {"cluster", "admin"} & roles:
        ctx["cluster_notes"] = list(ClusterNote.objects.filter(tenant=tenant).order_by("-created_at"))
    else:
        ctx["cluster_notes"] = []

    return render(request, "app/tenant_detail.html", ctx)
