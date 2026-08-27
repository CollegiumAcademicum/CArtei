from django import template
from django.utils.html import format_html

from app.views._shared import display as _display

register = template.Library()


@register.filter
def display(tenant):
    """Preferred name, else first + last. Empty for None."""
    return _display(tenant) if tenant else ""


@register.simple_tag
def tenant_link(tenant):
    """A tenant's display name as a link to their detail page. Renders nothing
    for None, so callers don't need their own {% if %} guard. Use this wherever
    a tenant name is shown — a name should never render link-less."""
    if not tenant:
        return ""
    return format_html('<a href="{}" class="ca-tl-name">{}</a>', tenant.get_absolute_url(), _display(tenant))
