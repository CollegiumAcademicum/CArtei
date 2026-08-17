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
        "soli_miete_wunsch": "150",     # owner-editable — must apply
        "date_of_birth": "1990-05-01",  # MV-only — must be ignored
    })
    assert resp.status_code in (200, 302)
    t.refresh_from_db()
    assert t.email == "changed@ca.de"
    assert str(t.soli_miete_wunsch) == "150.00"  # owner may set it
    assert t.date_of_birth is None  # unchanged (owner cannot edit)


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
    assert 'sublet_of_tenant' in body  # rendered on the room-assignment form (prefixed name)


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
def test_past_assignment_is_editable_for_manager(settings):
    """A past (moved_out in the past) assignment must render as an editable form for MV/Admin."""
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("mvpast")
    b = Building.objects.create(name="BauP")
    wg = WG.objects.create(building=b, name="WGP", cluster="OG3")
    room = Room.objects.create(wg=wg, name="301", size_sqm=15)
    a = TenantRoomAssignment.objects.create(
        tenant=t, room=room,
        moved_in=datetime.date(2020, 1, 1), moved_out=datetime.date(2021, 1, 1),
    )
    c = Client()
    _login(c, "mvp", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert "Frühere Zimmer" in body
    assert f'name="room_{a.pk}-room"' in body, "Past assignment must be editable, not read-only"


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


@pytest.mark.django_db
def test_housing_post_with_all_browser_fields(settings):
    """Browser sends tenant housing fields too — ensure those don't block room assignment save."""
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("mvtest3")
    b = Building.objects.create(name="Bau2")
    wg = WG.objects.create(building=b, name="WG2", cluster="OG1")
    room = Room.objects.create(wg=wg, name="202", size_sqm=14)
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2024, 3, 1))
    c = Client()
    _login(c, "mv3test", groups=["ag.mietverwaltung"])
    resp = c.post(f"/tenants/{t.pk}/", {
        "section": "housing",
        "assignment_ids": str(a.pk),
        f"room_{a.pk}-room": str(room.pk),
        f"room_{a.pk}-moved_in": "2024-03-01",
        f"room_{a.pk}-moved_out": "2026-01-01",
        # Tenant housing fields that the browser also sends
        "is_sublet": "",
        "sublet_of_tenant": "",
        "sublet_from": "",
        "sublet_to": "",
        "mailbox_key": "",
        # New room form empty
        "new_room-room": "",
        "new_room-moved_in": "",
        "new_room-moved_out": "",
        "new_room-deposit_iban": "",
    })
    if resp.status_code == 200 and hasattr(resp, 'context') and resp.context:
        form = resp.context.get('form')
        if form: print("TenantForm errors:", form.errors)
        for aa, af in resp.context.get('active_assignment_forms', []):
            if af.errors: print(f"Assign {aa.pk} errors:", af.errors)
        nf = resp.context.get('new_room_form')
        if nf and nf.errors: print("new_room errors:", nf.errors)
    assert resp.status_code == 302, "Expected redirect on save"
    a.refresh_from_db()
    assert str(a.moved_out) == "2026-01-01"


@pytest.mark.django_db
def test_new_room_without_moved_in_shows_error_not_silent(settings):
    """Adding a room but leaving Eingezogen blank must re-render with a visible
    error, not silently drop the assignment."""
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("mvnew")
    b = Building.objects.create(name="Bau3")
    wg = WG.objects.create(building=b, name="WG3", cluster="OG2")
    room = Room.objects.create(wg=wg, name="303", size_sqm=15)
    c = Client()
    _login(c, "mvnewtest", groups=["ag.mietverwaltung"])
    resp = c.post(f"/tenants/{t.pk}/", {
        "section": "housing",
        "new_room-room": str(room.pk),
        "new_room-moved_in": "",
    })
    assert resp.status_code == 200, "Invalid new-room submit must re-render, not redirect"
    assert not TenantRoomAssignment.objects.filter(tenant=t).exists(), "No assignment should be created"
    body = resp.content.decode()
    # The error must be rendered in the page (not just present on the form object),
    # and the collapsible "Zimmer zuordnen" section must be opened so the user sees it.
    assert "errorlist" in body, "New-room field errors must be visible in the rendered page"
    assert "ca-field-error" in body, "Errored required field must get the red-border class"


@pytest.mark.django_db
def test_detail_shows_reverse_sublet(settings):
    """A tenant who sublets their room out sees 'Untervermietet an <subletter>'."""
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"]}
    landlord = _tenant("land", preferred_name="Vermieta")
    subletter = _tenant("subby", preferred_name="Untermieta")
    b = Building.objects.create(name="BauS")
    wg = WG.objects.create(building=b, name="WGS")
    room = Room.objects.create(wg=wg, name="401", size_sqm=13)
    TenantRoomAssignment.objects.create(
        tenant=subletter, room=room, moved_in=datetime.date(2024, 1, 1),
        is_sublet=True, sublet_of_tenant=landlord,
    )
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{landlord.pk}/").content.decode()
    assert "Untervermietet an" in body
    assert "Untermieta" in body


@pytest.mark.django_db
def test_room_renters_endpoint_lists_only_active_and_gates_access(settings):
    import datetime
    from app.models import Building, WG, Room, TenantRoomAssignment
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    b = Building.objects.create(name="BauR")
    wg = WG.objects.create(building=b, name="WGR", cluster="OG1")
    room = Room.objects.create(wg=wg, name="401", size_sqm=14)
    cur = _tenant("cur"); cur.email = "cur@ca.de"; cur.save()
    old = Tenant.objects.create(first_name="Old", last_name="T", email="old@ca.de",
                                intranet_username="old", intranet_uuid=uuid.uuid4())
    TenantRoomAssignment.objects.create(tenant=cur, room=room, moved_in=datetime.date(2024, 1, 1))
    TenantRoomAssignment.objects.create(tenant=old, room=room,
        moved_in=datetime.date(2020, 1, 1), moved_out=datetime.date(2021, 1, 1))

    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    assert c.get(f"/rooms/{room.pk}/renters/").json() == [cur.pk]

    # Non-manager gets an empty list, not the occupancy.
    c2 = Client()
    _login(c2, "nobody", groups=[])
    assert c2.get(f"/rooms/{room.pk}/renters/").json() == []
