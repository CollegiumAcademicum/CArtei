import logging
from datetime import date, datetime, timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from app import ldap_utils
from app.auth import ag_group_names, sync_user_groups
from app.decorators import require_group
from app.models import AGAbfrage, AGAbfrageHealth, AGAbfrageResult, Tenant
from app.residency import has_active_assignment
from app.views.ag_membership import (
    MembershipError, actor_username, change_membership, is_self_service,
)

logger = logging.getLogger(__name__)

# Ordered worst-last so the slider index maps green→black / active→inactive.
_STATUS_CHOICES = [
    ("ZU_AKTIV", "zu aktiv"),
    ("AKTIV", "aktiv"),
    ("NICHT_AUSREICHEND", "nicht ausreichend"),
    ("IM_GESPRAECH", "im Gespräch"),
    ("INAKTIV", "inaktiv"),
]

_HEALTH_CHOICES = [
    ("GESUND", "gesund"),
    ("KERNAUFGABEN", "nur Kernaufgaben"),
    ("KRITISCH", "kritisch"),
    ("TOT", "tot"),
]


@login_required
def abfragen_list(request: HttpRequest):
    abfragen = AGAbfrage.objects.all()
    is_privileged = request.user.groups.filter(name__in=["admins", "gr.cluster"]).exists()
    user_groups = ag_group_names(request.user)
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
    health_by_ag = {
        h.ag_name: h for h in AGAbfrageHealth.objects.filter(abfrage=abfrage)
    }
    ags = [
        {"name": name, "results": rs, "health": health_by_ag.get(name)}
        for name, rs in by_ag.items()
    ]
    is_privileged = request.user.groups.filter(name__in=["admins", "gr.cluster"]).exists()
    return render(request, "app/abfragen/detail.html", {
        "abfrage": abfrage,
        "ags": ags,
        "is_privileged": is_privileged,
    })


def _apply_member_changes(request, ag_name: str, members: list[dict]) -> None:
    """Apply the engagement form's remove_<uid> / add_<tenant_id> marks in FreeIPA,
    one at a time, each verified and logged by change_membership. Only current
    LDAP members can be removed and only non-members added, so a stale tab or a
    crafted field never logs a change that didn't happen."""
    names = {m["username"]: f"{m['first_name']} {m['last_name']}" for m in members}
    actor = actor_username(request)
    removed, added, own = [], [], None
    for uid in sorted(k.removeprefix("remove_") for k in request.POST if k.startswith("remove_")):
        if uid not in names:
            logger.error("ag_edit: remove of non-member ignored: actor=%s cn=%s uid=%s", actor, ag_name, uid)
            continue
        try:
            all_cns, _ = change_membership(ag_name, uid, "leave", actor=actor)
        except MembershipError as exc:
            messages.error(request, str(exc))
            continue
        removed.append(names[uid])
        if uid == request.user.username:
            own = all_cns
    add_ids = [k.removeprefix("add_") for k in request.POST if k.startswith("add_")]
    for tenant in Tenant.objects.filter(pk__in=[i for i in add_ids if i.isdigit()]):
        name = f"{tenant.first_name} {tenant.last_name}"
        uid = tenant.intranet_username
        if not uid:
            messages.warning(request, f"{name} hat kein Intranet-Account und wurde nicht zu {ag_name} hinzugefügt.")
            continue
        if uid in names:
            continue
        try:
            all_cns, _ = change_membership(ag_name, uid, "join", actor=actor)
        except MembershipError as exc:
            messages.error(request, str(exc))
            continue
        added.append(name)
        if uid == request.user.username:
            own = all_cns
    if own is not None:
        sync_user_groups(request.user, own)
    parts = ([f"Aus {ag_name} entfernt: {', '.join(removed)}"] if removed else []) + \
            ([f"Zu {ag_name} hinzugefügt: {', '.join(added)}"] if added else [])
    if parts:
        messages.success(request, ". ".join(parts) + ".")


