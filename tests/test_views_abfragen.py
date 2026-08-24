import uuid
from datetime import date, timedelta
import pytest
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.test import Client


def _open_abfrage():
    from app.models import AGAbfrage
    today = date.today()
    return AGAbfrage.objects.create(
        date=today,
        label="Test Abfrage",
        ends_at=today + timedelta(days=7),
        grace_ends_at=today + timedelta(days=14),
    )


def _closed_abfrage():
    from app.models import AGAbfrage
    today = date.today()
    return AGAbfrage.objects.create(
        date=today - timedelta(days=30),
        ends_at=today - timedelta(days=15),
        grace_ends_at=today - timedelta(days=8),
    )


def _user_in_group(username, *group_names):
    user = User.objects.create_user(username=username, password="pw")
    for name in group_names:
        g, _ = Group.objects.get_or_create(name=name)
        user.groups.add(g)
    return user


@pytest.mark.django_db
def test_list_requires_login():
    client = Client()
    response = client.get("/abfragen/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_list_shows_abfragen():
    _open_abfrage()
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/abfragen/")
    assert response.status_code == 200
    assert b"Test Abfrage" in response.content


@pytest.mark.django_db
def test_new_abfrage_requires_privileged():
    client = Client()
    client.force_login(User.objects.create_user(username="nobody"))
    response = client.post("/abfragen/new/", {
        "date": "2024-09-01",
        "label": "Test",
        "ends_at": "2024-09-30",
        "grace_ends_at": "2024-10-07",
    })
    assert response.status_code == 403


@pytest.mark.django_db
def test_new_abfrage_creates_and_redirects():
    client = Client()
    client.force_login(_user_in_group("clusteruser", "gr.cluster"))
    response = client.post("/abfragen/new/", {
        "date": "2024-09-01",
        "label": "Q3 2024",
        "ends_at": "2024-09-30",
        "grace_ends_at": "2024-10-07",
    })
    assert response.status_code == 302
    from app.models import AGAbfrage
    assert AGAbfrage.objects.filter(label="Q3 2024").exists()


@pytest.mark.django_db
def test_ag_edit_denies_wrong_ag():
    abfrage = _open_abfrage()
    user = _user_in_group("kueche_user", "ag.kueche")
    client = Client()
    client.force_login(user)
    # User is in ag.kueche but tries to edit ag.garten
    response = client.get(f"/abfragen/{abfrage.pk}/ag/ag.garten/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_ag_edit_allows_own_ag():
    abfrage = _open_abfrage()
    user = _user_in_group("kueche_user2", "ag.kueche")
    client = Client()
    client.force_login(user)

    fake_members = [{"username": "kueche_user2", "first_name": "K", "last_name": "U", "email": "k@ca.de", "uuid": str(uuid.uuid4())}]
    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=fake_members):
        response = client.get(f"/abfragen/{abfrage.pk}/ag/ag.kueche/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_ag_edit_closed_returns_closed_page():
    abfrage = _closed_abfrage()
    user = _user_in_group("kueche_user3", "ag.kueche")
    client = Client()
    client.force_login(user)

    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=[]):
        response = client.get(f"/abfragen/{abfrage.pk}/ag/ag.kueche/")
    assert response.status_code == 200
    assert b"geschlossen" in response.content


@pytest.mark.django_db
def test_ag_edit_post_saves_result():
    from app.models import AGAbfrage, AGAbfrageResult, Tenant
    abfrage = _open_abfrage()
    tenant = Tenant.objects.create(
        first_name="T", last_name="U", email="tu@ca.de",
        intranet_username="tu_post", intranet_uuid=uuid.uuid4(),
    )
    user = _user_in_group("tu_post", "ag.kueche")
    client = Client()
    client.force_login(user)

    fake_members = [{"username": "tu_post", "first_name": "T", "last_name": "U", "email": "tu@ca.de", "uuid": str(tenant.intranet_uuid)}]
    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=fake_members):
        response = client.post(
            f"/abfragen/{abfrage.pk}/ag/ag.kueche/",
            {f"status_{tenant.pk}": "AKTIV", f"note_{tenant.pk}": "Good work"},
        )

    assert response.status_code == 302
    result = AGAbfrageResult.objects.get(abfrage=abfrage, tenant=tenant, ag_name="ag.kueche")
    assert result.status == "AKTIV"
    assert result.note == "Good work"


