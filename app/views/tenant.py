import logging
from collections import namedtuple
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Min, Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from django.core.exceptions import PermissionDenied

from app.emails import send_welcome_email
from app.forms import TenantCreateForm, TenantForm, TenantRoomAssignmentForm
from app.ldap_utils import get_member, provision_ldap_account, search_accounts

logger = logging.getLogger(__name__)
from app.models import (
    AGAbfrage, AGAbfrageResult, AGStatus,
    DOCUMENT_MODELS, DocumentType, document_readers,
    EnrollmentProof, InternalNote, Tenant, TenantRoomAssignment,
    RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, DamageSize,
)
from app.damages import can_view_damages, can_fix_damage, open_and_fixed
from app.residency import has_active_assignment, set_move_dates
from app.tenant_access import (
    SECTIONS, editable_fields, global_roles, viewer_roles, visible_fields,
)
from app.views._shared import (
    ACTIVE_STATES, BELEGIUM_EDIT_WINDOW, assignment_doc_groups, assignment_editable_by,
    display, engagement_verdict, submitted_assignment_forms, write_through_email,
)

ProofStatus = namedtuple("ProofStatus", "state count")


# Short pill codes per document type — one source for the list column and the
# detail-view Rechtsdokumente header. Ordered to match DOCUMENT_MODELS.
_DOC_SHORT = {
    "datenschutz": "DS", "photoerlaubnis": "FoE", "vertraulichkeitserklaerung": "VE",
    "mietvertrag": "MVt", "mietbedingungen": "AMB",
    "sepa_lastschriftmandat": "SEPA", "bescheid_ausbildungsstelle": "Bes",
    "selbstverpflichtung_engagement": "SVE",
}


def _proof_status(proofs, today):
    """Overview verdict for a tenant's Ausbildungsnachweise. Priority:
    pending/needs-review (actionable) beats a still-valid proof, which beats none."""
    pending = sum(1 for p in proofs if p.verified_at is None or p.needs_human_review)
    if pending:
        return ProofStatus("pruefung", pending)
    if any(
        p.verified_at is not None and not p.needs_human_review and p.valid_until >= today
        for p in proofs
    ):
        return ProofStatus("gueltig", 0)
    return ProofStatus("fehlt", 0)



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
        for a, results, _verdict in row["survey_results"]:
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
    # Ersteinzug = earliest move-in across the tenant's room assignments (computed).
    qs = Tenant.objects.annotate(ersteinzug=Min("tenantroomassignment__moved_in"))
    residents = request.GET.get("residents", "active")
    active = has_active_assignment(today)
    if residents == "active":
        qs = qs.filter(active)
    elif residents == "former":
        # Had a room but holds none now.
        qs = qs.filter(ersteinzug__isnull=False).filter(~active)
    tenants = list(qs)

    grouped = show_cluster and request.GET.get("group") == "cluster"

    # All active assignments per tenant (a tenant may hold several rooms) + the
    # reverse-sublet map ("subletting to …"), both built in one pass.
    assigns_by_tenant: dict[int, list] = {}
    reverse_by_tenant: dict[int, list[str]] = {}
    if show_room or show_cluster:
        for a in (
            TenantRoomAssignment.objects
            .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=today))
            .select_related("room__wg", "tenant", "sublet_of_tenant")
            .order_by("moved_in")
        ):
            assigns_by_tenant.setdefault(a.tenant_id, []).append(a)
            if a.is_sublet and a.sublet_of_tenant_id:
                reverse_by_tenant.setdefault(a.sublet_of_tenant_id, []).append(display(a.tenant))

    # Proof status per tenant (one bulk query, gated with the personal columns).
    proof_by_tenant = {}
    if show_realname:
        by_tid: dict[int, list] = {}
        for p in EnrollmentProof.objects.filter(tenant_id__in=[t.pk for t in tenants]):
            by_tid.setdefault(p.tenant_id, []).append(p)
        proof_by_tenant = {tid: _proof_status(ps, today) for tid, ps in by_tid.items()}

    # Consent-document completeness (Datenschutz + Fotoerlaubnis), same gate as
    # proofs: one query per type for tenants holding a non-revoked doc.
    active_doc_ids: dict[str, set[int]] = {}
    if show_realname:
        tenant_ids = [t.pk for t in tenants]
        # Overview column tracks every per-tenant document type (_DOC_SHORT),
        # one non-revoked-doc query per type.
        for dtype in _DOC_SHORT:
            active_doc_ids[dtype] = set(
                DOCUMENT_MODELS[dtype].objects.filter(tenant_id__in=tenant_ids, revoked_at__isnull=True)
                .values_list("tenant_id", flat=True)
            )

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
        assigns = assigns_by_tenant.get(t.pk, [])
        # ponytail: cluster column/grouping keys off the earliest active room; a
        # tenant with rooms in two clusters lands under one (all rooms still shown).
        cluster = assigns[0].room.wg.cluster if assigns else None
        row = {
            "tenant": t, "cluster": cluster, "cluster_key": cluster or "",
            "rooms": [
                (a, display(a.sublet_of_tenant) if a.is_sublet and a.sublet_of_tenant_id else None)
                for a in assigns
            ],
            "sublet_to": reverse_by_tenant.get(t.pk, []),
            "proof": proof_by_tenant.get(t.pk, ProofStatus("fehlt", 0)) if show_realname else None,
        }
        if show_realname:
            row["documents"] = [
                {"short": _DOC_SHORT[dt], "label": DocumentType(dt).label,
                 "present": t.pk in active_doc_ids[dt]}
                for dt in _DOC_SHORT
            ]
            row["documents_missing"] = sum(1 for d in row["documents"] if not d["present"])
        if show_surveys:
            tr = results_by_tenant.get(t.pk, {})
            row["survey_results"] = [
                (ab, tr.get(ab.pk, []), engagement_verdict(tr.get(ab.pk, [])))
                for ab in selected_abfragen
            ]
        rows.append(row)

    # Default order by name; client-side sorting takes over on header click.
    rows.sort(key=lambda r: (r["tenant"].last_name.lower(), r["tenant"].first_name.lower()))

    # Grouped mode: bucket rows per cluster with server-side tallies (mirrors the
    # engagement-summary pattern — tallies reflect scope, not live per-column filters).
    groups = None
    if grouped:
        buckets: dict[str, dict] = {}
        for row in rows:
            g = buckets.setdefault(row["cluster_key"], {
                "cluster": row["cluster"], "rows": [], "flags": 0, "proofs_due": 0,
                "mailbox_yes": 0, "docs_incomplete": 0,
            })
            g["rows"].append(row)
            if any(v for _ab, _r, v in row.get("survey_results", [])):
                g["flags"] += 1
            if show_realname:
                if row["proof"].state == "pruefung":
                    g["proofs_due"] += 1
                if row["tenant"].mailbox_list_opt_in:
                    g["mailbox_yes"] += 1
                if not all(d["present"] for d in row["documents"]):
                    g["docs_incomplete"] += 1
        groups = [buckets[k] for k in sorted(buckets)]

    return render(request, "app/tenant_list.html", {
        "rows": rows,
        "groups": groups,
        "grouped": grouped,
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
        "can_create_tenant": bool({"mietverwaltung", "admin"} & roles),
    })


