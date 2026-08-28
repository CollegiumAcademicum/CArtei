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
def test_email_required(settings):
    settings.TENANT_ROLE_GROUPS = MV_GROUPS
    c = Client()
    _login(c, "mv2", groups=["ag.mietverwaltung"])
    resp = c.post("/tenants/neu/", {"first_name": "A", "last_name": "B", "email": ""})
    assert resp.status_code == 200  # re-rendered with errors
    assert Tenant.objects.count() == 0
