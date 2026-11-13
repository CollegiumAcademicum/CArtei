import json

import ldap
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app import ldap_utils
from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP
from app.models import AGMembershipAction, AGMembershipEvent, Tenant

# settings_test maps the "mietverwaltung" role to ag.mietverwaltung: an AG-named
# rights group, which self-service must refuse.
GROUPS = [
    {"cn": "ag.garten", "description": "Garten-AG"},
    {"cn": "ag.mietverwaltung", "description": ""},
    {"cn": "in.kino", "description": ""},
]


@pytest.fixture
def user(db):
    Tenant.objects.create(
        first_name="Lea", last_name="Test", email="lea@example.com",
        intranet_username="lea_test", intranet_uuid="00000000-0000-0000-0000-000000000201",
    )
    u = User.objects.create_user(username="lea_test", password="x")
    u.groups.add(Group.objects.get_or_create(name="gr.vorstand")[0])
    return u


class FakeIPA:
    """IPA writes + LDAP reads backed by one membership set."""

    def __init__(self, monkeypatch, direct=(), nested=()):
        self.direct, self.nested, self.calls = set(direct), set(nested), []
        monkeypatch.setattr(ldap_utils, "list_self_service_groups", lambda: list(GROUPS))
        monkeypatch.setattr(ldap_utils, "add_group_member", self.add)
        monkeypatch.setattr(ldap_utils, "remove_group_member", self.remove)
        monkeypatch.setattr(ldap_utils, "user_memberships", self.read)

    def add(self, cn, uid):
        self.calls.append(("add", cn, uid))
        self.direct.add(cn)

    def remove(self, cn, uid):
        self.calls.append(("remove", cn, uid))
        self.direct.discard(cn)

    def read(self, uid):
        return self.direct | self.nested | {"gr.vorstand"}, set(self.direct) | {"gr.vorstand"}


def _post(client, group, action):
    return client.post(reverse("ag_membership"), {"group": group, "action": action})


def test_join(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch)
    client.force_login(user)
    r = _post(client, "ag.garten", "join")
    d = r.json()
    assert r.status_code == 200 and d["ok"], d
    assert ipa.calls == [("add", "ag.garten", "lea_test")]
    assert set(user.groups.values_list("name", flat=True)) == {"ag.garten", "gr.vorstand"}
    ev = AGMembershipEvent.objects.get()
    assert (ev.group_cn, ev.uid, ev.action, ev.actor_username) == (
        "ag.garten", "lea_test", AGMembershipAction.JOIN, "lea_test")
    assert 'data-cn="ag.garten"' in d["html"] and "ag.garten verlassen" in d["html"]
    assert "gr.vorstand verlassen" not in d["html"]


def test_leave(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch, direct={"in.kino"})
    user.groups.add(Group.objects.get_or_create(name="in.kino")[0])
    client.force_login(user)
    d = _post(client, "in.kino", "leave").json()
    assert d["ok"], d
    assert ipa.calls == [("remove", "in.kino", "lea_test")]
    assert not user.groups.filter(name="in.kino").exists()
    assert AGMembershipEvent.objects.get().action == AGMembershipAction.LEAVE
    assert 'data-cn="in.kino"' not in d["html"]


def test_leave_nested_membership_refused(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch, nested={"in.kino"})
    client.force_login(user)
    r = _post(client, "in.kino", "leave")
    assert r.status_code == 409 and not r.json()["ok"]
    assert ipa.calls == [] and not AGMembershipEvent.objects.exists()


@pytest.mark.parametrize("cn", ["gr.vorstand", "ag.mietverwaltung", "ag.unbekannt", "ag.x)(cn=*", ""])
def test_crafted_group_refused(client, user, monkeypatch, cn):
    ipa = FakeIPA(monkeypatch)
    client.force_login(user)
    r = _post(client, cn, "join")
    assert r.status_code == 403 and not r.json()["ok"]
    assert ipa.calls == []


def test_unknown_action_refused(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch)
    client.force_login(user)
    assert _post(client, "ag.garten", "kick").status_code == 400
    assert ipa.calls == []


def test_impersonation_allowed_logs_impersonator(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch)
    admin = User.objects.create_user(username="imp", password="x")
    admin.groups.add(Group.objects.get_or_create(name=IMPERSONATION_GROUP)[0])
    client.force_login(admin)
    session = client.session
    session[IMPERSONATED_USER_SESSION_KEY] = user.pk
    session.save()
    assert _post(client, "ag.garten", "join").json()["ok"]
    assert ipa.calls == [("add", "ag.garten", "lea_test")]
    assert user.groups.filter(name="ag.garten").exists()
    assert AGMembershipEvent.objects.get().actor_username == "imp"
    assert "ag-tags-add" in client.get(reverse("dashboard")).content.decode()


