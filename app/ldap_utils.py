"""LDAP helper functions for querying group members.

These functions are only called from views that require cluster/admin access.
In tests, patch `app.views.admin_views.ldap_utils.get_clearance_members` and `get_ag_members`.
"""
import logging
import uuid as uuid_module
from collections import namedtuple

import ldap
import ldap.filter
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# uid + the one-time random password IPA generated (must be changed on first use;
# the onboarding step delivers it to the tenant).
ProvisionResult = namedtuple("ProvisionResult", ["uid", "temp_password"])


def _dn_to_cn(dn: str) -> str:
    for part in dn.split(","):
        if part.lower().startswith("cn="):
            return part[3:]
    return dn


def _connect():
    for opt, val in getattr(settings, "LDAP_GLOBAL_OPTIONS", {}).items():
        ldap.set_option(opt, val)
    conn = ldap.initialize(settings.LDAP_SERVER_URI)
    conn.simple_bind_s(settings.LDAP_BIND_DN, settings.LDAP_BIND_PASSWORD)
    return conn


def _parse(attrs: dict) -> dict:
    def d(key):
        v = attrs.get(key, [b""])[0]
        return v.decode() if isinstance(v, bytes) else (v or "")

    return {
        "username": d("uid"),
        "first_name": d("givenName"),
        "last_name": d("sn"),
        "email": d("mail"),
        "uuid": d("ipaUniqueID"),
    }


_ATTRS = ["uid", "givenName", "sn", "mail", "ipaUniqueID"]


def get_clearance_members() -> list[dict]:
    """Return all members of LDAP_REQUIRE_GROUP (confidentiality_clearance)."""
    conn = _connect()
    results = conn.search_s(
        settings.LDAP_USER_SEARCH_BASE,
        ldap.SCOPE_SUBTREE,
        f"(memberOf={settings.LDAP_REQUIRE_GROUP})",
        _ATTRS,
    )
    return [_parse(attrs) for _, attrs in results if attrs]


def clearance_member_uuids() -> set[str] | None:
    """ipaUniqueIDs of all clearance-group members; None if LDAP is unreachable."""
    try:
        return {m["uuid"] for m in get_clearance_members()}
    except ldap.LDAPError:
        logger.warning("clearance_member_uuids: LDAP error", exc_info=True)
        return None


def is_clearance_member(intranet_uuid) -> bool | None:
    """Whether the account is in the clearance group; None if unknown."""
    if not intranet_uuid:
        return None
    try:
        results = _connect().search_s(
            settings.LDAP_USER_SEARCH_BASE,
            ldap.SCOPE_SUBTREE,
            f"(&(ipaUniqueID={ldap.filter.escape_filter_chars(str(intranet_uuid))})"
            f"(memberOf={settings.LDAP_REQUIRE_GROUP}))",
            ["uid"],
        )
    except ldap.LDAPError:
        logger.warning("is_clearance_member: LDAP error", exc_info=True)
        return None
    return any(attrs for _, attrs in results)


def get_member(uid: str) -> dict | None:
    """One intranet account by uid, or None — regardless of group membership."""
    conn = _connect()
    results = conn.search_s(
        settings.LDAP_USER_SEARCH_BASE,
        ldap.SCOPE_SUBTREE,
        f"(uid={ldap.filter.escape_filter_chars(uid)})",
        _ATTRS,
    )
    found = [_parse(attrs) for _, attrs in results if attrs]
    return found[0] if found else None


def search_accounts(q: str, limit: int = 10) -> list[dict]:
    """Intranet accounts whose uid, first/last name or mail contains q."""
    v = ldap.filter.escape_filter_chars(q)
    conn = _connect()
    results = conn.search_s(
        settings.LDAP_USER_SEARCH_BASE,
        ldap.SCOPE_SUBTREE,
        f"(|(uid=*{v}*)(givenName=*{v}*)(sn=*{v}*)(mail=*{v}*))",
        _ATTRS,
    )
    # ponytail: fetches all matches then slices; fine for a few hundred accounts.
    return [_parse(attrs) for _, attrs in results if attrs][:limit]


def get_ag_members(ag_name: str) -> list[dict]:
    """Return members of LDAP group cn=<ag_name>,<LDAP_GROUPS_BASE>."""
    group_dn = f"cn={ldap.filter.escape_filter_chars(ag_name)},{settings.LDAP_GROUPS_BASE}"
    conn = _connect()
    results = conn.search_s(
        settings.LDAP_USER_SEARCH_BASE,
        ldap.SCOPE_SUBTREE,
        f"(memberOf={group_dn})",
        _ATTRS,
    )
    return [_parse(attrs) for _, attrs in results if attrs]


