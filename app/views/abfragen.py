from datetime import datetime, timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from app import ldap_utils
from app.decorators import require_group
from app.models import AGAbfrage, AGAbfrageResult, ClusterNote, Tenant

_STATUS_CHOICES = [
    ("ZU_AKTIV", "zu aktiv"),
    ("AKTIV", "aktiv"),
    ("NICHT_AUSREICHEND", "nicht ausreichend"),
    ("IM_GESPRAECH", "im Gespräch"),
    ("INAKTIV", "inaktiv"),
]


_SYSTEM_GROUPS = {"admins", "gr.cluster"}


@login_required
def abfragen_list(request: HttpRequest):
    abfragen = AGAbfrage.objects.all()
    is_privileged = request.user.groups.filter(name__in=["admins", "gr.cluster"]).exists()
    user_groups = sorted(
        g for g in request.user.groups.values_list("name", flat=True)
        if g not in _SYSTEM_GROUPS
    )
    return render(request, "app/abfragen/list.html", {
        "abfragen": abfragen,
        "is_privileged": is_privileged,
        "user_groups": user_groups,
    })


@require_group("admins", "gr.cluster")
def abfrage_new(request: HttpRequest):
    if request.method == "POST":
        abfrage = AGAbfrage.objects.create(
            date=request.POST["date"],
            label=request.POST.get("label") or None,
            ends_at=request.POST["ends_at"],
            grace_ends_at=request.POST["grace_ends_at"],
        )
        return redirect("abfrage_detail", pk=abfrage.pk)
    return render(request, "app/abfragen/new.html")


@require_group("admins", "gr.cluster")
def abfrage_detail(request: HttpRequest, pk: int):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    results = AGAbfrageResult.objects.filter(abfrage=abfrage).select_related("tenant")
    by_ag: dict[str, list] = {}
    for r in results:
        by_ag.setdefault(r.ag_name, []).append(r)
    is_privileged = request.user.groups.filter(name__in=["admins", "gr.cluster"]).exists()
    return render(request, "app/abfragen/detail.html", {
        "abfrage": abfrage,
        "by_ag": by_ag,
        "is_privileged": is_privileged,
    })


@login_required
def ag_edit(request: HttpRequest, pk: int, ag_name: str):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    user_groups = set(request.user.groups.values_list("name", flat=True))
    is_privileged = bool(user_groups & {"admins", "gr.cluster"})

    if not is_privileged and ag_name not in user_groups:
        raise PermissionDenied

    if not is_privileged and not abfrage.can_ag_edit():
        return render(request, "app/abfragen/ag_edit.html", {
            "abfrage": abfrage,
            "ag_name": ag_name,
            "closed": True,
            "rows": [],
            "is_privileged": False,
        })

    members = ldap_utils.get_ag_members(ag_name)
    usernames = [m["username"] for m in members]
    tenants_by_username = {
        t.intranet_username: t
        for t in Tenant.objects.filter(intranet_username__in=usernames)
    }

    if request.method == "POST":
        for username, tenant in tenants_by_username.items():
            key = f"status_{tenant.pk}"
            if key in request.POST:
                AGAbfrageResult.objects.update_or_create(
                    abfrage=abfrage,
                    ag_name=ag_name,
                    tenant=tenant,
                    defaults={
                        "status": request.POST[key],
                        "note": request.POST.get(f"note_{tenant.pk}", "").strip() or None,
                    },
                )
        return redirect("ag_edit", pk=pk, ag_name=ag_name)

    existing = {
        r.tenant_id: r
        for r in AGAbfrageResult.objects.filter(abfrage=abfrage, ag_name=ag_name)
    }
    rows = [
        {
            "member": m,
            "tenant": (t := tenants_by_username.get(m["username"])),
            "result": existing.get(t.pk) if t else None,
        }
        for m in members
    ]
    return render(request, "app/abfragen/ag_edit.html", {
        "abfrage": abfrage,
        "ag_name": ag_name,
        "rows": rows,
        "status_choices": _STATUS_CHOICES,
        "closed": False,
        "is_privileged": is_privileged,
    })


@require_group("admins", "gr.cluster")
def abfrage_tenants(request: HttpRequest, pk: int):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    tenants = Tenant.objects.filter(move_out__isnull=True)

    results_by_tenant: dict[int, list] = {}
    for r in AGAbfrageResult.objects.filter(abfrage=abfrage):
        results_by_tenant.setdefault(r.tenant_id, []).append(r)

    notes = {n.tenant_id: n for n in ClusterNote.objects.filter(abfrage=abfrage)}

    if request.method == "POST":
        tenant_id = request.POST.get("note_tenant_id")
        note_text = request.POST.get("note_text", "").strip()
        if tenant_id and note_text:
            ClusterNote.objects.update_or_create(
                tenant_id=tenant_id,
                abfrage=abfrage,
                defaults={
                    "note": note_text,
                    "created_at": datetime.now(tz=timezone.utc),
                    "created_by": request.user.username,
                },
            )
        return redirect("abfrage_tenants", pk=pk)

    rows = [
        {
            "tenant": t,
            "results": results_by_tenant.get(t.pk, []),
            "sufficient": any(r.status in ("AKTIV", "ZU_AKTIV") for r in results_by_tenant.get(t.pk, [])),
            "note": notes.get(t.pk),
        }
        for t in tenants
    ]
    return render(request, "app/abfragen/tenants.html", {
        "abfrage": abfrage,
        "rows": rows,
    })


