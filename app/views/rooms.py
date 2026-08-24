from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.damages import author_for, can_view_damages, damage_counts, is_room_resident, is_wg_resident, open_and_fixed
from app.forms import RoomAssignmentCreateForm, RoomFurnitureForm, TenantRoomAssignmentForm
from app.models import AGAbfrage, AGAbfrageResult, Building, DamageSize, InternalNote, Room, RoomDamage, RoomDamageLine, Tenant, TenantRoomAssignment, WG, WGDamage, WGDamageLine
from app.residency import assignment_active_on
from app.tenant_access import global_roles, visible_fields
from app.views._shared import (
    ACTIVE_STATES,
    BELEGIUM_EDIT_WINDOW,
    assignment_doc_groups,
    assignment_editable_by,
    display,
    submitted_assignment_forms,
)

# Room furniture ("Ausstattung"), rendered as a comma-joined list per room.
AUSSTATTUNG = [("has_mattress", "Matratze"), ("has_bed", "Bett"), ("has_table", "Tisch"), ("has_closet", "Schrank")]

# Engagement states ranked best→worst. A tenant with several AG results is
# bucketed once, by their most favourable status. AKTIV/ZU_AKTIV clear the flag.
ENGAGEMENT_ORDER = ["AKTIV", "ZU_AKTIV", "IM_GESPRAECH", "NICHT_AUSREICHEND", "INAKTIV"]
ENGAGEMENT_LABELS = {
    "AKTIV": "aktiv", "ZU_AKTIV": "zu aktiv", "IM_GESPRAECH": "im Gespräch",
    "NICHT_AUSREICHEND": "nicht ausreichend", "INAKTIV": "inaktiv",
}


def parse_as_of(request: HttpRequest) -> date:
    """?as_of=YYYY-MM-DD, defaulting to today. Never raises on bad input."""
    raw = request.GET.get("as_of")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def _occupants_by_room(as_of, may_see_names):
    """room_id -> list of occupant labels active on as_of."""
    out: dict[int, list[str]] = {}
    qs = (
        TenantRoomAssignment.objects.filter(assignment_active_on(as_of))
        .select_related("tenant")
    )
    for a in qs:
        label = display(a.tenant) if may_see_names else "belegt"
        out.setdefault(a.room_id, []).append({"pk": a.tenant_id, "label": label})
    return out


def _engagement_rollup(tenant_ids, as_of):
    """met/total plus a per-state breakdown over tenant_ids against the most
    recent Abfrage as of as_of (latest AGAbfrage.date <= as_of). Each tenant is
    counted once, in their best (most engaged) status; tenants with no result
    fall into 'kein Eintrag'. None when no tenants or no survey qualifies."""
    if not tenant_ids:
        return None
    ab = AGAbfrage.objects.filter(date__lte=as_of).order_by("-date").first()
    if ab is None:
        return None
    rank = {s: i for i, s in enumerate(ENGAGEMENT_ORDER)}
    best: dict[int, str | None] = {tid: None for tid in tenant_ids}
    for r in AGAbfrageResult.objects.filter(abfrage=ab, tenant_id__in=tenant_ids):
        cur = best[r.tenant_id]
        if r.status in rank and (cur is None or rank[r.status] < rank[cur]):
            best[r.tenant_id] = r.status
    counts = {s: 0 for s in ENGAGEMENT_ORDER}
    no_entry = 0
    for s in best.values():
        if s is None:
            no_entry += 1
        else:
            counts[s] += 1
    met = counts["AKTIV"] + counts["ZU_AKTIV"]
    rows = [{"status": s, "label": ENGAGEMENT_LABELS[s], "count": counts[s]}
            for s in ENGAGEMENT_ORDER if counts[s]]
    return {"met": met, "total": len(tenant_ids), "abfrage": ab,
            "rows": rows, "no_entry": no_entry}


def _engaged_tenant_ids(as_of):
    """Tenant ids meeting engagement in the latest Abfrage as of as_of, or None
    when no survey qualifies (engagement then reads as unknown → shown blank)."""
    ab = AGAbfrage.objects.filter(date__lte=as_of).order_by("-date").first()
    if ab is None:
        return None
    return set(
        AGAbfrageResult.objects.filter(abfrage=ab, status__in=ACTIVE_STATES)
        .values_list("tenant_id", flat=True)
    )


def _room_engagement(tenant_ids, engaged):
    """A room is 'ok' when at least one active tenant meets engagement, 'flag'
    when it has tenants but none do, None when empty or engagement unknown."""
    if engaged is None or not tenant_ids:
        return None
    return "ok" if any(t in engaged for t in tenant_ids) else "flag"


def _wg_engagement(room_statuses):
    """WG is 'ok' only when every occupied room is 'ok'. Empty rooms (None) are
    ignored; None overall when no room has a status."""
    statuses = [s for s in room_statuses if s]
    if not statuses:
        return None
    return "ok" if all(s == "ok" for s in statuses) else "flag"


