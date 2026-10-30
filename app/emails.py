"""Outgoing mail (SMTP). Fire-and-forget notifications — not routed through the
ticket system, so one-time secrets don't get persisted in ticket history."""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from app.ldap_utils import get_mail_by_uuid

logger = logging.getLogger(__name__)


def current_email(tenant) -> str:
    """The address to send to. Email source of truth (CArtei#70):

    - linked tenant (has intranet_uuid): FreeIPA `mail`. tenant.email is only a
      cache, refreshed here (and at login) and stamped with email_refreshed_at;
    - unlinked tenant, deleted account, or LDAP down: the cached tenant.email —
      the only copy before provisioning and after move-out.

    Every outgoing mail must resolve its recipient through this.
    """
    if not tenant.intranet_uuid:
        return tenant.email
    try:
        mail = get_mail_by_uuid(tenant.intranet_uuid)
    except Exception as exc:
        logger.warning("Email refresh failed for tenant %s, using cache: %s", tenant.pk, exc)
        return tenant.email
    if mail:
        tenant.email, tenant.email_refreshed_at = mail, timezone.now()
        tenant.save(update_fields=["email", "email_refreshed_at"])
    return tenant.email


def send_welcome_email(tenant, uid, temp_password) -> None:
    """Email a freshly provisioned tenant their intranet credentials.

    Raises on SMTP/render failure — the caller decides whether to surface it
    (the account already exists, so a mail failure must not undo provisioning).
    """
    body = render_to_string("app/emails/welcome.txt", {
        "name": tenant.first_name,
        "uid": uid,
        "temp_password": temp_password,
        "intranet_url": getattr(settings, "INTRANET_URL", ""),
        "guide_url": getattr(settings, "PASSWORD_GUIDE_URL", ""),
    })
    send_mail(
        subject="Deine Zugangsdaten für das CA-Intranet / Your CA intranet login",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[current_email(tenant)],
        fail_silently=False,
    )
