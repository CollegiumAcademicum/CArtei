import pytest


@pytest.mark.django_db
def test_relational_mirrors_queryable():
    from app.models import Building, WG, Room, TenantRoomAssignment, EnrollmentProof
    # Tables build under the conftest fixture; empty queries must not raise.
    assert list(Building.objects.all()) == []
    assert list(WG.objects.all()) == []
    assert list(Room.objects.all()) == []
    assert list(TenantRoomAssignment.objects.all()) == []
    assert list(EnrollmentProof.objects.all()) == []


@pytest.mark.django_db
def test_room_assignment_relations():
    from app.models import Building, WG, Room, Tenant, TenantRoomAssignment
    import uuid
    from datetime import date
    b = Building.objects.create(name="Haupthaus")
    wg = WG.objects.create(building=b, name="WG 1", cluster="1A")
    room = Room.objects.create(wg=wg, name="Z1", size_sqm=12, has_bed=True)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="ab", intranet_uuid=uuid.uuid4())
    tra = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2026, 1, 1))
    assert tra.room.wg.building.name == "Haupthaus"
