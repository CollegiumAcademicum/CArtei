import pytest


@pytest.mark.django_db
def test_form_trims_to_allowed_fields():
    from app.forms import TenantForm
    form = TenantForm(allowed_fields={"email", "phone"})
    assert set(form.fields) == {"email", "phone"}


@pytest.mark.django_db
def test_form_rejects_bad_email():
    from app.forms import TenantForm
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de",
                              intranet_username="ab", intranet_uuid=uuid.uuid4())
    form = TenantForm(data={"email": "not-an-email"}, instance=t, allowed_fields={"email"})
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_form_saves_allowed_field():
    from app.forms import TenantForm
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de",
                              intranet_username="cd", intranet_uuid=uuid.uuid4())
    form = TenantForm(data={"email": "new@b.de"}, instance=t, allowed_fields={"email"})
    assert form.is_valid(), form.errors
    form.save()
    t.refresh_from_db()
    assert t.email == "new@b.de"


def _room(name="R1"):
    from app.models import Building, WG, Room
    b = Building.objects.create(name="B" + name)
    wg = WG.objects.create(building=b, name="WG" + name, cluster="OG1")
    return Room.objects.create(wg=wg, name=name, size_sqm=14)


def _tenant(u):
    from app.models import Tenant
    import uuid
    return Tenant.objects.create(first_name=u, last_name="X", email=f"{u}@b.de",
                                 intranet_username=u, intranet_uuid=uuid.uuid4())


def _post(room, source):
    return {"new_room-room": room.pk, "new_room-moved_in": "2024-01-01",
            "new_room-is_sublet": "on", "new_room-sublet_of_tenant": source.pk}


@pytest.mark.django_db
def test_sublet_source_must_rent_the_room():
    import datetime
    from app.forms import TenantRoomAssignmentForm
    from app.models import TenantRoomAssignment
    room, other = _room("A"), _tenant("landlord")
    # Landlord rents the room -> allowed.
    TenantRoomAssignment.objects.create(tenant=other, room=room, moved_in=datetime.date(2024, 1, 1))
    assert TenantRoomAssignmentForm(data=_post(room, other), prefix="new_room").is_valid()


@pytest.mark.django_db
def test_sublet_source_who_does_not_rent_is_rejected():
    from app.forms import TenantRoomAssignmentForm
    room, stranger = _room("B"), _tenant("stranger")
    form = TenantRoomAssignmentForm(data=_post(room, stranger), prefix="new_room")
    assert not form.is_valid()
    assert "sublet_of_tenant" in form.errors


@pytest.mark.django_db
def test_sublet_source_whose_tenancy_ended_is_rejected():
    import datetime
    from app.forms import TenantRoomAssignmentForm
    from app.models import TenantRoomAssignment
    room, former = _room("C"), _tenant("former")
    TenantRoomAssignment.objects.create(tenant=former, room=room,
        moved_in=datetime.date(2020, 1, 1), moved_out=datetime.date(2021, 1, 1))
    assert not TenantRoomAssignmentForm(data=_post(room, former), prefix="new_room").is_valid()
