"""AG/INI self-service: the dashboard "Meine AGs" tag editor. A user joins and
leaves ag.* / in.* groups in FreeIPA for themselves only. Every failure answers
{"ok": false, "error"} and is logged; the chips only ever show LDAP's re-read."""
import logging

import ldap
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.timezone import now
from django.views.decorators.http import require_GET, require_POST

from app import ldap_utils
from app.auth import ag_group_names, rights_group_cns, sync_user_groups
from app.models import AGMembershipAction, AGMembershipEvent, Tenant

logger = logging.getLogger(__name__)

SELF_SERVICE_PREFIXES = ("ag.", "in.")
_LDAP_ERRORS = (ldap.LDAPError, LookupError)
_UNREADABLE = "Gruppenliste aus LDAP nicht lesbar."


def _self_service(cn: str, rights: set[str]) -> bool:
    return cn.startswith(SELF_SERVICE_PREFIXES) and cn.lower() not in rights


def _joinable() -> list[dict]:
    rights = rights_group_cns()
    return [g for g in ldap_utils.list_self_service_groups() if _self_service(g["cn"], rights)]


def ag_tags_html(request, direct: set[str] | None = None) -> str:
    """The "Meine AGs" chip block, shared by the dashboard and every POST answer.
    direct = the user's direct group cns from LDAP; None (dashboard load, no LDAP
    call) treats every self-service chip as removable."""
    # ponytail: on dashboard load a nested-only membership still shows ×; leaving
    # it is refused with a clear error. Read LDAP on load if that bites.
    rights = rights_group_cns()
    chips = []
    for cn in ag_group_names(request.user):
        if not _self_service(cn, rights):
            hint = ("Gremium – wird von der IT-AG verwaltet" if cn.startswith("gr.")
                    else "Rechtegruppe – wird von der IT-AG verwaltet")
        elif direct is not None and cn not in direct:
            hint = "über eine andere Gruppe"
        else:
            hint = ""
        chips.append({"cn": cn, "hint": hint})
    return render_to_string("app/_ag_tags.html", {
        "chips": chips,
        "editable": not getattr(request, "impersonator", None),
    }, request=request)


def _fail(status: int, error: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": error}, status=status)


@login_required
@require_GET
def ag_available(request):
    try:
        groups = _joinable()
    except _LDAP_ERRORS:
        logger.exception("AG self-service: listing groups failed")
        return _fail(502, _UNREADABLE)
    return JsonResponse({"groups": groups})


@login_required
@require_POST
def ag_membership(request):
    cn = request.POST.get("group", "")
    action = request.POST.get("action", "")
    ctx = f"user={request.user.username} cn={cn!r} action={action!r}"
    if getattr(request, "impersonator", None):
        logger.error("AG self-service refused while impersonating: %s", ctx)
        return _fail(403, "Während einer Impersonation nicht möglich.")
    tenant = Tenant.objects.filter(intranet_username=request.user.username).first()
    if tenant is None or not tenant.intranet_username:
        logger.error("AG self-service without linked intranet account: %s", ctx)
        return _fail(400, "Kein Intranet-Account verknüpft.")
    uid = tenant.intranet_username
    if action not in ("join", "leave"):
        logger.error("AG self-service unknown action: %s", ctx)
        return _fail(400, "Unbekannte Aktion.")
    try:
        joinable = {g["cn"] for g in _joinable()}
    except _LDAP_ERRORS:
        logger.exception("AG self-service: listing groups failed: %s", ctx)
        return _fail(502, _UNREADABLE)
    if cn not in joinable:
        # Not a user mistake: the UI only offers joinable groups.
        logger.error("AG self-service refused, not self-joinable: %s", ctx)
        return _fail(403, f"{cn} ist keine selbst verwaltbare AG/INI.")

    verb = "Beitritt zu" if action == "join" else "Austritt aus"
    try:
        if action == "leave":
            all_cns, direct = ldap_utils.user_memberships(uid)
            if cn in all_cns and cn not in direct:
                logger.error("AG self-service leave of nested membership: %s", ctx)
                return _fail(409, f"{cn}: Mitgliedschaft besteht über eine andere Gruppe "
                                  "und kann hier nicht verlassen werden.")
            ldap_utils.remove_group_member(cn, uid)
        else:
            ldap_utils.add_group_member(cn, uid)
    except _LDAP_ERRORS as exc:
        logger.exception("AG self-service: LDAP read failed: %s", ctx)
        return _fail(502, f"{verb} {cn} fehlgeschlagen: {exc}")
    except ldap_utils.GroupIPAError as exc:
        logger.exception("AG self-service: IPA write failed: %s", ctx)
        return _fail(502, f"{verb} {cn} fehlgeschlagen: {exc}")

    # Re-read: the chips and Django groups show what FreeIPA says, not what we asked.
    try:
        all_cns, direct = ldap_utils.user_memberships(uid)
    except _LDAP_ERRORS as exc:
        logger.exception("AG self-service: LDAP re-read failed: %s", ctx)
        return _fail(502, f"{verb} {cn}: Änderung nicht überprüfbar ({exc}). Seite neu laden.")
    if (cn in direct) != (action == "join"):
        logger.error("AG self-service: re-read disagrees: %s direct=%s", ctx, sorted(direct))
        return _fail(502, f"FreeIPA meldet die Änderung, aber {cn} ist "
                          f"{'nicht ' if action == 'join' else ''}in deinen Gruppen. "
                          "Bitte IT-AG Bescheid geben.")
    sync_user_groups(request.user, all_cns)
    AGMembershipEvent.objects.create(
        tenant=tenant, uid=uid, group_cn=cn, created_at=now(),
        action=AGMembershipAction.JOIN if action == "join" else AGMembershipAction.LEAVE,
    )
    return JsonResponse({
        "ok": True,
        "html": ag_tags_html(request, direct),
        "message": f"{cn} {'beigetreten' if action == 'join' else 'verlassen'}",
    })
