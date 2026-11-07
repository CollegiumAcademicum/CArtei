import uuid
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from app.models import Building, Room, Tenant, TenantRoomAssignment, WG

_MV_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}


def _tenant(username, **kw):
    return Tenant.objects.create(
        first_name=kw.get("first_name", "Ada"),
        last_name=kw.get("last_name", "Lovelace"),
        email=kw.get("email", f"{username}@ca.de"),
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
        preferred_name=kw.get("preferred_name", "Ada"),
        pronouns="sie/ihr",
    )


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)
    return user


def _assign(tenant, cluster=None, is_sublet=False, moved_in=date(2024, 1, 1), moved_out=None):
    b = Building.objects.create(name=f"Haus-{uuid.uuid4().hex[:6]}")
    wg = WG.objects.create(building=b, name="WG1", cluster=cluster)
    room = Room.objects.create(wg=wg, name="R1", size_sqm=12)
    return TenantRoomAssignment.objects.create(
        tenant=tenant, room=room, moved_in=moved_in, moved_out=moved_out, is_sublet=is_sublet
    )


def _abfrage(label="Q3-Umfrage"):
    from app.models import AGAbfrage
    today = date.today()
    return AGAbfrage.objects.create(
        date=today, label=label,
        ends_at=today + timedelta(days=7), grace_ends_at=today + timedelta(days=14),
    )


def _result(abfrage, tenant, ag_name="ag.kueche", status="AKTIV"):
    from app.models import AGAbfrageResult
    return AGAbfrageResult.objects.create(
        abfrage=abfrage, tenant=tenant, ag_name=ag_name, status=status
    )


@pytest.mark.django_db
def test_list_requires_login():
    resp = Client().get("/tenants/")
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.django_db
def test_list_returns_200():
    c = Client()
    _login(c, "viewer")
    assert c.get("/tenants/").status_code == 200


