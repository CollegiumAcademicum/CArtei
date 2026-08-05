import pytest
from unittest.mock import MagicMock, patch
from django.contrib.auth.models import User, Group


def make_ldap_user(member_of):
    """Helper: fake ldap_user with memberOf attribute."""
    ldap_user = MagicMock()
    ldap_user.attrs.get = lambda key, default=None: member_of if key == "memberOf" else (default or [])
    return ldap_user


def test_dn_to_cn_extracts_first_cn():
    from app.auth import _dn_to_cn
    assert _dn_to_cn("cn=ag.kueche,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de") == "ag.kueche"


def test_dn_to_cn_handles_no_cn():
    from app.auth import _dn_to_cn
    assert _dn_to_cn("something-without-cn") == "something-without-cn"


@pytest.mark.django_db
def test_sync_groups_adds_admins(settings):
    settings.CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
    settings.CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"

    from app.auth import CustomLDAPBackend
    user = User.objects.create_user(username="alice")
    ldap_user = make_ldap_user(["cn=admins,dc=test", "cn=ag.kueche,dc=test"])
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    backend._sync_groups(user)

    group_names = list(user.groups.values_list("name", flat=True))
    assert "admins" in group_names
    assert "ag.kueche" in group_names
    assert "cluster" not in group_names


@pytest.mark.django_db
def test_sync_groups_adds_cluster(settings):
    settings.CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
    settings.CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"

    from app.auth import CustomLDAPBackend
    user = User.objects.create_user(username="bob")
    ldap_user = make_ldap_user(["cn=cluster,dc=test"])
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    backend._sync_groups(user)

    assert user.groups.filter(name="cluster").exists()


@pytest.mark.django_db
def test_sync_groups_removes_stale_groups(settings):
    settings.CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
    settings.CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"

    from app.auth import CustomLDAPBackend
    user = User.objects.create_user(username="carol")
    old_group, _ = Group.objects.get_or_create(name="ag.kueche")
    user.groups.add(old_group)

    # LDAP now shows no groups
    ldap_user = make_ldap_user([])
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    backend._sync_groups(user)

    assert not user.groups.filter(name="ag.kueche").exists()


@pytest.mark.django_db
def test_sync_groups_skips_non_ag_groups(settings):
    settings.CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
    settings.CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"

    from app.auth import CustomLDAPBackend
    user = User.objects.create_user(username="dave")
    ldap_user = make_ldap_user(["cn=ipausers,dc=test"])  # not ag. prefixed, not admin/cluster
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    backend._sync_groups(user)

    assert user.groups.count() == 0


@pytest.mark.django_db
def test_require_group_denies_wrong_group():
    from django.test import RequestFactory
    from django.core.exceptions import PermissionDenied
    from app.decorators import require_group

    factory = RequestFactory()
    user = User.objects.create_user(username="eve")

    @require_group("admins")
    def protected_view(request):
        return "ok"

    request = factory.get("/")
    request.user = user
    with pytest.raises(PermissionDenied):
        protected_view(request)


@pytest.mark.django_db
def test_require_group_allows_correct_group():
    from django.test import RequestFactory
    from django.http import HttpResponse
    from app.decorators import require_group

    factory = RequestFactory()
    user = User.objects.create_user(username="frank")
    group, _ = Group.objects.get_or_create(name="admins")
    user.groups.add(group)

    @require_group("admins")
    def protected_view(request):
        return HttpResponse("ok")

    request = factory.get("/")
    request.user = user
    response = protected_view(request)
    assert response.status_code == 200
