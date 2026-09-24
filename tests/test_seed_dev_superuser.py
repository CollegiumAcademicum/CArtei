import pytest
from django.contrib.auth.models import User
from django.test import override_settings

from app.management.commands.seed_dev_data import Command
from app.models import Tenant


@pytest.mark.django_db
def test_dev_superuser_password_can_be_rotated_without_duplicate_records():
    command = Command()
    with override_settings(DEV_SUPERUSER_PASSWORD="first-local-password"):
        command._ensure_superuser()
        user = User.objects.get(username="dev_superuser")
        first_hash = user.password
        assert user.is_superuser and user.is_staff
        assert user.check_password("first-local-password")
        command._ensure_superuser()
        user.refresh_from_db()
        assert user.password == first_hash

    with override_settings(DEV_SUPERUSER_PASSWORD="second-local-password"):
        command._ensure_superuser()
    user.refresh_from_db()
    assert user.check_password("second-local-password")
    assert not user.check_password("first-local-password")
    assert User.objects.filter(username="dev_superuser").count() == 1
    assert Tenant.objects.filter(intranet_username="dev_superuser").count() == 1
