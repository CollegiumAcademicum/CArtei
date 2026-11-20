"""Compare-two-dates view (#120): occupancy, paperwork and damages."""
import uuid
from datetime import date, datetime, timezone

import pytest
from django.contrib.auth.models import Group, User

from app.models import (
    Building, DatenschutzDocument, EnrollmentProof, PhotoerlaubnisDocument, Room,
    RoomDamage, RoomDamageLine, Tenant, TenantRoomAssignment, WG, WGDamage, WGDamageLine,
)

pytestmark = pytest.mark.django_db

A, B = date(2026, 3, 1), date(2026, 6, 1)
BEFORE, BETWEEN, AFTER = date(2026, 1, 15), date(2026, 4, 15), date(2026, 7, 15)
ROLES = {
    "mietverwaltung": ["ag.mietverwaltung"], "cluster": ["gr.cluster"], "belegium": ["gr.belegium"],
    "werkstatt": ["cartei_werkstatt"], "granter": ["cartei_grant_clearance"], "admin": ["admins"],
}


def _dt(d):
    return datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc)


def _tenant(name):
    return Tenant.objects.create(first_name=name, last_name="Test", preferred_name=name,
                                 intranet_username=name.lower(), intranet_uuid=uuid.uuid4())


@pytest.fixture
def house():
    wg = WG.objects.create(building=Building.objects.create(name="Haus A"), name="WG 1", cluster="A")
    r1 = Room.objects.create(wg=wg, name="1.01", size_sqm=12)
    r2 = Room.objects.create(wg=wg, name="1.02", size_sqm=12)
    r3 = Room.objects.create(wg=wg, name="1.03", size_sqm=12)
    return wg, r1, r2, r3


@pytest.fixture
def people(house):
    """Ina moves in, Otto moves out, Wanda switches 1.01 -> 1.02, Stefan stays put."""
    wg, r1, r2, r3 = house
    ina, otto, wanda, stefan = (_tenant(n) for n in ("Ina", "Otto", "Wanda", "Stefan"))
    TenantRoomAssignment.objects.create(tenant=ina, room=r3, moved_in=BETWEEN)
    TenantRoomAssignment.objects.create(tenant=otto, room=r3, moved_in=BEFORE, moved_out=BETWEEN)
    TenantRoomAssignment.objects.create(tenant=wanda, room=r1, moved_in=BEFORE, moved_out=BETWEEN)
    TenantRoomAssignment.objects.create(tenant=wanda, room=r2, moved_in=BETWEEN)
    r4 = Room.objects.create(wg=wg, name="1.04", size_sqm=12)
    TenantRoomAssignment.objects.create(tenant=stefan, room=r4, moved_in=BEFORE)
    return ina, otto, wanda, stefan


def _login(client, settings, *roles):
    settings.TENANT_ROLE_GROUPS = ROLES
    u = User.objects.create_user("viewer")
    for r in roles:
        u.groups.add(Group.objects.get_or_create(name=ROLES[r][0])[0])
    client.force_login(u)
    return u


# --- app.diff ---------------------------------------------------------------

def test_occupancy_changes_with_rooms(people):
    from app.diff import tenant_changes
    ina, otto, wanda, stefan = people
    ch = tenant_changes(A, B, occupancy=True, rooms=True)
    assert ch[ina.pk] == ["eingezogen"]
    assert ch[otto.pk] == ["ausgezogen"]
    assert ch[wanda.pk] == ["Zimmerwechsel 1.01 → 1.02"]
    assert stefan.pk not in ch


def test_room_switch_hidden_without_room_gate(people):
    from app.diff import tenant_changes
    ina, otto, wanda, _ = people
    ch = tenant_changes(A, B, occupancy=True, rooms=False)
    assert ch[ina.pk] == ["eingezogen"] and ch[otto.pk] == ["ausgezogen"]
    assert wanda.pk not in ch


def test_dates_in_either_order(people):
    from app.diff import tenant_changes
    ina = people[0]
    assert tenant_changes(B, A, occupancy=True)[ina.pk] == ["eingezogen"]


def test_documents_added_and_revoked(house):
    from app.diff import tenant_changes
    t, up = _tenant("Doro"), _tenant("Uploader")
    kw = dict(file_data=b"%PDF", uploaded_by=up, signed_at=BEFORE)
    DatenschutzDocument.objects.create(tenant=t, file_name="ds.pdf", uploaded_at=_dt(BETWEEN), **kw)
    PhotoerlaubnisDocument.objects.create(tenant=t, file_name="foe.pdf", uploaded_at=_dt(BEFORE),
                                          revoked_at=_dt(BETWEEN), **kw)
    DatenschutzDocument.objects.create(tenant=up, file_name="old.pdf", uploaded_at=_dt(BEFORE), **kw)
    ch = tenant_changes(A, B, doc_types=["datenschutz", "photoerlaubnis"])
    assert ch[t.pk] == ["+ DS", "– FoE"]
    assert up.pk not in ch  # present on both dates
    assert tenant_changes(A, B, doc_types=["photoerlaubnis"])[t.pk] == ["– FoE"]


def test_proof_state_change(house):
    from app.diff import tenant_changes
    t = _tenant("Paula")
    EnrollmentProof.objects.create(tenant=t, enrollment_type="STUDY", file_name="immat.pdf", file_data=b"%PDF",
                                   uploaded_at=_dt(BETWEEN), verified_at=_dt(BETWEEN),
                                   valid_until=date(2026, 9, 30))
    assert tenant_changes(A, B, proofs=True)[t.pk] == ["Nachweis fehlt → gültig"]
    assert tenant_changes(A, B) == {}  # nothing gated in


