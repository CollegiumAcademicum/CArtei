from django.conf import settings

from app.middleware import can_impersonate
from app.models import Tenant


def privileged(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "current_tenant": Tenant.objects.filter(intranet_username=request.user.username).first(),
        "can_impersonate": can_impersonate(request.user),
    }


def version(request):
    return {"cartei_version": settings.CARTEI_VERSION}
