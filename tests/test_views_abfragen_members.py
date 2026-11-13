"""AG member add/remove on the engagement-check page (CArtei#36)."""
import logging
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.contrib.messages import get_messages

from app import ldap_utils
from app.middleware import IMPERSONATED_USER_SESSION_KEY, IMPERSONATION_GROUP
from app.models import AGAbfrage, AGAbfrageResult, AGMembershipEvent, Tenant


def _abfrage(open_=True):
    today = date.today()
    if open_:
        return AGAbfrage.objects.create(date=today, label="Nov", ends_at=today + timedelta(days=7),
                                        grace_ends_at=today + timedelta(days=14))
    return AGAbfrage.objects.create(date=today - timedelta(days=30), ends_at=today - timedelta(days=15),
                                    grace_ends_at=today - timedelta(days=8))


def _tenant(uid, first, last, intranet=True):
    return Tenant.objects.create(first_name=first, last_name=last, email=f"{uid}@ca.de",
                                 intranet_username=uid if intranet else None)


def _user(username, *groups):
    u = User.objects.create_user(username=username, password="x")
    for g in groups:
        u.groups.add(Group.objects.get_or_create(name=g)[0])
    return u


def _member(uid, first="F", last="L"):
    return {"username": uid, "first_name": first, "last_name": last, "email": "", "uuid": ""}


class FakeIPA:
    """IPA writes + LDAP reads for one AG, backed by a set of direct members."""

    def __init__(self, monkeypatch, cn, members, nested=()):
        self.cn, self.direct, self.nested, self.calls = cn, {m["username"] for m in members}, set(nested), []
        # Like LDAP (memberOf): reflects earlier writes and includes nested members.
        monkeypatch.setattr(ldap_utils, "get_ag_members",
                            lambda ag: [m for m in members if m["username"] in self.direct | self.nested])
        monkeypatch.setattr(ldap_utils, "add_group_member", self.add)
        monkeypatch.setattr(ldap_utils, "remove_group_member", self.remove)
        monkeypatch.setattr(ldap_utils, "user_memberships", self.read)

    def add(self, cn, uid):
        self.calls.append(("add", cn, uid))
        self.direct.add(uid)

    def remove(self, cn, uid):
        self.calls.append(("remove", cn, uid))
        self.direct.discard(uid)

    def read(self, uid):
        direct = {self.cn} if uid in self.direct else set()
        return direct | ({self.cn} if uid in self.nested else set()), direct


def _url(a, ag="ag.garten"):
    return f"/abfragen/{a.pk}/ag/{ag}/"


def _msgs(r):
    return [str(m) for m in get_messages(r.wsgi_request)]


@pytest.fixture
def lea(db):
    _tenant("lea", "Lea", "Test")
    return _user("lea", "ag.garten")


@pytest.mark.django_db
def test_remove_and_add_on_save(client, lea, monkeypatch):
    a = _abfrage()
    max_ = _tenant("max_muster", "Max", "Muster")
    sam = _tenant("sam_neu", "Sam", "Neu")
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea"), _member("max_muster", "Max", "Muster")])
    client.force_login(lea)
    r = client.post(_url(a), {f"status_{max_.pk}": "INAKTIV", "remove_max_muster": "1",
                              f"status_{sam.pk}": "AKTIV", f"add_{sam.pk}": "1"})
    assert r.status_code == 302 and r["Location"] == _url(a)
    assert ipa.calls == [("remove", "ag.garten", "max_muster"), ("add", "ag.garten", "sam_neu")]
    evs = list(AGMembershipEvent.objects.order_by("id").values_list("uid", "action", "actor_username"))
    assert evs == [("max_muster", "LEAVE", "lea"), ("sam_neu", "JOIN", "lea")]
    assert AGAbfrageResult.objects.get(tenant=max_).status == "INAKTIV"
    assert any("Max Muster" in m and "Sam Neu" in m for m in _msgs(r))
    # Double submit: Max is no longer a member, so nothing happens again.
    client.post(_url(a), {"remove_max_muster": "1"})
    assert AGMembershipEvent.objects.count() == 2


