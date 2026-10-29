import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import SuspiciousOperation
from django.test import Client, RequestFactory

from app.models import Tenant

UUID_A = "11111111-1111-1111-1111-111111111111"


def backend():
    from app.auth import KeycloakOIDCBackend
    return KeycloakOIDCBackend()


def claims(username="alice", uuid_=UUID_A, groups=("clearance",), **extra):
    return {"preferred_username": username, "ipaUniqueID": uuid_, "groups": list(groups),
            "given_name": "Alice", "family_name": "A", "email": "a@ca.de", **extra}


def login(c):
    """Run the backend's user resolution on a given userinfo payload."""
    with patch("app.auth.KeycloakOIDCBackend.get_userinfo", return_value=c):
        return backend().get_or_create_user("at", "it", {})


def test_dn_to_cn_extracts_first_cn():
    from app.auth import _dn_to_cn
    assert _dn_to_cn("cn=ag.kueche,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de") == "ag.kueche"


def test_dn_to_cn_handles_no_cn():
    from app.auth import _dn_to_cn
    assert _dn_to_cn("something-without-cn") == "something-without-cn"


def test_claim_group_names_strips_full_paths():
    from app.auth import claim_group_names
    assert claim_group_names({"groups": ["/ag.it", "gr.cluster"]}) == {"ag.it", "gr.cluster"}
    assert claim_group_names({}) == set()


# --- group sync -------------------------------------------------------------

@pytest.mark.django_db
def test_sync_groups_adds_admins():
    user = User.objects.create_user(username="alice")
    backend()._sync_groups(user, {"admins", "ag.kueche"})
    names = set(user.groups.values_list("name", flat=True))
    assert {"admins", "ag.kueche"} <= names
    assert "gr.cluster" not in names


@pytest.mark.django_db
def test_sync_groups_adds_cluster():
    user = User.objects.create_user(username="bob")
    backend()._sync_groups(user, {"cluster"})
    assert user.groups.filter(name="gr.cluster").exists()


@pytest.mark.django_db
def test_sync_groups_adds_mietverwaltung(settings):
    # cartei_mietverwaltung has no AG prefix, so it is only synced via its DN's cn.
    settings.CARTEI_MIETVERWALTUNG_GROUP = "cn=cartei_mietverwaltung,dc=test"
    user = User.objects.create_user(username="mara")
    backend()._sync_groups(user, {"cartei_mietverwaltung"})
    assert user.groups.filter(name="cartei_mietverwaltung").exists()


@pytest.mark.django_db
def test_sync_groups_keeps_prefixed_groups_only():
    user = User.objects.create_user(username="hans")
    backend()._sync_groups(user, {"ag.kueche", "gr.vorstand", "in.finanzen", "ipausers"})
    assert set(user.groups.values_list("name", flat=True)) == {"ag.kueche", "gr.vorstand", "in.finanzen"}


@pytest.mark.django_db
def test_sync_groups_admin_group_is_also_an_ag(settings):
    # The IT AG doubles as the admin group: membership must grant admin AND
    # keep ag.it as a normal AG so its members can submit engagement reports.
    settings.CARTEI_ADMIN_GROUP = "cn=ag.it,dc=test"
    user = User.objects.create_user(username="ida")
    backend()._sync_groups(user, {"ag.it"})
    assert {"admins", "ag.it"} <= set(user.groups.values_list("name", flat=True))


@pytest.mark.django_db
def test_sync_groups_grants_and_revokes_impersonation():
    user = User.objects.create_user(username="sam")
    backend()._sync_groups(user, {"cartei_impersonation"})
    assert user.groups.filter(name="cartei_impersonation").exists()
    user.refresh_from_db()
    assert user.is_superuser is False  # a plain group, not the superuser flag

    backend()._sync_groups(user, {"ag.kueche"})
    assert not user.groups.filter(name="cartei_impersonation").exists()


@pytest.mark.django_db
def test_sync_groups_removes_stale_groups():
    user = User.objects.create_user(username="carol")
    user.groups.add(Group.objects.create(name="ag.kueche"))
    backend()._sync_groups(user, set())
    assert user.groups.count() == 0


# --- login: uuid is the identity -------------------------------------------

@pytest.mark.django_db
def test_first_login_creates_user_and_tenant():
    user = login(claims(groups=["clearance", "ag.kueche"]))
    assert user.username == "alice" and user.email == "a@ca.de"
    assert user.groups.filter(name="ag.kueche").exists()
    t = Tenant.objects.get(intranet_uuid=UUID_A)
    assert t.intranet_username == "alice" and t.first_name == "Alice"


