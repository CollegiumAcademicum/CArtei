"""View-level wiring for the new overview columns: Briefkasten, Nachweis,
FLINTA/Barrierefrei, per-survey engagement verdict, and bidirectional sublet.
"""
import uuid
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.utils import timezone

from app.models import (
    AGAbfrage, AGAbfrageResult, Building, EnrollmentProof, Room, Tenant,
    TenantRoomAssignment, WG,
)

_MV_GROUPS = {"cluster": ["gr.cluster"], "mietverwaltung": ["ag.mietverwaltung"]}


def _tenant(username, **kw):
    return Tenant.objects.create(
        first_name=kw.get("first_name", "Ada"), last_name=kw.get("last_name", "Lovelace"),
        email=f"{username}@ca.de", intranet_username=username, intranet_uuid=uuid.uuid4(),
        preferred_name=kw.get("preferred_name", username),
        is_flinta=kw.get("is_flinta", False),
        barrier_free_needed=kw.get("barrier_free_needed", False),
        mailbox_list_opt_in=kw.get("mailbox_list_opt_in", False),
    )


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)


def _room(cluster=None, name="R1"):
    b = Building.objects.create(name=f"Haus-{uuid.uuid4().hex[:6]}")
    wg = WG.objects.create(building=b, name="WG1", cluster=cluster)
    return Room.objects.create(wg=wg, name=name, size_sqm=12)


def _proof(tenant, verified=True, needs_review=False, valid_days=30):
    return EnrollmentProof.objects.create(
        tenant=tenant, enrollment_type="STUDY", file_name="n.pdf", file_data=b"x",
        uploaded_at=timezone.now(), valid_until=date.today() + timedelta(days=valid_days),
        verified_at=timezone.now() if verified else None, needs_human_review=needs_review,
    )


def _abfrage():
    today = date.today()
    return AGAbfrage.objects.create(
        date=today, label="Q3", ends_at=today + timedelta(days=7),
        grace_ends_at=today + timedelta(days=14),
    )


@pytest.mark.django_db
def test_briefkasten_column_shows_ja_for_opt_in(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("ada", mailbox_list_opt_in=True)
    c = Client(); _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert 'data-col="mailbox"' in body


@pytest.mark.django_db
def test_proof_column_flags_pending_for_verifier(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    _proof(t, verified=False)
    c = Client(); _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert 'data-col="proof"' in body
    assert "Prüfung" in body


@pytest.mark.django_db
def test_proof_column_hidden_from_plain_user(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("ada")
    c = Client(); _login(c, "plain")
    assert 'data-col="proof"' not in c.get("/tenants/").content.decode()


def _datenschutz(tenant, revoked=False):
    from app.models import DatenschutzDocument
    return DatenschutzDocument.objects.create(
        tenant=tenant, file_name="d.pdf", file_data=b"x", signed_at=date.today(),
        uploaded_at=timezone.now(), uploaded_by=tenant,
        revoked_at=timezone.now() if revoked else None,
    )


@pytest.mark.django_db
def test_documents_column_shows_missing_type(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    _datenschutz(t)  # has Datenschutz, no Fotoerlaubnis
    c = Client(); _login(c, "mv", groups=["ag.mietverwaltung"])
    resp = c.get("/tenants/?residents=all")
    row = {r["tenant"].pk: r for r in resp.context["rows"]}[t.pk]
    present = {d["short"]: d["present"] for d in row["documents"]}
    assert present == {
        "DS": True, "FoE": False, "VE": False, "MVt": False, "AMB": False,
        "SEPA": False, "Bes": False, "SVE": False,
    }
    assert 'data-col="documents"' in resp.content.decode()


@pytest.mark.django_db
def test_documents_column_ignores_revoked(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    _datenschutz(t, revoked=True)  # revoked -> counts as missing
    c = Client(); _login(c, "mv", groups=["ag.mietverwaltung"])
    row = {r["tenant"].pk: r for r in c.get("/tenants/?residents=all").context["rows"]}[t.pk]
    assert {d["short"]: d["present"] for d in row["documents"]} == {
        "DS": False, "FoE": False, "VE": False, "MVt": False, "AMB": False,
        "SEPA": False, "Bes": False, "SVE": False,
    }


@pytest.mark.django_db
def test_documents_column_hidden_from_plain_user(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    _tenant("ada")
    c = Client(); _login(c, "plain")
    assert 'data-col="documents"' not in c.get("/tenants/").content.decode()


@pytest.mark.django_db
def test_reverse_sublet_shows_both_directions(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    landlord = _tenant("owner", preferred_name="Vermieta")
    subletter = _tenant("subby", preferred_name="Untermieta")
    room = _room()
    # landlord holds the room; subletter rents it from them
    TenantRoomAssignment.objects.create(tenant=landlord, room=room, moved_in=date(2024, 1, 1))
    TenantRoomAssignment.objects.create(
        tenant=subletter, room=room, moved_in=date(2024, 1, 1),
        is_sublet=True, sublet_of_tenant=landlord,
    )
    c = Client(); _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert "Untermiete von" in body          # on the subletter's row
    assert "Untervermietet an" in body       # on the landlord's row (reverse)


@pytest.mark.django_db
def test_multiple_active_assignments_all_shown(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    TenantRoomAssignment.objects.create(tenant=t, room=_room(name="Zimmer-Alpha"), moved_in=date(2024, 1, 1))
    TenantRoomAssignment.objects.create(tenant=t, room=_room(name="Zimmer-Beta"), moved_in=date(2024, 6, 1))
    c = Client(); _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get("/tenants/").content.decode()
    assert "Zimmer-Alpha" in body
    assert "Zimmer-Beta" in body


@pytest.mark.django_db
def test_engagement_verdict_flag_for_inactive(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    a = _abfrage()
    AGAbfrageResult.objects.create(abfrage=a, tenant=t, ag_name="ag.kueche", status="INAKTIV")
    c = Client(); _login(c, "cl", groups=["gr.cluster"])
    body = c.get(f"/tenants/?surveys={a.pk}&residents=all").content.decode()
    assert "verdict-flag" in body


@pytest.mark.django_db
def test_engagement_verdict_cleared_for_active(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    a = _abfrage()
    AGAbfrageResult.objects.create(abfrage=a, tenant=t, ag_name="ag.kueche", status="AKTIV")
    c = Client(); _login(c, "cl", groups=["gr.cluster"])
    body = c.get(f"/tenants/?surveys={a.pk}&residents=all").content.decode()
    assert "verdict-ok" in body


@pytest.mark.django_db
def test_cluster_grouping_renders_group_header(settings):
    settings.TENANT_ROLE_GROUPS = _MV_GROUPS
    t = _tenant("ada")
    room = _room(cluster="A")
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2024, 1, 1))
    c = Client(); _login(c, "cl", groups=["gr.cluster"])
    body = c.get("/tenants/?group=cluster").content.decode()
    assert "cluster-group-header" in body
    assert "Cluster A" in body