def test_damage_delta(house):
    from app.diff import damage_delta
    wg, r1, r2, _ = house
    by = _tenant("Inspector")
    RoomDamage.objects.create(room=r1, line=RoomDamageLine.BODEN_FLECKEN, created_at=_dt(BETWEEN), created_by=by)
    RoomDamage.objects.create(room=r1, line=RoomDamageLine.BODEN_FLECKEN, created_at=_dt(BEFORE), created_by=by,
                              fixed_at=_dt(BETWEEN), fixed_by=by)
    RoomDamage.objects.create(room=r2, line=RoomDamageLine.BODEN_FLECKEN, created_at=_dt(BEFORE), created_by=by)
    RoomDamage.objects.create(room=r2, line=RoomDamageLine.BODEN_FLECKEN, created_at=_dt(AFTER), created_by=by)
    WGDamage.objects.create(wg=wg, line=WGDamageLine.BAD_FLECK, created_at=_dt(BETWEEN), created_by=by)
    assert damage_delta(RoomDamage, "room_id", A, B) == {r1.pk: (1, 1)}
    assert damage_delta(WGDamage, "wg_id", B, A) == {wg.pk: (1, 0)}


# --- tenant list --------------------------------------------------------------

def _tl(client, **extra):
    q = f"/tenants/?diff_from={A}&diff_to={B}"
    return client.get(q, **extra).content.decode()


def test_tenant_list_diff_mv_sees_only_changed_with_rooms(client, settings, people):
    _login(client, settings, "mietverwaltung")
    body = _tl(client)
    assert "Zimmerwechsel 1.01 → 1.02" in body and "eingezogen" in body and "ausgezogen" in body
    assert 'name="diff_from"' in body


def test_tenant_list_diff_skips_unchanged(client, settings, house):
    _login(client, settings, "mietverwaltung")
    t = _tenant("Unchanged")
    TenantRoomAssignment.objects.create(tenant=t, room=house[1], moved_in=BEFORE)
    assert "Unchanged" not in _tl(client)
    assert "Unchanged" in client.get("/tenants/").content.decode()


def test_tenant_list_diff_belegium_no_room_switch(client, settings, people):
    _login(client, settings, "belegium")
    body = _tl(client)
    assert "eingezogen" in body and "Zimmerwechsel" not in body and "Wanda" not in body


def test_tenant_list_diff_unavailable_for_cluster(client, settings, people):
    _login(client, settings, "cluster")
    body = _tl(client)
    assert 'name="diff_from"' not in body and "eingezogen" not in body
    assert "Stefan" in body  # params ignored: normal list


def test_tenant_list_diff_granter_sees_only_ve(client, settings, house):
    from app.models import VertraulichkeitserklaerungDocument
    _login(client, settings, "granter")
    t, up = _tenant("Vera"), _tenant("Up")
    kw = dict(file_data=b"%PDF", uploaded_by=up, signed_at=BEFORE, uploaded_at=_dt(BETWEEN))
    VertraulichkeitserklaerungDocument.objects.create(tenant=t, file_name="ve.pdf", **kw)
    DatenschutzDocument.objects.create(tenant=up, file_name="ds.pdf", **kw)
    body = _tl(client)
    assert "+ VE" in body and "+ DS" not in body and "Up Test" not in body


# --- WG list ------------------------------------------------------------------

def _wl(client, only=False):
    q = f"/wgs/?as_of={B}&compare={A}" + ("&changed_only=1" if only else "")
    return client.get(q).content.decode()


def test_wg_list_compare_names_for_mv(client, settings, people):
    _login(client, settings, "mietverwaltung")
    body = _wl(client)
    assert "ca-diff-add" in body and "ca-diff-del" in body
    assert 'name="compare"' in body


def test_wg_list_compare_without_names_shows_counts(client, settings, people):
    _login(client, settings, "cluster")
    body = _wl(client)
    assert "Otto" not in body and "Ina" not in body
    # 1.01 empties, 1.02 fills; 1.03 swaps Otto for Ina at the same count, so it stays unmarked
    assert body.count('class="ca-diff-changed"') == 2
    assert "belegt (1) → frei" in body and "frei → belegt (1)" in body


def test_wg_list_compare_count_change_without_names(client, settings, house):
    _login(client, settings, "cluster")
    TenantRoomAssignment.objects.create(tenant=_tenant("Nina"), room=house[3], moved_in=BETWEEN)
    body = _wl(client)
    assert "Nina" not in body and "frei → belegt (1)" in body


def test_wg_list_compare_damages_only_for_damage_viewers(client, settings, house):
    wg, r1, _, _ = house
    by = _tenant("Inspector")
    RoomDamage.objects.create(room=r1, line=RoomDamageLine.BODEN_FLECKEN, created_at=_dt(BETWEEN), created_by=by)
    _login(client, settings, "werkstatt")
    assert "+1 neu" in _wl(client)
    client.logout()
    User.objects.all().delete()
    _login(client, settings, "belegium")
    assert "+1 neu" not in _wl(client)


def test_wg_list_changed_only(client, settings, house):
    wg, r1, r2, r3 = house
    _login(client, settings, "mietverwaltung")
    TenantRoomAssignment.objects.create(tenant=_tenant("Nina"), room=r3, moved_in=BETWEEN)
    body = _wl(client, only=True)
    assert "1.03" in body
    assert "1.01" not in body and "1.02" not in body
