from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest
from django.shortcuts import render

from app.models import Building, Room, TenantRoomAssignment
from app.residency import assignment_active_on
from app.tenant_access import global_roles, visible_fields
from app.views._shared import display


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


@login_required
def wg_detail_stub(request: HttpRequest, pk: int):
    """Placeholder replaced by Task 4. Raises 404 so wg_list template can url-reverse it."""
    raise Http404


@login_required
def wg_list(request: HttpRequest):
    roles = global_roles(request.user)
    may_see_names = "first_name" in visible_fields(roles)
    as_of = parse_as_of(request)
    occ = _occupants_by_room(as_of, may_see_names)

    buildings = []
    for b in Building.objects.order_by("name"):
        wgs = []
        for wg in b.wg_set.order_by("name"):
            rooms = []
            for room in Room.objects.filter(wg=wg).order_by("name"):
                rooms.append({"room": room, "occupants": occ.get(room.id, [])})
            wgs.append({"wg": wg, "rooms": rooms})
        buildings.append({"building": b, "wgs": wgs})

    return render(request, "app/wg_list.html", {
        "buildings": buildings, "as_of": as_of, "may_see_names": may_see_names,
    })
