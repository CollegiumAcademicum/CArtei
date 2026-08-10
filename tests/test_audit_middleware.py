from unittest.mock import MagicMock, patch

import pytest

from app.middleware import AuditActorMiddleware, _set_audit_actor


class _User:
    def __init__(self, authed, username="pbartz"):
        self.is_authenticated = authed
        self.username = username


def test_set_audit_actor_noop_on_sqlite():
    conn = MagicMock()
    conn.vendor = "sqlite"
    _set_audit_actor(conn, "pbartz")
    conn.cursor.assert_not_called()


def test_set_audit_actor_runs_on_postgres():
    conn = MagicMock()
    conn.vendor = "postgresql"
    cursor = conn.cursor.return_value.__enter__.return_value
    _set_audit_actor(conn, "pbartz")
    calls = [c.args for c in cursor.execute.call_args_list]
    assert any("set_config('cartei.changed_by'" in a[0] and a[1] == ["pbartz"] for a in calls)
    assert any("set_config('cartei.change_source'" in a[0] and a[1] == ["HUMAN"] for a in calls)


def test_middleware_skips_anonymous():
    get_response = MagicMock(return_value="resp")
    mw = AuditActorMiddleware(get_response)
    request = MagicMock()
    request.user = _User(authed=False)
    with patch("app.middleware._set_audit_actor") as spy:
        assert mw(request) == "resp"
        spy.assert_not_called()


@pytest.mark.django_db
def test_middleware_sets_actor_for_authenticated():
    get_response = MagicMock(return_value="resp")
    mw = AuditActorMiddleware(get_response)
    request = MagicMock()
    request.user = _User(authed=True, username="pbartz")
    with patch("app.middleware._set_audit_actor") as spy:
        assert mw(request) == "resp"
        spy.assert_called_once()
        assert spy.call_args.args[1] == "pbartz"
