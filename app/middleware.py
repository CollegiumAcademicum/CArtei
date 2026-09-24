from django.contrib.auth import get_user_model
from django.db import connection, transaction


IMPERSONATED_USER_SESSION_KEY = "cartei_impersonated_user_id"


def _set_audit_actor(conn, username: str, source: str = "HUMAN") -> None:
    # Trigger-based audit reads these Postgres settings; SQLite (tests) has no set_config.
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as c:
        c.execute("SELECT set_config('cartei.changed_by', %s, true)", [username])
        c.execute("SELECT set_config('cartei.change_source', %s, true)", [source])


class ImpersonationMiddleware:
    """Use the selected account for authorization while retaining the real login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonator = None
        real_user = request.user
        target_id = request.session.get(IMPERSONATED_USER_SESSION_KEY)
        if target_id is not None:
            if not real_user.is_authenticated or not real_user.is_active or not real_user.is_superuser:
                request.session.pop(IMPERSONATED_USER_SESSION_KEY, None)
            else:
                target = get_user_model().objects.filter(
                    pk=target_id, is_active=True, is_superuser=False,
                ).first()
                if target is None:
                    request.session.pop(IMPERSONATED_USER_SESSION_KEY, None)
                else:
                    request.impersonator = real_user
                    request.user = target
        return self.get_response(request)


class AuditActorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(request.user, "is_authenticated", False):
            return self.get_response(request)
        with transaction.atomic():
            impersonator = getattr(request, "impersonator", None)
            actor = (
                f"{impersonator.username} (als {request.user.username})"
                if impersonator else request.user.username
            )
            _set_audit_actor(connection, actor)
            return self.get_response(request)
