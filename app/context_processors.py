from app.models import Tenant


def privileged(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "is_cluster_user": request.user.groups.filter(name__in=["admins", "gr.cluster"]).exists(),
        "current_tenant": Tenant.objects.filter(intranet_username=request.user.username).first(),
    }
