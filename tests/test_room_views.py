import datetime
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import Building, Room, Tenant, TenantRoomAssignment, WG

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