@pytest.mark.django_db
def test_plain_user_sees_preferred_but_not_email_or_realname(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _assign(_tenant("owner", preferred_name="Owzy", last_name="Secret", email="owner@ca.de"))
    c = Client()
    _login(c, "stranger")
    body = c.get("/tenants/").content.decode()
    assert "Owzy" in body
    assert "owner@ca.de" not in body
    assert "Secret" not in body


@pytest.mark.django_db
def test_mietverwaltung_sees_email_and_realname(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _assign(_tenant("owner", preferred_name="Owzy", last_name="Secret", email="owner@ca.de"))
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert "owner@ca.de" in body
    assert "Secret" in body


@pytest.mark.django_db
def test_active_default_excludes_former(settings):
    # residents scope stays server-side (decides which records are loaded).
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _assign(_tenant("current", preferred_name="Current"))  # active assignment
    _assign(_tenant("gone", preferred_name="Gone"), moved_out=date.today() - timedelta(days=5))
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    active = c.get("/tenants/").content.decode()
    assert "Current" in active and "Gone" not in active
    allr = c.get("/tenants/?residents=all").content.decode()
    assert "Current" in allr and "Gone" in allr


@pytest.mark.django_db
def test_all_rows_rendered_no_pagination(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    for i in range(30):
        _tenant(f"t{i}", preferred_name=f"Person{i:02d}", last_name=f"N{i:02d}")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/?residents=all").content.decode()
    assert "Person00" in body and "Person29" in body


@pytest.mark.django_db
def test_move_in_column_has_date_filter(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _assign(_tenant("ada", preferred_name="Ada"))
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert 'data-col="ersteinzug"' in body
    assert 'type="date"' in body


@pytest.mark.django_db
def test_rows_carry_sort_and_value_data_attributes(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _assign(_tenant("ada", first_name="Ada", last_name="Lovelace"), moved_in=date(2024, 3, 15))
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert 'data-sort="lovelace ada"' in body           # name sorts by last, first
    assert 'data-value="2024-03-15"' in body            # ersteinzug machine value for date filter/sort


@pytest.mark.django_db
def test_sublet_shown_in_room_cell_only_for_room_users(settings):
    # Sublet now lives inside the room cell (both directions), gated by room access.
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    landlord = _tenant("land", preferred_name="Vermieta")
    t = _tenant("ada", preferred_name="Ada")
    a = _assign(t, is_sublet=True)
    a.sublet_of_tenant = landlord
    a.save()
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert 'data-col="room"' in body
    assert "Untermiete von" in body
    c2 = Client()
    _login(c2, "plain")
    plain = c2.get("/tenants/").content.decode()
    assert 'data-col="room"' not in plain
    assert "Untermiete von" not in plain


@pytest.mark.django_db
def test_column_chooser_lists_only_allowed_columns(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("ada", preferred_name="Ada")
    plain = Client()
    _login(plain, "plain")
    pbody = plain.get("/tenants/").content.decode()
    assert 'data-col-toggle="email"' not in pbody
    assert 'data-col-toggle="room"' not in pbody

    mv = Client()
    _login(mv, "mv", groups=["ag.mietverwaltung"])
    mbody = mv.get("/tenants/").content.decode()
    assert 'data-col-toggle="email"' in mbody
    assert 'data-col-toggle="room"' in mbody

    cl = Client()
    _login(cl, "cl", groups=["gr.cluster"])
    assert 'data-col-toggle="cluster"' in cl.get("/tenants/").content.decode()


@pytest.mark.django_db
def test_cluster_user_sees_survey_selector(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _abfrage(label="Q3-Umfrage")
    c = Client()
    _login(c, "cl", groups=["gr.cluster"])
    body = c.get("/tenants/").content.decode()
    assert 'name="surveys"' in body
    assert "Q3-Umfrage" in body


@pytest.mark.django_db
def test_mietverwaltung_has_no_survey_selector(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _abfrage(label="Q3-Umfrage")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert 'name="surveys"' not in body


@pytest.mark.django_db
def test_survey_results_render_for_selected_survey(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada", preferred_name="Ada")
    a = _abfrage(label="Q3")
    _result(a, t, ag_name="ag.kueche", status="AKTIV")
    c = Client()
    _login(c, "cl", groups=["gr.cluster"])
    body = c.get(f"/tenants/?surveys={a.pk}&residents=all").content.decode()
    assert "ag.kueche" in body
    assert "aktiv" in body


@pytest.mark.django_db
def test_engagement_summary_panel_when_surveys_selected(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada", preferred_name="Ada")
    _assign(t, cluster="A")
    a = _abfrage(label="Q3")
    _result(a, t, status="AKTIV")
    c = Client()
    _login(c, "cl", groups=["gr.cluster"])
    with_surveys = c.get(f"/tenants/?surveys={a.pk}").content.decode()
    assert "engagement-summary" in with_surveys
    without = c.get("/tenants/").content.decode()
    assert "engagement-summary" not in without


# --- VE clearance colour on the list pill (#65) ------------------------------

def _ve_doc(tenant, approved=False):
    from django.utils.timezone import now

    from app.models import ClearanceAction, ConfidentialityClearanceEvent, VertraulichkeitserklaerungDocument
    doc = VertraulichkeitserklaerungDocument.objects.create(
        tenant=tenant, file_name="ve.pdf", file_data=b"x", signed_at=date(2026, 8, 1),
        uploaded_at=now(), uploaded_by=tenant,
    )
    if approved:
        ConfidentialityClearanceEvent.objects.create(
            tenant=tenant, document=doc, action=ClearanceAction.GRANT, created_at=now()
        )
    return doc


def _ve_pill_classes(resp, tenant):
    row = next(r for r in resp.context["rows"] if r["tenant"].pk == tenant.pk)
    return next(d for d in row["documents"] if d["short"] == "VE")


@pytest.mark.django_db
def test_list_ve_pill_black_when_group_without_approval(client, monkeypatch, settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ve1")
    _assign(t)
    _ve_doc(t)
    monkeypatch.setattr("app.clearance.clearance_member_uuids", lambda: {str(t.intranet_uuid)})
    _login(client, "mv", ["ag.mietverwaltung"])
    resp = client.get("/tenants/")
    ve = _ve_pill_classes(resp, t)
    assert ve["color"] == "black" and not ve["present"]
    assert 'ca-pill-black' in resp.content.decode()


@pytest.mark.django_db
def test_list_ve_pill_green(client, monkeypatch, settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ve2")
    _assign(t)
    _ve_doc(t, approved=True)
    monkeypatch.setattr("app.clearance.clearance_member_uuids", lambda: {str(t.intranet_uuid)})
    _login(client, "mv", ["ag.mietverwaltung"])
    ve = _ve_pill_classes(client.get("/tenants/"), t)
    assert ve["color"] == "green" and ve["present"]


@pytest.mark.django_db
def test_list_granter_sees_only_ve_pill(client, monkeypatch, settings):
    settings.TENANT_ROLE_GROUPS = {**_MV_GROUPS, "granter": ["ag.granter"]}
    t = _tenant("ve3", first_name="Realname")
    _assign(t)
    _ve_doc(t)
    _login(client, "gr", ["ag.granter"])
    resp = client.get("/tenants/")
    assert resp.status_code == 200
    assert not resp.context["show_realname"]
    row = next(r for r in resp.context["rows"] if r["tenant"].pk == t.pk)
    assert [d["short"] for d in row["documents"]] == ["VE"]
    assert row["documents"][0]["color"] == "yellow"
    html = resp.content.decode()
    assert 'data-col="documents"' in html and 'data-col="email"' not in html
    assert "Realname" not in html


@pytest.mark.django_db
def test_list_ldap_down_renders_unknown(client, monkeypatch, settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ve4")
    _assign(t)
    monkeypatch.setattr("app.clearance.clearance_member_uuids", lambda: None)
    _login(client, "mv", ["ag.mietverwaltung"])
    resp = client.get("/tenants/")
    assert _ve_pill_classes(resp, t)["color"] == "unknown"
    assert "ca-pill-unknown" in resp.content.decode()
