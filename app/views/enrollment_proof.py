from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import EnrollmentProof, EnrollmentType, Tenant


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


@login_required
@require_POST
def upload_proof(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    caller = _caller(request.user)
    if caller is None:
        raise PermissionDenied

    f = request.FILES.get("proof_file")
    if not f:
        return HttpResponseBadRequest()

    enrollment_type = request.POST.get("enrollment_type", "")
    if enrollment_type not in EnrollmentType.values:
        return HttpResponseBadRequest()

    EnrollmentProof.objects.create(
        tenant=tenant,
        enrollment_type=enrollment_type,
        field_of_study=request.POST.get("field_of_study", "") or None,
        educational_institution=request.POST.get("educational_institution", "") or None,
        file_name=f.name,
        file_data=f.read(),
        uploaded_at=now(),
        uploaded_by=caller,
        valid_until=request.POST.get("valid_until"),
    )
    return redirect("tenant_detail", pk=pk)
