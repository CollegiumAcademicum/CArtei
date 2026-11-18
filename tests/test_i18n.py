import uuid

import pytest
from django.contrib.auth.models import Group, User

from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP
from app.models import Tenant

EN = {"HTTP_ACCEPT_LANGUAGE": "en-US,en;q=0.9"}
DE = {"HTTP_ACCEPT_LANGUAGE": "de-DE,de;q=0.9"}


def _make_tenant(username, locale=None, **extra):
    return Tenant.objects.create(
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
        first_name="Ada",
        last_name="Lovelace",
        preferred_name="Ada",
        locale=locale,
        **extra,
    )


def _login(client, username, locale=None):
    tenant = _make_tenant(username, locale)
    user = User.objects.create_user(username=username)
    client.force_login(user)
    return tenant, user


def _lang(response):
    return response["Content-Language"]


# --- language selection ---------------------------------------------------

@pytest.mark.django_db
def test_anonymous_default_is_german(client):
    assert _lang(client.get("/")) == "de"


@pytest.mark.django_db
def test_anonymous_follows_browser(client):
    assert _lang(client.get("/", **EN)) == "en"


@pytest.mark.django_db
def test_tenant_locale_wins_over_browser(client):
    _login(client, "ada", "de")
    assert _lang(client.get("/dashboard/", **EN)) == "de"


@pytest.mark.django_db
def test_tenant_locale_en_without_browser(client):
    _login(client, "ada", "en")
    assert _lang(client.get("/dashboard/")) == "en"


@pytest.mark.django_db
@pytest.mark.parametrize("loc", ["en-GB", "EN"])
def test_tenant_locale_primary_subtag(client, loc):
    _login(client, "ada", loc)
    assert _lang(client.get("/dashboard/", **DE)) == "en"


@pytest.mark.django_db
@pytest.mark.parametrize("loc", ["fr", "", None])
def test_unsupported_locale_falls_back_to_browser(client, loc):
    _login(client, "ada", loc)
    assert _lang(client.get("/dashboard/", **EN)) == "en"
    assert _lang(client.get("/dashboard/")) == "de"


@pytest.mark.django_db
def test_staff_without_tenant_follows_browser(client):
    client.force_login(User.objects.create_user(username="staff"))
    assert _lang(client.get("/dashboard/", **EN)) == "en"


@pytest.mark.django_db
def test_impersonation_uses_target_locale(client):
    _make_tenant("super", "de")
    impersonator = User.objects.create_user(username="super")
    impersonator.groups.add(Group.objects.get_or_create(name=IMPERSONATION_GROUP)[0])
    _make_tenant("target", "en")
    target = User.objects.create_user(username="target")
    client.force_login(impersonator)
    session = client.session
    session[IMPERSONATED_USER_SESSION_KEY] = target.pk
    session.save()
    assert _lang(client.get("/dashboard/")) == "en"


@pytest.mark.django_db
def test_german_after_english_request(client):
    assert _lang(client.get("/", **EN)) == "en"
    assert _lang(client.get("/", **DE)) == "de"


@pytest.mark.django_db
def test_vary_accept_language(client):
    assert "Accept-Language" in client.get("/")["Vary"]


@pytest.mark.django_db
def test_html_lang_attribute(client):
    assert '<html lang="en">' in client.get("/info/", **EN).content.decode()
