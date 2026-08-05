import logging
import uuid as uuid_module

from django.conf import settings
from django.contrib.auth.models import Group
from django_auth_ldap.backend import LDAPBackend

logger = logging.getLogger(__name__)


def _dn_to_cn(dn: str) -> str:
    for part in dn.split(","):
        if part.lower().startswith("cn="):
            return part[3:]
    return dn


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
        try:
            member_of: list[str] = user.ldap_user.attrs.get("memberOf", [])
            desired: set[str] = set()
            for dn in member_of:
                dn_l = dn.lower()
                if dn_l == admin_dn:
                    desired.add("admins")
                elif dn_l == cluster_dn:
                    desired.add("cluster")
                else:
                    cn = _dn_to_cn(dn)
                    if cn.startswith("ag."):
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
            intranet_uuid = uuid_module.UUID(uuid_raw) if uuid_raw else uuid_module.uuid4()
            Tenant.objects.create(
                first_name=user.first_name or "",
                last_name=user.last_name or "",
                email=user.email or "",
                intranet_username=user.username,
                intranet_uuid=intranet_uuid,
            )
        except Exception as exc:
            logger.error(f"Failed to auto-create Tenant for {user.username!r}: {exc}")
