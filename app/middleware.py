from django.db import connection, transaction


def _set_audit_actor(conn, username: str, source: str = "HUMAN") -> None:
    # Trigger-based audit reads these Postgres settings; SQLite (tests) has no set_config.
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as c:
        c.execute("SELECT set_config('cartei.changed_by', %s, true)", [username])
        c.execute("SELECT set_config('cartei.change_source', %s, true)", [source])


class AuditActorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(request.user, "is_authenticated", False):
            return self.get_response(request)
        with transaction.atomic():
            _set_audit_actor(connection, request.user.username)
            return self.get_response(request)
