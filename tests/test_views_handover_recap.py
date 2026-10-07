# CArtei/tests/test_views_handover_recap.py
import uuid
import pytest
from datetime import date, datetime, timezone
from django.contrib.auth.models import User, Group

from app.models import (
    Building, WG, Room, Tenant, TenantRoomAssignment,
    RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, Uebergabe,
)


def _dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    wg2 = WG.objects.create(building=b, name="W2")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    t = Tenant.objects.create(first_name="Out", last_name="Going",
                              intranet_username="outg", intranet_uuid=uuid.uuid4())
    a = TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=date(2026, 1, 1), moved_out=date(2026, 6, 30))
    return {"wg": wg, "wg2": wg2, "room": room, "tenant": t, "assignment": a}


def _login_mv(client):
    u = User.objects.create_user(username="mv", password="x")
    g, _ = Group.objects.get_or_create(name="ag.mietverwaltung")
    u.groups.add(g)
    Tenant.objects.create(first_name="mv", last_name="T", intranet_username="mv",
                          intranet_uuid=uuid.uuid4())
    client.force_login(u)


def test_recap_windows_and_splits(client, world):
    _login_mv(client)
    t = world["tenant"]
    # inside window: one open, one fixed room damage
    RoomDamage.objects.create(room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
                              created_at=_dt(2026, 3, 1), created_by=t)
    RoomDamage.objects.create(room=world["room"], line=RoomDamageLine.WAND_LOECHER,
                              created_at=_dt(2026, 3, 2), created_by=t,
                              fixed_at=_dt(2026, 4, 1), fixed_by=t)
    # outside window (after move-out): must NOT appear
    RoomDamage.objects.create(room=world["room"], line=RoomDamageLine.TUER_FLECKEN,
                              created_at=_dt(2026, 9, 1), created_by=t)
    # WG damage inside window on THIS wg (appears) and on another wg (excluded)
    WGDamage.objects.create(wg=world["wg"], line=WGDamageLine.BAD_FLECK,
                            created_at=_dt(2026, 3, 3), created_by=t)
    WGDamage.objects.create(wg=world["wg2"], line=WGDamageLine.KUECHE_FLECK,
                            created_at=_dt(2026, 3, 3), created_by=t)

    u = Uebergabe.objects.create(room=world["room"], outgoing_assignment=world["assignment"],
                                 conducted_by=t, conducted_at=_dt(2026, 6, 30))
    r = client.get(f"/uebergabe/{u.id}/")
    assert r.status_code == 200
    assert len(r.context["room_open"]) == 1
    assert len(r.context["room_fixed"]) == 1
    assert len(r.context["wg_open"]) == 1   # only this wg's
    assert len(r.context["wg_fixed"]) == 0


def test_recap_no_assignment_no_lower_bound(client, world):
    _login_mv(client)
    t = world["tenant"]
    RoomDamage.objects.create(room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
                              created_at=_dt(2025, 1, 1), created_by=t)
    u = Uebergabe.objects.create(room=world["room"], outgoing_assignment=None,
                                 conducted_by=t, conducted_at=_dt(2026, 6, 30))
    r = client.get(f"/uebergabe/{u.id}/")
    assert r.status_code == 200
    assert len(r.context["room_open"]) == 1  # no lower bound → included


def test_recap_shows_both_tenants(client, world):
    _login_mv(client)
    incoming = Tenant.objects.create(first_name="New", last_name="Resident",
                                     intranet_username="newres", intranet_uuid=uuid.uuid4())
    in_a = TenantRoomAssignment.objects.create(tenant=incoming, room=world["room"],
                                               moved_in=date(2026, 7, 1))
    u = Uebergabe.objects.create(room=world["room"], outgoing_assignment=world["assignment"],
                                 incoming_assignment=in_a,
                                 conducted_by=world["tenant"], conducted_at=_dt(2026, 6, 30))
    r = client.get(f"/uebergabe/{u.id}/")
    body = r.content.decode()
    assert "Going" in body          # outgoing tenant last name (fixture "Out Going")
    assert "New Resident" in body   # incoming tenant


def test_recap_without_incoming_only_shows_outgoing(client, world):
    _login_mv(client)
    u = Uebergabe.objects.create(room=world["room"], outgoing_assignment=world["assignment"],
                                 incoming_assignment=None,
                                 conducted_by=world["tenant"], conducted_at=_dt(2026, 6, 30))
    r = client.get(f"/uebergabe/{u.id}/")
    assert r.status_code == 200
    assert "Einzug:" not in r.content.decode()
