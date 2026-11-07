import ldap
import pytest

from app import ldap_utils
from app.ldap_utils import ClearanceIPAError


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def group_add_member(self, **kw):
        self.calls.append(("add", kw))
        return self.reply

    def group_remove_member(self, **kw):
        self.calls.append(("remove", kw))
        return self.reply


def _failed(msg):
    return {"result": {}, "completed": 0,
            "failed": {"member": {"user": [["max_muster", msg]], "group": []}}}


def _use(monkeypatch, reply):
    client = FakeClient(reply)
    monkeypatch.setattr(ldap_utils, "_ipa_client", lambda: client)
    return client


def test_add_member_ok(monkeypatch, settings):
    settings.LDAP_REQUIRE_GROUP = "cn=confidentiality_clearance,cn=groups,cn=accounts,dc=x"
    c = _use(monkeypatch, {"result": {}, "completed": 1,
                           "failed": {"member": {"user": [], "group": []}}})
    ldap_utils.add_clearance_member("max_muster")
    assert c.calls == [("add", {"a_cn": "confidentiality_clearance", "o_user": ["max_muster"]})]


def test_add_member_already_member_is_ok(monkeypatch):
    _use(monkeypatch, _failed("This entry is already a member"))
    ldap_utils.add_clearance_member("max_muster")


def test_add_member_other_failure_raises(monkeypatch):
    _use(monkeypatch, _failed("no such entry"))
    with pytest.raises(ClearanceIPAError, match="no such entry"):
        ldap_utils.add_clearance_member("max_muster")


def test_remove_member_not_member_is_ok(monkeypatch):
    c = _use(monkeypatch, _failed("This entry is not a member"))
    ldap_utils.remove_clearance_member("max_muster")
    assert c.calls[0][0] == "remove"


def test_client_exception_wrapped(monkeypatch):
    def boom():
        raise RuntimeError("IPA_SERVER not configured")
    monkeypatch.setattr(ldap_utils, "_ipa_client", boom)
    with pytest.raises(ClearanceIPAError, match="IPA_SERVER"):
        ldap_utils.add_clearance_member("max_muster")


def test_clearance_member_uuids_ldap_error_returns_none(monkeypatch):
    def boom():
        raise ldap.SERVER_DOWN()
    monkeypatch.setattr(ldap_utils, "get_clearance_members", boom)
    assert ldap_utils.clearance_member_uuids() is None


def test_clearance_member_uuids(monkeypatch):
    monkeypatch.setattr(ldap_utils, "get_clearance_members", lambda: [{"uuid": "a"}, {"uuid": "b"}])
    assert ldap_utils.clearance_member_uuids() == {"a", "b"}


def test_is_member_falsy_uuid_and_error(monkeypatch):
    assert ldap_utils.is_clearance_member(None) is None
    def boom():
        raise ldap.SERVER_DOWN()
    monkeypatch.setattr(ldap_utils, "_connect", boom)
    assert ldap_utils.is_clearance_member("abc") is None


def test_is_member_filter(monkeypatch):
    seen = {}
    class Conn:
        def search_s(self, base, scope, flt, attrs):
            seen["flt"] = flt
            return [("dn", {"uid": [b"x"]})]
    monkeypatch.setattr(ldap_utils, "_connect", lambda: Conn())
    assert ldap_utils.is_clearance_member("a*b") is True
    assert "ipaUniqueID=a\\2ab" in seen["flt"] and "memberOf=" in seen["flt"]