@login_required
def ag_edit(request: HttpRequest, pk: int, ag_name: str):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    user_groups = set(request.user.groups.values_list("name", flat=True))
    is_privileged = bool(user_groups & {"admins", "gr.cluster"})
    is_admin = "admins" in user_groups
    is_member = ag_name in user_groups

    if not is_privileged and not is_member:
        raise PermissionDenied
    # Admins edit any AG any time; members their own AG while the check runs.
    # Cluster only views other AGs' submissions (editing them was a bug, #36).
    can_edit = is_admin or (is_member and abfrage.can_ag_edit())
    readonly = not can_edit and "gr.cluster" in user_groups
    can_manage = can_edit and is_self_service(ag_name) and abfrage.can_ag_edit()
    if request.method == "POST" and not can_edit:
        raise PermissionDenied

    if not can_edit and not readonly:
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
        # Save every status_<tenant_id> present in the POST — this covers both LDAP
        # members and arbitrary tenants added via the picker.
        for key in request.POST:
            if not key.startswith("status_"):
                continue
            tenant = Tenant.objects.filter(pk=key.removeprefix("status_")).first()
            if tenant is None:
                continue
            AGAbfrageResult.objects.update_or_create(
                abfrage=abfrage,
                ag_name=ag_name,
                tenant=tenant,
                defaults={
                    "status": request.POST[key],
                    "note": request.POST.get(f"note_{tenant.pk}", "").strip() or None,
                },
            )
        if request.POST.get("health"):
            AGAbfrageHealth.objects.update_or_create(
                abfrage=abfrage,
                ag_name=ag_name,
                defaults={
                    "health": request.POST["health"],
                    "note": request.POST.get("health_note", "").strip() or None,
                },
            )
        if any(k.startswith(("remove_", "add_")) for k in request.POST):
            if can_manage:
                _apply_member_changes(request, ag_name, members)
            else:
                logger.error("ag_edit: member fields ignored (not manageable): user=%s cn=%s",
                             request.user.username, ag_name)
        # Removed yourself from the AG: this page is no longer yours.
        if not is_admin and not request.user.groups.filter(name=ag_name).exists():
            return redirect("dashboard")
        return redirect("ag_edit", pk=pk, ag_name=ag_name)

    existing = {
        r.tenant_id: r
        for r in AGAbfrageResult.objects.filter(abfrage=abfrage, ag_name=ag_name)
    }
    health = AGAbfrageHealth.objects.filter(abfrage=abfrage, ag_name=ag_name).first()
    status_labels = dict(_STATUS_CHOICES)
    rows = [
        {
            "name": f"{m['first_name']} {m['last_name']}",
            "member": m,
            "tenant": (t := tenants_by_username.get(m["username"])),
            "result": existing.get(t.pk) if t else None,
        }
        for m in members
    ]
    # Arbitrary tenants added outside LDAP membership — keep them visible on reload.
    member_ids = {t.pk for t in tenants_by_username.values()}
    extra = Tenant.objects.filter(pk__in=[tid for tid in existing if tid not in member_ids])
    rows += [
        {"name": f"{t.first_name} {t.last_name}", "member": None, "tenant": t, "result": existing[t.pk]}
        for t in extra
    ]
    for row in rows:
        row["status_label"] = status_labels.get(row["result"].status) if row["result"] else None
    return render(request, "app/abfragen/ag_edit.html", {
        "abfrage": abfrage,
        "ag_name": ag_name,
        "rows": rows,
        "all_tenants": Tenant.objects.order_by("last_name", "first_name"),
        "status_choices": _STATUS_CHOICES,
        "health_choices": _HEALTH_CHOICES,
        "health": health,
        "health_label": dict(_HEALTH_CHOICES).get(health.health) if health else None,
        "readonly": readonly,
        "closed": False,
        "is_privileged": is_privileged,
    })


@require_group("admins", "gr.cluster")
def abfrage_tenants(request: HttpRequest, pk: int):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    tenants = Tenant.objects.filter(has_active_assignment(date.today()))

    results_by_tenant: dict[int, list] = {}
    for r in AGAbfrageResult.objects.filter(abfrage=abfrage):
        results_by_tenant.setdefault(r.tenant_id, []).append(r)

    rows = [
        {
            "tenant": t,
            "results": results_by_tenant.get(t.pk, []),
            "sufficient": any(r.status in ("AKTIV", "ZU_AKTIV") for r in results_by_tenant.get(t.pk, [])),
        }
        for t in tenants
    ]
    return render(request, "app/abfragen/tenants.html", {
        "abfrage": abfrage,
        "rows": rows,
    })


@require_POST
@require_group("admins", "gr.cluster")
def abfrage_delete(request: HttpRequest, pk: int):
    abfrage = get_object_or_404(AGAbfrage, pk=pk)
    label = str(abfrage)
    AGAbfrageResult.objects.filter(abfrage=abfrage).delete()
    abfrage.delete()
    messages.success(request, f'Abfrage "{label}" wurde gelöscht.')
    return redirect("abfragen_list")
