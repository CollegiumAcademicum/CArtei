import datetime
import mimetypes

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import ASSIGNMENT_DOCUMENT_MODELS, DOCUMENT_MODELS, DocumentType, Tenant, TenantRoomAssignment
from app.uploads import upload_error


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


def _download_response(doc):
    """Serve stored document bytes. attachment (never inline) so a crafted PDF
    can't render same-origin; content_disposition_header escapes the filename."""
    content_type, _ = mimetypes.guess_type(doc.file_name)
    response = HttpResponse(bytes(doc.file_data), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = content_disposition_header(as_attachment=True, filename=doc.file_name)
    return response


def _assignment_redirect(request, assignment):
    """Back to the posting page (?next=) when it's a safe same-host URL — so
    assignment docs edited from the WG view stay there — else the tenant page."""
    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return redirect("tenant_detail", pk=assignment.tenant_id)


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
    err = upload_error(f)
    if err:
        messages.error(request, err)
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
    return _download_response(doc)


def _parse_date(value):
    """ISO date or None on any bad/empty input."""
    try:
        return datetime.date.fromisoformat(value or "")
    except ValueError:
        return None


# Per-type extra POST fields for a room-assignment document.
#   date fields -> model date columns; "company_signed_by" -> FK tenant id.
_ASSIGNMENT_DOC_FIELDS = {
    "mietvertrag": {"dates": ("renter_signed_at", "company_signed_at"), "company_signer": True},
    "mietbedingungen": {"dates": ("signed_at",), "company_signer": False},
    "wohnungsgeberbescheinigung": {"dates": ("signed_at",), "company_signer": True},
}


@login_required
@require_POST
def upload_assignment_document(request, assignment_pk):
    assignment = get_object_or_404(TenantRoomAssignment, pk=assignment_pk)
    caller = _caller(request.user)
    if caller is None or not _is_mv(request.user):
        raise PermissionDenied

    document_type = request.POST.get("document_type", "")
    model = ASSIGNMENT_DOCUMENT_MODELS.get(document_type)
    spec = _ASSIGNMENT_DOC_FIELDS.get(document_type)
    if model is None or spec is None:
        return HttpResponseBadRequest()

    f = request.FILES.get("document_file")
    if not f:
        return HttpResponseBadRequest()
    err = upload_error(f)
    if err:
        messages.error(request, err)
        return _assignment_redirect(request, assignment)

    values = {}
    for field in spec["dates"]:
        parsed = _parse_date(request.POST.get(field, ""))
        if parsed is None:
            return HttpResponseBadRequest()
        values[field] = parsed
    if spec["company_signer"]:
        signer = Tenant.objects.filter(pk=request.POST.get("company_signed_by") or 0).first()
        if signer is None:
            return HttpResponseBadRequest()
        values["company_signed_by"] = signer

    model.objects.create(
        assignment=assignment,
        file_name=f.name,
        file_data=f.read(),
        uploaded_at=now(),
        uploaded_by=caller,
        **values,
    )
    return _assignment_redirect(request, assignment)


@login_required
@require_POST
def revoke_assignment_document(request, assignment_pk, document_type, doc_pk):
    assignment = get_object_or_404(TenantRoomAssignment, pk=assignment_pk)
    caller = _caller(request.user)
    if caller is None or not _is_mv(request.user):
        raise PermissionDenied
    model = ASSIGNMENT_DOCUMENT_MODELS.get(document_type)
    if model is None:
        return HttpResponseBadRequest()
    doc = get_object_or_404(model, pk=doc_pk, assignment_id=assignment_pk)
    note = (request.POST.get("revoked_note") or "").strip()
    if not note:
        return HttpResponseBadRequest()
    if doc.revoked_at is not None:
        return _assignment_redirect(request, assignment)
    model.objects.filter(pk=doc.pk).update(
        revoked_at=now(), revoked_by_id=caller.pk, revoked_note=note,
    )
    return _assignment_redirect(request, assignment)


@login_required
def download_assignment_document(request, assignment_pk, document_type, doc_pk):
    assignment = get_object_or_404(TenantRoomAssignment, pk=assignment_pk)
    caller = _caller(request.user)
    if caller is None or (caller.pk != assignment.tenant_id and not _is_mv(request.user)):
        raise PermissionDenied
    model = ASSIGNMENT_DOCUMENT_MODELS.get(document_type)
    if model is None:
        return HttpResponseBadRequest()
    doc = get_object_or_404(model, pk=doc_pk, assignment_id=assignment_pk)
    return _download_response(doc)
