import uuid
import pytest
from django.contrib.auth.models import User, Group

from app.models import Building, WG, Room, Tenant


def _login(client, username, group=None):
    u = User.objects.create_user(username=username, password="x")
    if group:
        g, _ = Group.objects.get_or_create(name=group)
        u.groups.add(g)
    Tenant.objects.create(first_name=username, last_name="T", intranet_username=username, intranet_uuid=uuid.uuid4())
    client.force_login(u)
    return u


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    return {"wg": wg, "room": room}


def test_staff_sees_damage_panels(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.get(f"/wgs/{world['wg'].id}/")
    assert r.status_code == 200
    assert b"damages/add" in r.content  # add form rendered for staff


def test_belegium_sees_no_damage_panels(client, world):
    _login(client, "beleg", "gr.belegium")
    r = client.get(f"/wgs/{world['wg'].id}/")
    assert r.status_code == 200
    assert b"damages/add" not in r.content  # no add form action rendered