def get_mail_by_uuid(intranet_uuid) -> str | None:
    """Current FreeIPA `mail` of the account with this ipaUniqueID; None if the
    account doesn't exist (anymore) or has no mail. Raises on LDAP errors."""
    conn = _connect()
    results = conn.search_s(
        settings.LDAP_USER_SEARCH_BASE,
        ldap.SCOPE_SUBTREE,
        f"(ipaUniqueID={ldap.filter.escape_filter_chars(str(intranet_uuid))})",
        ["mail"],
    )
    found = [_parse(attrs)["email"] for _, attrs in results if attrs]
    return found[0] if found and found[0] else None


def is_ldap_mail_taken(email: str, exclude_username: str | None = None) -> bool:
    """Return True if email is already in use by another intranet account in FreeIPA."""
    if not getattr(settings, "LDAP_SERVER_URI", None):
        return False
    try:
        conn = _connect()
        results = conn.search_s(
            settings.LDAP_USER_SEARCH_BASE,
            ldap.SCOPE_SUBTREE,
            f"(mail={ldap.filter.escape_filter_chars(email)})",
            ["uid"],
        )
        for _, attrs in results:
            if not attrs:
                continue
            uids = attrs.get("uid", [])
            uid = uids[0].decode() if isinstance(uids[0], bytes) else uids[0]
            if not exclude_username or uid != exclude_username:
                return True
        return False
    except Exception as exc:
        logger.warning("LDAP email uniqueness check skipped: %s", exc)
        return False


# --- Writes (CArtei -> FreeIPA) -------------------------------------------
# Email: FreeIPA `mail` is the source of truth for linked tenants; tenant.email
# is a read-through cache (see app/emails.current_email). CArtei edits are
# written through here first. A raw LDAP `add` can NOT create a working FreeIPA
# user (the DNA plugin must assign uidNumber and the Kerberos principal is built
# server-side), so all writes go through the IPA JSON-RPC API via python-freeipa,
# as svc-cartei ("CArtei Provisioner" role, see operations.md).

def _ipa_client():
    if not settings.IPA_SERVER:
        raise RuntimeError("IPA_SERVER not configured")
    from python_freeipa import ClientMeta  # lazy: only the write paths need the dep
    client = ClientMeta(settings.IPA_SERVER, verify_ssl=settings.IPA_VERIFY_SSL)
    client.login(settings.IPA_PROVISION_USER, settings.IPA_PROVISION_PASSWORD)
    return client


def set_ldap_mail(uid: str, email: str) -> None:
    """Write a tenant's email to FreeIPA. Raises on failure — the caller must not
    save the DB change then, or the next cache refresh would silently undo it."""
    from python_freeipa.exceptions import BadRequest
    try:
        _ipa_client().user_mod(a_uid=uid, o_mail=email)
    except BadRequest as exc:
        if getattr(exc, "code", None) != 4202:  # EmptyModlist: mail already equal
            raise

class GroupIPAError(Exception):
    """Changing a FreeIPA group membership failed."""


class ClearanceIPAError(GroupIPAError):
    """Changing the clearance group membership in FreeIPA failed."""


_ALREADY_MEMBER = "This entry is already a member"
_NOT_MEMBER = "This entry is not a member"


def _change_membership(method: str, cn: str, uid: str, benign: str,
                       error: type[GroupIPAError] = GroupIPAError) -> None:
    import requests
    from python_freeipa.exceptions import FreeIPAError
    try:
        reply = getattr(_ipa_client(), method)(a_cn=cn, o_user=[uid])
    except (FreeIPAError, RuntimeError, requests.RequestException) as exc:
        raise error(str(exc)) from exc
    # python-freeipa returns the RPC "result" dict: {"result", "failed", "completed"}
    benign_seen = False
    for _, msg in reply.get("failed", {}).get("member", {}).get("user", []):
        if msg != benign:
            raise error(msg)
        benign_seen = True
    # Fail closed: nothing changed and no "already (not) a member" → unexplained.
    if reply.get("completed", 0) < 1 and not benign_seen:
        raise error(f"IPA {method} für {uid} ohne Wirkung: {reply!r}")


def add_clearance_member(uid: str) -> None:
    _change_membership("group_add_member", _dn_to_cn(settings.LDAP_REQUIRE_GROUP), uid,
                       _ALREADY_MEMBER, ClearanceIPAError)


def remove_clearance_member(uid: str) -> None:
    _change_membership("group_remove_member", _dn_to_cn(settings.LDAP_REQUIRE_GROUP), uid,
                       _NOT_MEMBER, ClearanceIPAError)


# AG/INI self-service (app.views.ag_membership). svc-cartei may only write
# `member` of ag.*/in.* groups (operations.md); "only yourself" and "no rights
# groups" are app-side checks in the view.
def add_group_member(cn: str, uid: str) -> None:
    _change_membership("group_add_member", cn, uid, _ALREADY_MEMBER)


