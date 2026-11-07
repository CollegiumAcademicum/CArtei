import datetime

import pytest
from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils.timezone import now

from app import clearance
from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP
from app.models import (
    ClearanceAction, ConfidentialityClearanceEvent, Tenant,
    VertraulichkeitserklaerungDocument,
)


def _user(username, group, uuid):
    t = Tenant.objects.create(
        first_name=username, last_name="Caller", email=f"{username}@example.com",
        intranet_username=username, intranet_uuid=uuid,
    )
    u = User.objects.create_user(username=username, password="x")
    u.groups.add(Group.objects.get_or_create(name=group)[0])
    return t, u


@pytest.fixture
def granter(db):
    return _user("granter", "cartei_grant_clearance", "00000000-0000-0000-0000-000000000101")


@pytest.fixture
def target(db):
    return Tenant.objects.create(
        first_name="Max", last_name="Muster", email="m@example.com",
        intranet_username="max_muster", intranet_uuid="00000000-0000-0000-0000-000000000102",
    )


def _doc(tenant, **kw):
    return VertraulichkeitserklaerungDocument.objects.create(
        tenant=tenant, signed_at=datetime.date(2026, 8, 1), uploaded_at=now(), uploaded_by=tenant, **kw
    )


@pytest.fixture
def spy(monkeypatch):
    calls = []
    monkeypatch.setattr("app.clearance.add_clearance_member", lambda uid: calls.append(uid))
    return calls


def _post(client, tenant, doc, **data):
    return client.post(
        reverse("clearance_grant", args=[tenant.pk, doc.pk]), data
    )


def test_grant_creates_event_and_adds_group(client, granter, target, spy):
    caller, user = granter
    client.force_login(user)
    doc = _doc(target)
    r = _post(client, target, doc, confirm_name="Max Muster")
    assert r.status_code == 302
    assert r["Location"].endswith("#section-documents")
    ev = ConfidentialityClearanceEvent.objects.get()
    assert (ev.action, ev.actor_id, ev.document_id) == (ClearanceAction.GRANT, caller.pk, doc.pk)
    assert spy == ["max_muster"]


def test_regrant_on_approved_doc_writes_regrant(client, granter, target, spy):
    client.force_login(granter[1])
    doc = _doc(target)
    ConfidentialityClearanceEvent.objects.create(
        tenant=target, document=doc, action=ClearanceAction.GRANT, created_at=now()
    )
    _post(client, target, doc, confirm_name=" Max Muster ")
    assert ConfidentialityClearanceEvent.objects.filter(action=ClearanceAction.REGRANT).count() == 1
    assert spy == ["max_muster"]


@pytest.mark.parametrize("data", [{"confirm_name": "max muster"}, {"confirm_name": "Max"}, {}])
def test_grant_rejects_wrong_name(client, granter, target, spy, data):
    client.force_login(granter[1])
    doc = _doc(target)
    r = _post(client, target, doc, **data)
    assert r.status_code == 302
    assert not ConfidentialityClearanceEvent.objects.exists()
    assert spy == []
    assert any("Name stimmt nicht" in str(m) for m in get_messages(r.wsgi_request))


def test_grant_requires_granter(client, target, spy):
    _, mv = _user("mvonly", "ag.mietverwaltung", "00000000-0000-0000-0000-000000000103")
    client.force_login(mv)
    doc = _doc(target)
    assert _post(client, target, doc, confirm_name="Max Muster").status_code == 403
    assert not ConfidentialityClearanceEvent.objects.exists()
    assert spy == []


def test_grant_refuses_revoked_foreign_or_accountless(client, granter, target, spy):
    client.force_login(granter[1])
    revoked = _doc(target, revoked_at=now(), revoked_note="x")
    r = _post(client, target, revoked, confirm_name="Max Muster")
    assert r.status_code == 302

    other = Tenant.objects.create(
        first_name="Ot", last_name="Her", email="o@example.com",
        intranet_username="other", intranet_uuid="00000000-0000-0000-0000-000000000104",
    )
    foreign = _doc(other)
    assert _post(client, target, foreign, confirm_name="Max Muster").status_code == 404

    nouser = Tenant.objects.create(first_name="No", last_name="Account", email="n@example.com")
    doc = _doc(nouser)
    r = _post(client, nouser, doc, confirm_name="No Account")
    assert r.status_code == 302
    assert not ConfidentialityClearanceEvent.objects.exists()
    assert spy == []


def test_grant_blocked_while_impersonating(client, granter, target, spy):
    _, real = _user("imp", "cartei_grant_clearance", "00000000-0000-0000-0000-000000000105")
    real.groups.add(Group.objects.get_or_create(name=IMPERSONATION_GROUP)[0])
    client.force_login(real)
    session = client.session
    session[IMPERSONATED_USER_SESSION_KEY] = granter[1].pk
    session.save()
    doc = _doc(target)
    assert _post(client, target, doc, confirm_name="Max Muster").status_code == 403
    assert not ConfidentialityClearanceEvent.objects.exists()
    assert spy == []