@require_group("admins", "gr.cluster")
def cluster(request: HttpRequest):
    abfragen = list(AGAbfrage.objects.all())
    selected_ids = {int(x) for x in request.GET.getlist("surveys") if x.isdigit()}

    with connection.cursor() as c:
        c.execute("""
            SELECT tra.tenant_id, w.cluster
            FROM tenant_room_assignment tra
            JOIN room r ON r.id = tra.room_id
            JOIN wg w ON w.id = r.wg_id
            WHERE tra.moved_out IS NULL AND w.cluster IS NOT NULL
        """)
        cluster_by_tenant = dict(c.fetchall())

    all_clusters = sorted(set(cluster_by_tenant.values()))
    # "" is the bucket for residents whose WG has no cluster; residents no longer
    # require a cluster to show up — it's just a filter now.
    cluster_keys = all_clusters + [""]
    selected_clusters = set(request.GET.getlist("clusters")) or set(cluster_keys)

    selected_abfragen = [a for a in abfragen if a.pk in selected_ids]

    results_by_tenant: dict[int, dict[int, list]] = {}
    if selected_ids:
        for r in AGAbfrageResult.objects.filter(abfrage_id__in=selected_ids):
            results_by_tenant.setdefault(r.tenant_id, {}).setdefault(r.abfrage_id, []).append(r)

    sort = request.GET.get("sort", "name")
    sort_dir = request.GET.get("dir", "asc")
    reverse = sort_dir == "desc"

    rows = []
    for t in Tenant.objects.filter(move_out__isnull=True):
        cluster = cluster_by_tenant.get(t.pk)  # None when WG has no cluster
        key = cluster or ""
        if key not in selected_clusters:
            continue
        tenant_results = results_by_tenant.get(t.pk, {})
        rows.append({
            "tenant": t,
            "cluster": cluster,
            "cluster_key": key,
            "survey_results": [(a, tenant_results.get(a.pk, [])) for a in selected_abfragen],
        })

    if sort == "cluster":
        rows.sort(key=lambda r: (r["cluster_key"], r["tenant"].last_name, r["tenant"].first_name), reverse=reverse)
    else:
        rows.sort(key=lambda r: (r["tenant"].last_name, r["tenant"].first_name), reverse=reverse)

    # per-cluster group stats, broken down per selected survey (rendered as a
    # header row when sorting by cluster)
    status_label = dict(_STATUS_CHOICES)
    cluster_stats: dict[str, dict] = {}
    for row in rows:
        st = cluster_stats.setdefault(
            row["cluster_key"],
            {"count": 0, "counts": {a.pk: {} for a in selected_abfragen}},
        )
        st["count"] += 1
        for a, results in row["survey_results"]:
            counts = st["counts"][a.pk]
            for r in results:
                counts[r.status] = counts.get(r.status, 0) + 1
    for st in cluster_stats.values():
        st["surveys"] = [
            {
                "abfrage": a,
                "badges": [
                    {"status": s, "label": status_label.get(s, s), "count": st["counts"][a.pk][s]}
                    for s, _l in _STATUS_CHOICES if s in st["counts"][a.pk]
                ],
            }
            for a in selected_abfragen
        ]
    for row in rows:
        row["stats"] = cluster_stats[row["cluster_key"]]

    return render(request, "app/abfragen/cluster.html", {
        "abfragen": abfragen,
        "selected_ids": selected_ids,
        "selected_abfragen": selected_abfragen,
        "all_clusters": all_clusters,
        "selected_clusters": selected_clusters,
        "no_cluster_selected": "" in selected_clusters,
        "rows": rows,
        "group_by_cluster": sort == "cluster",
        "col_count": 2 + (len(selected_abfragen) or 1),
        "sort": sort,
        "sort_dir": sort_dir,
    })


@require_POST
@require_group("admins", "gr.cluster")
def abfrage_delete(request: HttpRequest, pk: int):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    label = str(abfrage)
    ClusterNote.objects.filter(abfrage=abfrage).delete()
    AGAbfrageResult.objects.filter(abfrage=abfrage).delete()
    abfrage.delete()
    messages.success(request, f'Abfrage "{label}" wurde gelöscht.')
    return redirect("abfragen_list")
