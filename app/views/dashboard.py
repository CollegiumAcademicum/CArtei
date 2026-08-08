from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from app.models import AGAbfrage, Tenant

_SYSTEM_GROUPS = {"admins", "cluster"}


@login_required
def dashboard(request):
    try:
        tenant = Tenant.objects.get(intranet_username=request.user.username)
    except Tenant.DoesNotExist:
        tenant = None

    user_groups = sorted(
        g for g in request.user.groups.values_list("name", flat=True)
        if g not in _SYSTEM_GROUPS
    )

    active_abfragen = AGAbfrage.objects.filter(grace_ends_at__gte=date.today()).order_by("-date")

    return render(request, "app/dashboard.html", {
        "tenant": tenant,
        "user_groups": user_groups,
        "active_abfragen": active_abfragen,
    })
