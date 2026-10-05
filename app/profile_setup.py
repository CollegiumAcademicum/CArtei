"""Find residents who must complete their contact and mailbox choices."""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from app.models import Tenant
from app.residency import has_active_assignment


def resident_for_user(user):
    """Current or future room holders, regardless of their staff roles."""
    if not user.is_authenticated:
        return None
    return Tenant.objects.filter(
        intranet_username=user.username,
    ).filter(has_active_assignment(timezone.localdate())).first()


def profile_setup_required(tenant):
    if tenant.profile_setup_completed_at is None:
        return True
    try:
        validate_email((tenant.email or "").strip())
    except ValidationError:
        return True
    has_phone = bool((tenant.phone or "").strip())
    return has_phone == tenant.no_phone_number
