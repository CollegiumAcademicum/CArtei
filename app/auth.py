import logging
import uuid as uuid_module
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import Group, User
from django.core.exceptions import SuspiciousOperation
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView

from app.ldap_utils import _dn_to_cn  # noqa: F401  (re-exported)
from app.middleware import IMPERSONATION_GROUP

logger = logging.getLogger(__name__)

# Prefixes of the org working groups (AGs, Gremien, Institute) that a user can
# belong to. Rights-granting groups ("admins" and — as a dev placeholder — the
# groups mapped via CARTEI_ADMIN_GROUP/CARTEI_CLUSTER_GROUP) are tracked
# separately as markers; in the final deployment those live outside these
# prefixes, so filtering on them keeps rights groups out of the AG display.
GROUP_PREFIXES = ("ag.", "gr.", "in.")


def ag_group_names(user) -> list[str]:
    """The user's org working groups (ag./gr./in.), sorted, for dashboard
    display. Non-prefixed rights markers like 'admins' are excluded."""
    return sorted(
        g for g in user.groups.values_list("name", flat=True)
        if g.startswith(GROUP_PREFIXES)
    )


# Keycloak claim carrying FreeIPA's ipaUniqueID (user-attribute mapper on the
# cartei client). It is the identity anchor: uids can be renamed, it can't.
UUID_CLAIM = "ipaUniqueID"


def claim_group_names(claims) -> set[str]:
    """Group names from the Keycloak "groups" claim; tolerates full paths ("/ag.it")."""
    return {g.rsplit("/", 1)[-1] for g in claims.get("groups", [])}


def keycloak_logout_url(request) -> str:
    """End the Keycloak session too, else "Abmelden" signs straight back in."""
    id_token = request.session.get("oidc_id_token")
    if not id_token:  # not a Keycloak login (e.g. /dev-login/)
        return settings.LOGOUT_REDIRECT_URL
    params = {
        "id_token_hint": id_token,
        "post_logout_redirect_uri": request.build_absolute_uri(settings.LOGOUT_REDIRECT_URL),
    }
    return f"{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(params)}"


class KeycloakCallbackView(OIDCAuthenticationCallbackView):
    """OIDC callback, also hit by SessionRefresh's silent re-check every
    OIDC_RENEW_ID_TOKEN_EXPIRY_SECONDS — which re-runs the backend, so groups,
    clearance and email are re-synced (CArtei#69)."""

    def get(self, request):
        if request.GET.get("error") in ("login_required", "interaction_required"):
            # Silent re-check found no Keycloak session (idle/expired): log in
            # interactively and come back to the page instead of the error page.
            next_url = request.session.get("oidc_login_next") or "/"
            auth.logout(request)
            return redirect(f"{reverse('login')}?{urlencode({'next': next_url})}")
        return super().get(request)

    def login_success(self):
        # While impersonating, request.user is the target; compare against the real
        # login so a refresh doesn't re-login (and rotate the CSRF token) needlessly.
        if impersonator := getattr(self.request, "impersonator", None):
            self.request.user = impersonator
        return super().login_success()

    def login_failure(self):
        # A failed re-check (clearance removed, account disabled) must end the
        # session — the library would leave it alive and bounce on every page load.
        if self.request.user.is_authenticated:
            auth.logout(self.request)
        return super().login_failure()


class KeycloakOIDCBackend(OIDCAuthenticationBackend):
    def verify_claims(self, claims):
        return bool(
            claims.get(UUID_CLAIM)
            and claims.get("preferred_username")
            and _dn_to_cn(settings.LDAP_REQUIRE_GROUP) in claim_group_names(claims)
        )

    def get_or_create_user(self, access_token, id_token, payload):
        claims = self.get_userinfo(access_token, id_token, payload)
        if not self.verify_claims(claims):
            raise SuspiciousOperation(
                f"Claims verification failed for {claims.get('preferred_username')!r}"
            )
        try:
            intranet_uuid = uuid_module.UUID(claims[UUID_CLAIM])
        except ValueError:
            raise SuspiciousOperation(f"Invalid {UUID_CLAIM} {claims[UUID_CLAIM]!r}")
        username = claims["preferred_username"]
        try:
            with transaction.atomic():
                self._link_tenant(intranet_uuid, username, claims)
                user, _ = User.objects.get_or_create(username=username)
                user.first_name = claims.get("given_name", "")
                user.last_name = claims.get("family_name", "")
                user.email = claims.get("email", "")
                user.save()
        except IntegrityError as exc:
            raise SuspiciousOperation(f"Identity conflict for {username!r}: {exc}")
        self._sync_groups(user, claim_group_names(claims))
        return user

    def _link_tenant(self, intranet_uuid, username, claims) -> None:
        """Find the tenant by uuid (create on first login); follow uid renames and
        refresh the email cache from the claim (FreeIPA mail is the SSOT)."""
        from app.models import Tenant
        email = claims.get("email", "")
        refreshed_at = timezone.now() if email else None
        tenant = Tenant.objects.filter(intranet_uuid=intranet_uuid).first()
        if tenant is None:
            if Tenant.objects.filter(intranet_username=username).exists():
                raise SuspiciousOperation(
                    f"Tenant {username!r} is linked to a different intranet uuid than {intranet_uuid}"
                )
            Tenant.objects.create(
                first_name=claims.get("given_name", ""),
                last_name=claims.get("family_name", ""),
                email=email,
                email_refreshed_at=refreshed_at,
                intranet_username=username,
                intranet_uuid=intranet_uuid,
            )
            return
        old = tenant.intranet_username
        fields = []
        if old != username:
            logger.info(f"Intranet uid renamed {old!r} -> {username!r} ({intranet_uuid})")
            tenant.intranet_username = username
            fields.append("intranet_username")
            if old:
                User.objects.filter(username=old).update(username=username)
        if email:
            tenant.email, tenant.email_refreshed_at = email, refreshed_at
            fields += ["email", "email_refreshed_at"]
        if fields:
            tenant.save(update_fields=fields)

    def _sync_groups(self, user, group_names: set[str]) -> None:
        markers = {
            _dn_to_cn(getattr(settings, name, "")).lower(): marker
            for name, marker in (
                ("CARTEI_IMPERSONATION_GROUP", IMPERSONATION_GROUP),
                ("CARTEI_ADMIN_GROUP", "admins"),
                ("CARTEI_CLUSTER_GROUP", "gr.cluster"),
                ("CARTEI_MIETVERWALTUNG_GROUP", "cartei_mietverwaltung"),
                ("CARTEI_HELFER_MIETVERWALTUNG_GROUP", "cartei_helfer_mietverwaltung"),
                ("CARTEI_GRANT_CLEARANCE_GROUP", "cartei_grant_clearance"),
            )
            if getattr(settings, name, "")
        }
        # Rights groups map to fixed marker names; they aren't AG-prefixed so they
        # never appear in the dashboard AG list. A group can be a rights group AND
        # a prefixed group (gr.cluster), so both checks apply.
        desired: set[str] = set()
        for cn in group_names:
            if marker := markers.get(cn.lower()):
                desired.add(marker)
            if cn.startswith(GROUP_PREFIXES):
                desired.add(cn)
        current = set(user.groups.values_list("name", flat=True))
        for name in desired - current:
            group, _ = Group.objects.get_or_create(name=name)
            user.groups.add(group)
        user.groups.remove(*Group.objects.filter(name__in=current - desired))