def test_no_intranet_account(client, db, monkeypatch):
    ipa = FakeIPA(monkeypatch)
    client.force_login(User.objects.create_user(username="nobody", password="x"))
    r = _post(client, "ag.garten", "join")
    assert r.status_code == 400 and not r.json()["ok"]
    assert ipa.calls == []


def test_ipa_failure(client, user, monkeypatch):
    FakeIPA(monkeypatch)

    def boom(cn, uid):
        raise ldap_utils.GroupIPAError("Insufficient access")

    monkeypatch.setattr(ldap_utils, "add_group_member", boom)
    client.force_login(user)
    r = _post(client, "ag.garten", "join")
    assert r.status_code == 502 and "Insufficient access" in r.json()["error"]
    assert not AGMembershipEvent.objects.exists()


def test_reread_disagrees(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch)
    monkeypatch.setattr(ldap_utils, "add_group_member", lambda cn, uid: None)  # silently no-op
    client.force_login(user)
    r = _post(client, "ag.garten", "join")
    assert r.status_code == 502 and "IT-AG" in r.json()["error"]
    assert not AGMembershipEvent.objects.exists()
    assert not user.groups.filter(name="ag.garten").exists()


def test_reread_ldap_error(client, user, monkeypatch):
    ipa = FakeIPA(monkeypatch)

    def boom(uid):
        raise ldap.SERVER_DOWN()

    monkeypatch.setattr(ldap_utils, "user_memberships", boom)
    client.force_login(user)
    r = _post(client, "ag.garten", "join")
    assert r.status_code == 502 and not r.json()["ok"]
    assert ipa.calls == [("add", "ag.garten", "lea_test")]
    assert not AGMembershipEvent.objects.exists()


def test_available_excludes_rights_groups(client, user, monkeypatch):
    FakeIPA(monkeypatch)
    client.force_login(user)
    d = client.get(reverse("ag_available")).json()
    assert [g["cn"] for g in d["groups"]] == ["ag.garten", "in.kino"]


def test_available_ldap_failure_dashboard_still_renders(client, user, monkeypatch):
    def boom():
        raise ldap.SERVER_DOWN()

    monkeypatch.setattr(ldap_utils, "list_self_service_groups", boom)
    client.force_login(user)
    r = client.get(reverse("ag_available"))
    assert r.status_code == 502 and not r.json()["ok"]
    assert client.get(reverse("dashboard")).status_code == 200


def test_dashboard_chips(client, user):
    for name in ("ag.garten", "ag.mietverwaltung"):
        user.groups.add(Group.objects.get_or_create(name=name)[0])
    client.force_login(user)
    html = client.get(reverse("dashboard")).content.decode()
    assert "ag.garten verlassen" in html
    assert "gr.vorstand verlassen" not in html
    assert "ag.mietverwaltung verlassen" not in html  # rights group
    assert 'id="ag-tags-options"' in html


# --- ldap_utils readers ------------------------------------------------------

class FakeConn:
    def __init__(self, results):
        self.results = results  # list of search_s results, consumed in order
        self.filters = []

    def search_s(self, base, scope, flt, attrs):
        self.filters.append(flt)
        return self.results.pop(0)


def test_user_memberships_splits_all_and_direct(monkeypatch, settings):
    settings.LDAP_GROUPS_BASE = "cn=groups,dc=test"
    user_dn = "uid=lea_test,cn=users,dc=test"
    conn = FakeConn([
        [(user_dn, {"memberOf": [b"cn=ag.garten,cn=groups,dc=test", b"cn=in.kino,cn=groups,dc=test",
                                 b"cn=CArtei Provisioner,cn=roles,dc=test"]}),
         (None, ["ldap://referral"])],
        [("cn=ag.garten,cn=groups,dc=test", {"cn": [b"ag.garten"]})],
    ])
    monkeypatch.setattr(ldap_utils, "_connect", lambda: conn)
    assert ldap_utils.user_memberships("lea_test") == ({"ag.garten", "in.kino"}, {"ag.garten"})
    assert conn.filters[1] == f"(member={user_dn})"


def test_user_memberships_unknown_uid(monkeypatch):
    monkeypatch.setattr(ldap_utils, "_connect", lambda: FakeConn([[]]))
    with pytest.raises(LookupError):
        ldap_utils.user_memberships("ghost")


def test_group_member_write_uses_cn(monkeypatch):
    calls = []

    class Client:
        def group_add_member(self, **kw):
            calls.append(kw)
            return {"completed": 1, "failed": {"member": {"user": []}}}

    monkeypatch.setattr(ldap_utils, "_ipa_client", lambda: Client())
    ldap_utils.add_group_member("ag.garten", "lea_test")
    assert calls == [{"a_cn": "ag.garten", "o_user": ["lea_test"]}]
