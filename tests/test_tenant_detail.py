import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from app.models import Tenant


def _tenant(username="owner", **kw):
    return Tenant.objects.create(
        first_name=kw.get("first_name", "Owner"), last_name="Test",
        email="owner@ca.de", intranet_username=username,
        intranet_uuid=uuid.uuid4(), preferred_name=kw.get("preferred_name", "Owzy"),
        pronouns="sie/ihr",
    )


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_owner_sees_edit_inputs_for_six_fields():
    t = _tenant("owner")
    c = Client()
    _login(c, "owner")
    resp = c.get(f"/tenants/{t.pk}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    for name in ["email", "phone", "is_flinta", "mailbox_list_opt_in", "preferred_name", "pronouns"]:
        assert f'name="{name}"' in body
    assert 'name="date_of_birth"' not in body  # owner sees DOB read-only


@pytest.mark.django_db
def test_stranger_sees_only_public_card():
    t = _tenant("owner")
    c = Client()
    _login(c, "stranger")
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert "Owzy" in body and "sie/ihr" in body
    assert "owner@ca.de" not in body  # email not visible to strangers
    assert "Test" not in body  # real last name is private once a preferred_name is set
    assert 'name="preferred_name"' not in body  # no edit inputs


@pytest.mark.django_db
def test_heading_falls_back_to_real_name_without_preferred():
    t = _tenant("np", preferred_name="")  # no preferred name set
    c = Client()
    _login(c, "stranger2")
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert "Owner" in body and "Test" in body  # heading falls back to real name for everyone


@pytest.mark.django_db
def test_owner_post_updates_only_allowed_field():
    t = _tenant("owner")
    c = Client()
    _login(c, "owner")
    resp = c.post(f"/tenants/{t.pk}/", {
        "email": "changed@ca.de", "phone": "123", "preferred_name": "Owzy",
        "pronouns": "sie/ihr", "is_flinta": "on", "mailbox_list_opt_in": "",
        "soli_miete_wunsch": "999",  # not editable by owner — must be ignored
    })
    assert resp.status_code in (200, 302)
    t.refresh_from_db()
    assert t.email == "changed@ca.de"
    assert str(t.soli_miete_wunsch) == "0.00"  # unchanged


@pytest.mark.django_db
def test_owner_post_bad_email_rejected():
    t = _tenant("owner")
    c = Client()
    _login(c, "owner")
    resp = c.post(f"/tenants/{t.pk}/", {
        "email": "nope", "phone": "", "preferred_name": "Owzy",
        "pronouns": "sie/ihr", "is_flinta": "", "mailbox_list_opt_in": "",
    })
    assert resp.status_code == 200
    t.refresh_from_db()
    assert t.email == "owner@ca.de"  # unchanged


@pytest.mark.django_db
def test_mietverwaltung_can_edit_dob(settings):
    settings.TENANT_ROLE_GROUPS = {"cluster": ["cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("someone")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert 'name="date_of_birth"' in body  # editable input for MV
