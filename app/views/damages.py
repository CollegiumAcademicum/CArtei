from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app import damages as perms
from app.models import Room, WG, RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, DamageSize
from app.tenant_access import global_roles


def _clean_size(raw):
    return raw if raw in DamageSize.values else None


def _add(request, *, model, target_kwarg, target_id, line_choices, allowed):
    roles = global_roles(request.user)
    if not allowed(request.user, roles, target_id, date.today()):
        raise PermissionDenied
    author = perms.author_for(request.user)
    if author is None:
        raise PermissionDenied
    line = request.POST.get("line", "")
    if line not in line_choices.values:
        raise PermissionDenied
    model.objects.create(
        **{target_kwarg: target_id},
        line=line,
        size=_clean_size(request.POST.get("size", "")),
        note=(request.POST.get("note", "").strip() or None),
        created_at=now(),
        created_by=author,
    )
    return redirect(request.POST.get("next", "/"))


@login_required
@require_POST
def room_damage_add(request, room_pk):
    get_object_or_404(Room, pk=room_pk)
    return _add(
        request, model=RoomDamage, target_kwarg="room_id", target_id=room_pk,
        line_choices=RoomDamageLine, allowed=perms.can_add_room_damage,
    )


@login_required
@require_POST
def wg_damage_add(request, wg_pk):
    get_object_or_404(WG, pk=wg_pk)
    return _add(
        request, model=WGDamage, target_kwarg="wg_id", target_id=wg_pk,
        line_choices=WGDamageLine, allowed=perms.can_add_wg_damage,
    )


def _fix(request, model, pk):
    if not perms.can_fix_damage(global_roles(request.user)):
        raise PermissionDenied
    author = perms.author_for(request.user)
    if author is None:
        raise PermissionDenied
    d = get_object_or_404(model, pk=pk)
    if d.fixed_at is None:
        model.objects.filter(pk=pk).update(fixed_at=now(), fixed_by=author)
    else:
        model.objects.filter(pk=pk).update(fixed_at=None, fixed_by=None)
    return redirect(request.POST.get("next", "/"))


@login_required
@require_POST
def room_damage_fix(request, pk):
    return _fix(request, RoomDamage, pk)


@login_required
@require_POST
def wg_damage_fix(request, pk):
    return _fix(request, WGDamage, pk)