@login_required
def tenant_create(request: HttpRequest):
    """Mietverwaltung adds a tenant manually (no LDAP account link yet)."""
    if not ({"mietverwaltung", "admin"} & global_roles(request.user)):
        raise PermissionDenied

    if request.method == "POST":
        form = TenantCreateForm(request.POST)
        if form.is_valid():
            if form.cleaned_data.get("create_ldap_account"):
                with transaction.atomic():
                    tenant = form.save()
                    try:
                        result = provision_ldap_account(tenant)
                    except Exception as exc:
                        transaction.set_rollback(True)
                        logger.error("Failed to provision account during tenant creation: %s", exc)
                        err_msg = str(exc)
                        if "mail" in err_msg.lower() and ("unique" in err_msg.lower() or "already" in err_msg.lower()):
                            form.add_error("email", "Diese E-Mail-Adresse wird bereits im Intranet verwendet.")
                        else:
                            form.add_error("email", f"Intranet-Account konnte nicht angelegt werden: {exc}")
                        return render(request, "app/tenant_create.html", {"form": form})

                try:
                    send_welcome_email(tenant, result.uid, result.temp_password)
                    messages.success(request, f"Bewohner:in angelegt: {result.uid} — Willkommens-E-Mail an {tenant.email}")
                except Exception as exc:
                    logger.error("Welcome email failed for tenant %s: %s", tenant.pk, exc)
                    messages.warning(request, f"Account {result.uid} angelegt, aber Willkommens-E-Mail fehlgeschlagen.")
                return redirect("tenant_detail", pk=tenant.pk)
            else:
                tenant = form.save()
                messages.success(request, "Bewohner:in angelegt.")
                return redirect("tenant_detail", pk=tenant.pk)
    else:
        form = TenantCreateForm()

    return render(request, "app/tenant_create.html", {"form": form})


