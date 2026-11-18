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


# --- catalogue guard --------------------------------------------------------

def test_po_complete_and_mo_in_sync():
    import polib
    from django.conf import settings
    base = settings.LOCALE_PATHS[0] / "en/LC_MESSAGES"
    po = polib.pofile(str(base / "django.po"))
    mo = polib.mofile(str(base / "django.mo"))
    assert not po.untranslated_entries()
    assert not po.fuzzy_entries()
    assert ({e.msgid: e.msgstr for e in po.translated_entries()}
            == {e.msgid: e.msgstr for e in mo if e.msgid})


# --- dashboard --------------------------------------------------------------

@pytest.mark.django_db
def test_dashboard_english(client):
    _login(client, "ada", "en")
    body = client.get("/dashboard/").content.decode()
    assert "My profile" in body and "Mein Profil" not in body
    assert "Log out" in body and "Abmelden" not in body


@pytest.mark.django_db
def test_dashboard_german(client):
    _login(client, "ada", "de")
    body = client.get("/dashboard/").content.decode()
    assert "Mein Profil" in body and "FLINTA-Quote" in body and "Abmelden" in body


@pytest.mark.django_db
def test_ag_tags_messages_attrs_english(client):
    _login(client, "ada", "en")
    body = client.get("/dashboard/").content.decode()
    assert 'data-msg-unexpected="Unexpected error' in body


@pytest.mark.django_db
@pytest.mark.parametrize("loc,error", [("en", "Unknown action."), ("de", "Unbekannte Aktion.")])
def test_ag_membership_error_language(client, loc, error):
    _login(client, "ada", loc)
    r = client.post("/ags/", {"group": "ag.x", "action": "bogus"})
    assert r.json()["error"] == error


# --- shared labels ------------------------------------------------------------

def test_access_labels_follow_active_language():
    from django.utils import translation
    from app import tenant_access
    label = next(f.label for f in tenant_access._ALL_FIELDS if f.name == "preferred_name")
    with translation.override("en"):
        assert str(label) == "Preferred name"
    with translation.override("de"):
        assert str(label) == "Rufname"


def test_choice_label_english():
    from django.utils import translation
    from app.models import EnrollmentType
    with translation.override("en"):
        assert str(EnrollmentType.STUDY.label) == "Studies"
    with translation.override("de"):
        assert str(EnrollmentType.STUDY.label) == "Studium"


@pytest.mark.django_db
def test_form_email_error_english():
    from django.utils import translation
    from app.forms import TenantForm
    _make_tenant("t1", email="taken@b.de")
    t2 = _make_tenant("t2")
    with translation.override("en"):
        form = TenantForm(data={"email": "taken@b.de"}, instance=t2, allowed_fields={"email"})
        assert not form.is_valid()
        assert "This email address is already in use." in form.errors["email"]


# --- tenant detail ------------------------------------------------------------

_MV_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["cartei_finanzierung"]}


@pytest.mark.django_db
def test_tenant_detail_english(client):
    t, _u = _login(client, "ada", "en")
    body = client.get(f"/tenants/{t.pk}/").content.decode()
    assert "Personal information" in body and "Preferred name" in body
    assert "Persönliche Informationen" not in body and "Rufname" not in body


@pytest.mark.django_db
def test_tenant_detail_german(client):
    t, _u = _login(client, "ada", "de")
    body = client.get(f"/tenants/{t.pk}/").content.decode()
    assert "Persönliche Informationen" in body and "Rufname" in body


@pytest.mark.django_db
def test_mv_viewer_language_not_profile_language(client, settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _make_tenant("eng", "en")
    _make_tenant("mv", "de")
    mv = User.objects.create_user(username="mv")
    mv.groups.add(Group.objects.get_or_create(name="ag.mietverwaltung")[0])
    client.force_login(mv)
    body = client.get(f"/tenants/{t.pk}/").content.decode()
    assert "Persönliche Informationen" in body and "Personal information" not in body


@pytest.mark.django_db
def test_save_message_english(client):
    t, _u = _login(client, "ada", "en")
    r = client.post(f"/tenants/{t.pk}/", {
        "section": "personal", "email": "ada@ca.de", "phone": "123", "preferred_name": "Ada",
        "pronouns": "", "is_flinta": "", "mailbox_list_opt_in": "", "soli_miete_wunsch": "150",
    }, follow=True)
    assert "Saved." in r.content.decode()


@pytest.mark.django_db
def test_welcome_email_stays_german(mailoutbox, settings):
    from django.utils import translation
    from app.emails import send_welcome_email
    settings.DEFAULT_FROM_EMAIL = "noreply@ca-hd.de"
    t = Tenant.objects.create(first_name="Mara", last_name="Test", email="mara@x.de")
    with translation.override("en"):
        send_welcome_email(t, "mara_test", "OneTime-9")
    assert "Deine Zugangsdaten lauten wie folgt" in mailoutbox[0].body
