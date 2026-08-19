import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from app.models import InternalNote, Tenant


def _make_tenant(username):
    return Tenant.objects.create(
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
        first_name="Test",
        last_name="User",
    )


def _make_user_in_group(username, group_name):
    user = User.objects.create_user(username=username)
    g, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(g)
    return user


@pytest.mark.django_db
def test_add_note_requires_login():
    client = Client()
    resp = client.post("/notes/add/", {"source_group": "mietverwaltung", "subject_type": "tenant", "subject_id": "1", "body": "hi"})
    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


@pytest.mark.django_db
def test_cluster_user_can_add_note(settings):
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"]}
    user = _make_user_in_group("cluster_user", "gr.cluster")
    _make_tenant("cluster_user")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "clustersprechende",
        "subject_type": "tenant",
        "subject_id": "1",
        "body": "Cluster note",
        "next": "/dashboard/",
    })
    assert resp.status_code == 302
    assert InternalNote.objects.filter(body="Cluster note", source_group="clustersprechende").exists()


@pytest.mark.django_db
def test_add_note_creates_note(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    user = _make_user_in_group("mv_user", "ag.mietverwaltung")
    _make_tenant("mv_user")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "mietverwaltung",
        "subject_type": "tenant",
        "subject_id": "42",
        "body": "Test note",
        "next": "/dashboard/",
    })
    assert resp.status_code == 302
    assert resp["Location"] == "/dashboard/"
    note = InternalNote.objects.get(body="Test note")
    assert note.body == "Test note"
    assert note.source_group == "mietverwaltung"
    assert note.subject_id == 42
    assert note.deleted_at is None


@pytest.mark.django_db
def test_add_note_denied_wrong_group(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    user = _make_user_in_group("cluster_user", "gr.cluster")
    _make_tenant("cluster_user")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "mietverwaltung",
        "subject_type": "tenant",
        "subject_id": "1",
        "body": "should fail",
    })
    assert resp.status_code == 403


@pytest.mark.django_db
def test_add_note_denied_empty_body(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    user = _make_user_in_group("mv2", "ag.mietverwaltung")
    _make_tenant("mv2")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "mietverwaltung",
        "subject_type": "tenant",
        "subject_id": "1",
        "body": "   ",
    })
    assert resp.status_code == 403


@pytest.mark.django_db
def test_add_note_admin_gets_all_groups(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "cluster": ["gr.cluster"]}
    user = _make_user_in_group("admin_user", "admins")
    _make_tenant("admin_user")
    client = Client()
    client.force_login(user)
    # Admin can write as clustersprechende
    resp = client.post("/notes/add/", {
        "source_group": "clustersprechende",
        "subject_type": "cluster",
        "subject_id": "5",
        "body": "admin note",
    })
    assert resp.status_code == 302
    assert InternalNote.objects.filter(source_group="clustersprechende").exists()


@pytest.mark.django_db
def test_delete_note_soft_deletes(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    user = _make_user_in_group("mv3", "ag.mietverwaltung")
    author = _make_tenant("mv3")
    from django.utils.timezone import now
    note = InternalNote.objects.create(
        body="to delete",
        source_group="mietverwaltung",
        subject_type="tenant",
        subject_id=1,
        created_at=now(),
        created_by=author,
    )
    client = Client()
    client.force_login(user)
    resp = client.post(f"/notes/{note.pk}/delete/", {"next": "/dashboard/"})
    assert resp.status_code == 302
    note.refresh_from_db()
    assert note.deleted_at is not None


@pytest.mark.django_db
def test_delete_note_denied_wrong_group(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "cluster": ["gr.cluster"]}
    author_user = _make_user_in_group("mv4", "ag.mietverwaltung")
    author = _make_tenant("mv4")
    cluster_user = _make_user_in_group("cluster4", "gr.cluster")
    _make_tenant("cluster4")
    from django.utils.timezone import now
    note = InternalNote.objects.create(
        body="mv note",
        source_group="mietverwaltung",
        subject_type="tenant",
        subject_id=1,
        created_at=now(),
        created_by=author,
    )
    client = Client()
    client.force_login(cluster_user)
    resp = client.post(f"/notes/{note.pk}/delete/", {})
    assert resp.status_code == 403
    note.refresh_from_db()
    assert note.deleted_at is None


@pytest.mark.django_db
def test_belegium_can_add_room_assignment_note(settings):
    settings.TENANT_ROLE_GROUPS = {"belegium": ["gr.belegium"]}
    user = _make_user_in_group("bel_user", "gr.belegium")
    _make_tenant("bel_user")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "belegung",
        "subject_type": "room_assignment",
        "subject_id": "7",
        "body": "Belegium note",
    })
    assert resp.status_code == 302
    assert InternalNote.objects.filter(
        body="Belegium note", source_group="belegung", subject_type="room_assignment"
    ).exists()


@pytest.mark.django_db
def test_mietverwaltung_can_add_belegung_note(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    user = _make_user_in_group("mv_bel", "ag.mietverwaltung")
    _make_tenant("mv_bel")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "belegung",
        "subject_type": "room_assignment",
        "subject_id": "7",
        "body": "MV belegung note",
    })
    assert resp.status_code == 302
    assert InternalNote.objects.filter(source_group="belegung").exists()


@pytest.mark.django_db
def test_cluster_cannot_add_belegung_note(settings):
    settings.TENANT_ROLE_GROUPS = {"cluster": ["gr.cluster"], "belegium": ["gr.belegium"]}
    user = _make_user_in_group("clus_bel", "gr.cluster")
    _make_tenant("clus_bel")
    client = Client()
    client.force_login(user)
    resp = client.post("/notes/add/", {
        "source_group": "belegung",
        "subject_type": "room_assignment",
        "subject_id": "7",
        "body": "nope",
    })
    assert resp.status_code == 403


@pytest.mark.django_db
def test_belegium_can_delete_mv_authored_belegung_note(settings):
    # Shared thread: Mietverwaltung writes, Belegium deletes the same note.
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"], "belegium": ["gr.belegium"]}
    author = _make_tenant("mv_author")
    bel_user = _make_user_in_group("bel_del", "gr.belegium")
    _make_tenant("bel_del")
    from django.utils.timezone import now
    note = InternalNote.objects.create(
        body="shared", source_group="belegung", subject_type="room_assignment",
        subject_id=7, created_at=now(), created_by=author,
    )
    client = Client()
    client.force_login(bel_user)
    resp = client.post(f"/notes/{note.pk}/delete/", {"next": "/"})
    assert resp.status_code == 302
    note.refresh_from_db()
    assert note.deleted_at is not None


@pytest.mark.django_db
def test_admin_can_delete_any_note(settings):
    settings.TENANT_ROLE_GROUPS = {"mietverwaltung": ["ag.mietverwaltung"]}
    author = _make_tenant("author_admin_delete")
    admin_user = _make_user_in_group("admin_delete", "admins")
    _make_tenant("admin_delete")
    from django.utils.timezone import now
    note = InternalNote.objects.create(
        body="admin delete test",
        source_group="mietverwaltung",
        subject_type="tenant",
        subject_id=1,
        created_at=now(),
        created_by=author,
    )
    client = Client()
    client.force_login(admin_user)
    resp = client.post(f"/notes/{note.pk}/delete/", {"next": "/"})
    assert resp.status_code == 302
    note.refresh_from_db()
    assert note.deleted_at is not None