@pytest.mark.django_db
def test_relogin_reuses_tenant():
    login(claims())
    login(claims())
    assert Tenant.objects.count() == 1 and User.objects.count() == 1


@pytest.mark.django_db
def test_uid_rename_follows_uuid():
    login(claims(username="alice"))
    user = login(claims(username="alice.new"))
    assert user.username == "alice.new"
    assert User.objects.count() == 1
    assert Tenant.objects.get(intranet_uuid=UUID_A).intranet_username == "alice.new"


@pytest.mark.django_db
def test_same_uid_different_uuid_is_refused():
    Tenant.objects.create(first_name="X", last_name="Y", email="x@ca.de",
                          intranet_username="alice", intranet_uuid=uuid.uuid4())
    with pytest.raises(SuspiciousOperation):
        login(claims())
    assert not User.objects.filter(username="alice").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [
    claims(uuid_=""),                 # no ipaUniqueID claim
    claims(uuid_="not-a-uuid"),
    claims(groups=["ag.kueche"]),     # no confidentiality clearance
    claims(username=""),
])
def test_bad_claims_are_refused(bad):
    with pytest.raises(SuspiciousOperation):
        login(bad)
    assert Tenant.objects.count() == 0 and User.objects.count() == 0


def test_logout_url_ends_keycloak_session():
    from app.auth import keycloak_logout_url
    request = RequestFactory().post("/logout/")
    request.session = {"oidc_id_token": "tok"}
    url = keycloak_logout_url(request)
    assert url.startswith("https://kc.test/realms/test/protocol/openid-connect/logout?")
    assert "id_token_hint=tok" in url and "post_logout_redirect_uri=http%3A%2F%2Ftestserver%2F" in url

    request.session = {}  # password (dev) login: no Keycloak session to end
    assert keycloak_logout_url(request) == "/"


@pytest.mark.django_db
def test_login_url_redirects_to_keycloak():
    resp = Client().get("/login/?next=/dashboard/")
    assert resp.status_code == 302
    assert resp.url.startswith("https://kc.test/realms/test/protocol/openid-connect/auth?")


# --- admin links an intranet account ----------------------------------------

def _client(username, groups=()):
    c = Client()
    user = User.objects.create_user(username=username)
    for g in groups:
        user.groups.add(Group.objects.get_or_create(name=g)[0])
    c.force_login(user)
    return c


def _tenant(**kw):
    return Tenant.objects.create(first_name="Neu", last_name="B", email="n@ca.de", **kw)


@pytest.mark.django_db
def test_admin_links_and_unlinks_account():
    t = _tenant()
    c = _client("adm", ["admins"])
    member = {"username": "neu_b", "uuid": UUID_A, "first_name": "", "last_name": "", "email": ""}
    with patch("app.views.tenant.get_clearance_member", return_value=member) as get:
        c.post(f"/tenants/{t.pk}/link/", {"uid": "neu_b"})
    get.assert_called_once_with("neu_b")
    t.refresh_from_db()
    assert t.intranet_username == "neu_b" and str(t.intranet_uuid) == UUID_A

    c.post(f"/tenants/{t.pk}/link/", {"uid": ""})
    t.refresh_from_db()
    assert t.intranet_username is None and t.intranet_uuid is None


@pytest.mark.django_db
def test_link_unknown_uid_changes_nothing():
    t = _tenant()
    with patch("app.views.tenant.get_clearance_member", return_value=None):
        _client("adm", ["admins"]).post(f"/tenants/{t.pk}/link/", {"uid": "ghost"})
    t.refresh_from_db()
    assert t.intranet_username is None


@pytest.mark.django_db
def test_link_requires_admin():
    t = _tenant()
    resp = _client("mv", ["ag.mietverwaltung"]).post(f"/tenants/{t.pk}/link/", {"uid": "x"})
    assert resp.status_code == 403


# --- decorators -------------------------------------------------------------

@pytest.mark.django_db
def test_require_group_denies_wrong_group():
    from django.core.exceptions import PermissionDenied
    from app.decorators import require_group

    @require_group("admins")
    def protected_view(request):
        return "ok"

    request = RequestFactory().get("/")
    request.user = User.objects.create_user(username="eve")
    with pytest.raises(PermissionDenied):
        protected_view(request)


@pytest.mark.django_db
def test_require_group_allows_correct_group():
    from django.http import HttpResponse
    from app.decorators import require_group

    user = User.objects.create_user(username="frank")
    user.groups.add(Group.objects.get_or_create(name="admins")[0])

    @require_group("admins")
    def protected_view(request):
        return HttpResponse("ok")

    request = RequestFactory().get("/")
    request.user = user
    assert protected_view(request).status_code == 200