@login_required
def tenant_provision(request: HttpRequest, pk: int):
    """Mietverwaltung creates a FreeIPA account for an unlinked tenant."""
    if request.method != "POST":
        raise PermissionDenied
    if not ({"mietverwaltung", "admin"} & global_roles(request.user)):
        raise PermissionDenied
    tenant = get_object_or_404(Tenant, pk=pk)
    _provision_and_notify(request, tenant)
    return redirect("tenant_detail", pk=pk)


@login_required
def tenant_link_search(request: HttpRequest):
    """Type-ahead for the link form: matching intranet accounts as JSON."""
    if "admin" not in global_roles(request.user):
        raise PermissionDenied
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    try:
        found = search_accounts(q)
    except Exception as exc:
        logger.error("Account search failed: %s", exc)
        return JsonResponse({"results": []}, status=502)
    return JsonResponse({"results": [
        {"uid": m["username"], "name": f"{m['first_name']} {m['last_name']}".strip()} for m in found
    ]})


@login_required
def tenant_link(request: HttpRequest, pk: int):
    """Admin links an existing intranet account to a tenant (by uid, stored with
    its ipaUniqueID — the login identity), or clears a wrong link."""
    if request.method != "POST" or "admin" not in global_roles(request.user):
        raise PermissionDenied
    tenant = get_object_or_404(Tenant, pk=pk)
    uid = request.POST.get("uid", "").strip()
    if not uid:
        tenant.intranet_username = tenant.intranet_uuid = None
        tenant.save(update_fields=["intranet_username", "intranet_uuid"])
        messages.success(request, "Intranet-Verknüpfung entfernt.")
        return redirect("tenant_detail", pk=pk)
    if tenant.intranet_username:
        messages.error(request, "Bereits verknüpft — erst die Verknüpfung entfernen.")
        return redirect("tenant_detail", pk=pk)
    try:
        member = get_member(uid)
    except Exception as exc:
        messages.error(request, f"LDAP-Abfrage fehlgeschlagen: {exc}")
        return redirect("tenant_detail", pk=pk)
    if not member or not member["uuid"]:
        messages.error(request, f"Kein Intranet-Account {uid!r} gefunden.")
        return redirect("tenant_detail", pk=pk)
    tenant.intranet_username = member["username"]
    tenant.intranet_uuid = member["uuid"]
    try:
        tenant.save(update_fields=["intranet_username", "intranet_uuid"])
    except IntegrityError:
        messages.error(request, f"{uid!r} ist bereits mit einer anderen Person verknüpft.")
        return redirect("tenant_detail", pk=pk)
    messages.success(request, f"Mit Intranet-Account {member['username']} verknüpft.")
    return redirect("tenant_detail", pk=pk)


@login_required
def tenant_reset_profile_setup(request: HttpRequest, pk: int):
    """Clear a tenant's completed profile setup so they are re-prompted at their
    next request. Keeps their entered data (pre-fills the form again)."""
    if request.method != "POST":
        raise PermissionDenied
    if not ({"mietverwaltung", "admin"} & global_roles(request.user)):
        raise PermissionDenied
    tenant = get_object_or_404(Tenant, pk=pk)
    tenant.profile_setup_completed_at = None
    tenant.save(update_fields=["profile_setup_completed_at"])
    messages.success(request, "Profil-Einrichtung zurückgesetzt — wird beim nächsten Login erneut abgefragt.")
    return redirect("tenant_detail", pk=pk)


def _provision_and_notify(request, tenant):
    """Provision a FreeIPA account and email the tenant their one-time password.

    Provisioning failure is reported and stops here. A later email failure does
    NOT undo the (already created) account — it degrades to a warning so the
    Mietverwaltung knows to hand over the credentials another way.
    """
    try:
        result = provision_ldap_account(tenant)
    except Exception as exc:
        messages.error(request, f"Account konnte nicht angelegt werden: {exc}")
        return
    try:
        send_welcome_email(tenant, result.uid, result.temp_password)
        messages.success(request, f"Account angelegt: {result.uid} — Willkommens-E-Mail an {tenant.email}")
    except Exception as exc:
        logger.error("Welcome email failed for tenant %s: %s", tenant.pk, exc)
        messages.warning(request, f"Account {result.uid} angelegt, aber Willkommens-E-Mail fehlgeschlagen.")


def _current_tenant(request):
    return Tenant.objects.filter(intranet_username=request.user.username).first()


