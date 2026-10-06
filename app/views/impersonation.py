"""User impersonation within the existing login session.

Gated by membership in the cartei_impersonation group (not is_superuser): it
grants only this capability. Members may impersonate any active non-member."""

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP, can_impersonate
from app.models import ImpersonationEvent


def _log_impersonation(impersonator, target, action):
    ImpersonationEvent.objects.create(
        impersonator_username=impersonator.username,
        target_username=target.username,
        action=action,
        created_at=timezone.now(),
    )


def _require_impersonator(request):
    if request.impersonator or not can_impersonate(request.user):
        raise PermissionDenied


@login_required
@require_GET
def choose_user(request):
    _require_impersonator(request)
    users = get_user_model().objects.filter(is_active=True).exclude(groups__name=IMPERSONATION_GROUP)
    query = request.GET.get("q", "").strip()
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    return render(request, "app/admin/impersonation.html", {
        "users": users.order_by("username")[:100],
        "query": query,
    })


@login_required
@require_POST
def start(request, user_id):
    _require_impersonator(request)
    target = get_object_or_404(
        get_user_model().objects.exclude(groups__name=IMPERSONATION_GROUP),
        pk=user_id, is_active=True,
    )
    request.session[IMPERSONATED_USER_SESSION_KEY] = target.pk
    # request.user is still the real superuser here; the swap happens next request.
    _log_impersonation(request.user, target, ImpersonationEvent.Action.START)
    return redirect("dashboard")


@login_required
@require_POST
def stop(request):
    if request.impersonator is None or not can_impersonate(request.impersonator):
        raise PermissionDenied
    # request.user is the impersonated target; request.impersonator is the real superuser.
    _log_impersonation(request.impersonator, request.user, ImpersonationEvent.Action.STOP)
    request.session.pop(IMPERSONATED_USER_SESSION_KEY, None)
    return redirect("impersonation_choose")