@pytest.mark.django_db
def test_remove_ignored_for_non_member_uid(client, lea, monkeypatch, caplog):
    a = _abfrage()
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    client.force_login(lea)
    with caplog.at_level(logging.ERROR):
        client.post(_url(a), {"remove_stranger": "1"})
    assert ipa.calls == [] and not AGMembershipEvent.objects.exists()
    assert "stranger" in caplog.text


@pytest.mark.django_db
def test_add_ignored_for_existing_member(client, lea, monkeypatch):
    a = _abfrage()
    max_ = _tenant("max_muster", "Max", "Muster")
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea"), _member("max_muster")])
    client.force_login(lea)
    client.post(_url(a), {f"add_{max_.pk}": "1"})
    assert ipa.calls == [] and not AGMembershipEvent.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("ag", ["gr.vorstand", "ag.mietverwaltung"])
def test_non_self_service_group_ignores_member_fields(client, monkeypatch, ag):
    a = _abfrage()
    _tenant("lea2", "Lea", "Zwei")
    sam = _tenant("sam_neu", "Sam", "Neu")
    ipa = FakeIPA(monkeypatch, ag, [_member("lea2"), _member("max_muster")])
    client.force_login(_user("lea2", ag))
    client.post(_url(a, ag), {"remove_max_muster": "1", f"add_{sam.pk}": "1"})
    assert ipa.calls == []
    assert 'class="remove-btn"' not in client.get(_url(a, ag)).content.decode()


@pytest.mark.django_db
def test_closed_abfrage_admin_no_member_changes(client, monkeypatch):
    a = _abfrage(open_=False)
    max_ = _tenant("max_muster", "Max", "Muster")
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("max_muster")])
    client.force_login(_user("adm", "admins"))
    client.post(_url(a), {f"status_{max_.pk}": "AKTIV", "remove_max_muster": "1"})
    assert ipa.calls == []
    assert AGAbfrageResult.objects.get(tenant=max_).status == "AKTIV"
    assert 'class="remove-btn"' not in client.get(_url(a)).content.decode()


@pytest.mark.django_db
def test_one_failure_other_applies(client, lea, monkeypatch):
    a = _abfrage()
    max_ = _tenant("max_muster", "Max", "Muster")
    sam = _tenant("sam_neu", "Sam", "Neu")
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea"), _member("max_muster", "Max", "Muster")])

    def boom(cn, uid):
        raise ldap_utils.GroupIPAError("Insufficient access")

    monkeypatch.setattr(ldap_utils, "remove_group_member", boom)
    client.force_login(lea)
    r = client.post(_url(a), {f"status_{max_.pk}": "INAKTIV", "remove_max_muster": "1", f"add_{sam.pk}": "1"})
    assert ipa.calls == [("add", "ag.garten", "sam_neu")]
    assert list(AGMembershipEvent.objects.values_list("uid", flat=True)) == ["sam_neu"]
    assert AGAbfrageResult.objects.get(tenant=max_).status == "INAKTIV"
    assert any("max_muster" in m and "Insufficient access" in m for m in _msgs(r))


@pytest.mark.django_db
def test_reread_disagrees_no_event(client, lea, monkeypatch):
    a = _abfrage()
    sam = _tenant("sam_neu", "Sam", "Neu")
    FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    monkeypatch.setattr(ldap_utils, "add_group_member", lambda cn, uid: None)
    client.force_login(lea)
    r = client.post(_url(a), {f"add_{sam.pk}": "1"})
    assert not AGMembershipEvent.objects.exists()
    assert any("IT-AG" in m for m in _msgs(r))


@pytest.mark.django_db
def test_nested_member_removal_refused(client, lea, monkeypatch):
    a = _abfrage()
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea"), _member("nest")])
    ipa.direct.discard("nest")
    ipa.nested.add("nest")
    client.force_login(lea)
    r = client.post(_url(a), {"remove_nest": "1"})
    assert ipa.calls == []
    assert any("über eine andere Gruppe" in m for m in _msgs(r))


@pytest.mark.django_db
def test_add_tenant_without_intranet_account(client, lea, monkeypatch):
    a = _abfrage()
    ext = _tenant("ext", "Ex", "Tern", intranet=False)
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    client.force_login(lea)
    r = client.post(_url(a), {f"status_{ext.pk}": "AKTIV", f"add_{ext.pk}": "1"})
    assert ipa.calls == []
    assert AGAbfrageResult.objects.get(tenant=ext).status == "AKTIV"
    assert any("kein Intranet-Account" in m for m in _msgs(r))


