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


# --- final review fixes -------------------------------------------------------

def test_handover_steps_stay_german_when_imported_under_english():
    import importlib
    from django.utils import translation
    import app.handover
    with translation.override("en"):
        importlib.reload(app.handover)
    areas = [area for _kind, area, _lines in app.handover.STEPS]
    assert areas == ["Zimmer", "Bad", "Küche", "Gemeinschaftsfläche"]


@pytest.mark.django_db
def test_write_through_duplicate_error_english():
    from unittest.mock import MagicMock, patch
    from django.utils import translation
    from app.views._shared import write_through_email
    t = _make_tenant("ada", email="old@x.de")
    form = MagicMock(cleaned_data={"email": "new@x.de"})
    with patch("app.views._shared.set_ldap_mail", side_effect=RuntimeError("mail: unique constraint")), \
            translation.override("en"):
        assert write_through_email(form, t) is False
    form.add_error.assert_called_once_with("email", "This email address is already used in the intranet.")


# --- more views: profile setup, lists, WGs, surveys, admin portal ----------------

_STAFF_GROUPS = {"admin": ["admins"], "mietverwaltung": ["ag.mietverwaltung"], "cluster": ["gr.cluster"]}


@pytest.fixture
def staff(client, settings):
    settings.TENANT_ROLE_GROUPS = _STAFF_GROUPS
    user = User.objects.create_user(username="staff")
    for g in ("admins", "ag.mietverwaltung", "gr.cluster"):
        user.groups.add(Group.objects.get_or_create(name=g)[0])
    client.force_login(user)
    return user


@pytest.fixture
def wg_room():
    from app.models import Building, Room, WG
    wg = WG.objects.create(building=Building.objects.create(name="Neubau"), name="1.02")
    return Room.objects.create(wg=wg, name="1.02.1", size_sqm="12.00", has_bed=True)


@pytest.fixture
def abfrage():
    from datetime import date, timedelta
    from app.models import AGAbfrage
    today = date.today()
    return AGAbfrage.objects.create(date=today, ends_at=today + timedelta(days=7),
                                    grace_ends_at=today + timedelta(days=14))


def _body(client, url):
    r = client.get(url, **EN)
    assert r.status_code == 200
    return r.content.decode()


@pytest.mark.django_db
def test_profile_setup_english(client, wg_room):
    from django.utils import timezone
    from app.models import TenantRoomAssignment
    t, _u = _login(client, "ada", "en")
    TenantRoomAssignment.objects.create(tenant=t, room=wg_room, moved_in=timezone.localdate())
    body = client.get("/profile/setup/").content.decode()
    assert "Complete your profile" in body and "Should your name appear on the mailbox list?" in body
    assert "Profil vervollständigen" not in body and "Briefkastenliste" not in body


@pytest.mark.django_db
def test_tenant_list_english(client, staff):
    _make_tenant("ada")
    body = _body(client, "/tenants/?residents=all")
    assert "Group by cluster" in body and "1 person<" in body and "Mailbox" in body
    assert "Nach Cluster gruppieren" not in body and "Briefkasten" not in body


@pytest.mark.django_db
def test_tenant_create_english(client, staff):
    from django.urls import reverse
    body = _body(client, reverse("tenant_create"))
    assert "New resident" in body and "First name" in body and "Create intranet account right away" in body
    assert "Vorname" not in body and "Abbrechen" not in body


@pytest.mark.django_db
def test_wg_list_and_detail_english(client, staff, wg_room):
    body = _body(client, "/wgs/")
    assert "WGs & rooms" in body and "1 room<" in body and "Furnishings" in body and "Bed" in body
    assert "Ausstattung" not in body and "Bett" not in body
    body = _body(client, f"/wgs/{wg_room.wg.pk}/")
    assert "Common areas" in body and "Save furnishings" in body and "Mattress" in body
    assert "Gemeinschaftsflächen" not in body and "Matratze" not in body


@pytest.mark.django_db
def test_wg_detail_german(client, staff, wg_room):
    body = client.get(f"/wgs/{wg_room.wg.pk}/", **DE).content.decode()
    assert "Gemeinschaftsflächen" in body and "Ausstattung speichern" in body


@pytest.mark.django_db
def test_survey_views_english(client, staff, abfrage):
    body = _body(client, "/abfragen/")
    assert "AG engagement surveys" in body and "Grace period until" in body
    assert f"Survey {abfrage.ends_at}" in body and "Nachfrist" not in body
    body = _body(client, "/abfragen/new/")
    assert "Create new survey" in body and "Official deadline" in body
    body = _body(client, f"/abfragen/{abfrage.pk}/")
    assert "Results by AG" in body and "Delete permanently" in body and "Löschen" not in body
    body = _body(client, f"/abfragen/{abfrage.pk}/tenants/")
    assert "Sufficient?" in body and "Ausreichend" not in body


@pytest.mark.django_db
def test_ag_edit_english(client, staff, abfrage, monkeypatch):
    from app import ldap_utils
    monkeypatch.setattr(ldap_utils, "get_ag_members", lambda ag: [])
    body = _body(client, f"/abfragen/{abfrage.pk}/ag/ag.test/")
    assert "Overall state of the AG" in body and "Add another resident" in body
    assert 'data-labels="too active,active,' in body and 'data-labels="healthy,core tasks only,' in body
    assert "Gesamtzustand" not in body and "nur Kernaufgaben" not in body


@pytest.mark.django_db
def test_admin_portal_english(client, staff):
    body = _body(client, "/admin/")
    assert "Admin portal" in body and "Invalidate all sessions" in body
    assert "Admin-Portal" not in body and "Sitzungen" not in body


def test_abfrage_str_follows_language():
    from datetime import date
    from django.utils import translation
    from app.models import AGAbfrage
    a = AGAbfrage(ends_at=date(2026, 12, 1))
    with translation.override("en"):
        assert str(a) == "Survey 2026-12-01"
    with translation.override("de"):
        assert str(a) == "Abfrage 2026-12-01"
