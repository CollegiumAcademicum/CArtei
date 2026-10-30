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


# --- Provisioning (CArtei -> FreeIPA) ------------------------------------
# The DB (tenant.email) is the source of truth; FreeIPA is a downstream replica
# CArtei writes. A raw LDAP `add` can NOT create a working FreeIPA user (the DNA
# plugin must assign uidNumber and the Kerberos principal is built server-side),
# so provisioning goes through the IPA JSON-RPC API via python-freeipa.

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
    if not settings.IPA_SERVER:
        raise RuntimeError("IPA_SERVER not configured — cannot provision")

    from python_freeipa import ClientMeta  # lazy: only this path needs the dep
    from python_freeipa.exceptions import DuplicateEntry

    client = ClientMeta(settings.IPA_SERVER, verify_ssl=settings.IPA_VERIFY_SSL)
    client.login(settings.IPA_PROVISION_USER, settings.IPA_PROVISION_PASSWORD)

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
    tenant.save(update_fields=["intranet_username", "intranet_uuid"])
    logger.info("Provisioned FreeIPA account %r for tenant %s", uid, tenant.pk)
    return ProvisionResult(uid, temp_password)


# --- Drift detection (admin edited mail in FreeIPA, bypassing CArtei) -----

def _email_mismatches(db_by_uid: dict[str, str], ldap_by_uid: dict[str, str]) -> list[dict]:
    """Pure comparison: linked tenants whose DB email differs from LDAP mail.
    Missing LDAP entries are reported too (account deleted out-of-band)."""
    out = []
    for uid, db_email in db_by_uid.items():
        ldap_email = ldap_by_uid.get(uid)
        if ldap_email is None:
            out.append({"uid": uid, "db_email": db_email, "ldap_email": None})
        elif (db_email or "").strip().lower() != ldap_email.strip().lower():
            out.append({"uid": uid, "db_email": db_email, "ldap_email": ldap_email})
    return out


def find_email_drift() -> list[dict]:
    """Compare tenant.email (SSOT) against FreeIPA mail for all linked tenants.
    Read-only — reports drift for a human, never auto-corrects (an admin edit
    might be a legit emergency fix; silently reverting would hide it)."""
    from app.models import Tenant

    db_by_uid = {
        t.intranet_username: t.email
        for t in Tenant.objects.exclude(intranet_username__isnull=True)
        .exclude(intranet_username="")
        .only("intranet_username", "email")
    }
    if not db_by_uid:
        return []

    conn = _connect()
    uid_filter = "".join(
        f"(uid={ldap.filter.escape_filter_chars(u)})" for u in db_by_uid
    )
    results = conn.search_s(
        settings.LDAP_USER_SEARCH_BASE,
        ldap.SCOPE_SUBTREE,
        f"(|{uid_filter})",
        ["uid", "mail"],
    )
    ldap_by_uid = {p["username"]: p["email"] for _, a in results if (p := _parse(a))["username"]}
    return _email_mismatches(db_by_uid, ldap_by_uid)
