def privileged(request):
    if not request.user.is_authenticated:
        return {}
    return {"is_cluster_user": request.user.groups.filter(name__in=["admins", "cluster"]).exists()}
