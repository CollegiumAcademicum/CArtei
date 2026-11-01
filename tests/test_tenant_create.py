from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from app.models import Tenant

MV_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "admin": ["admins"]}


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_non_mv_forbidden(settings):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "nobody")
    assert c.get("/tenants/neu/").status_code == 403
    assert c.post("/tenants/neu/", {"first_name": "X", "last_name": "Y", "email": "x@ca.de"}).status_code == 403
    assert Tenant.objects.count() == 0


@pytest.mark.django_db
def test_mv_creates_account_less_tenant(settings):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    resp = c.post("/tenants/neu/", {
        "first_name": "Neu", "last_name": "Bewohner", "email": "neu@ca.de",
    })
    t = Tenant.objects.get(last_name="Bewohner")
    assert t.intranet_username is None and t.intranet_uuid is None
    assert resp.status_code == 302 and resp.url == f"/tenants/{t.pk}/"


@pytest.mark.django_db
def test_optin_provisions_ldap_account(settings, mailoutbox):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "mv3", groups=["ag.mietverwaltung"])
    from app.ldap_utils import ProvisionResult
    with patch("app.views.tenant.provision_ldap_account",
               return_value=ProvisionResult("neu.optin", "Tmp-Pw")) as prov:
        c.post("/tenants/neu/", {
            "first_name": "Neu", "last_name": "Optin", "email": "optin@ca.de",
            "create_ldap_account": "on",
        })
    t = Tenant.objects.get(last_name="Optin")
    prov.assert_called_once_with(t)
    assert len(mailoutbox) == 1 and mailoutbox[0].to == ["optin@ca.de"]  # welcome mail sent


@pytest.mark.django_db
def test_email_required(settings):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "mv2", groups=["ag.mietverwaltung"])
    resp = c.post("/tenants/neu/", {"first_name": "A", "last_name": "B", "email": ""})
    assert resp.status_code == 200  # re-rendered with errors
    assert Tenant.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("existing_mail,new_mail", [
    ("alice@ca.de", "alice@ca.de"),
    ("alice@ca.de", "ALICE@ca.de"),
    ("ALICE@ca.de", "alice@ca.de"),
])
def test_duplicate_email_rejected_case_insensitive(settings, existing_mail, new_mail):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    Tenant.objects.create(first_name="Alice", last_name="Alt", email=existing_mail)
    c = Client()
    _login(c, "mv_dup", groups=["ag.mietverwaltung"])
    resp = c.post("/tenants/neu/", {
        "first_name": "Bob", "last_name": "Neu", "email": new_mail,
    })
    assert resp.status_code == 200
    assert "Diese E-Mail-Adresse wird bereits verwendet." in resp.content.decode()
    assert Tenant.objects.count() == 1  # No partial write


@pytest.mark.django_db
def test_ldap_duplicate_email_rejected(settings):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "mv_ldap_dup", groups=["ag.mietverwaltung"])
    with patch("app.ldap_utils.is_ldap_mail_taken", return_value=True):
        resp = c.post("/tenants/neu/", {
            "first_name": "Clara", "last_name": "Neu", "email": "clara@ca.de",
        })
    assert resp.status_code == 200
    assert "Diese E-Mail-Adresse wird bereits im Intranet verwendet." in resp.content.decode()
    assert Tenant.objects.count() == 0  # No partial write


@pytest.mark.django_db
def test_optin_provision_failure_rolls_back_tenant(settings, mailoutbox):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "mv_fail", groups=["ag.mietverwaltung"])
    with patch("app.views.tenant.provision_ldap_account", side_effect=RuntimeError("LDAP constraint: mail must be unique")):
        resp = c.post("/tenants/neu/", {
            "first_name": "Daniel", "last_name": "Neu", "email": "daniel@ca.de",
            "create_ldap_account": "on",
        })
    assert resp.status_code == 200
    assert "bereits im Intranet verwendet" in resp.content.decode()
    assert Tenant.objects.filter(last_name="Neu").count() == 0  # Rolled back, no partial write
    assert len(mailoutbox) == 0  # No email sent
