"""AG/INI membership changes in FreeIPA: the dashboard "Meine AGs" tag editor
(a user joins/leaves ag.* / in.* groups for themselves) and the shared
write-verify-log step also used by the engagement check (app.views.abfragen).
Every failure is logged and reported; the UI only ever shows LDAP's re-read."""
import logging
from typing import Literal

import ldap
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.timezone import now
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_GET, require_POST

from app import ldap_utils
from app.auth import ag_group_names, rights_group_cns, sync_user_groups
from app.models import AGMembershipAction, AGMembershipEvent, Tenant

logger = logging.getLogger(__name__)

SELF_SERVICE_PREFIXES = ("ag.", "in.")
_LDAP_ERRORS = (ldap.LDAPError, LookupError)
_UNREADABLE = gettext_lazy("Gruppenliste aus LDAP nicht lesbar.")


def _self_service(cn: str, rights: set[str]) -> bool:
    return cn.startswith(SELF_SERVICE_PREFIXES) and cn.lower() not in rights


def is_self_service(cn: str) -> bool:
    """ag.* / in.* and not a rights group: membership may be changed via CArtei."""
    return _self_service(cn, rights_group_cns())


def actor_username(request) -> str:
    """Who really acted: the impersonator while impersonating."""
    return (getattr(request, "impersonator", None) or request.user).username


class MembershipError(Exception):
    """A membership change failed; str() is the message for the user (UI language).
    Already logged when raised."""


class NestedMembershipError(MembershipError):
    """The membership exists only through another group; IPA can't remove it here."""


def change_membership(cn: str, uid: str, action: Literal["join", "leave"], *,
                      actor: str) -> tuple[set[str], set[str]]:
    """Add/remove uid to/from cn in FreeIPA, verify by re-read, log the event.
    Returns uid's (all, direct) group cns from the re-read. The caller has
    checked that cn is self-service and that actor may do this; Django groups
    are not synced here."""
    ctx = f"actor={actor} uid={uid} cn={cn!r} action={action}"
    failed = (_("Beitritt zu %(cn)s fehlgeschlagen (%(uid)s): %(exc)s") if action == "join"
              else _("Austritt aus %(cn)s fehlgeschlagen (%(uid)s): %(exc)s"))
    try:
        if action == "leave":
            all_cns, direct = ldap_utils.user_memberships(uid)
            if cn in all_cns and cn not in direct:
                logger.error("AG membership: leave of nested membership: %s", ctx)
                raise NestedMembershipError(
                    _("%(cn)s: Mitgliedschaft von %(uid)s besteht über eine andere Gruppe "
                      "und kann hier nicht beendet werden.") % {"cn": cn, "uid": uid})
            ldap_utils.remove_group_member(cn, uid)
        else:
            ldap_utils.add_group_member(cn, uid)
    except _LDAP_ERRORS as exc:
        logger.exception("AG membership: LDAP read failed: %s", ctx)
        raise MembershipError(failed % {"cn": cn, "uid": uid, "exc": exc}) from exc
    except ldap_utils.GroupIPAError as exc:
        logger.exception("AG membership: IPA write failed: %s", ctx)
        raise MembershipError(failed % {"cn": cn, "uid": uid, "exc": exc}) from exc

    # Re-read: callers show what FreeIPA says, not what was asked.
    try:
        all_cns, direct = ldap_utils.user_memberships(uid)
    except _LDAP_ERRORS as exc:
        logger.exception("AG membership: LDAP re-read failed: %s", ctx)
        unverifiable = (_("Beitritt zu %(cn)s (%(uid)s): Änderung nicht überprüfbar (%(exc)s). Seite neu laden.")
                        if action == "join" else
                        _("Austritt aus %(cn)s (%(uid)s): Änderung nicht überprüfbar (%(exc)s). Seite neu laden."))
        raise MembershipError(unverifiable % {"cn": cn, "uid": uid, "exc": exc}) from exc
    if (cn in direct) != (action == "join"):
        logger.error("AG membership: re-read disagrees: %s direct=%s", ctx, sorted(direct))
        disagrees = (_("FreeIPA meldet die Änderung, aber %(uid)s ist nicht in %(cn)s. Bitte IT-AG Bescheid geben.")
                     if action == "join" else
                     _("FreeIPA meldet die Änderung, aber %(uid)s ist in %(cn)s. Bitte IT-AG Bescheid geben."))
        raise MembershipError(disagrees % {"cn": cn, "uid": uid})
    AGMembershipEvent.objects.create(
        tenant=Tenant.objects.filter(intranet_username=uid).first(),
        uid=uid, group_cn=cn, actor_username=actor, created_at=now(),
        action=AGMembershipAction.JOIN if action == "join" else AGMembershipAction.LEAVE,
    )
    return all_cns, direct


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
            hint = (_("Gremium – wird von der IT-AG verwaltet") if cn.startswith("gr.")
                    else _("Rechtegruppe – wird von der IT-AG verwaltet"))
        elif direct is not None and cn not in direct:
            hint = _("über eine andere Gruppe")
        else:
            hint = ""
        chips.append({"cn": cn, "hint": hint})
    return render_to_string("app/_ag_tags.html", {"chips": chips}, request=request)


def _fail(status: int, error: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": error}, status=status)


@login_required
@require_GET
def ag_available(request):
    try:
        groups = _joinable()
    except _LDAP_ERRORS:
        logger.exception("AG self-service: listing groups failed")
        return _fail(502, str(_UNREADABLE))
    return JsonResponse({"groups": groups})


@login_required
@require_POST
def ag_membership(request):
    cn = request.POST.get("group", "")
    action = request.POST.get("action", "")
    ctx = f"user={request.user.username} cn={cn!r} action={action!r}"
    tenant = Tenant.objects.filter(intranet_username=request.user.username).first()
    if tenant is None or not tenant.intranet_username:
        logger.error("AG self-service without linked intranet account: %s", ctx)
        return _fail(400, _("Kein Intranet-Account verknüpft."))
    uid = tenant.intranet_username
    if action not in ("join", "leave"):
        logger.error("AG self-service unknown action: %s", ctx)
        return _fail(400, _("Unbekannte Aktion."))
    try:
        joinable = {g["cn"] for g in _joinable()}
    except _LDAP_ERRORS:
        logger.exception("AG self-service: listing groups failed: %s", ctx)
        return _fail(502, str(_UNREADABLE))
    if cn not in joinable:
        # Not a user mistake: the UI only offers joinable groups.
        logger.error("AG self-service refused, not self-joinable: %s", ctx)
        return _fail(403, _("%(cn)s ist keine selbst verwaltbare AG/INI.") % {"cn": cn})

    try:
        all_cns, direct = change_membership(cn, uid, action, actor=actor_username(request))
    except NestedMembershipError as exc:
        return _fail(409, str(exc))
    except MembershipError as exc:
        return _fail(502, str(exc))
    sync_user_groups(request.user, all_cns)
    return JsonResponse({
        "ok": True,
        "html": ag_tags_html(request, direct),
        "message": (_("%(cn)s beigetreten") if action == "join" else _("%(cn)s verlassen")) % {"cn": cn},
    })
