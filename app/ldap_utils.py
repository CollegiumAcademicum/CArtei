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
