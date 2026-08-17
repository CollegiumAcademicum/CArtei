from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from app.auth import ag_group_names
from app.models import AGAbfrage, EnrollmentType, Tenant
from app.residency import has_active_assignment


@login_required
def dashboard(request):
    try:
        tenant = Tenant.objects.get(intranet_username=request.user.username)
    except Tenant.DoesNotExist:
        tenant = None

    user_groups = ag_group_names(request.user)

    active_abfragen = AGAbfrage.objects.filter(grace_ends_at__gte=date.today()).order_by("-date")

    total = Tenant.objects.count()
    current = Tenant.objects.filter(has_active_assignment(date.today())).count()
    flinta = Tenant.objects.filter(is_flinta=True).count()
    azubi = Tenant.objects.filter(
        enrollment_proofs__enrollment_type=EnrollmentType.APPRENTICESHIP
    ).distinct().count()

    return render(request, "app/dashboard.html", {
        "tenant": tenant,
        "user_groups": user_groups,
        "active_abfragen": active_abfragen,
        "current_tenants": current,
        "total_tenants": total,
        "flinta_quote": round(flinta / total * 100, 1) if total else 0,
        "azubi_quote": round(azubi / total * 100, 1) if total else 0,
    })
