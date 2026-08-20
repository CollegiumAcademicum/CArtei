import datetime
import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from app.models import (Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll, WG)
from app.models import DamageLine, UebergabeProtokollDamage

@pytest.fixture
def assignment(db):
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="ab", intranet_uuid=uuid.uuid4())
    return TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))

@pytest.fixture
def helper(db):
    u = User.objects.create_user("helper", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    return u

@pytest.mark.django_db
def test_start_creates_draft_with_damage_rows(client, assignment, helper):
    client.force_login(helper)
    resp = client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)
    assert p.protocol_type == "EINZUG"
    assert p.damages.count() == 18
    assert resp.status_code == 302 and f"/uebergabe/{p.pk}/step/0/" in resp.url

@pytest.mark.django_db
def test_start_forbidden_for_outsider(client, assignment, db):
    client.force_login(User.objects.create_user("nobody", password="x"))
    resp = client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_step_saves_and_advances(client, assignment, helper):
    client.force_login(helper)
    client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)

    # Step 2 (index 2) = Boden: 3 damage rows.
    rows = list(p.damages.filter(line__in=["BODEN_FLECKEN", "BODEN_LOECHER", "FUSSLEISTE_FLECKEN"]).order_by("line"))
    data = {
        "direction": "weiter",
        "form-TOTAL_FORMS": "3", "form-INITIAL_FORMS": "3",
        "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
    }
    for i, r in enumerate(rows):
        data[f"form-{i}-id"] = str(r.pk)
        data[f"form-{i}-count_lt1"] = "3"
        data[f"form-{i}-count_mid"] = "0"
        data[f"form-{i}-count_gt"] = "0"
        data[f"form-{i}-note"] = ""
    resp = client.post(reverse("uebergabe_step", args=[p.pk, 2]), data)
    assert resp.status_code == 302 and resp.url.endswith("/step/3/")
    assert UebergabeProtokollDamage.objects.get(pk=rows[0].pk).count_lt1 == 3


@pytest.mark.django_db
def test_loecher_step_omitting_count_mid_saves_zero(client, assignment, helper):
    """Real browser POST for a Löcher row omits count_mid; must 302 and persist 0."""
    client.force_login(helper)
    client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)

    # Step 4 = Tür: TUER_FLECKEN (flecken, 3 buckets) + TUER_LOECHER (loecher, 2 buckets).
    rows = list(p.damages.filter(line__in=["TUER_FLECKEN", "TUER_LOECHER"]).order_by("line"))
    data = {
        "direction": "weiter",
        "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
        "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
    }
    for i, r in enumerate(rows):
        data[f"form-{i}-id"] = str(r.pk)
        data[f"form-{i}-count_lt1"] = "2"
        # count_mid intentionally omitted for both rows (simulates browser not rendering it for Löcher)
        data[f"form-{i}-count_gt"] = "1"
        data[f"form-{i}-note"] = ""
    resp = client.post(reverse("uebergabe_step", args=[p.pk, 4]), data)
    assert resp.status_code == 302, "Expected 302 (advance); got 200 meaning form invalid"
    loecher = UebergabeProtokollDamage.objects.get(pk=rows[1].pk)  # TUER_LOECHER
    assert loecher.count_mid == 0
    assert loecher.count_lt1 == 2
    assert loecher.count_gt == 1


import datetime as _dt

def _weasyprint_available():
    try:
        from weasyprint import HTML  # triggers native-lib load
        return True
    except OSError:
        return False

@pytest.mark.skipif(not _weasyprint_available(), reason="WeasyPrint native libs not available")
@pytest.mark.django_db
def test_pdf_requires_header_then_renders(client, assignment, helper):
    client.force_login(helper)
    client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)
    # Missing mv_representative/protocol_at -> 400.
    assert client.get(reverse("uebergabe_pdf", args=[p.pk])).status_code == 400
    p.mv_representative = assignment.tenant
    p.protocol_at = _dt.datetime(2026, 1, 2, 10, 0, tzinfo=_dt.timezone.utc)
    p.save()
    resp = client.get(reverse("uebergabe_pdf", args=[p.pk]))
    assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    p.refresh_from_db()
    assert p.finalized_at is not None
