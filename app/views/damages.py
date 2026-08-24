import mimetypes
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app import damages as perms
from app.models import Room, WG, RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, DamageSize
from app.tenant_access import global_roles
from app.uploads import upload_error

# Per damage kind: model, the FK column holding the target id, and the
# permission gate (staff, or a resident of that room/WG).
_KINDS = {
    "room": (RoomDamage, "room_id", perms.can_add_room_damage),
    "wg": (WGDamage, "wg_id", perms.can_add_wg_damage),
}


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
    f = request.FILES.get("photo")
    if f:
        err = upload_error(f)
        if err:
            messages.error(request, err)
            return redirect(request.POST.get("next", "/"))
    model.objects.create(
        **{target_kwarg: target_id},
        line=line,
        size=_clean_size(request.POST.get("size", "")),
        note=(request.POST.get("note", "").strip() or None),
        created_at=now(),
        created_by=author,
        photo_name=f.name if f else None,
        photo_data=f.read() if f else None,
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


@login_required
@require_POST
def damage_photo_set(request, kind, pk):
    """Attach a photo to an existing damage that has none yet. Same gate as
    adding a damage: staff, or a resident of that room/WG. Photos are not
    overwritable once set."""
    if kind not in _KINDS:
        return HttpResponseBadRequest()
    model, target_col, allowed = _KINDS[kind]
    d = get_object_or_404(model, pk=pk)
    if not allowed(request.user, global_roles(request.user), getattr(d, target_col), date.today()):
        raise PermissionDenied
    if d.photo_name:
        return HttpResponseBadRequest()  # already has a photo; no overwrite
    f = request.FILES.get("photo")
    if not f:
        return HttpResponseBadRequest()
    err = upload_error(f)
    if err:
        messages.error(request, err)
        return redirect(request.POST.get("next", "/"))
    model.objects.filter(pk=pk).update(photo_name=f.name, photo_data=f.read())
    return redirect(request.POST.get("next", "/"))


@login_required
def damage_photo(request, kind, pk):
    """Serve a damage photo inline (image or PDF). Visible to anyone who could
    add a damage on that room/WG (staff or the resident)."""
    if kind not in _KINDS:
        return HttpResponseBadRequest()
    model, target_col, allowed = _KINDS[kind]
    d = get_object_or_404(model, pk=pk)
    if not allowed(request.user, global_roles(request.user), getattr(d, target_col), date.today()):
        raise PermissionDenied
    if not d.photo_name:
        return HttpResponseBadRequest()
    content_type, _ = mimetypes.guess_type(d.photo_name)
    response = HttpResponse(bytes(d.photo_data), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{d.photo_name}"'
    return response
