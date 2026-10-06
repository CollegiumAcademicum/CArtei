import logging
import uuid as uuid_module

from django.conf import settings
from django.contrib.auth.models import Group
from django_auth_ldap.backend import LDAPBackend

logger = logging.getLogger(__name__)

# Prefixes of the org working groups (AGs, Gremien, Institute) that a user can
# belong to. Rights-granting groups ("admins" and — as a dev placeholder — the
# groups mapped via CARTEI_ADMIN_GROUP/CARTEI_CLUSTER_GROUP) are tracked
# separately as markers; in the final deployment those live outside these
# prefixes, so filtering on them keeps rights groups out of the AG display.
GROUP_PREFIXES = ("ag.", "gr.", "in.")


def _dn_to_cn(dn: str) -> str:
    for part in dn.split(","):
        if part.lower().startswith("cn="):
            return part[3:]
    return dn


def ag_group_names(user) -> list[str]:
    """The user's org working groups (ag./gr./in.), sorted, for dashboard
    display. Non-prefixed rights markers like 'admins' are excluded."""
    return sorted(
        g for g in user.groups.values_list("name", flat=True)
        if g.startswith(GROUP_PREFIXES)
    )


class CustomLDAPBackend(LDAPBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(request, username, password, **kwargs)
        if user is not None:
            self._sync_groups(user)
            self._ensure_tenant(user)
        return user

    def _sync_groups(self, user) -> None:
        admin_dn = getattr(settings, "CARTEI_ADMIN_GROUP", "").lower()
        cluster_dn = getattr(settings, "CARTEI_CLUSTER_GROUP", "").lower()
        mietverwaltung_dn = getattr(settings, "CARTEI_MIETVERWALTUNG_GROUP", "").lower()
        helper_dn = getattr(settings, "CARTEI_HELFER_MIETVERWALTUNG_GROUP", "").lower()
        superuser_dn = getattr(settings, "CARTEI_SUPERUSER_GROUP", "").lower()
        try:
            member_of: list[str] = user.ldap_user.attrs.get("memberOf", [])
            desired: set[str] = set()
            is_superuser = False
            for dn in member_of:
                dn_l = dn.lower()
                if dn_l == superuser_dn:
                    is_superuser = True
                # Rights groups (cartei_admin/cluster/cartei_mietverwaltung) map to
                # fixed marker names; they aren't AG-prefixed so they never appear
                # in the dashboard AG list. A DN could still be a rights group AND
                # a prefixed AG, so checks are independent (not elif).
                if dn_l == admin_dn:
                    desired.add("admins")
                if dn_l == cluster_dn:
                    desired.add("gr.cluster")
                if dn_l == mietverwaltung_dn:
                    desired.add("cartei_mietverwaltung")
                if dn_l == helper_dn:
                    desired.add("cartei_helfer_mietverwaltung")
                cn = _dn_to_cn(dn)
                if cn.startswith(GROUP_PREFIXES):
                    desired.add(cn)
            current = set(user.groups.values_list("name", flat=True))
            for name in desired - current:
                group, _ = Group.objects.get_or_create(name=name)
                user.groups.add(group)
            for name in current - desired:
                try:
                    user.groups.remove(Group.objects.get(name=name))
                except Group.DoesNotExist:
                    pass
            # is_superuser is bound to CARTEI_SUPERUSER_GROUP (authoritative:
            # membership grants it, absence revokes it). Always enforced — the
            # setting falls back to the standard DN, so it is never blank.
            if user.is_superuser != is_superuser:
                user.is_superuser = is_superuser
                user.save(update_fields=["is_superuser"])
        except Exception as exc:
            logger.error(f"Group sync failed for {user.username!r}: {exc}")

    def _ensure_tenant(self, user) -> None:
        from app.models import Tenant
        if Tenant.objects.filter(intranet_username=user.username).exists():
            return
        try:
            uuid_raw = user.ldap_user.attrs.get("ipaUniqueID", [None])[0]
            if isinstance(uuid_raw, bytes):
                uuid_raw = uuid_raw.decode()
            try:
                intranet_uuid = uuid_module.UUID(uuid_raw)
            except (ValueError, AttributeError):
                intranet_uuid = None
            Tenant.objects.create(
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                email=user.email or "",
                intranet_username=user.username,
                intranet_uuid=intranet_uuid or uuid_module.uuid4(),
            )
        except Exception as exc:
            logger.error(f"Failed to auto-create Tenant for {user.username!r}: {exc}")
