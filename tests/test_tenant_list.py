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
        move_out=kw.get("move_out"),
        move_in=kw.get("move_in"),
    )


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)
    return user


def _assign(tenant, cluster=None, is_sublet=False):
    b = Building.objects.create(name=f"Haus-{uuid.uuid4().hex[:6]}")
    wg = WG.objects.create(building=b, name="WG1", cluster=cluster)
    room = Room.objects.create(wg=wg, name="R1", size_sqm=12)
    return TenantRoomAssignment.objects.create(
        tenant=tenant, room=room, moved_in=date(2024, 1, 1), is_sublet=is_sublet
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
    _tenant("owner", preferred_name="Owzy", last_name="Secret", email="owner@ca.de")
    c = Client()
    _login(c, "stranger")
    body = c.get("/tenants/").content.decode()
    assert "Owzy" in body
    assert "owner@ca.de" not in body
    assert "Secret" not in body


@pytest.mark.django_db
def test_mietverwaltung_sees_email_and_realname(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("owner", preferred_name="Owzy", last_name="Secret", email="owner@ca.de")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert "owner@ca.de" in body
    assert "Secret" in body


@pytest.mark.django_db
def test_search_filters_by_name(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("ada", first_name="Ada", last_name="Lovelace", preferred_name="")
    _tenant("grace", first_name="Grace", last_name="Hopper", preferred_name="")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/?q=Hopper").content.decode()
    assert "Hopper" in body
    assert "Lovelace" not in body


@pytest.mark.django_db
def test_active_default_excludes_former(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("current", preferred_name="Current")
    _tenant("gone", preferred_name="Gone", move_out=date.today() - timedelta(days=5))
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    active = c.get("/tenants/").content.decode()
    assert "Current" in active and "Gone" not in active
    allr = c.get("/tenants/?residents=all").content.decode()
    assert "Current" in allr and "Gone" in allr


@pytest.mark.django_db
def test_sublet_filter(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    sub = _tenant("sub", preferred_name="Subby")
    reg = _tenant("reg", preferred_name="Reggy")
    _assign(sub, is_sublet=True)
    _assign(reg, is_sublet=False)
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/?sublet=only").content.decode()
    assert "Subby" in body and "Reggy" not in body


@pytest.mark.django_db
def test_sort_by_email(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("b", preferred_name="Bea", email="b@ca.de")
    _tenant("a", preferred_name="Ann", email="a@ca.de")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/?sort=email&dir=asc").content.decode()
    assert body.index("a@ca.de") < body.index("b@ca.de")


@pytest.mark.django_db
def test_hidden_column_sort_falls_back_and_does_not_crash(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("x", preferred_name="Xavier")
    c = Client()
    _login(c, "plain")  # no groups → can't see email/room columns
    resp = c.get("/tenants/?sort=email")
    assert resp.status_code == 200
    assert "Xavier" in resp.content.decode()


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
    body = c.get(f"/tenants/?surveys={a.pk}").content.decode()
    assert "ag.kueche" in body
    assert "aktiv" in body


@pytest.mark.django_db
def test_cluster_summary_rows_only_when_sorted_by_cluster(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada", preferred_name="Ada")
    _assign(t, cluster="A")
    a = _abfrage(label="Q3")
    _result(a, t, status="AKTIV")
    c = Client()
    _login(c, "cl", groups=["gr.cluster"])
    grouped = c.get(f"/tenants/?surveys={a.pk}&sort=cluster").content.decode()
    assert "cluster-summary" in grouped
    ungrouped = c.get(f"/tenants/?surveys={a.pk}&sort=name").content.decode()
    assert "cluster-summary" not in ungrouped


@pytest.mark.django_db
def test_kein_cluster_filter_shows_only_clusterless(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    clustered = _tenant("c", preferred_name="Clustered")
    _assign(clustered, cluster="A")
    _tenant("l", preferred_name="Lonely")  # no assignment → no cluster
    c = Client()
    _login(c, "cl", groups=["gr.cluster"])
    body = c.get("/tenants/?cluster=").content.decode()
    assert "Lonely" in body and "Clustered" not in body


@pytest.mark.django_db
def test_pagination(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    for i in range(30):
        _tenant(f"t{i}", preferred_name=f"Person{i:02d}", last_name=f"N{i:02d}")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    p1 = c.get("/tenants/?per_page=25&sort=name&dir=asc").content.decode()
    assert "Person00" in p1 and "Person29" not in p1
    p2 = c.get("/tenants/?per_page=25&sort=name&dir=asc&page=2").content.decode()
    assert "Person29" in p2 and "Person00" not in p2
