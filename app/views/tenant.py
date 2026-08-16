from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.forms import TenantForm, TenantRoomAssignmentForm
from app.models import (
    AGAbfrageResult, EnrollmentProof, InternalNote, Tenant, TenantRoomAssignment,
)
from app.tenant_access import (
    SECTIONS, editable_fields, global_roles, viewer_roles, visible_fields,
)

_PER_PAGE_CHOICES = [25, 50, 100]


@login_required
def tenant_list(request: HttpRequest):
    roles = global_roles(request.user)
    visible = visible_fields(roles)
    show_realname = "first_name" in visible      # real name + email + move dates
    show_room = bool({"mietverwaltung", "admin"} & roles)
    show_cluster = bool({"mietverwaltung", "admin", "cluster"} & roles)
    today = date.today()

    qs = Tenant.objects.all()
    residents = request.GET.get("residents", "active")
    if residents == "active":
        qs = qs.filter(Q(move_out__isnull=True) | Q(move_out__gt=today))
    elif residents == "former":
        qs = qs.filter(move_out__isnull=False, move_out__lte=today)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(preferred_name__icontains=q)
        )
    tenants = list(qs)

    # One active assignment per tenant (room/wg/cluster/sublet), keyed by tenant_id.
    assign_by_tenant = {}
    if show_room or show_cluster:
        for a in (
            TenantRoomAssignment.objects
            .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=today))
            .select_related("room__wg")
        ):
            assign_by_tenant.setdefault(a.tenant_id, a)

    all_clusters = sorted(
        {a.room.wg.cluster for a in assign_by_tenant.values() if a.room.wg.cluster}
    ) if show_cluster else []
    selected_clusters = set(request.GET.getlist("cluster"))
    sublet = request.GET.get("sublet", "all")

    rows = []
    for t in tenants:
        a = assign_by_tenant.get(t.pk)
        cluster = a.room.wg.cluster if a else None
        is_sublet = bool(a and a.is_sublet)
        if show_cluster and selected_clusters and (cluster or "") not in selected_clusters:
            continue
        if show_room and sublet == "only" and not is_sublet:
            continue
        if show_room and sublet == "none" and is_sublet:
            continue
        rows.append({"tenant": t, "assignment": a, "cluster": cluster, "is_sublet": is_sublet})

    def _room_key(r):
        a = r["assignment"]
        return (a.room.wg.name.lower(), a.room.name.lower()) if a else ("", "")

    _name_key = lambda r: (r["tenant"].last_name.lower(), r["tenant"].first_name.lower())
    sort_keys = {
        "name": _name_key,
        "move_in": lambda r: (r["tenant"].move_in or date.min, _name_key(r)),
        "email": lambda r: (r["tenant"].email.lower(), _name_key(r)),
        "room": lambda r: (_room_key(r), _name_key(r)),
        "sublet": lambda r: (r["is_sublet"], _name_key(r)),
        "cluster": lambda r: (r["cluster"] or "", _name_key(r)),
    }
    # Columns hidden from this viewer must not be sortable — fall back to name.
    allowed_sorts = {"name"}
    if show_realname:
        allowed_sorts |= {"move_in", "email"}
    if show_room:
        allowed_sorts |= {"room", "sublet"}
    if show_cluster:
        allowed_sorts.add("cluster")

    sort = request.GET.get("sort", "name")
    if sort not in allowed_sorts:
        sort = "name"
    reverse = request.GET.get("dir", "asc") == "desc"
    rows.sort(key=sort_keys[sort], reverse=reverse)

    try:
        per_page = int(request.GET.get("per_page", 25))
    except ValueError:
        per_page = 25
    if per_page not in _PER_PAGE_CHOICES:
        per_page = 25
    page = Paginator(rows, per_page).get_page(request.GET.get("page"))

    return render(request, "app/tenant_list.html", {
        "page": page,
        "total": len(rows),
        "show_realname": show_realname,
        "show_room": show_room,
        "show_cluster": show_cluster,
        "all_clusters": all_clusters,
        "selected_clusters": selected_clusters,
        "per_page": per_page,
        "per_page_choices": _PER_PAGE_CHOICES,
        "q": q,
        "residents": residents,
        "sublet": sublet,
        "sort": sort,
        "dir": "desc" if reverse else "asc",
    })


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
    today = date.today()
    if {"owner", "mietverwaltung", "admin"} & roles:
        assignments = list(
            TenantRoomAssignment.objects.filter(tenant=tenant)
            .select_related("room__wg__building")
            .order_by("-moved_in")
        )
        active_assignments = [a for a in assignments if not a.moved_out or a.moved_out > today]
        past_assignments = [a for a in assignments if a.moved_out and a.moved_out <= today]
    else:
        active_assignments = []
        past_assignments = []
    ctx["active_assignments"] = active_assignments
    ctx["past_assignments"] = past_assignments

    if can_manage_room:
        # On a failed POST, reuse the bound forms (which hold the errors); otherwise
        # build a fresh edit form per assignment. Both current and past are editable.
        failed_by_pk = dict((a.pk, rf) for a, rf in (failed_assignment_forms or []))

        def _form_for(a):
            return failed_by_pk.get(a.pk) or TenantRoomAssignmentForm(
                instance=a, prefix=f"room_{a.pk}"
            )

        ctx["active_assignment_forms"] = [(a, _form_for(a)) for a in active_assignments]
        ctx["past_assignment_forms"] = [(a, _form_for(a)) for a in past_assignments]
        ctx["new_room_form"] = failed_new_room_form or TenantRoomAssignmentForm(prefix="new_room")
    else:
        ctx["active_assignment_forms"] = []
        ctx["past_assignment_forms"] = []

    if {"owner", "mietverwaltung", "admin"} & roles:
        proofs = list(EnrollmentProof.objects.filter(tenant=tenant).order_by("-uploaded_at"))
        ctx["pending_proofs"] = [p for p in proofs if not p.verified_at or p.needs_human_review]
        ctx["verified_proofs"] = [p for p in proofs if p.verified_at and not p.needs_human_review]
    else:
        ctx["pending_proofs"] = []
        ctx["verified_proofs"] = []
    if {"owner", "cluster", "admin"} & roles:
        ctx["engagement"] = list(
            AGAbfrageResult.objects.filter(tenant=tenant)
            .select_related("abfrage")
            .order_by("-abfrage__ends_at", "abfrage_id")
        )
    else:
        ctx["engagement"] = []
    can_write_mv = bool({"mietverwaltung", "admin"} & roles)
    can_write_cluster = bool({"cluster", "admin"} & roles)
    ctx["can_write_mv"] = can_write_mv
    ctx["can_write_cluster"] = can_write_cluster
    ctx["can_upload"] = bool({"owner", "mietverwaltung", "admin"} & roles)

    _note_qs = InternalNote.objects.filter(
        subject_type="tenant", subject_id=tenant.pk, deleted_at__isnull=True
    ).select_related("created_by").order_by("-created_at")

    ctx["mv_notes"] = list(_note_qs.filter(source_group="mietverwaltung")) if can_write_mv else []
    ctx["cluster_notes"] = list(_note_qs.filter(source_group="clustersprechende")) if can_write_cluster else []

    return render(request, "app/tenant_detail.html", ctx)
