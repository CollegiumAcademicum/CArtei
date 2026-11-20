"""Untermiete filter on the tenant and WG lists (#121)."""
import uuid
from datetime import date

import pytest
from django.contrib.auth.models import Group, User

from app.models import Building, Room, Tenant, TenantRoomAssignment, WG

pytestmark = pytest.mark.django_db

ROLES = {"mietverwaltung": ["ag.mietverwaltung"], "belegium": ["gr.belegium"], "cluster": ["gr.cluster"]}


def _tenant(name):
    return Tenant.objects.create(first_name=name, last_name="Test", preferred_name=name,
                                 intranet_username=name.lower(), intranet_uuid=uuid.uuid4())


@pytest.fixture
def flat():
    wg = WG.objects.create(building=Building.objects.create(name="Haus"), name="WG 1")
    r1 = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    r2 = Room.objects.create(wg=wg, name="1.02", size_sqm=12)
    main, sub, other = _tenant("Hauptmiete"), _tenant("Unterm"), _tenant("Normalo")
    TenantRoomAssignment.objects.create(tenant=main, room=r1, moved_in=date(2025, 1, 1))
    TenantRoomAssignment.objects.create(tenant=sub, room=r1, moved_in=date(2025, 6, 1),
                                        is_sublet=True, sublet_of_tenant=main)
    TenantRoomAssignment.objects.create(tenant=other, room=r2, moved_in=date(2025, 1, 1))
    return wg


def _login(client, settings, role):
    settings.TENANT_ROLE_GROUPS = ROLES
    u = User.objects.create_user("viewer")
    u.groups.add(Group.objects.get_or_create(name=ROLES[role][0])[0])
    client.force_login(u)


def _get(client, url):
    r = client.get(url)
    assert r.status_code == 200
    return r.content.decode()


def test_tenant_list_only_and_exclude_sublets(client, settings, flat):
    _login(client, settings, "mietverwaltung")
    only = _get(client, "/tenants/?sublet=only")
    assert "Unterm" in only and "Normalo" not in only and 'name="sublet"' in only
    excl = _get(client, "/tenants/?sublet=exclude")
    assert "Unterm (" not in excl and ">Unterm<" not in excl and "Normalo" in excl and "Hauptmiete" in excl


def test_tenant_list_sublet_filter_needs_room_column(client, settings, flat):
    _login(client, settings, "cluster")
    body = _get(client, "/tenants/?sublet=only")
    assert 'name="sublet"' not in body and "Normalo" in body  # parameter ignored


def test_wg_list_sublet_filter_and_pill(client, settings, flat):
    _login(client, settings, "belegium")
    body = _get(client, "/wgs/?sublet=only")
    assert "1.01" in body and "1.02" not in body and 'name="sublet"' in body
    assert "ca-pill-sublet" in body
    excl = _get(client, "/wgs/?sublet=exclude")
    assert "1.02" in excl and "1.01" not in excl


def test_wg_list_sublet_hidden_for_cluster(client, settings, flat):
    _login(client, settings, "cluster")
    body = _get(client, "/wgs/?sublet=only")
    assert 'name="sublet"' not in body and "ca-pill-sublet" not in body and "1.02" in body
