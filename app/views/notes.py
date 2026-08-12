from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import InternalNote, Tenant

# Maps viewer role name → NoteSourceGroup value. Extend here to add more groups.
_ROLE_TO_SOURCE_GROUP = {
    "mietverwaltung": "mietverwaltung",
    "cluster": "clustersprechende",
}


def _user_source_groups(user):
    """Return list of source_group values the user may write/delete."""
    group_names = set(user.groups.values_list("name", flat=True))
    if "admins" in group_names:
        return list(_ROLE_TO_SOURCE_GROUP.values())
    result = []
    for role, cns in settings.TENANT_ROLE_GROUPS.items():
        if group_names.intersection(cns) and role in _ROLE_TO_SOURCE_GROUP:
            result.append(_ROLE_TO_SOURCE_GROUP[role])
    return result


def _author(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


@login_required
@require_POST
def add_note(request):
    source_group = request.POST.get("source_group", "")
    subject_type = request.POST.get("subject_type", "")
    subject_id = request.POST.get("subject_id", "")
    body = request.POST.get("body", "").strip()
    next_url = request.POST.get("next", "/")

    allowed = _user_source_groups(request.user)
    if source_group not in allowed or not body or not subject_id:
        raise PermissionDenied

    author = _author(request.user)
    if author is None:
        raise PermissionDenied

    InternalNote.objects.create(
        body=body,
        source_group=source_group,
        subject_type=subject_type,
        subject_id=int(subject_id),
        created_at=now(),
        created_by=author,
    )
    return redirect(next_url)


@login_required
@require_POST
def delete_note(request, pk):
    note = get_object_or_404(InternalNote, pk=pk)
    next_url = request.POST.get("next", "/")

    allowed = _user_source_groups(request.user)
    if note.source_group not in allowed:
        raise PermissionDenied

    author = _author(request.user)
    if author is None:
        raise PermissionDenied
    InternalNote.objects.filter(pk=note.pk).update(deleted_at=now(), deleted_by=author)
    return redirect(next_url)
