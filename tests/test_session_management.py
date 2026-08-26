from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from app.models import UserSession


def _admin(username="admin"):
    user = User.objects.create_user(username=username, password="pw")
    group, _ = Group.objects.get_or_create(name="admins")
    user.groups.add(group)
    return user


def _live_session(key, username, when=None):
    Session.objects.create(
        session_key=key, session_data="",
        expire_date=timezone.now() + timedelta(days=1),
    )
    return UserSession.objects.create(
        session_key=key, username=username,
        ip_address="10.0.0.1", user_agent="Firefox",
        created_at=when or timezone.now(),
    )


@pytest.mark.django_db
def test_login_records_session_metadata():
    User.objects.create_user(username="alice", password="pw")
    client = Client()
    assert client.login(username="alice", password="pw")  # fires user_logged_in
    row = UserSession.objects.get(username="alice")
    assert row.session_key == client.session.session_key


@pytest.mark.django_db
def test_logout_drops_session_metadata():
    User.objects.create_user(username="alice", password="pw")
    client = Client()
    client.login(username="alice", password="pw")
    client.logout()
    assert not UserSession.objects.filter(username="alice").exists()


@pytest.mark.django_db
def test_session_management_requires_admin():
    client = Client()
    client.force_login(User.objects.create_user(username="nobody", password="pw"))
    assert client.get("/admin/sessions/").status_code == 403


@pytest.mark.django_db
def test_session_management_lists_live_sessions_only():
    _live_session("live1", "alice")
    # metadata with no matching Session row must not show up
    UserSession.objects.create(
        session_key="orphan", username="ghost", created_at=timezone.now()
    )
    client = Client()
    client.force_login(_admin())
    content = client.get("/admin/sessions/").content
    assert b"alice" in content
    assert b"ghost" not in content


@pytest.mark.django_db
def test_revoke_single_session():
    _live_session("k1", "alice")
    client = Client()
    client.force_login(_admin())
    resp = client.post("/admin/sessions/k1/revoke/")
    assert resp.status_code == 302
    assert not Session.objects.filter(session_key="k1").exists()
    assert not UserSession.objects.filter(session_key="k1").exists()


@pytest.mark.django_db
def test_invalidate_all_sessions_of_user():
    _live_session("k1", "alice")
    _live_session("k2", "alice")
    _live_session("k3", "bob")
    client = Client()
    client.force_login(_admin())
    resp = client.post("/admin/sessions/user/alice/revoke/")
    assert resp.status_code == 302
    assert not UserSession.objects.filter(username="alice").exists()
    assert not Session.objects.filter(session_key__in=["k1", "k2"]).exists()
    assert UserSession.objects.filter(username="bob").exists()  # untouched
