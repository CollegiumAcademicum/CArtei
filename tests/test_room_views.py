import datetime
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import AGAbfrage, AGAbfrageResult, Building, Room, Tenant, TenantRoomAssignment, WG
from app.forms import TenantRoomAssignmentForm  # noqa: F401

pytestmark = pytest.mark.django_db


def _login(client, *groups):
    u = User.objects.create_user("staff", password="x")
    for g in groups:
        u.groups.add(Group.objects.get_or_create(name=g)[0])
    client.force_login(u)
    return u


def _housing():
    b = Building.objects.create(name="Haus A")
    wg = WG.objects.create(building=b, name="WG 1", cluster="1A")
    room = Room.objects.create(wg=wg, name="Zimmer 1", size_sqm=15)
    t = Tenant.objects.create(
        first_name="Mira", last_name="Muster", email="m@x.de",
        intranet_username="mira", intranet_uuid="00000000-0000-0000-0000-000000000001",
    )
    return b, wg, room, t


def test_list_groups_rooms_under_wg(client):
    _login(client, "ag.mietverwaltung")
    b, wg, room, t = _housing()
    resp = client.get(reverse("wg_list"))
    assert resp.status_code == 200
    assert b"Haus A" in resp.content and b"WG 1" in resp.content and b"Zimmer 1" in resp.content


def test_list_asof_occupancy(client):
    _login(client, "ag.mietverwaltung")
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room,
        moved_in=datetime.date(2026, 1, 1), moved_out=datetime.date(2026, 3, 1),
    )
    inside = client.get(reverse("wg_list"), {"as_of": "2026-02-01"})
    assert b"Mira" in inside.content
    after = client.get(reverse("wg_list"), {"as_of": "2026-06-01"})
    assert b"Mira" not in after.content  # frei on that date


def test_list_hides_name_without_permission(client):
    _login(client, "gr.cluster")  # cluster does not grant first_name
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    resp = client.get(reverse("wg_list"))
    assert b"Mira" not in resp.content
    assert b"belegt" in resp.content


def test_list_bad_as_of_falls_back(client):
    _login(client, "ag.mietverwaltung")
    _housing()
    resp = client.get(reverse("wg_list"), {"as_of": "not-a-date"})
    assert resp.status_code == 200


# ---- Task 4: WG detail tests ------------------------------------------------

def test_detail_shows_history_and_asof_marker(client):
    _login(client, "ag.mietverwaltung")
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room,
        moved_in=datetime.date(2026, 1, 1), moved_out=datetime.date(2026, 3, 1),
    )
    resp = client.get(reverse("wg_detail", args=[wg.pk]), {"as_of": "2026-02-01"})
    assert resp.status_code == 200
    assert b"Zimmer 1" in resp.content
    assert b"wg-current" in resp.content  # active-on-date marker present


def test_detail_engagement_rollup_time_travels(client):
    _login(client, "admins")
    b, wg, room, t = _housing()
    t2 = Tenant.objects.create(
        first_name="Ada", last_name="Test", email="a@x.de",
        intranet_username="ada", intranet_uuid="00000000-0000-0000-0000-000000000002",
    )
    room2 = Room.objects.create(wg=wg, name="Zimmer 2", size_sqm=12)
    for tt, rr in ((t, room), (t2, room2)):
        TenantRoomAssignment.objects.create(tenant=tt, room=rr, moved_in=datetime.date(2026, 1, 1), moved_out=None)
    old = AGAbfrage.objects.create(date=datetime.date(2026, 1, 15), ends_at=datetime.date(2026, 2, 1), grace_ends_at=datetime.date(2026, 2, 8))
    new = AGAbfrage.objects.create(date=datetime.date(2026, 5, 15), ends_at=datetime.date(2026, 6, 1), grace_ends_at=datetime.date(2026, 6, 8))
    # In the old survey only Mira is active; in the new survey nobody is.
    AGAbfrageResult.objects.create(abfrage=old, ag_name="Garten", tenant=t, status="AKTIV")
    # as_of before the new survey -> uses `old` -> 1 von 2 met
    resp = client.get(reverse("wg_detail", args=[wg.pk]), {"as_of": "2026-03-01"})
    assert b"1 von 2" in resp.content
    # as_of after the new survey -> uses `new` -> 0 von 2 met
    resp2 = client.get(reverse("wg_detail", args=[wg.pk]), {"as_of": "2026-07-01"})
    assert b"0 von 2" in resp2.content


def test_detail_engagement_hidden_for_non_cluster(client):
    _login(client, "ag.mietverwaltung")  # not cluster/admin
    b, wg, room, t = _housing()
    resp = client.get(reverse("wg_detail", args=[wg.pk]))
    assert b"erf\xc3\xbcllen ihr Engagement" not in resp.content


# ---- Task 5: inline editing tests -------------------------------------------

def test_detail_mv_can_edit_assignment(client):
    _login(client, "ag.mietverwaltung")
    b, wg, room, t = _housing()
    a = TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    resp = client.post(reverse("wg_detail", args=[wg.pk]), {
        "section": "housing",
        "assignment_ids": str(a.pk),
        f"room_{a.pk}-room": str(room.pk),
        f"room_{a.pk}-moved_in": "2026-01-05",
        f"room_{a.pk}-is_sublet": "",
    })
    assert resp.status_code in (200, 302)
    a.refresh_from_db()
    assert a.moved_in == datetime.date(2026, 1, 5)


def test_detail_owner_cannot_edit(client):
    _login(client, "gr.cluster")  # cluster role: neither MV/admin nor belegium — read-only
    b, wg, room, t = _housing()
    a = TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    client.post(reverse("wg_detail", args=[wg.pk]), {
        "section": "housing", "assignment_ids": str(a.pk),
        f"room_{a.pk}-room": str(room.pk), f"room_{a.pk}-moved_in": "2026-02-02",
    })
    a.refresh_from_db()
    assert a.moved_in == datetime.date(2026, 1, 1)  # unchanged — read-only for this role


# ---- Finding 1: PII gate on detail view -----------------------------------------

def test_detail_history_hidden_for_non_room_staff(client):
    """gr.cluster viewer (not room-staff) sees belegt/frei summary, not cards/names/dates/forms."""
    _login(client, "gr.cluster")
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    resp = client.get(reverse("wg_detail", args=[wg.pk]))
    assert resp.status_code == 200
    assert b"Mira" not in resp.content
    assert b"2026-01-01" not in resp.content  # no move-in date string
    assert b"form-room-" not in resp.content  # no edit form
    assert b"belegt" in resp.content


def test_detail_shows_occupant_name_for_mv(client):
    """ag.mietverwaltung viewer (room-staff + may_see_names) sees occupant display name."""
    _login(client, "ag.mietverwaltung")
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    resp = client.get(reverse("wg_detail", args=[wg.pk]))
    assert resp.status_code == 200
    assert b"Mira" in resp.content
