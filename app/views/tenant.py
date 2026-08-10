from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.forms import TenantForm
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

    if request.method == "POST":
        if not editable:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect("tenant_detail", pk=pk)
        form = TenantForm(request.POST, instance=tenant, allowed_fields=editable)
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
    # Relational read-only blocks, gated by role.
    if {"mietverwaltung", "admin"} & roles:
        ctx["room_assignments"] = list(
            TenantRoomAssignment.objects.filter(tenant=tenant).select_related("room__wg__building")
        )
    else:
        ctx["room_assignments"] = []
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
