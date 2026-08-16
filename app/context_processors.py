from app.models import Tenant


def privileged(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "current_tenant": Tenant.objects.filter(intranet_username=request.user.username).first(),
    }
