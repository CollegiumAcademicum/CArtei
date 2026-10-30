import uuid
import pytest
from unittest.mock import patch
from django.contrib.auth.models import User, Group
from django.test import Client


def _admin_user(username="admin"):
    user = User.objects.create_user(username=username, password="pw")
    group, _ = Group.objects.get_or_create(name="admins")
    user.groups.add(group)
    return user


FAKE_MEMBERS = [
    {"username": "alice", "first_name": "Alice", "last_name": "A", "email": "alice@ca.de", "uuid": str(uuid.uuid4())},
    {"username": "bob",   "first_name": "Bob",   "last_name": "B", "email": "bob@ca.de",   "uuid": str(uuid.uuid4())},
]


@pytest.mark.django_db
def test_admin_portal_requires_admin():
    client = Client()
    user = User.objects.create_user(username="nobody", password="pw")
    client.force_login(user)
    assert client.get("/admin/").status_code == 403


@pytest.mark.django_db
def test_admin_portal_renders():
    client = Client()
    client.force_login(_admin_user())
    response = client.get("/admin/")
    assert response.status_code == 200
    assert b"Admin-Portal" in response.content


@pytest.mark.django_db
def test_sync_requires_admin():
    client = Client()
    user = User.objects.create_user(username="nobody", password="pw")
    client.force_login(user)
    assert client.post("/admin/sync-from-ldap/").status_code == 403


@pytest.mark.django_db
def test_sync_requires_post():
    client = Client()
    client.force_login(_admin_user())
    assert client.get("/admin/sync-from-ldap/").status_code == 405


@pytest.mark.django_db
def test_sync_creates_tenants():
    client = Client()
    client.force_login(_admin_user())

    with patch("app.views.admin_views.ldap_utils.get_clearance_members", return_value=FAKE_MEMBERS):
        response = client.post("/admin/sync-from-ldap/")

    assert response.status_code == 302
    assert response["Location"] == "/admin/"

    from app.models import Tenant
    assert Tenant.objects.filter(intranet_username="alice").exists()
    assert Tenant.objects.filter(intranet_username="bob").exists()


@pytest.mark.django_db
def test_sync_does_not_overwrite_existing():
    from app.models import Tenant
    Tenant.objects.create(
        first_name="Old", last_name="Name", email="old@ca.de",
        intranet_username="alice", intranet_uuid=uuid.uuid4(),
    )

    client = Client()
    client.force_login(_admin_user())

    with patch("app.views.admin_views.ldap_utils.get_clearance_members", return_value=FAKE_MEMBERS):
        client.post("/admin/sync-from-ldap/")

    alice = Tenant.objects.get(intranet_username="alice")
    assert alice.first_name == "Old"  # not overwritten


def _history(entity_type, entity_id, snapshot, by="alice"):
    from django.utils import timezone
    from app.models import EntityHistory
    return EntityHistory.objects.create(
        entity_type=entity_type, entity_id=entity_id, snapshot=snapshot,
        changed_at=timezone.now(), changed_by=by, change_source="HUMAN",
    )


@pytest.mark.django_db
def test_audit_log_requires_admin():
    client = Client()
    client.force_login(User.objects.create_user(username="nobody", password="pw"))
    assert client.get("/admin/history/").status_code == 403


@pytest.mark.django_db
def test_audit_log_diffs_against_next_snapshot_and_live_row():
    from app.models import Tenant
    t = Tenant.objects.create(
        first_name="Carla", last_name="Neu", email="c@ca.de", intranet_uuid=uuid.uuid4(),
    )
    _history("tenant", t.pk, {"id": t.pk, "first_name": "Karla", "last_name": "Alt"})
    _history("tenant", t.pk, {"id": t.pk, "first_name": "Carla", "last_name": "Alt"}, by="bob")
    _history("wg", 999, {"id": 999, "name": "Weg"})

    client = Client()
    client.force_login(_admin_user())
    entries = client.get("/admin/history/").context["entries"]

    wg, newest, oldest = entries
    assert wg["deleted"]  # no live row
    assert newest["changes"] == [{"field": "last_name", "before": "Alt", "after": "Neu"}]
    assert oldest["changes"] == [{"field": "first_name", "before": "Karla", "after": "Carla"}]

    filtered = client.get(f"/admin/history/?type=tenant&by=bob").context["entries"]
    assert [e["h"].changed_by for e in filtered] == ["bob"]