def test_grant_ipa_failure_writes_nothing(client, granter, target, monkeypatch):
    def boom(uid):
        raise clearance.ClearanceIPAError("IPA down")
    monkeypatch.setattr("app.clearance.add_clearance_member", boom)
    client.force_login(granter[1])
    doc = _doc(target)
    r = _post(client, target, doc, confirm_name="Max Muster")
    assert r.status_code == 302
    assert not ConfidentialityClearanceEvent.objects.exists()
    assert any("IPA down" in str(m) for m in get_messages(r.wsgi_request))


# --- revoke (Task 5) ---

@pytest.fixture
def rm_spy(monkeypatch):
    calls = []
    monkeypatch.setattr("app.clearance.remove_clearance_member", lambda uid: calls.append(uid))
    return calls


def _approve(tenant, doc):
    ConfidentialityClearanceEvent.objects.create(
        tenant=tenant, document=doc, action=ClearanceAction.GRANT, created_at=now()
    )


def _revoke(client, tenant, doc, dtype="vertraulichkeitserklaerung", note="weg"):
    return client.post(
        reverse("document_revoke", args=[tenant.pk, dtype, doc.pk]), {"revoked_note": note}
    )


def test_revoke_approved_removes_group_and_logs_event(client, granter, target, rm_spy):
    caller, user = granter
    client.force_login(user)
    doc = _doc(target)
    _approve(target, doc)
    assert _revoke(client, target, doc).status_code == 302
    doc.refresh_from_db()
    assert doc.revoked_at is not None and doc.revoked_note == "weg"
    assert rm_spy == ["max_muster"]
    ev = ConfidentialityClearanceEvent.objects.get(action=ClearanceAction.REVOKE)
    assert (ev.actor_id, ev.document_id, ev.tenant_id) == (caller.pk, doc.pk, target.pk)


def test_revoke_pending_does_not_touch_group(client, granter, target, rm_spy):
    client.force_login(granter[1])
    doc = _doc(target)
    _revoke(client, target, doc)
    doc.refresh_from_db()
    assert doc.revoked_at is not None
    assert rm_spy == []
    assert not ConfidentialityClearanceEvent.objects.exists()


def test_granter_may_revoke_ve_but_not_other_types(client, granter, target, rm_spy):
    from app.models import DatenschutzDocument
    client.force_login(granter[1])
    ds = DatenschutzDocument.objects.create(
        tenant=target, signed_at=datetime.date(2026, 8, 1), uploaded_at=now(), uploaded_by=target
    )
    assert _revoke(client, target, ds, dtype="datenschutz").status_code == 403
    ds.refresh_from_db()
    assert ds.revoked_at is None


def test_revoke_ipa_failure_keeps_doc(client, granter, target, monkeypatch):
    def boom(uid):
        raise clearance.ClearanceIPAError("IPA down")
    monkeypatch.setattr("app.clearance.remove_clearance_member", boom)
    client.force_login(granter[1])
    doc = _doc(target)
    _approve(target, doc)
    r = _revoke(client, target, doc)
    assert r.status_code == 302
    doc.refresh_from_db()
    assert doc.revoked_at is None
    assert not ConfidentialityClearanceEvent.objects.filter(action=ClearanceAction.REVOKE).exists()
    assert any("IPA down" in str(m) for m in get_messages(r.wsgi_request))


def test_revoke_with_second_approved_fails_loudly(client, granter, target, rm_spy, caplog):
    client.force_login(granter[1])
    doc, other = _doc(target), _doc(target)
    _approve(target, doc)
    _approve(target, other)
    r = _revoke(client, target, doc)
    assert rm_spy == ["max_muster"]
    msgs = list(get_messages(r.wsgi_request))
    assert any(m.level_tag == "error" and "weitere bestätigte" in str(m) for m in msgs)
    doc.refresh_from_db()
    assert doc.revoked_at is not None
    assert any(rec.levelname == "ERROR" and str(target.pk) in rec.getMessage() for rec in caplog.records)


def test_revoke_accountless_tenant_db_only(client, granter, rm_spy):
    client.force_login(granter[1])
    nouser = Tenant.objects.create(first_name="No", last_name="Account", email="n@example.com")
    doc = _doc(nouser)
    _approve(nouser, doc)
    _revoke(client, nouser, doc)
    doc.refresh_from_db()
    assert doc.revoked_at is not None
    assert rm_spy == []
    assert ConfidentialityClearanceEvent.objects.filter(action=ClearanceAction.REVOKE).exists()


def test_revoke_approved_blocked_while_impersonating(client, granter, target, rm_spy):
    _, real = _user("imp", "cartei_grant_clearance", "00000000-0000-0000-0000-000000000105")
    real.groups.add(Group.objects.get_or_create(name=IMPERSONATION_GROUP)[0])
    client.force_login(real)
    session = client.session
    session[IMPERSONATED_USER_SESSION_KEY] = granter[1].pk
    session.save()
    doc = _doc(target)
    _approve(target, doc)
    assert _revoke(client, target, doc).status_code == 403
    doc.refresh_from_db()
    assert doc.revoked_at is None
    assert not ConfidentialityClearanceEvent.objects.filter(action=ClearanceAction.REVOKE).exists()
    assert rm_spy == []
