import pytest
from django.template import Context, Template

from app.models import Tenant
from app.templatetags.tenant_extras import display, tenant_link


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        first_name="Ada", last_name="Lovelace", email="a@example.com",
        intranet_username="ada", intranet_uuid="00000000-0000-0000-0000-0000000009aa",
    )


def test_get_absolute_url(tenant):
    assert tenant.get_absolute_url() == f"/tenants/{tenant.pk}/"


def test_tenant_link_renders_anchor(tenant):
    html = tenant_link(tenant)
    assert tenant.get_absolute_url() in html
    assert "Ada Lovelace" in html
    assert 'class="ca-tl-name"' in html


def test_tenant_link_prefers_preferred_name(tenant):
    tenant.preferred_name = "Ada L."
    assert "Ada L." in tenant_link(tenant)


def test_tenant_link_none_is_empty():
    assert tenant_link(None) == ""
    assert display(None) == ""


def test_tag_in_template(tenant):
    out = Template("{% load tenant_extras %}{% tenant_link t %}").render(Context({"t": tenant}))
    assert f'href="{tenant.get_absolute_url()}"' in out
