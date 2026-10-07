from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.damages import author_for
from app.forms import StartHandoverForm
from app.handover import STEPS, can_conduct_handover, existing_open_damages
from app.models import (
    DamageSize, Room, RoomDamage, RoomDamageLine, TenantRoomAssignment,
    Uebergabe, WGDamage, WGDamageLine,
)
from app.tenant_access import global_roles


def _require_conduct(request):
    if not can_conduct_handover(global_roles(request.user)):
        raise PermissionDenied
    author = author_for(request.user)
    if author is None:
        raise PermissionDenied
    return author


def _step_index(request):
    """Validated 0-based step index from ?step=, or None if out of range/bad."""
    try:
        n = int(request.GET.get("step", 0))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n < len(STEPS) else None


@login_required
def start(request):
    author = _require_conduct(request)
    if request.method == "POST":
        form = StartHandoverForm(request.POST)
        if form.is_valid():
            room = form.cleaned_data["room"]
            out_ = form.cleaned_data["outgoing_tenant"]
            assignment = (
                TenantRoomAssignment.objects.filter(room=room, tenant=out_)
                .order_by("-moved_in").first()
                if out_ else None
            )
            u = Uebergabe.objects.create(
                room=room, assignment=assignment,
                incoming_tenant=form.cleaned_data["incoming_tenant"],
                conducted_by=author, conducted_at=now(),
            )
            return redirect(f"{reverse('uebergabe_step', args=[u.pk])}?step=0")
    else:
        initial = {}
        room_pk = request.GET.get("room")
        room = (Room.objects.filter(pk=room_pk).first()
                if room_pk and room_pk.isdigit() else None)
        if room:
            initial["room"] = room
            active = (TenantRoomAssignment.objects.filter(room=room, moved_out__isnull=True)
                      .order_by("-moved_in").first())
            if active:
                initial["outgoing_tenant"] = active.tenant
        form = StartHandoverForm(initial=initial)
    return render(request, "app/handover/start.html", {"form": form})


@login_required
def step(request, pk):
    _require_conduct(request)
    u = get_object_or_404(Uebergabe, pk=pk)
    n = _step_index(request)
    if n is None:
        return redirect("uebergabe_recap", pk=u.pk)
    kind, area, lines = STEPS[n]
    labels = dict(RoomDamageLine.choices if kind == "room" else WGDamageLine.choices)
    categories = [(line, labels[line], existing_open_damages(u, kind, line))
                  for line in lines]
    return render(request, "app/handover/step.html", {
        "u": u, "n": n, "total": len(STEPS), "kind": kind, "area": area,
        "categories": categories, "sizes": DamageSize.choices,
    })


@login_required
@require_POST
def add_damage(request, pk):
    author = _require_conduct(request)
    u = get_object_or_404(Uebergabe, pk=pk)
    n = _step_index(request)
    if n is None:
        return redirect("uebergabe_recap", pk=u.pk)
    kind, area, lines = STEPS[n]
    step_url = f"{reverse('uebergabe_step', args=[u.pk])}?step={n}"
    # The category comes from the client now (the step covers a whole area);
    # it must be one of this step's lines, or nothing is recorded.
    line = request.POST.get("line", "")
    if line not in lines:
        messages.error(request, "Bitte eine Kategorie dieses Bereichs wählen.")
        return redirect(step_url)
    f = request.FILES.get("photo")
    if f:
        from app.uploads import upload_error
        err = upload_error(f)
        if err:
            messages.error(request, err)
            return redirect(step_url)
    size = request.POST.get("size", "")
    model = RoomDamage if kind == "room" else WGDamage
    target = {"room_id": u.room_id} if kind == "room" else {"wg_id": u.room.wg_id}
    model.objects.create(
        **target, line=line,
        size=size if size in DamageSize.values else None,
        note=(request.POST.get("note", "").strip() or None),
        created_at=now(), created_by=author,
        photo_name=f.name if f else None, photo_data=f.read() if f else None,
    )
    # Stay on the same step so several categories in this area can be recorded.
    return redirect(step_url)


@login_required
@require_POST
def complete(request, pk):
    _require_conduct(request)
    u = get_object_or_404(Uebergabe, pk=pk)
    if u.completed_at is None:
        Uebergabe.objects.filter(pk=pk).update(completed_at=now())
    return redirect("uebergabe_recap", pk=u.pk)


@login_required
def recap(request, pk):
    _require_conduct(request)
    u = get_object_or_404(Uebergabe, pk=pk)
    from app.handover import recap_damages
    (room_open, room_fixed), (wg_open, wg_fixed) = recap_damages(u)
    return render(request, "app/handover/recap.html", {
        "u": u, "room_open": room_open, "room_fixed": room_fixed,
        "wg_open": wg_open, "wg_fixed": wg_fixed,
    })