@pytest.mark.django_db
def test_remove_self_redirects_to_dashboard(client, lea, monkeypatch):
    a = _abfrage()
    FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    client.force_login(lea)
    r = client.post(_url(a), {"remove_lea": "1"})
    assert r.status_code == 302 and r["Location"] == "/dashboard/"
    assert not lea.groups.filter(name="ag.garten").exists()


@pytest.mark.django_db
def test_impersonator_removes_target_from_ag(client, lea, monkeypatch):
    a = _abfrage()
    FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    real = _user("imp", IMPERSONATION_GROUP)
    client.force_login(real)
    s = client.session
    s[IMPERSONATED_USER_SESSION_KEY] = lea.pk
    s.save()
    r = client.post(_url(a), {"remove_lea": "1"})
    assert r["Location"] == "/dashboard/"
    assert not lea.groups.filter(name="ag.garten").exists()
    assert AGMembershipEvent.objects.get().actor_username == "imp"


@pytest.mark.django_db
def test_admin_removes_ldap_member_without_tenant(client, monkeypatch):
    a = _abfrage()
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("ghost")])
    client.force_login(_user("adm", "admins"))
    client.post(_url(a), {"remove_ghost": "1"})
    assert ipa.calls == [("remove", "ag.garten", "ghost")]
    ev = AGMembershipEvent.objects.get()
    assert (ev.tenant_id, ev.actor_username) == (None, "adm")


@pytest.mark.django_db
def test_manage_buttons_rendered(client, lea, monkeypatch):
    a = _abfrage()
    _tenant("max_muster", "Max", "Muster")
    _tenant("sam_neu", "Sam", "Neu")
    FakeIPA(monkeypatch, "ag.garten", [_member("lea"), _member("max_muster", "Max", "Muster")])
    client.force_login(lea)
    html = client.get(_url(a)).content.decode()
    assert 'class="remove-btn"' in html and 'data-uid="max_muster"' in html
    assert 'id="ag-member-summary"' in html
    assert 'data-uid="sam_neu"' in html  # picker option carries the uid for add_<pk>


@pytest.mark.django_db
def test_extra_row_tagged_not_in_ag(client, lea, monkeypatch):
    a = _abfrage()
    gone = _tenant("gone", "Gone", "Away")
    AGAbfrageResult.objects.create(abfrage=a, ag_name="ag.garten", tenant=gone, status="INAKTIV")
    FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    client.force_login(lea)
    html = client.get(_url(a)).content.decode()
    assert "nicht mehr in der AG" in html
    assert 'class="remove-btn" data-uid="gone"' not in html


@pytest.mark.django_db
def test_self_removal_submits_natively_so_messages_reach_dashboard(client, lea, monkeypatch):
    # base.html's AJAX swap pre-fetches a cross-page redirect and then navigates
    # again, eating the messages. The form names the viewer's uid so the JS can
    # opt out of the swap (data-no-swap) when they mark themselves.
    a = _abfrage()
    FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    client.force_login(lea)
    html = client.get(_url(a)).content.decode()
    assert 'data-self-uid="lea"' in html
    assert "dataset.noSwap" in html  # base.html honours the opt-out
    r = client.post(_url(a), {"remove_lea": "1"}, follow=True)
    assert "Aus ag.garten entfernt" in r.content.decode()


@pytest.mark.django_db
def test_extra_row_can_be_readded(client, lea, monkeypatch):
    a = _abfrage()
    gone = _tenant("gone", "Gone", "Away")
    noacc = _tenant("noacc", "No", "Account", intranet=False)
    for t in (gone, noacc):
        AGAbfrageResult.objects.create(abfrage=a, ag_name="ag.garten", tenant=t, status="INAKTIV")
    ipa = FakeIPA(monkeypatch, "ag.garten", [_member("lea")])
    client.force_login(lea)
    html = client.get(_url(a)).content.decode()
    assert f'class="readd-btn" data-pk="{gone.pk}"' in html
    assert f'data-pk="{noacc.pk}"' not in html
    client.post(_url(a), {f"add_{gone.pk}": "1"})
    assert ipa.calls == [("add", "ag.garten", "gone")]
