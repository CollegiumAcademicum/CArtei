from app.tenant_access import (
    viewer_roles, visible_fields, editable_fields, global_roles,
    EDITABLE_COLUMNS, SYSTEM_ID_FIELDS,
)


class _GroupsShim:
    def __init__(self, names): self._names = list(names)
    def values_list(self, field, flat=False): return list(self._names)


class FakeUser:
    def __init__(self, group_names, username="u"):
        self.username = username
        self.groups = _GroupsShim(group_names)


class FakeTenant:
    def __init__(self, pk): self.pk = pk


def test_owner_roles():
    user = FakeUser([], username="me")
    t = FakeTenant(1)
    roles = viewer_roles(user, tenant=t, current_tenant=t)
    assert "owner" in roles and "public" in roles and "admin" not in roles


def test_admin_role_derived_from_group_via_role_map():
    # admin is now defined in TENANT_ROLE_GROUPS like every other role.
    assert "admin" in global_roles(FakeUser(["admins"]))
    assert "admin" not in global_roles(FakeUser(["ag.kueche"]))


def test_public_only_for_stranger():
    user = FakeUser([], username="x")
    roles = viewer_roles(user, tenant=FakeTenant(1), current_tenant=FakeTenant(2))
    assert roles == {"public"}


def test_admin_sees_and_edits_all_but_system_ids():
    roles = {"public", "admin"}
    vis = visible_fields(roles)
    edt = editable_fields(roles)
    assert "soli_miete_wunsch" in vis and "comments" in vis
    assert "email" in edt
    assert SYSTEM_ID_FIELDS.isdisjoint(edt)


def test_owner_edits_exactly_eight():
    edt = editable_fields({"public", "owner"})
    assert edt == {"email", "phone", "no_phone_number", "is_flinta", "mailbox_list_opt_in",
                   "preferred_name", "pronouns", "soli_miete_wunsch"}


def test_stranger_sees_only_public_card():
    assert visible_fields({"public"}) == {"preferred_name", "pronouns"}


def test_mietverwaltung_can_edit_dob_and_contact():
    edt = editable_fields({"public", "mietverwaltung"})
    assert {"date_of_birth", "email", "barrier_free_needed"} <= edt
    assert "soli_miete_wunsch" not in edt  # owner-only (admin override aside)


def test_editable_columns_are_real_tenant_fields():
    from app.models import Tenant
    names = {f.name for f in Tenant._meta.get_fields()}
    assert set(EDITABLE_COLUMNS) <= names


def test_sublet_is_no_longer_a_tenant_field():
    # Untermiete moved to the room assignment; it is not governed by tenant field-access.
    assert "sublet_of_tenant" not in visible_fields({"public", "mietverwaltung"})
    assert "mailbox_key" not in editable_fields({"public", "mietverwaltung"})
