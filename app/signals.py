import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.utils import timezone

from app.models import UserSession

logger = logging.getLogger(__name__)


def _client_ip(request):
    # Behind the reverse proxy, REMOTE_ADDR is the proxy; prefer the first hop
    # of X-Forwarded-For when present.
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@receiver(user_logged_in)
def record_session(sender, request, user, **kwargs):
    """Snapshot login metadata so admins can list/revoke a user's devices.
    session_key is already set here — login() cycles the key before firing this."""
    key = request.session.session_key
    if not key:
        return
    try:
        UserSession.objects.update_or_create(
            session_key=key,
            defaults={
                "username": user.get_username(),
                "ip_address": _client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:2000],
                "created_at": timezone.now(),
            },
        )
    except Exception as exc:
        logger.error(f"Failed to record session for {user.get_username()!r}: {exc}")


@receiver(user_logged_out)
def drop_session(sender, request, user, **kwargs):
    key = getattr(getattr(request, "session", None), "session_key", None)
    if key:
        UserSession.objects.filter(session_key=key).delete()