def remove_group_member(cn: str, uid: str) -> None:
    _change_membership("group_remove_member", cn, uid, _NOT_MEMBER)


def list_self_service_groups() -> list[dict]:
    """Every ag.* / in.* group in FreeIPA as {"cn", "description"}, sorted by cn.
    Read live (Django only knows groups someone has logged in with). Raises
    ldap.LDAPError; callers drop rights groups."""
    results = _connect().search_s(
        settings.LDAP_GROUPS_BASE, ldap.SCOPE_SUBTREE,
        "(|(cn=ag.*)(cn=in.*))", ["cn", "description"],
    )

    def first(attrs, key):
        return attrs.get(key, [b""])[0].decode()

    return sorted(
        ({"cn": first(a, "cn"), "description": first(a, "description")} for dn, a in results if dn),
        key=lambda g: g["cn"],
    )


def user_memberships(uid: str) -> tuple[set[str], set[str]]:
    """(all, direct) group cns of a user, read fresh. `all` is memberOf, which
    includes nested memberships just like the Keycloak groups claim; `direct` are
    the groups whose `member` lists the user (only those can be left via IPA).
    Raises ldap.LDAPError, or LookupError if the uid isn't exactly one entry."""
    conn = _connect()
    users = [(dn, a) for dn, a in conn.search_s(
        settings.LDAP_USER_SEARCH_BASE, ldap.SCOPE_SUBTREE,
        f"(uid={ldap.filter.escape_filter_chars(uid)})", ["memberOf"],
    ) if dn]
    if len(users) != 1:
        raise LookupError(f"LDAP: {len(users)} Konten für uid {uid}")
    user_dn, attrs = users[0]
    groups_suffix = "," + settings.LDAP_GROUPS_BASE.lower()
    # memberOf also lists roles, privileges, HBAC/sudo rules — keep only groups.
    all_cns = {
        _dn_to_cn(dn) for dn in (v.decode() for v in attrs.get("memberOf", []))
        if dn.lower().endswith(groups_suffix)
    }
    direct = {
        a["cn"][0].decode() for dn, a in conn.search_s(
            settings.LDAP_GROUPS_BASE, ldap.SCOPE_SUBTREE,
            f"(member={ldap.filter.escape_filter_chars(user_dn)})", ["cn"],
        ) if dn
    }
    return all_cns, direct


_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                         "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def _uid_base(tenant) -> str:
    """firstname_lastname, transliterated to ASCII, lowercased (org convention,
    e.g. philipp_bartz)."""
    raw = f"{tenant.first_name}_{tenant.last_name}".translate(_UMLAUT).lower()
    return "".join(c for c in raw if c.isalnum() or c == "_").strip("_")


def _uid_candidates(base: str, limit: int = 50):
    """base, then base2, base3, … — for collision retry on user_add."""
    yield base
    for n in range(2, limit + 1):
        yield f"{base}{n}"


def provision_ldap_account(tenant) -> ProvisionResult:
    """Create a FreeIPA account from a DB Tenant row and link it back.

    Returns ProvisionResult(uid, temp_password). The account is created with
    `--random`: IPA sets a one-time password (must be changed on first use) as
    part of the add, so this needs no password-reset privilege. Delivering that
    temp password to the tenant is a separate onboarding step. Raises if the
    tenant is already linked, IPA is unconfigured, or user_add fails.
    """
    if tenant.intranet_username:
        raise ValueError(f"Tenant {tenant.pk} already linked to {tenant.intranet_username!r}")
    client = _ipa_client()
    from python_freeipa.exceptions import DuplicateEntry

    res = uid = None
    for candidate in _uid_candidates(_uid_base(tenant)):
        try:
            res = client.user_add(
                a_uid=candidate,
                o_givenname=tenant.first_name,
                o_sn=tenant.last_name,
                o_cn=f"{tenant.first_name} {tenant.last_name}",
                o_mail=tenant.email,
                o_random=True,
            )
            uid = candidate
            break
        except DuplicateEntry:
            continue
    if res is None:
        raise RuntimeError(f"No free uid for tenant {tenant.pk} (base {_uid_base(tenant)!r})")
    result = res["result"]
    ipa_uuid = result["ipauniqueid"][0]
    temp_password = result.get("randompassword")
    if isinstance(temp_password, (list, tuple)):  # IPA may return it wrapped
        temp_password = temp_password[0]

    tenant.intranet_username = uid
    tenant.intranet_uuid = uuid_module.UUID(ipa_uuid)
    tenant.email_refreshed_at = timezone.now()  # FreeIPA mail was just set from it
    tenant.save(update_fields=["intranet_username", "intranet_uuid", "email_refreshed_at"])
    logger.info("Provisioned FreeIPA account %r for tenant %s", uid, tenant.pk)
    return ProvisionResult(uid, temp_password)