@login_required
def wg_detail(request: HttpRequest, pk: int):
    wg = get_object_or_404(WG, pk=pk)
    roles = global_roles(request.user)
    show_damages = can_view_damages(roles)
    may_see_names = "first_name" in visible_fields(roles)
    show_engagement = bool({"cluster", "admin"} & roles)
    as_of = parse_as_of(request)
    today = date.today()

    # A non-staff tenant living in this WG may see their own room assignment and
    # the damages on their own room + the shared spaces — the same scope owners
    # get on their tenant_detail page. Other rooms stay belegt/frei only.
    current = author_for(request.user)
    resident_wg = is_wg_resident(current, wg.id, today)

    can_edit_rooms = bool({"mietverwaltung", "admin", "belegium"} & roles)
    can_edit_furniture = bool({"mietverwaltung", "admin", "werkstatt"} & roles)
    # Assignment documents (Mietvertrag etc.) are MV/admin only — Belegium sees
    # room data but not contracts, matching the tenant detail view's gating.
    can_see_assignment_docs = bool({"mietverwaltung", "admin"} & roles)
    can_manage_documents = can_see_assignment_docs
    # The shared Belegung note thread: read+write for MV, Belegium and Admin.
    show_assignment_notes = bool({"mietverwaltung", "belegium", "admin"} & roles)
    if request.method == "POST" and "furniture_room_id" in request.POST:
        redirect_to = redirect(f"{request.path}?as_of={as_of:%Y-%m-%d}")
        if not can_edit_furniture:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect_to
        room = Room.objects.filter(wg=wg, pk=request.POST["furniture_room_id"]).first()
        if room is None:
            messages.error(request, "Zimmer nicht gefunden.")
            return redirect_to
        fform = RoomFurnitureForm(request.POST, instance=room, prefix=f"furn_{room.pk}")
        if fform.is_valid():
            fform.save()
            messages.success(request, "Ausstattung gespeichert.")
        else:
            messages.error(request, "Bitte Eingaben prüfen.")
        return redirect_to
    # Create a new assignment for one room (tenant chosen, room fixed by the card).
    new_room_forms: dict[int, RoomAssignmentCreateForm] = {}
    if request.method == "POST" and "new_assignment_room_id" in request.POST:
        redirect_to = redirect(f"{request.path}?as_of={as_of:%Y-%m-%d}")
        if not can_edit_rooms:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect_to
        room = Room.objects.filter(wg=wg, pk=request.POST["new_assignment_room_id"]).first()
        if room is None:
            messages.error(request, "Zimmer nicht gefunden.")
            return redirect_to
        cf = RoomAssignmentCreateForm(request.POST, room=room, prefix=f"new_{room.pk}")
        # Belegium may only create assignments within their edit window.
        if (cf.is_valid() and "belegium" in roles and not {"mietverwaltung", "admin"} & roles
                and cf.cleaned_data["moved_in"] < today - BELEGIUM_EDIT_WINDOW):
            cf.add_error("moved_in", "Belegium darf Zimmer nur ab zwei Wochen vor Einzug zuordnen.")
        if cf.is_valid():
            obj = cf.save(commit=False)
            obj.room = room
            obj.save()
            messages.success(request, "Zimmer zugeordnet.")
            return redirect_to
        messages.error(request, "Bitte Eingaben prüfen.")
        new_room_forms[room.pk] = cf  # re-render this room's form open with errors
        failed = {}
    elif request.method == "POST":
        if not can_edit_rooms:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect(f"{request.path}?as_of={as_of:%Y-%m-%d}")
        a_forms = submitted_assignment_forms(
            request, roles, today,
            TenantRoomAssignment.objects.filter(room__wg=wg),
        )
        if all(rf.is_valid() for _, rf in a_forms):
            for _, rf in a_forms:
                rf.save()
            messages.success(request, "Gespeichert.")
            return redirect(f"{request.path}?as_of={as_of:%Y-%m-%d}")
        messages.error(request, "Bitte Eingaben prüfen.")
        # fall through to re-render; failed forms are re-bound below by pk match
        failed = {a.pk: rf for a, rf in a_forms}
    else:
        failed = {}

    active_pks = set(
        TenantRoomAssignment.objects.filter(assignment_active_on(as_of), room__wg=wg)
        .values_list("id", flat=True)
    )

    # Belegung notes for every assignment in the WG, fetched in one query.
    notes_by_aid: dict[int, list] = {}
    if show_assignment_notes:
        aids = list(TenantRoomAssignment.objects.filter(room__wg=wg).values_list("id", flat=True))
        for n in (
            InternalNote.objects
            .filter(subject_type="room_assignment", subject_id__in=aids,
                    source_group="belegung", deleted_at__isnull=True)
            .select_related("created_by").order_by("created_at")
        ):
            notes_by_aid.setdefault(n.subject_id, []).append(n)

    rooms = []
    active_tenant_ids: set[int] = set()
    for room in Room.objects.filter(wg=wg).order_by("name"):
        assignments = list(
            TenantRoomAssignment.objects.filter(room=room)
            .select_related("tenant", "room__wg__building", "sublet_of_tenant")
            .order_by("-moved_in")
        )
        cards = []
        active_count = 0
        for a in assignments:
            a.active_on_asof = a.id in active_pks
            if can_see_assignment_docs:
                a.doc_groups = assignment_doc_groups(a)
            if show_assignment_notes:
                a.notes = notes_by_aid.get(a.id, [])
            if a.active_on_asof:
                active_tenant_ids.add(a.tenant_id)
                active_count += 1
            if can_edit_rooms and assignment_editable_by(a, roles, today):
                aform = failed.get(a.pk) or TenantRoomAssignmentForm(instance=a, prefix=f"room_{a.pk}")
            else:
                aform = None
            occupant = display(a.tenant) if may_see_names else None
            cards.append({"assignment": a, "aform": aform, "occupant": occupant})
        # Non-staff resident: only their own card(s) for the room they live in.
        own_resident = resident_wg and is_room_resident(current, room.id, today)
        own_cards = [c for c in cards if c["assignment"].tenant_id == current.pk] if own_resident else []
        if show_damages or own_resident:
            room.damages_open, room.damages_fixed = open_and_fixed(
                RoomDamage.objects.filter(room=room)
            )
        rooms.append({
            "room": room, "cards": cards, "active_count": active_count,
            "active_cards": [c for c in cards if c["assignment"].active_on_asof],
            "past_cards": [c for c in cards if not c["assignment"].active_on_asof],
            "own_resident": own_resident, "own_cards": own_cards,
            "ausstattung": [label for attr, label in AUSSTATTUNG if getattr(room, attr)],
            "fform": RoomFurnitureForm(instance=room, prefix=f"furn_{room.pk}") if can_edit_furniture else None,
            "cform": (new_room_forms.get(room.pk)
                      or RoomAssignmentCreateForm(room=room, prefix=f"new_{room.pk}")) if can_edit_rooms else None,
        })

    rollup = _engagement_rollup(list(active_tenant_ids), as_of) if show_engagement else None
    wg_damages_open, wg_damages_fixed = (
        open_and_fixed(WGDamage.objects.filter(wg=wg)) if show_damages or resident_wg else ([], [])
    )

    return render(request, "app/wg_detail.html", {
        "wg": wg, "as_of": as_of, "rooms": rooms,
        "show_engagement": show_engagement, "rollup": rollup,
        "may_see_names": may_see_names, "can_edit_rooms": can_edit_rooms,
        "can_edit_furniture": can_edit_furniture,
        "can_see_assignment_docs": can_see_assignment_docs,
        "can_manage_documents": can_manage_documents,
        "show_assignment_notes": show_assignment_notes,
        "all_tenants": list(Tenant.objects.order_by("last_name", "first_name")) if can_manage_documents else [],
        "show_damages": show_damages,
        "resident_wg": resident_wg,
        "wg_damages_open": wg_damages_open,
        "wg_damages_fixed": wg_damages_fixed,
        "room_damage_lines": RoomDamageLine.choices,
        "wg_damage_lines": WGDamageLine.choices,
        "damage_sizes": DamageSize.choices,
    })


