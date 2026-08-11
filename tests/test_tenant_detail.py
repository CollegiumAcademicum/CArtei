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
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("someone")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert 'name="date_of_birth"' in body  # editable input for MV


@pytest.mark.django_db
def test_mietverwaltung_sees_sublet_of_picker(settings):
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("subj")
    c = Client()
    _login(c, "mv2", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert 'name="sublet_of_tenant"' in body


@pytest.mark.django_db
def test_date_fields_use_native_picker_and_iso_roundtrip(settings):
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("dsubj")
    c = Client()
    _login(c, "mvd", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert 'type="date"' in body  # native browser date picker
    # ISO submission parses and saves despite the de-de locale
    resp = c.post(f"/tenants/{t.pk}/", {"email": "x@ca.de", "date_of_birth": "1990-05-01"})
    assert resp.status_code in (200, 302)
    t.refresh_from_db()
    assert str(t.date_of_birth) == "1990-05-01"


@pytest.mark.django_db
def test_future_moved_out_shows_as_active_room(settings):
    """An assignment with a future moved_out date must appear as an active (editable) room."""
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("mvfuture")
    b = Building.objects.create(name="BauF")
    wg = WG.objects.create(building=b, name="WGF", cluster="OG2")
    room = Room.objects.create(wg=wg, name="201", size_sqm=14)
    future_date = datetime.date.today() + datetime.timedelta(days=30)
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2024, 1, 1), moved_out=future_date)
    c = Client()
    _login(c, "mvf", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert 'name="assignment_ids"' in body, "Future-dated assignment must appear as editable, not past"


@pytest.mark.django_db
def test_housing_post_saves_without_new_room(settings):
    """Housing section should save existing assignment changes even when new-room form is blank."""
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("mvtest2")
    b = Building.objects.create(name="Bau")
    wg = WG.objects.create(building=b, name="WG1", cluster="OG1")
    room = Room.objects.create(wg=wg, name="101", size_sqm=12)
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2024, 1, 1))
    c = Client()
    _login(c, "mv2test", groups=["ag.mietverwaltung"])
    resp = c.post(f"/tenants/{t.pk}/", {
        "section": "housing",
        "assignment_ids": str(a.pk),
        f"room_{a.pk}-room": str(room.pk),
        f"room_{a.pk}-moved_in": "2024-01-01",
        f"room_{a.pk}-moved_out": "2025-12-31",
        "new_room-room": "",
        "new_room-moved_in": "",
    })
    if resp.status_code == 200 and hasattr(resp, 'context') and resp.context:
        print("TenantForm errors:", resp.context.get('form', {}).errors if resp.context.get('form') else 'no form')
        for aa, af in resp.context.get('active_assignment_forms', []):
            print(f"Assignment {aa.pk} form errors:", af.errors)
    assert resp.status_code == 302, f"Expected redirect, got 200. Check printed errors above."
    a.refresh_from_db()
    assert str(a.moved_out) == "2025-12-31"
