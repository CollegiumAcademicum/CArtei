"""Email SSOT (CArtei#70): FreeIPA `mail` is the truth for linked tenants,
tenant.email a read-through cache; edits are written through to FreeIPA first."""
import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from app.emails import current_email
from app.ldap_utils import _uid_candidates, provision_ldap_account, set_ldap_mail
from app.models import Tenant

UID_UUID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _linked(**kw):
    return Tenant.objects.create(first_name="Ada", last_name="Byte", email="old@x.de",
                                 intranet_username="ada_byte", intranet_uuid=UID_UUID, **kw)


# --- read-through cache -----------------------------------------------------

@pytest.mark.django_db
def test_current_email_unlinked_uses_cache_without_ldap():
    t = Tenant.objects.create(first_name="No", last_name="Account", email="no@x.de")
    with patch("app.emails.get_mail_by_uuid") as lookup:
        assert current_email(t) == "no@x.de"
    lookup.assert_not_called()


@pytest.mark.django_db
def test_current_email_linked_refreshes_cache():
    t = _linked()
    with patch("app.emails.get_mail_by_uuid", return_value="new@x.de") as lookup:
        assert current_email(t) == "new@x.de"
    lookup.assert_called_once_with(UID_UUID)
    t.refresh_from_db()
    assert t.email == "new@x.de" and t.email_refreshed_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize("ldap", [
    {"return_value": None},                         # account deleted (moved out)
    {"side_effect": RuntimeError("ldap down")},     # LDAP unreachable
])
def test_current_email_falls_back_to_cache(ldap):
    t = _linked()
    with patch("app.emails.get_mail_by_uuid", **ldap):
        assert current_email(t) == "old@x.de"
    t.refresh_from_db()
    assert t.email == "old@x.de" and t.email_refreshed_at is None


# --- write-through ----------------------------------------------------------

def _ipa(user_mod):
    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a, **k): pass
    FakeClient.user_mod = staticmethod(user_mod)
    return patch("python_freeipa.ClientMeta", FakeClient)


def _ipa_settings(settings):
    settings.IPA_SERVER, settings.IPA_VERIFY_SSL = "ipa.test", True
    settings.IPA_PROVISION_USER, settings.IPA_PROVISION_PASSWORD = "svc", "pw"


def test_set_ldap_mail_tolerates_unchanged_mail(settings):
    from python_freeipa.exceptions import BadRequest
    _ipa_settings(settings)

    def user_mod(**k):
        raise BadRequest("no modifications to be performed", 4202)
    with _ipa(user_mod):
        set_ldap_mail("ada_byte", "same@x.de")  # no raise


def test_set_ldap_mail_raises_other_errors(settings):
    from python_freeipa.exceptions import Denied
    _ipa_settings(settings)

    def user_mod(**k):
        raise Denied("insufficient access", 2100)
    with _ipa(user_mod), pytest.raises(Denied):
        set_ldap_mail("ada_byte", "x@x.de")


def _mv_client():
    c = Client()
    user = User.objects.create_user(username="mv")
    user.groups.add(Group.objects.get_or_create(name="ag.mietverwaltung")[0])
    c.force_login(user)
    return c


def _post_email(client, t, email):
    return client.post(f"/tenants/{t.pk}/", {
        "section": "personal",
        "email": email,
    })


@pytest.mark.django_db
def test_tenant_page_email_edit_writes_through_first(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "admin": ["admins"]}
    t = _linked()
    with patch("app.views._shared.set_ldap_mail") as push:
        _post_email(_mv_client(), t, "edited@x.de")
    push.assert_called_once_with("ada_byte", "edited@x.de")
    t.refresh_from_db()
    assert t.email == "edited@x.de" and t.email_refreshed_at is not None


@pytest.mark.django_db
def test_tenant_page_email_edit_rejected_when_freeipa_fails(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "admin": ["admins"]}
    t = _linked()
    with patch("app.views._shared.set_ldap_mail", side_effect=RuntimeError("ipa down")):
        resp = _post_email(_mv_client(), t, "edited@x.de")
    assert resp.status_code == 200 and "nicht gespeichert" in resp.content.decode()
    t.refresh_from_db()
    assert t.email == "old@x.de"


@pytest.mark.django_db
def test_unlinked_tenant_email_edit_stays_local(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "admin": ["admins"]}
    t = Tenant.objects.create(first_name="No", last_name="Account", email="no@x.de")
    with patch("app.views._shared.set_ldap_mail") as push:
        _post_email(_mv_client(), t, "new@x.de")
    push.assert_not_called()
    t.refresh_from_db()
    assert t.email == "new@x.de"


def test_uid_candidates():
    it = _uid_candidates("ada_byte")
    assert [next(it) for _ in range(3)] == ["ada_byte", "ada_byte2", "ada_byte3"]


@pytest.mark.django_db
def test_provision_retries_uid_on_collision(settings):
    from app.models import Tenant
    from python_freeipa.exceptions import DuplicateEntry
    settings.IPA_SERVER = "ipa.test"
    settings.IPA_VERIFY_SSL = True
    settings.IPA_PROVISION_USER = "svc"
    settings.IPA_PROVISION_PASSWORD = "pw"
    t = Tenant.objects.create(first_name="Ada", last_name="Byte", email="ada@x.de")

    taken = {"ada_byte", "ada_byte2"}
    added = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a, **k): pass
        def user_add(self, a_uid, o_random=False, **k):
            assert o_random is True  # accounts must never be created passwordless
            if a_uid in taken:
                raise DuplicateEntry(message=f"{a_uid} exists")
            added.append(a_uid)
            return {"result": {"ipauniqueid": ["550e8400-e29b-41d4-a716-446655440000"],
                               "randompassword": "Tmp-Pw-123"}}

    with patch("python_freeipa.ClientMeta", FakeClient):
        result = provision_ldap_account(t)

    assert result.uid == "ada_byte3" and result.temp_password == "Tmp-Pw-123"
    assert added == ["ada_byte3"]
    t.refresh_from_db()
    assert t.intranet_username == "ada_byte3"
    assert t.email_refreshed_at is not None  # FreeIPA mail was set from tenant.email
