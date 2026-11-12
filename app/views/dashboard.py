from datetime import date

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.shortcuts import render

from app.auth import GROUP_PREFIXES, ag_group_names
from app.models import AGAbfrage, AGAbfrageHealth, AGHealth, EnrollmentType, Tenant
from app.residency import has_active_assignment
from app.views.ag_membership import ag_tags_html

# Worst first, so struggling AGs surface at the top of the widget.
_HEALTH_RANK = {"TOT": 0, "KRITISCH": 1, "KERNAUFGABEN": 2, "GESUND": 3}


@login_required
def dashboard(request):
    try:
        tenant = Tenant.objects.get(intranet_username=request.user.username)
    except Tenant.DoesNotExist:
        tenant = None

    user_groups = ag_group_names(request.user)

    active_abfragen = AGAbfrage.objects.filter(grace_ends_at__gte=date.today()).order_by("-date")

    # Latest health submission per AG across all Abfragen (newest Abfrage wins).
    # Iterate oldest-first so newer rows overwrite older ones in the dict.
    latest_health = {
        h.ag_name: h.health
        for h in AGAbfrageHealth.objects.select_related("abfrage").order_by("abfrage__date")
    }

    # AG-Status widget: every AG with its latest health; AGs that never submitted default to TOT.
    # ponytail: AG roster = synced org Groups (ag./gr./in.) — the only app-side list we
    # have; an AG whose members never logged in won't appear until it does.
    roster = {
        g for g in Group.objects.values_list("name", flat=True)
        if g.startswith(GROUP_PREFIXES)
    } | set(latest_health)
    ag_status = []
    if roster:
        labels = dict(AGHealth.choices)
        ag_status = sorted(
            (
                {"ag_name": name, "health": (hv := latest_health.get(name, "TOT")), "label": labels[hv]}
                for name in roster
            ),
            key=lambda a: (_HEALTH_RANK[a["health"]], a["ag_name"]),
        )

    total = Tenant.objects.count()
    living = Tenant.objects.filter(has_active_assignment(date.today()))
    current = living.count()
    flinta = living.filter(is_flinta=True).count()
    azubi = living.filter(
        enrollment_proofs__enrollment_type=EnrollmentType.APPRENTICESHIP
    ).distinct().count()

    return render(request, "app/dashboard.html", {
        "tenant": tenant,
        "user_groups": user_groups,
        "ag_tags_html": ag_tags_html(request),
        "active_abfragen": active_abfragen,
        "ag_status": ag_status,
        "current_tenants": current,
        "total_tenants": total,
        "flinta_quote": round(flinta / current * 100, 1) if current else 0,
        "azubi_quote": round(azubi / current * 100, 1) if current else 0,
    })