@login_required
def wg_list(request: HttpRequest):
    roles = global_roles(request.user)
    may_see_names = "first_name" in visible_fields(roles)
    show_engagement = bool({"cluster", "admin"} & roles)
    show_damages = can_view_damages(roles)
    as_of = parse_as_of(request)
    occ = _occupants_by_room(as_of, may_see_names)
    engaged = _engaged_tenant_ids(as_of) if show_engagement else None
    room_dmg = damage_counts(RoomDamage, "room_id") if show_damages else {}
    wg_dmg = damage_counts(WGDamage, "wg_id") if show_damages else {}

    buildings = []
    total_rooms = 0
    for b in Building.objects.order_by("name"):
        wgs = []
        for wg in b.wg_set.order_by("name"):
            rooms = []
            for room in Room.objects.filter(wg=wg).order_by("name"):
                occupants = occ.get(room.id, [])
                rooms.append({
                    "room": room,
                    "occupants": occupants,
                    "ausstattung": [label for attr, label in AUSSTATTUNG if getattr(room, attr)],
                    "engagement": _room_engagement([o["pk"] for o in occupants], engaged),
                    "damages": room_dmg.get(room.id, (0, 0)),
                })
                total_rooms += 1
            wgs.append({
                "wg": wg, "rooms": rooms,
                "engagement": _wg_engagement([r["engagement"] for r in rooms]),
                "damages": wg_dmg.get(wg.id, (0, 0)),
            })
        buildings.append({"building": b, "wgs": wgs})

    return render(request, "app/wg_list.html", {
        "buildings": buildings, "as_of": as_of, "may_see_names": may_see_names,
        "total_rooms": total_rooms, "show_engagement": show_engagement,
        "show_damages": show_damages,
        # Zimmer, m², Ausstattung, Belegung + optional Engagement/Schäden.
        "col_count": 4 + show_engagement + show_damages,
    })
