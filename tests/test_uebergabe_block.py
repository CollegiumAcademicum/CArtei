import datetime
import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from app.models import Building, Room, Tenant, TenantRoomAssignment, WG

@pytest.fixture
def wg_setup(db):
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="Alice", last_name="B", intranet_username="ab", intranet_uuid=uuid.uuid4())
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))
    return wg

@pytest.fixture
def helper(db):
    u = User.objects.create_user("helper", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    return u

@pytest.mark.django_db
def test_helper_sees_protocol_block_not_contracts(client, wg_setup, helper):
    client.force_login(helper)
    html = client.get(reverse("wg_detail", args=[wg_setup.pk])).content.decode()
    assert "Übergabeprotokoll" in html          # protocol block present
    assert "Alice" in html                        # occupant name visible
    assert "Mietvertrag" not in html              # MV-only docs hidden
