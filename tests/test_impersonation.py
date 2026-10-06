import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP
from app.models import ImpersonationEvent


def _make_impersonator(username="super"):
    """A user who may impersonate: member of the cartei_impersonation group."""
    user = User.objects.create_user(username, password="pw")
    user.groups.add(Group.objects.get_or_create(name=IMPERSONATION_GROUP)[0])
    return user


@pytest.mark.django_db
def test_only_impersonation_group_can_choose_and_start(client):
    admin = User.objects.create_user("admin", password="pw")
    admin.groups.add(Group.objects.create(name="admins"))  # admin role, but NOT impersonation
    target = User.objects.create_user("resident", password="pw")

    client.force_login(admin)
    assert client.get(reverse("impersonation_choose")).status_code == 403
    assert client.post(reverse("impersonation_start", args=[target.pk])).status_code == 403
    assert IMPERSONATED_USER_SESSION_KEY not in client.session

    client.force_login(_make_impersonator())
    assert client.get(reverse("impersonation_choose")).status_code == 200
    assert client.get(reverse("impersonation_start", args=[target.pk])).status_code == 405
    assert client.post(reverse("impersonation_start", args=[target.pk])).status_code == 302


@pytest.mark.django_db
def test_impersonation_uses_target_roles_and_can_be_stopped(client):
    original = _make_impersonator()
    target = User.objects.create_user("resident", password="pw")
    client.force_login(original)

    response = client.post(reverse("impersonation_start", args=[target.pk]))
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(original.pk)
    assert client.session[IMPERSONATED_USER_SESSION_KEY] == target.pk

    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert response.wsgi_request.user.pk == target.pk
    assert response.wsgi_request.impersonator.pk == original.pk
    assert b"Du arbeitest als " in response.content
    assert client.get(reverse("admin_portal")).status_code == 403
    assert client.get(reverse("impersonation_choose")).status_code == 403

    assert client.get(reverse("impersonation_stop")).status_code == 405
    assert client.post(reverse("impersonation_stop")).status_code == 302
    assert IMPERSONATED_USER_SESSION_KEY not in client.session
    assert client.session["_auth_user_id"] == str(original.pk)
    response = client.get(reverse("impersonation_choose"))
    assert response.status_code == 200
    assert response.wsgi_request.user.pk == original.pk


@pytest.mark.django_db
def test_invalid_or_forged_impersonation_is_cleared(client):
    regular = User.objects.create_user("regular", password="pw")  # not in impersonation group
    target = User.objects.create_user("target", password="pw")
    client.force_login(regular)
    session = client.session
    session[IMPERSONATED_USER_SESSION_KEY] = target.pk
    session.save()
    response = client.get(reverse("dashboard"))
    assert response.wsgi_request.user.pk == regular.pk
    assert IMPERSONATED_USER_SESSION_KEY not in client.session

    original = _make_impersonator()
    client.force_login(original)
    client.post(reverse("impersonation_start", args=[target.pk]))
    target.is_active = False
    target.save(update_fields=["is_active"])
    response = client.get(reverse("impersonation_choose"))
    assert response.status_code == 200
    assert response.wsgi_request.user.pk == original.pk
    assert IMPERSONATED_USER_SESSION_KEY not in client.session
    assert client.post(reverse("impersonation_start", args=[target.pk])).status_code == 404
    # Cannot impersonate another impersonation-group member.
    assert client.post(reverse("impersonation_start", args=[original.pk])).status_code == 404


@pytest.mark.django_db
def test_start_and_stop_are_audited(client):
    original = _make_impersonator()
    target = User.objects.create_user("resident", password="pw")
    client.force_login(original)

    client.post(reverse("impersonation_start", args=[target.pk]))
    start = ImpersonationEvent.objects.get(action=ImpersonationEvent.Action.START)
    assert start.impersonator_username == "super"
    assert start.target_username == "resident"

    # Establish the impersonated session, then stop.
    client.get(reverse("dashboard"))
    client.post(reverse("impersonation_stop"))
    stop = ImpersonationEvent.objects.get(action=ImpersonationEvent.Action.STOP)
    assert stop.impersonator_username == "super"
    assert stop.target_username == "resident"
    assert ImpersonationEvent.objects.count() == 2
