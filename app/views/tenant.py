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

    room_form = None

    if request.method == "POST":
        if "room_action" in request.POST and can_manage_room:
            assignment_id = request.POST.get("assignment_id") or None
            instance = (
                TenantRoomAssignment.objects.filter(pk=assignment_id, tenant=tenant).first()
                if assignment_id else None
            )
            room_form = TenantRoomAssignmentForm(request.POST, instance=instance)
            if room_form.is_valid():
                obj = room_form.save(commit=False)
                obj.tenant = tenant
                obj.save()
                messages.success(request, "Zimmerzuordnung gespeichert.")
                return redirect("tenant_detail", pk=pk)
            form = TenantForm(instance=tenant, allowed_fields=editable)
        else:
            if not editable:
                messages.error(request, "Keine Berechtigung zum Bearbeiten.")
                return redirect("tenant_detail", pk=pk)
            section_key = request.POST.get("section")
            section_fields = {f.name for s in SECTIONS if s.key == section_key for f in s.fields}
            allowed = editable & section_fields if section_key else editable
            form = TenantForm(request.POST, instance=tenant, allowed_fields=allowed)
            if form.is_valid():
                form.save()
                messages.success(request, "Gespeichert.")
                return redirect("tenant_detail", pk=pk)
    else:
        form = TenantForm(instance=tenant, allowed_fields=editable)

    # Heading name: preferred_name for everyone if set (real name is then private,
    # shown only in the Personal section to owner/mietverwaltung/admin); otherwise
    # fall back to the real name since there is no alternative to display.
    display_name = tenant.preferred_name or f"{tenant.first_name} {tenant.last_name}".strip()

    ctx = {
        "tenant": tenant,
        "display_name": display_name,
        "sections": _build_sections(tenant, form, visible, editable),
        "form": form,
        "can_edit": bool(editable),
        "roles": roles,
    }
    # Relational blocks, gated by role.
    ctx["can_manage_room"] = can_manage_room
    if can_manage_room:
        assignments = list(
            TenantRoomAssignment.objects.filter(tenant=tenant)
            .select_related("room__wg__building")
            .order_by("-moved_in")
        )
        active_assignments = [a for a in assignments if not a.moved_out]
        ctx["past_assignments"] = [a for a in assignments if a.moved_out]
        edited_id = str(request.POST.get("assignment_id", "")) if room_form else ""
        ctx["active_assignment_forms"] = [
            (a, room_form if str(a.pk) == edited_id else TenantRoomAssignmentForm(instance=a))
            for a in active_assignments
        ]
        ctx["new_room_form"] = room_form if (room_form and not edited_id) else TenantRoomAssignmentForm()
    else:
        ctx["active_assignment_forms"] = []
        ctx["past_assignments"] = []
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
