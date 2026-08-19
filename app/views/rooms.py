from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.forms import TenantRoomAssignmentForm
from app.models import AGAbfrage, AGAbfrageResult, Building, Room, TenantRoomAssignment, WG
from app.residency import assignment_active_on
from app.tenant_access import global_roles, visible_fields
from app.views._shared import assignment_editable_by, display, engagement_verdict, submitted_assignment_forms


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
        out.setdefault(a.room_id, []).append(display(a.tenant) if may_see_names else "belegt")
    return out


def _engagement_rollup(tenant_ids, as_of):
    """met/total over tenant_ids against the most recent Abfrage as of as_of
    (latest AGAbfrage.date <= as_of). None when no survey qualifies."""
    if not tenant_ids:
        return None
    ab = AGAbfrage.objects.filter(date__lte=as_of).order_by("-date").first()
    if ab is None:
        return None
    results = AGAbfrageResult.objects.filter(abfrage=ab, tenant_id__in=tenant_ids)
    by_tenant: dict[int, list] = {tid: [] for tid in tenant_ids}
    for r in results:
        by_tenant[r.tenant_id].append(r)
    met = sum(0 if engagement_verdict(rs) else 1 for rs in by_tenant.values())
    return {"met": met, "total": len(tenant_ids), "abfrage": ab}


@login_required
def wg_detail(request: HttpRequest, pk: int):
    wg = get_object_or_404(WG, pk=pk)
    roles = global_roles(request.user)
    may_see_names = "first_name" in visible_fields(roles)
    show_engagement = bool({"cluster", "admin"} & roles)
    as_of = parse_as_of(request)
    today = date.today()

    can_edit_rooms = bool({"mietverwaltung", "admin", "belegium"} & roles)
    if request.method == "POST":
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
            if a.active_on_asof:
                active_tenant_ids.add(a.tenant_id)
                active_count += 1
            if can_edit_rooms and assignment_editable_by(a, roles, today):
                aform = failed.get(a.pk) or TenantRoomAssignmentForm(instance=a, prefix=f"room_{a.pk}")
            else:
                aform = None
            occupant = display(a.tenant) if may_see_names else None
            cards.append({"assignment": a, "aform": aform, "occupant": occupant})
        rooms.append({"room": room, "cards": cards, "active_count": active_count})

    rollup = _engagement_rollup(list(active_tenant_ids), as_of) if show_engagement else None

    return render(request, "app/wg_detail.html", {
        "wg": wg, "as_of": as_of, "rooms": rooms,
        "show_engagement": show_engagement, "rollup": rollup,
        "may_see_names": may_see_names, "can_edit_rooms": can_edit_rooms,
    })


@login_required
def wg_list(request: HttpRequest):
    roles = global_roles(request.user)
    may_see_names = "first_name" in visible_fields(roles)
    as_of = parse_as_of(request)
    occ = _occupants_by_room(as_of, may_see_names)

    buildings = []
    total_rooms = 0
    for b in Building.objects.order_by("name"):
        wgs = []
        for wg in b.wg_set.order_by("name"):
            rooms = []
            for room in Room.objects.filter(wg=wg).order_by("name"):
                rooms.append({"room": room, "occupants": occ.get(room.id, [])})
                total_rooms += 1
            wgs.append({"wg": wg, "rooms": rooms})
        buildings.append({"building": b, "wgs": wgs})

    return render(request, "app/wg_list.html", {
        "buildings": buildings, "as_of": as_of, "may_see_names": may_see_names,
        "total_rooms": total_rooms,
    })
