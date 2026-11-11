import uuid

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from app.models import Tenant


@pytest.mark.django_db
def test_briefkasten_redirects_to_own_profile():
    tenant = Tenant.objects.create(
        first_name="Ada", last_name="Muster", email="ada@example.invalid",
        intranet_username="ada", intranet_uuid=uuid.uuid4(),
    )
    client = Client()
    client.force_login(User.objects.create_user("ada"))
    resp = client.get(reverse("briefkasten"))
    assert resp.url == reverse("tenant_detail", args=[tenant.pk]) + "#section-personal"


@pytest.mark.django_db
def test_briefkasten_without_tenant_goes_to_dashboard():
    client = Client()
    client.force_login(User.objects.create_user("nobody"))
    assert client.get(reverse("briefkasten")).url == reverse("dashboard")
