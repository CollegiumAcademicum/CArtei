from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.forms import TenantForm, TenantRoomAssignmentForm
from app.models import (
    AGAbfrage, AGAbfrageResult, AGStatus, EnrollmentProof, InternalNote,
    Tenant, TenantRoomAssignment,
)
from app.tenant_access import (
    SECTIONS, editable_fields, global_roles, viewer_roles, visible_fields,
)


def _engagement_summary(rows, selected_abfragen):
    """Per-cluster tallies over the current scope (server-side, not affected by
    the live per-column row filters). Powers the summary panel above the table."""
    status_label = dict(AGStatus.choices)
    stats: dict[str, dict] = {}
    for row in rows:
        st = stats.setdefault(row["cluster_key"], {
            "cluster": row["cluster"], "count": 0,
            "counts": {a.pk: {} for a in selected_abfragen},
        })
        st["count"] += 1
        for a, results in row["survey_results"]:
            counts = st["counts"][a.pk]
            for r in results:
                counts[r.status] = counts.get(r.status, 0) + 1
    out = []
    for key in sorted(stats):
        st = stats[key]
        out.append({
            "cluster": st["cluster"],
            "count": st["count"],
            "surveys": [
                {"abfrage": a, "badges": [
                    {"status": s, "label": status_label.get(s, s), "count": st["counts"][a.pk][s]}
                    for s, _l in AGStatus.choices if s in st["counts"][a.pk]
                ]}
                for a in selected_abfragen
            ],
        })
    return out


@login_required
def tenant_list(request: HttpRequest):
    roles = global_roles(request.user)
    visible = visible_fields(roles)
    show_realname = "first_name" in visible      # real name + email + move dates
    show_room = bool({"mietverwaltung", "admin"} & roles)
    show_cluster = bool({"mietverwaltung", "admin", "cluster"} & roles)
    show_surveys = bool({"cluster", "admin"} & roles)  # AG-engagement columns
    today = date.today()

    # Server-side *scope* only (which records to load). Column filtering, sorting
    # and visibility are all client-side (see tenant_list.html).
    qs = Tenant.objects.all()
    residents = request.GET.get("residents", "active")
    if residents == "active":
        qs = qs.filter(Q(move_out__isnull=True) | Q(move_out__gt=today))
    elif residents == "former":
        qs = qs.filter(move_out__isnull=False, move_out__lte=today)
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

    # AG-engagement scope (cluster/admin): which surveys' results to load.
    abfragen = list(AGAbfrage.objects.all()) if show_surveys else []
    selected_ids = {int(x) for x in request.GET.getlist("surveys") if x.isdigit()} if show_surveys else set()
    selected_abfragen = [a for a in abfragen if a.pk in selected_ids]
    results_by_tenant: dict[int, dict[int, list]] = {}
    if selected_ids:
        for r in AGAbfrageResult.objects.filter(abfrage_id__in=selected_ids):
            results_by_tenant.setdefault(r.tenant_id, {}).setdefault(r.abfrage_id, []).append(r)

    rows = []
    for t in tenants:
        a = assign_by_tenant.get(t.pk)
        cluster = a.room.wg.cluster if a else None
        row = {"tenant": t, "assignment": a, "cluster": cluster,
               "cluster_key": cluster or "", "is_sublet": bool(a and a.is_sublet)}
        if show_surveys:
            tr = results_by_tenant.get(t.pk, {})
            row["survey_results"] = [(ab, tr.get(ab.pk, [])) for ab in selected_abfragen]
        rows.append(row)

    # Default order by name; client-side sorting takes over on header click.
    rows.sort(key=lambda r: (r["tenant"].last_name.lower(), r["tenant"].first_name.lower()))

    return render(request, "app/tenant_list.html", {
        "rows": rows,
        "total": len(rows),
        "show_realname": show_realname,
        "show_room": show_room,
        "show_cluster": show_cluster,
        "show_surveys": show_surveys,
        "abfragen": abfragen,
        "selected_ids": selected_ids,
        "selected_abfragen": selected_abfragen,
        "summary": _engagement_summary(rows, selected_abfragen) if selected_abfragen else None,
        "residents": residents,
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
        # Only surface the new-room form (with its errors) if the user actually
        # tried to add one; otherwise a failing tenant-form submit would show
        # spurious "required" errors on the untouched new-room fields.
        failed_new_room_form = new_rf if new_room_selected else None
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
