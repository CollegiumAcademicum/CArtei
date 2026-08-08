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

    latest = AGAbfrage.objects.order_by("-date").first()
    active_abfrage = latest if latest and latest.state in ("open", "grace") else None

    return render(request, "app/dashboard.html", {
        "tenant": tenant,
        "user_groups": user_groups,
        "active_abfrage": active_abfrage,
    })
