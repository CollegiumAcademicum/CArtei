import datetime
import mimetypes

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import EnrollmentProof, EnrollmentType, Tenant

MAX_PROOF_SIZE = 10 * 1024 * 1024  # 10 MB


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


@login_required
@require_POST
def upload_proof(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    caller = _caller(request.user)
    if caller is None:
        raise PermissionDenied
    if caller.pk != pk and not _is_mv(request.user):
        raise PermissionDenied

    f = request.FILES.get("proof_file")
    if not f:
        return HttpResponseBadRequest()
    if f.size > MAX_PROOF_SIZE:
        messages.error(request, "Die Datei ist zu groß (max. 10 MB).")
        return redirect("tenant_detail", pk=pk)

    enrollment_type = request.POST.get("enrollment_type", "")
    if enrollment_type not in EnrollmentType.values:
        return HttpResponseBadRequest()

    try:
        datetime.date.fromisoformat(request.POST.get("valid_until", ""))
    except ValueError:
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


def _is_mv(user):
    group_names = set(user.groups.values_list("name", flat=True))
    if "admins" in group_names:
        return True
    mv_cns = django_settings.TENANT_ROLE_GROUPS.get("mietverwaltung", [])
    return bool(group_names.intersection(mv_cns))


@login_required
@require_POST
def verify_proof(request, pk, proof_pk):
    get_object_or_404(Tenant, pk=pk)
    if not _is_mv(request.user):
        raise PermissionDenied
    caller = _caller(request.user)
    # caller may be None (MV staff without Tenant row); verified_by_id will be NULL
    proof = get_object_or_404(EnrollmentProof, pk=proof_pk, tenant_id=pk)
    EnrollmentProof.objects.filter(pk=proof.pk).update(
        verified_at=now(),
        verified_by_id=caller.pk if caller else None,
        needs_human_review=False,
    )
    return redirect("tenant_detail", pk=pk)


@login_required
@require_POST
def edit_proof(request, pk, proof_pk):
    get_object_or_404(Tenant, pk=pk)
    caller = _caller(request.user)
    if caller is None:
        raise PermissionDenied
    # Allow: the tenant themselves, or mietverwaltung/admin
    if caller.pk != pk and not _is_mv(request.user):
        raise PermissionDenied
    proof = get_object_or_404(EnrollmentProof, pk=proof_pk, tenant_id=pk)
    enrollment_type = request.POST.get("enrollment_type", proof.enrollment_type)
    if enrollment_type not in EnrollmentType.values:
        return HttpResponseBadRequest()
    try:
        datetime.date.fromisoformat(request.POST.get("valid_until", str(proof.valid_until)))
    except ValueError:
        return HttpResponseBadRequest()
    EnrollmentProof.objects.filter(pk=proof.pk).update(
        enrollment_type=enrollment_type,
        field_of_study=request.POST.get("field_of_study", proof.field_of_study) or None,
        educational_institution=request.POST.get("educational_institution", proof.educational_institution) or None,
        valid_until=request.POST.get("valid_until", str(proof.valid_until)),
        last_edited_at=now(),
        last_edited_by_id=caller.pk,
    )
    return redirect("tenant_detail", pk=pk)


@login_required
def download_proof(request, pk, proof_pk):
    caller = _caller(request.user)
    if caller is None:
        raise PermissionDenied
    if caller.pk != pk and not _is_mv(request.user):
        raise PermissionDenied
    proof = get_object_or_404(EnrollmentProof, pk=proof_pk, tenant_id=pk)
    content_type, _ = mimetypes.guess_type(proof.file_name)
    response = HttpResponse(bytes(proof.file_data), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{proof.file_name}"'
    return response
