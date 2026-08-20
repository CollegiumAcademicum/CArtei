import pytest
from django.contrib.auth.models import Group, User
from app.tenant_access import global_roles, visible_fields

@pytest.mark.django_db
def test_helper_group_maps_to_role():
    u = User.objects.create(username="helper")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    assert "mietverwaltung_helfer" in global_roles(u)
    assert "mietverwaltung" not in global_roles(u)


def test_helper_sees_names_and_rooms_only():
    v = visible_fields({"mietverwaltung_helfer"})
    assert {"first_name", "last_name", "room_assignments_view", "ersteinzug", "auszug"} <= v
    assert not ({"email", "phone", "date_of_birth"} & v)
