from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, render

from app.models import Tenant


@login_required
def tenant_detail(request: HttpRequest, pk: int):
    tenant = get_object_or_404(Tenant, pk=pk)
    return render(request, "app/tenant_detail.html", {"tenant": tenant})
