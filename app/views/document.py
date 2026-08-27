import datetime

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import (
    ASSIGNMENT_DOCUMENT_MODELS, DOCUMENT_MODELS, DocumentType,
    Tenant, TenantRoomAssignment, document_readers,
)
from app.tenant_access import global_roles
from app.uploads import upload_error
from app.views._shared import inline_file_response


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


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


# Extra POST fields per per-tenant document type. Most carry a single signed_at.
#   dates  -> date columns (required ISO dates)
#   text   -> required non-empty text columns (e.g. SEPA mandate fields)
#   signer -> a model FK field whose POST value is a tenant id (Mietvertrag GmbH
#             signer, Bescheid CA-side signer). The POST field name == model field.
_TENANT_DOC_FIELDS = {
    "mietvertrag": {"dates": ("renter_signed_at", "company_signed_at"), "signer": "company_signed_by"},
    "sepa_lastschriftmandat": {
        "dates": ("signed_at",),
        "text": ("mandatsreferenz", "kontoinhaber", "bank_name", "iban", "bic"),
    },
    "bescheid_ausbildungsstelle": {"dates": ("signed_at",), "signer": "signed_by"},
}
_DEFAULT_TENANT_DOC_FIELDS = {"dates": ("signed_at",)}


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
    spec = _TENANT_DOC_FIELDS.get(document_type, _DEFAULT_TENANT_DOC_FIELDS)

    f = request.FILES.get("document_file")
    if not f:
        return HttpResponseBadRequest()
    err = upload_error(f)
    if err:
        messages.error(request, err)
        return redirect("tenant_detail", pk=pk)

    values = {}
    for field in spec["dates"]:
        parsed = _parse_date(request.POST.get(field, ""))
        if parsed is None:
            return HttpResponseBadRequest()
        values[field] = parsed
    for field in spec.get("text", ()):
        val = (request.POST.get(field) or "").strip()
        if not val:
            return HttpResponseBadRequest()
        values[field] = val
    signer_field = spec.get("signer")
    if signer_field:
        signer = Tenant.objects.filter(pk=request.POST.get(signer_field) or 0).first()
        if signer is None:
            return HttpResponseBadRequest()
        values[signer_field] = signer

    # The tenant's own signature isn't modelled here (no co-signers); the
    # document_signer table is left unlinked from the document tables.
    model.objects.create(
        tenant=tenant,
        file_name=f.name,
        file_data=f.read(),
        uploaded_at=now(),
        uploaded_by=caller,
        **values,
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
    model = DOCUMENT_MODELS.get(document_type)
    if model is None:
        return HttpResponseBadRequest()
    if caller is None:
        raise PermissionDenied
    # Per-type read gating (owner + the type's reader roles, e.g. Finanzierung for SEPA).
    roles = set(global_roles(request.user))
    if caller.pk == pk:
        roles.add("owner")
    if not (document_readers(document_type) & roles):
        raise PermissionDenied
    doc = get_object_or_404(model, pk=doc_pk, tenant_id=pk)
    return inline_file_response(doc)


def _parse_date(value):
    """ISO date or None on any bad/empty input."""
    try:
        return datetime.date.fromisoformat(value or "")
    except ValueError:
        return None


# Per-type extra POST fields for a room-assignment document.
#   date fields -> model date columns; "company_signed_by" -> FK tenant id.
_ASSIGNMENT_DOC_FIELDS = {
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
    return inline_file_response(doc)
