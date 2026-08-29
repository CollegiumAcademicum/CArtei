"""Outgoing mail (SMTP). Fire-and-forget notifications — not routed through the
ticket system, so one-time secrets don't get persisted in ticket history."""
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string


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
        recipient_list=[tenant.email],
        fail_silently=False,
    )
