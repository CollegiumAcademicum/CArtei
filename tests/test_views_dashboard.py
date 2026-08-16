import uuid
from datetime import date, timedelta
import pytest
from django.contrib.auth.models import User, Group
from django.test import Client
from app.models import AGAbfrage, Tenant


def _open_abfrage():
    today = date.today()
    return AGAbfrage.objects.create(
        date=today,
        label="Aktive Abfrage",
        ends_at=today + timedelta(days=7),
        grace_ends_at=today + timedelta(days=14),
    )


def _closed_abfrage():
    today = date.today()
    return AGAbfrage.objects.create(
        date=today - timedelta(days=30),
        ends_at=today - timedelta(days=15),
        grace_ends_at=today - timedelta(days=8),
    )


def _make_tenant(username):
    return Tenant.objects.create(
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
        first_name="Ada",
        last_name="Lovelace",
        preferred_name="Ada",
    )


@pytest.mark.django_db
def test_dashboard_requires_login():
    client = Client()
    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_dashboard_returns_200():
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_shows_tenant_name():
    user = User.objects.create_user(username="ada")
    _make_tenant("ada")
    client = Client()
    client.force_login(user)
    response = client.get("/dashboard/")
    assert b"Ada" in response.content


@pytest.mark.django_db
def test_dashboard_shows_open_abfrage():
    _open_abfrage()
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert b"Aktive Abfrage" in response.content


@pytest.mark.django_db
def test_dashboard_shows_no_abfrage_message_when_none():
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert b"Keine aktive Abfrage" in response.content


@pytest.mark.django_db
def test_dashboard_shows_no_abfrage_message_when_closed():
    _closed_abfrage()
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert b"Keine aktive Abfrage" in response.content


@pytest.mark.django_db
def test_dashboard_handles_missing_tenant():
    # User exists in auth but has no Tenant row — must not crash
    client = Client()
    client.force_login(User.objects.create_user(username="ghost"))
    response = client.get("/dashboard/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_shows_all_org_groups_but_not_rights_markers():
    # ag./gr./in. groups are the user's working groups and must all appear;
    # the non-prefixed "admins" rights marker must not.
    user = User.objects.create_user(username="member")
    for name in ["ag.kueche", "gr.cluster", "in.finanzen", "admins"]:
        g, _ = Group.objects.get_or_create(name=name)
        user.groups.add(g)
    client = Client()
    client.force_login(user)
    response = client.get("/dashboard/")
    assert b"ag.kueche" in response.content
    assert b"gr.cluster" in response.content
    assert b"in.finanzen" in response.content
    assert b"admins" not in response.content