@pytest.mark.django_db
def test_ag_edit_post_saves_arbitrary_tenant():
    # A tenant who is NOT an LDAP member of the AG can still be recorded via the picker.
    from app.models import AGAbfrageResult, Tenant
    abfrage = _open_abfrage()
    editor = _user_in_group("editor_arb", "ag.kueche")
    outsider = Tenant.objects.create(
        first_name="Out", last_name="Sider", email="out@ca.de",
        intranet_username="outsider", intranet_uuid=uuid.uuid4(),
    )
    client = Client()
    client.force_login(editor)

    # LDAP returns no members — the outsider is added purely via the arbitrary picker.
    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=[]):
        response = client.post(
            f"/abfragen/{abfrage.pk}/ag/ag.kueche/",
            {f"status_{outsider.pk}": "IM_GESPRAECH", f"note_{outsider.pk}": "extern"},
        )
        assert response.status_code == 302
        result = AGAbfrageResult.objects.get(abfrage=abfrage, tenant=outsider, ag_name="ag.kueche")
        assert result.status == "IM_GESPRAECH"
        assert result.note == "extern"

        # Reappears on reload even though the tenant is not an LDAP member.
        get = client.get(f"/abfragen/{abfrage.pk}/ag/ag.kueche/")
    assert b"Out Sider" in get.content
    assert f'name="status_{outsider.pk}"'.encode() in get.content


@pytest.mark.django_db
def test_ag_edit_post_saves_health():
    from app.models import AGAbfrageHealth
    abfrage = _open_abfrage()
    user = _user_in_group("health_user", "ag.kueche")
    client = Client()
    client.force_login(user)

    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=[]):
        response = client.post(
            f"/abfragen/{abfrage.pk}/ag/ag.kueche/",
            {"health": "KRITISCH", "health_note": "kaum noch Leute"},
        )
    assert response.status_code == 302
    h = AGAbfrageHealth.objects.get(abfrage=abfrage, ag_name="ag.kueche")
    assert h.health == "KRITISCH"
    assert h.note == "kaum noch Leute"


@pytest.mark.django_db
def test_ag_edit_shows_health_slider():
    abfrage = _open_abfrage()
    user = _user_in_group("slider_user", "ag.kueche")
    client = Client()
    client.force_login(user)
    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=[]):
        response = client.get(f"/abfragen/{abfrage.pk}/ag/ag.kueche/")
    assert b"ca-slider" in response.content
    assert b'name="health"' in response.content


@pytest.mark.django_db
def test_detail_shows_ag_health_badge():
    from app.models import AGAbfrageHealth, AGAbfrageResult, Tenant
    abfrage = _open_abfrage()
    tenant = Tenant.objects.create(
        first_name="D", last_name="T", email="dt@ca.de",
        intranet_username="dt_detail", intranet_uuid=uuid.uuid4(),
    )
    AGAbfrageResult.objects.create(abfrage=abfrage, ag_name="ag.kueche", tenant=tenant, status="AKTIV")
    AGAbfrageHealth.objects.create(abfrage=abfrage, ag_name="ag.kueche", health="TOT")

    client = Client()
    client.force_login(_user_in_group("cluster_detail", "gr.cluster"))
    response = client.get(f"/abfragen/{abfrage.pk}/")
    assert response.status_code == 200
    assert b"badge-TOT" in response.content


@pytest.mark.django_db
def test_initiative_edit_allowed():
    abfrage = _open_abfrage()
    user = _user_in_group("in_user", "in.gemeinschaft")
    client = Client()
    client.force_login(user)
    fake_members = [{"username": "in_user", "first_name": "I", "last_name": "N", "email": "i@ca.de", "uuid": str(uuid.uuid4())}]
    with patch("app.views.abfragen.ldap_utils.get_ag_members", return_value=fake_members):
        response = client.get(f"/abfragen/{abfrage.pk}/ag/in.gemeinschaft/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_list_shows_user_groups_for_open_abfrage():
    _open_abfrage()
    user = _user_in_group("multi_user", "ag.kueche", "in.gemeinschaft")
    client = Client()
    client.force_login(user)
    response = client.get("/abfragen/")
    assert response.status_code == 200
    assert b"ag.kueche" in response.content
    assert b"in.gemeinschaft" in response.content


@pytest.mark.django_db
def test_tenants_view_requires_privileged():
    abfrage = _open_abfrage()
    user = User.objects.create_user(username="nobody2")
    client = Client()
    client.force_login(user)
    response = client.get(f"/abfragen/{abfrage.pk}/tenants/")
    assert response.status_code == 403
