"""LDAP helper functions for querying group members.

These functions are only called from views that require cluster/admin access.
In tests, patch `app.views.admin_views.ldap_utils.get_clearance_members` and `get_ag_members`.
"""
import ldap
import ldap.filter
from django.conf import settings


def _connect():
    for opt, val in getattr(settings, "AUTH_LDAP_GLOBAL_OPTIONS", {}).items():
        ldap.set_option(opt, val)
    conn = ldap.initialize(settings.AUTH_LDAP_SERVER_URI)
    conn.simple_bind_s(settings.AUTH_LDAP_BIND_DN, settings.AUTH_LDAP_BIND_PASSWORD)
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
