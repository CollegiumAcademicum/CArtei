"""Change timeline on tenant and WG detail (#115)."""
import uuid
from datetime import date, datetime, timezone

import pytest
from django.contrib.auth.models import Group, User

from app.models import (
    Building, DatenschutzDocument, EntityHistory, EnrollmentProof, Room, RoomDamage,
    RoomDamageLine, SepaLastschriftmandatDocument, Tenant, TenantRoomAssignment, WG,
    WohnungsgeberbescheinigungDocument,
)

pytestmark = pytest.mark.django_db

ROLES = {
    "mietverwaltung": ["ag.mietverwaltung"], "belegium": ["gr.belegium"], "cluster": ["gr.cluster"],
    "finanzierung": ["cartei_finanzierung"], "werkstatt": ["cartei_werkstatt"], "admin": ["admins"],
}
T1 = datetime(2026, 5, 1, 10, tzinfo=timezone.utc)
T2 = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def _tenant(name, **kw):
    return Tenant.objects.create(first_name=name, last_name="Test", preferred_name=name,
                                 intranet_username=name.lower(), intranet_uuid=uuid.uuid4(),
                                 profile_setup_completed_at=T1, **kw)


def _login(client, settings, username, *roles):
    settings.TENANT_ROLE_GROUPS = ROLES
    u = User.objects.create_user(username)
    for r in roles:
        u.groups.add(Group.objects.get_or_create(name=ROLES[r][0])[0])
    client.force_login(u)


def _hist(obj, table, at=T1, by="mvstaff", **before):
    """History row as the trigger writes it: the row's columns before the edit."""
    import json
    from django.core.serializers.json import DjangoJSONEncoder
    snap = json.loads(json.dumps(type(obj).objects.filter(pk=obj.pk).values().first(), cls=DjangoJSONEncoder))
    snap.update(before)
    return EntityHistory.objects.create(entity_type=table, entity_id=obj.pk, snapshot=snap,
                                        changed_at=at, changed_by=by, change_source="HUMAN")


@pytest.fixture
def setup():
    wg = WG.objects.create(building=Building.objects.create(name="Haus"), name="WG 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = _tenant("Ada", phone="+49 new")
    mv = _tenant("Mvstaff")
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2026, 1, 1),
                                            moved_out=date(2026, 9, 30), deposit_iban="DE22 new")
    _hist(t, "tenant", phone="+49 old", preferred_name="Ada")
    _hist(a, "tenant_room_assignment", at=T2, moved_out=None, deposit_iban="DE11 old")
    return wg, room, t, mv, a


def _td(client, t):
    r = client.get(f"/tenants/{t.pk}/")
    assert r.status_code == 200
    return r.content.decode()


# --- tenant detail ---------------------------------------------------------

def test_mv_sees_field_and_assignment_edits_with_iban(client, settings, setup):
    _, _, t, _, _ = setup
    _login(client, settings, "mvuser", "mietverwaltung")
    body = _td(client, t)
    assert 'id="section-history"' in body
    assert "+49 old" in body and "+49 new" in body
    assert "DE11 old" in body and "DE22 new" in body
    assert "Mvstaff" in body  # actor resolved to a display name
    assert "Einzug" in body  # assignment row event


def test_belegium_sees_assignment_edit_but_not_iban_or_phone(client, settings, setup):
    _, _, t, _, _ = setup
    _login(client, settings, "beleg", "belegium")
    body = _td(client, t)
    assert "30.09.2026" in body
    assert "DE11 old" not in body and "+49 old" not in body


def test_owner_sees_own_phone_change_not_iban(client, settings, setup):
    _, _, t, _, _ = setup
    _login(client, settings, "ada")  # owner: intranet_username matches
    body = _td(client, t)
    assert "+49 old" in body and "DE11 old" not in body


def test_public_viewer_sees_no_private_history(client, settings, setup):
    _, _, t, _, _ = setup
    _login(client, settings, "stranger", "cluster")
    body = _td(client, t)
    assert "+49 old" not in body and "DE11 old" not in body and "Einzug" not in body


def test_documents_by_reader(client, settings, setup):
    _, _, t, mv, _ = setup
    kw = dict(tenant=t, file_data=b"%PDF", uploaded_by=mv, signed_at=date(2026, 1, 1))
    DatenschutzDocument.objects.create(file_name="ds.pdf", uploaded_at=T1, revoked_at=T2, revoked_by=mv,
                                       revoked_note="falsche Version", **kw)
    SepaLastschriftmandatDocument.objects.create(file_name="sepa.pdf", uploaded_at=T1, iban="DE99", bic="X",
                                                 mandatsreferenz="M1", kontoinhaber="Ada", bank_name="B", **kw)
    _login(client, settings, "fin", "finanzierung")
    body = _td(client, t)
    assert "sepa.pdf" in body and "ds.pdf" not in body
    client.logout()
    _login(client, settings, "mvuser", "mietverwaltung")
    body = _td(client, t)
    assert "ds.pdf" in body and "falsche Version" in body


def test_proof_events_for_mv(client, settings, setup):
    _, _, t, mv, _ = setup
    EnrollmentProof.objects.create(tenant=t, enrollment_type="STUDY", file_name="immat.pdf", file_data=b"%PDF",
                                   uploaded_at=T1, uploaded_by=t, verified_at=T2, verified_by=mv,
                                   valid_until=date(2026, 9, 30))
    _login(client, settings, "mvuser", "mietverwaltung")
    body = _td(client, t)
    assert "immat.pdf" in body and "geprüft" in body


# --- WG detail -----------------------------------------------------------------

def _wd(client, wg):
    r = client.get(f"/wgs/{wg.pk}/")
    assert r.status_code == 200
    return r.content.decode()


def test_wg_room_edit_visible_to_staff_and_damages_gated(client, settings, setup):
    wg, room, t, mv, a = setup
    _hist(room, "room", size_sqm="12.00")
    RoomDamage.objects.create(room=room, line=RoomDamageLine.BODEN_FLECKEN, created_at=T1, created_by=mv,
                              fixed_at=T2, fixed_by=mv)
    WohnungsgeberbescheinigungDocument.objects.create(assignment=a, file_name="wgb.pdf", file_data=b"%PDF",
                                                     uploaded_at=T1, uploaded_by=mv, signed_at=date(2026, 1, 1),
                                                     company_signed_by=mv)
    _login(client, settings, "werk", "werkstatt")
    body = _wd(client, wg)
    assert 'id="section-history"' in body
    assert "12.00" in body or "12,00" in body
    assert "Boden – Flecken" in body
    assert "wgb.pdf" not in body and "Einzug" not in body
    client.logout()
    _login(client, settings, "mvuser", "mietverwaltung")
    body = _wd(client, wg)
    assert "wgb.pdf" in body and "DE11 old" in body and "Ada" in body


def test_wg_belegium_sees_assignments_without_names_or_iban(client, settings, setup):
    wg, *_ = setup
    _login(client, settings, "beleg", "belegium")
    body = _wd(client, wg)
    history = body[body.index('id="section-history"'):]
    assert "Einzug" in history and "DE11 old" not in history and "Ada" not in history
