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

from app.models import DOCUMENT_MODELS, DocumentType, Tenant

MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10 MB


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


def _is_mv(user):
    group_names = set(user.groups.values_list("name", flat=True))
    if "admins" in group_names:
        return True
    mv_cns = django_settings.TENANT_ROLE_GROUPS.get("mietverwaltung", [])
    return bool(group_names.intersection(mv_cns))


@login_required
@require_POST
def upload_document(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    caller = _caller(request.user)
    if caller is None or not _is_mv(request.user):
        raise PermissionDenied

    document_type = request.POST.get("document_type", "")
    model = DOCUMENT_MODELS.get(document_type)
    if model is None:
        return HttpResponseBadRequest()

    f = request.FILES.get("document_file")
    if not f:
        return HttpResponseBadRequest()
    if f.size > MAX_DOCUMENT_SIZE:
        messages.error(request, "Die Datei ist zu groß (max. 10 MB).")
        return redirect("tenant_detail", pk=pk)

    try:
        signed_at = datetime.date.fromisoformat(request.POST.get("signed_at", ""))
    except ValueError:
        return HttpResponseBadRequest()

    # The signer is always the tenant themselves — no co-signers. The
    # document_signer table is left unlinked from the document tables.
    model.objects.create(
        tenant=tenant,
        file_name=f.name,
        file_data=f.read(),
        signed_at=signed_at,
        uploaded_at=now(),
        uploaded_by=caller,
    )
    return redirect("tenant_detail", pk=pk)


@login_required
@require_POST
def revoke_document(request, pk, document_type, doc_pk):
    get_object_or_404(Tenant, pk=pk)
    caller = _caller(request.user)
    if caller is None or not _is_mv(request.user):
        raise PermissionDenied
    model = DOCUMENT_MODELS.get(document_type)
    if model is None:
        return HttpResponseBadRequest()
    doc = get_object_or_404(model, pk=doc_pk, tenant_id=pk)
    note = (request.POST.get("revoked_note") or "").strip()
    if not note:
        return HttpResponseBadRequest()
    if doc.revoked_at is not None:
        return redirect("tenant_detail", pk=pk)  # already revoked; trigger would reject
    model.objects.filter(pk=doc.pk).update(
        revoked_at=now(), revoked_by_id=caller.pk, revoked_note=note,
    )
    return redirect("tenant_detail", pk=pk)


@login_required
def download_document(request, pk, document_type, doc_pk):
    caller = _caller(request.user)
    if caller is None or (caller.pk != pk and not _is_mv(request.user)):
        raise PermissionDenied
    model = DOCUMENT_MODELS.get(document_type)
    if model is None:
        return HttpResponseBadRequest()
    doc = get_object_or_404(model, pk=doc_pk, tenant_id=pk)
    content_type, _ = mimetypes.guess_type(doc.file_name)
    response = HttpResponse(bytes(doc.file_data), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{doc.file_name}"'
    return response