@login_required
def briefkasten(request: HttpRequest):
    # Replaces abfrage.ca-hd.de: the opt-in lives in the own profile's "personal" section.
    tenant = _current_tenant(request)
    if tenant is None:
        return redirect("dashboard")
    return redirect(reverse("tenant_detail", args=[tenant.pk]) + "#section-personal")


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
    set_move_dates(tenant, date.today())  # computed .ersteinzug / .auszug
    roles = viewer_roles(request.user, tenant, _current_tenant(request))
    visible = visible_fields(roles)
    editable = editable_fields(roles)
    today = date.today()
    # May touch the housing room forms at all (per-assignment authorization below).
    can_edit_rooms = bool({"mietverwaltung", "admin", "belegium"} & roles)

    # Bound room forms from a failed POST — carried into context-building below.
    failed_assignment_forms = None
    failed_new_room_form = None

    if request.method == "POST":
        section_key = request.POST.get("section")
        section_fields = {f.name for s in SECTIONS if s.key == section_key for f in s.fields}
        allowed = editable & section_fields if section_key else editable

        # Housing carries no editable tenant fields (Ersteinzug/Auszug are computed);
        # it's still submittable to manage room assignments.
        housing_room_edit = section_key == "housing" and can_edit_rooms
        if not allowed and not housing_room_edit:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect("tenant_detail", pk=pk)

        form = TenantForm(request.POST, instance=tenant, allowed_fields=allowed)

        # Build room forms when the housing section is submitted. Each submitted
        # assignment is authorized individually — Belegium may only edit in-window ones.
        a_forms = []
        new_rf = None
        if section_key == "housing" and can_edit_rooms:
            a_forms = submitted_assignment_forms(
                request, roles, today,
                TenantRoomAssignment.objects.filter(tenant=tenant),
            )
            new_rf = TenantRoomAssignmentForm(request.POST, prefix="new_room")

        new_room_selected = bool(new_rf and request.POST.get("new_room-room"))
        new_rf_ok = not new_room_selected or new_rf.is_valid()
        # Belegium may only create assignments within their edit window.
        if (new_room_selected and new_rf_ok and "belegium" in roles
                and not {"mietverwaltung", "admin"} & roles
                and new_rf.cleaned_data["moved_in"] < today - BELEGIUM_EDIT_WINDOW):
            new_rf.add_error("moved_in", "Belegium darf Zimmer nur ab zwei Wochen vor Einzug zuordnen.")
            new_rf_ok = False

        if (form.is_valid() and all(rf.is_valid() for _, rf in a_forms) and new_rf_ok
                and ("email" not in form.cleaned_data or write_through_email(form, tenant))):
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

    display_name = display(tenant)

    ctx = {
        "tenant": tenant,
        "display_name": display_name,
        "sections": _build_sections(tenant, form, visible, editable),
        "can_edit": bool(editable),
        "roles": roles,
        "can_provision": (not tenant.intranet_username
                          and bool({"mietverwaltung", "admin"} & roles)),
        "can_link": "admin" in roles,
        "can_reset_profile_setup": (bool(tenant.profile_setup_completed_at)
                                    and bool({"mietverwaltung", "admin"} & roles)),
    }

    # Room assignments — fetch for owners, mietverwaltung, admins, Belegium and Übergabe helpers.
    if {"owner", "mietverwaltung", "admin", "belegium", "mietverwaltung_helfer"} & roles:
        assignments = list(
            TenantRoomAssignment.objects.filter(tenant=tenant)
            .select_related("room__wg__building")
            .order_by("-moved_in")
        )
        active_assignments = [a for a in assignments if not a.moved_out or a.moved_out > today]
        past_assignments = [a for a in assignments if a.moved_out and a.moved_out <= today]
        # Reverse sublets: other tenants currently renting one of this tenant's rooms.
        sublet_out = list(
            TenantRoomAssignment.objects
            .filter(sublet_of_tenant=tenant)
            .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=today))
            .select_related("tenant", "room__wg__building")
            .order_by("room__name")
        )
    else:
        active_assignments = []
        past_assignments = []
        sublet_out = []
    ctx["sublet_out"] = sublet_out

    # Documents stay owner/MV-only — Belegium/helpers see room data, not Mietverträge.
    can_see_assignment_docs = bool({"owner", "mietverwaltung", "admin"} & roles)
    for a in active_assignments + past_assignments:
        if can_see_assignment_docs:
            a.doc_groups = assignment_doc_groups(a)

    # Internal notes on room assignments: a shared Belegung thread, read+write for
    # Mietverwaltung and Belegium (independent of the room-data edit window).
    show_assignment_notes = bool({"mietverwaltung", "belegium", "admin"} & roles)
    ctx["show_assignment_notes"] = show_assignment_notes
    ctx["can_see_assignment_docs"] = can_see_assignment_docs
    notes_by_aid = {}
    if show_assignment_notes and (active_assignments or past_assignments):
        aids = [a.pk for a in active_assignments + past_assignments]
        for n in (
            InternalNote.objects
            .filter(subject_type="room_assignment", subject_id__in=aids,
                    source_group="belegung", deleted_at__isnull=True)
            .select_related("created_by").order_by("created_at")
        ):
            notes_by_aid.setdefault(n.subject_id, []).append(n)
    for a in active_assignments + past_assignments:
        a.notes = notes_by_aid.get(a.pk, [])

    # Each assignment renders as an editable card (bound form) or read-only (None),
    # decided per-assignment. Reuse the bound forms from a failed POST for errors.
    failed_by_pk = dict((a.pk, rf) for a, rf in (failed_assignment_forms or []))

    def _card_for(a):
        if not assignment_editable_by(a, roles, today):
            return (a, None)
        return (a, failed_by_pk.get(a.pk) or TenantRoomAssignmentForm(
            instance=a, prefix=f"room_{a.pk}"))

    ctx["active_assignment_cards"] = [_card_for(a) for a in active_assignments]
    ctx["past_assignment_cards"] = [_card_for(a) for a in past_assignments]
    ctx["can_create_room"] = bool({"mietverwaltung", "admin", "belegium"} & roles)
    ctx["new_room_form"] = failed_new_room_form or TenantRoomAssignmentForm(prefix="new_room")

    can_see_proofs = bool({"owner", "mietverwaltung", "admin"} & roles)
    ctx["can_see_proofs"] = can_see_proofs
    if can_see_proofs:
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

    # Per-type read gating: a viewer sees only the document types their roles may
    # read (e.g. AG Finanzierung sees SEPA and nothing else). Section shows if any.
    readable_types = [dt for dt in DOCUMENT_MODELS if document_readers(dt) & roles]
    ctx["can_see_documents"] = bool(readable_types)
    if ctx["can_see_documents"]:
        groups = []
        for dtype in readable_types:
            model = DOCUMENT_MODELS[dtype]
            docs = []
            for d in model.objects.filter(tenant=tenant).order_by("-uploaded_at"):
                d.doc_type = dtype
                d.doc_type_label = DocumentType(dtype).label
                docs.append(d)
            groups.append({
                "type": dtype,
                "label": DocumentType(dtype).label,
                "short": _DOC_SHORT[dtype],
                "docs": docs,
                "has_active": any(d.revoked_at is None for d in docs),
            })
        ctx["document_groups"] = groups
        ctx["can_manage_documents"] = bool({"mietverwaltung", "admin"} & roles)

    ctx["all_tenants"] = (
        list(Tenant.objects.order_by("last_name", "first_name"))
        if ctx.get("can_manage_documents") else []
    )

    show_assignment_damages = can_view_damages(roles) or "owner" in roles
    ctx["show_assignment_damages"] = show_assignment_damages
    ctx["can_fix_damages"] = can_fix_damage(roles)
    ctx["room_damage_lines"] = RoomDamageLine.choices
    ctx["wg_damage_lines"] = WGDamageLine.choices
    ctx["damage_sizes"] = DamageSize.choices
    if show_assignment_damages:
        for a in active_assignments:
            a.room_damages_open, a.room_damages_fixed = open_and_fixed(
                RoomDamage.objects.filter(room_id=a.room_id)
            )
            a.wg_damages_open, a.wg_damages_fixed = open_and_fixed(
                WGDamage.objects.filter(wg_id=a.room.wg_id)
            )

    return render(request, "app/tenant_detail.html", ctx)


@login_required
def room_renters(request: HttpRequest, room_id: int):
    """Current renters of one room — feeds the 'Untervermietet von' dropdown.
    Only room managers may ask; returns [] otherwise so the UI just shows nobody."""
    if not ({"mietverwaltung", "admin"} & global_roles(request.user)):
        return JsonResponse([], safe=False)
    ids = list(
        TenantRoomAssignment.objects
        .filter(room_id=room_id)
        .filter(Q(moved_out__isnull=True) | Q(moved_out__gt=date.today()))
        .values_list("tenant_id", flat=True)
    )
    return JsonResponse(ids, safe=False)
