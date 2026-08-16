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
    assert "gr.cluster" not in group_names


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

    assert user.groups.filter(name="gr.cluster").exists()


@pytest.mark.django_db
def test_sync_groups_adds_ag_gr_in_prefixed_groups(settings):
    settings.CARTEI_ADMIN_GROUP = "cn=admins,dc=test"
    settings.CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"

    from app.auth import CustomLDAPBackend
    user = User.objects.create_user(username="hans")
    ldap_user = make_ldap_user([
        "cn=ag.kueche,dc=test",
        "cn=gr.vorstand,dc=test",
        "cn=in.finanzen,dc=test",
        "cn=ipausers,dc=test",  # unprefixed, ignored
    ])
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    backend._sync_groups(user)

    names = set(user.groups.values_list("name", flat=True))
    assert names == {"ag.kueche", "gr.vorstand", "in.finanzen"}


@pytest.mark.django_db
def test_sync_groups_admin_group_is_also_an_ag(settings):
    # The IT AG doubles as the admin group: membership must grant admin AND
    # keep ag.it as a normal AG so its members can submit engagement reports.
    settings.CARTEI_ADMIN_GROUP = "cn=ag.it,dc=test"
    settings.CARTEI_CLUSTER_GROUP = "cn=cluster,dc=test"

    from app.auth import CustomLDAPBackend
    user = User.objects.create_user(username="ida")
    ldap_user = make_ldap_user(["cn=ag.it,dc=test"])
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    backend._sync_groups(user)

    group_names = set(user.groups.values_list("name", flat=True))
    assert "admins" in group_names
    assert "ag.it" in group_names


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


@pytest.mark.django_db
def test_ensure_tenant_creates_on_first_login():
    from app.auth import CustomLDAPBackend
    from app.models import Tenant

    user = User.objects.create_user(username="greta", first_name="Greta", last_name="X", email="g@ca.de")
    ldap_user = MagicMock()
    # "not-a-uuid" is not a valid UUID → uuid.UUID("not-a-uuid") raises ValueError naturally
    ldap_user.attrs.get = lambda key, default=None: [b"not-a-uuid"] if key == "ipaUniqueID" else (default or [])
    user.ldap_user = ldap_user

    backend = CustomLDAPBackend()
    # UUID parsing fails → falls back to uuid4()
    backend._ensure_tenant(user)

    assert Tenant.objects.filter(intranet_username="greta").exists()


@pytest.mark.django_db
def test_ensure_tenant_skips_if_exists():
    from app.auth import CustomLDAPBackend
    from app.models import Tenant
    import uuid

    Tenant.objects.create(
        first_name="Hanna", last_name="Y", email="h@ca.de",
        intranet_username="hanna", intranet_uuid=uuid.uuid4(),
    )
    user = User.objects.create_user(username="hanna")
    user.ldap_user = MagicMock()

    backend = CustomLDAPBackend()
    backend._ensure_tenant(user)

    # Still only one Tenant record
    assert Tenant.objects.filter(intranet_username="hanna").count() == 1
