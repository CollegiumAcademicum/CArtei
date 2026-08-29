"""Drift detection: DB email (SSOT) vs FreeIPA mail for linked tenants."""
from unittest.mock import patch

import pytest

from app.ldap_utils import _email_mismatches, _uid_candidates, find_email_drift, provision_ldap_account


def test_email_mismatches_pure():
    db = {"a.b": "a@x.de", "c.d": "c@x.de", "e.f": "keep@x.de", "g.h": "gone@x.de"}
    ldap = {"a.b": "a@x.de", "c.d": "CHANGED@x.de", "e.f": "KEEP@X.DE"}  # g.h absent
    out = {m["uid"]: m for m in _email_mismatches(db, ldap)}
    assert set(out) == {"c.d", "g.h"}           # e.f matches case-insensitively; a.b matches
    assert out["c.d"]["ldap_email"] == "CHANGED@x.de"
    assert out["g.h"]["ldap_email"] is None     # account deleted out-of-band


def test_uid_candidates():
    it = _uid_candidates("ada.byte")
    assert [next(it) for _ in range(3)] == ["ada.byte", "ada.byte2", "ada.byte3"]


@pytest.mark.django_db
def test_provision_retries_uid_on_collision(settings):
    from app.models import Tenant
    from python_freeipa.exceptions import DuplicateEntry
    settings.IPA_SERVER = "ipa.test"
    settings.IPA_VERIFY_SSL = True
    settings.IPA_PROVISION_USER = "svc"
    settings.IPA_PROVISION_PASSWORD = "pw"
    t = Tenant.objects.create(first_name="Ada", last_name="Byte", email="ada@x.de")

    taken = {"ada.byte", "ada.byte2"}
    added = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        def login(self, *a, **k): pass
        def user_add(self, a_uid, o_random=False, **k):
            assert o_random is True  # accounts must never be created passwordless
            if a_uid in taken:
                raise DuplicateEntry(message=f"{a_uid} exists")
            added.append(a_uid)
            return {"result": {"ipauniqueid": ["550e8400-e29b-41d4-a716-446655440000"],
                               "randompassword": "Tmp-Pw-123"}}

    with patch("python_freeipa.ClientMeta", FakeClient):
        result = provision_ldap_account(t)

    assert result.uid == "ada.byte3" and result.temp_password == "Tmp-Pw-123"
    assert added == ["ada.byte3"]
    t.refresh_from_db()
    assert t.intranet_username == "ada.byte3"


@pytest.mark.django_db
def test_find_email_drift_reports_admin_edit():
    from app.models import Tenant
    import uuid
    Tenant.objects.create(first_name="Ada", last_name="Byte", email="ada@x.de",
                          intranet_username="ada.byte", intranet_uuid=uuid.uuid4())
    Tenant.objects.create(first_name="No", last_name="Account", email="no@x.de")  # unlinked, skipped

    class FakeConn:
        def search_s(self, *a, **k):
            return [("dn", {"uid": [b"ada.byte"], "mail": [b"admin-edited@x.de"]})]

    with patch("app.ldap_utils._connect", return_value=FakeConn()):
        drift = find_email_drift()
    assert drift == [{"uid": "ada.byte", "db_email": "ada@x.de",
                      "ldap_email": "admin-edited@x.de"}]
