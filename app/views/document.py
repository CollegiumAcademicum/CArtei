import datetime
import logging

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import localdate, now
from django.views.decorators.http import require_POST

from app import clearance
from app.models import (
    ASSIGNMENT_DOCUMENT_MODELS, AssignmentDocumentType, DOCUMENT_MODELS,
    DocumentType, Tenant, TenantRoomAssignment, VertraulichkeitserklaerungDocument,
    document_readers,
)
from app.tenant_access import global_roles
from app.document_generation.mailbox_list import (
    MailboxListGenerationError, NoMailboxResidents, generate_mailbox_list,
)
from app.uploads import upload_error
from app.views._shared import inline_file_response


logger = logging.getLogger(__name__)

def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


def _fmt(d):
    return d.strftime("%d.%m.%Y") if d else "—"


def _signed_display(doc, dtype):
    """The signing date for the main column; Mietvertrag has no single one so
    show the renter's (both dates go into the detail block)."""
    if dtype == DocumentType.MIETVERTRAG.value:
        return _fmt(doc.renter_signed_at)
    return _fmt(doc.signed_at)


def _detail(doc, dtype):
    """Type-specific fields as (label, value) pairs for the expandable row. A
    value that is a Tenant is rendered as a link by the template (its .pk is
    truthy); plain strings render as text."""
    if dtype == DocumentType.MIETVERTRAG.value:
        return [
            ("Mieter*in unterschrieben", _fmt(doc.renter_signed_at)),
            ("GmbH unterschrieben", _fmt(doc.company_signed_at)),
            ("GmbH-Unterzeichner*in", doc.company_signed_by),
        ]
    if dtype == DocumentType.SEPA_LASTSCHRIFTMANDAT.value:
        return [
            ("Mandatsreferenz", doc.mandatsreferenz),
            ("Kontoinhaber*in", doc.kontoinhaber),
            ("Bank", doc.bank_name),
            ("IBAN", doc.iban),
            ("BIC", doc.bic),
        ]
    if dtype == DocumentType.BESCHEID_AUSBILDUNGSSTELLE.value:
        return [("Unterzeichnet von", doc.signed_by)]
    if dtype == AssignmentDocumentType.WOHNUNGSGEBERBESCHEINIGUNG.value:
        return [("GmbH-Unterzeichner*in", doc.company_signed_by)]
    return []


def _row(doc, dtype, label, tenant, download_url):
    return {
        "tenant": tenant,
        "type_key": dtype,
        "type_label": label,
        "file_name": doc.file_name,
        "signed": _signed_display(doc, dtype),
        "uploaded_at": doc.uploaded_at,
        "uploaded_by": doc.uploaded_by,
        "revoked": doc.revoked_at is not None,
        "revoked_at": _fmt(doc.revoked_at),
        "revoked_by": doc.revoked_by if doc.revoked_by_id else None,
        "revoked_note": doc.revoked_note or "",
        "detail": _detail(doc, dtype),
        "download_url": download_url,
    }


# Extra FKs to select_related per per-tenant type (avoids N+1 on the signer).
_TENANT_DOC_SIGNER_REL = {
    DocumentType.MIETVERTRAG.value: "company_signed_by",
    DocumentType.BESCHEID_AUSBILDUNGSSTELLE.value: "signed_by",
}


@login_required
def list_documents(request):
    """Cross-tenant overview of every document the caller may read. Per-tenant
    types use the same per-type reader gate as the download view; assignment
    types have no reader set, so (like their download) they show to MV/admin
    only. Rendered as one client-side-filtered table, same UX as tenant_list."""
    roles = set(global_roles(request.user))
    rows = []
    types_seen = {}  # type_key -> label, for the Typ filter dropdown

    for dtype, model in DOCUMENT_MODELS.items():
        if not (document_readers(dtype) & roles):
            continue
        label = DocumentType(dtype).label
        types_seen[dtype] = label
        rel = ["tenant", "uploaded_by", "revoked_by"]
        if dtype in _TENANT_DOC_SIGNER_REL:
            rel.append(_TENANT_DOC_SIGNER_REL[dtype])
        for doc in model.objects.select_related(*rel):
            rows.append(_row(doc, dtype, label, doc.tenant, reverse(
                "document_download",
                kwargs={"pk": doc.tenant_id, "document_type": dtype, "doc_pk": doc.pk})))

    if {"mietverwaltung", "admin"} & roles:
        for dtype, model in ASSIGNMENT_DOCUMENT_MODELS.items():
            label = AssignmentDocumentType(dtype).label
            types_seen[dtype] = label
            for doc in model.objects.select_related(
                "assignment__tenant", "uploaded_by", "revoked_by", "company_signed_by",
            ):
                rows.append(_row(doc, dtype, label, doc.assignment.tenant, reverse(
                    "assignment_document_download",
                    kwargs={"assignment_pk": doc.assignment_id, "document_type": dtype, "doc_pk": doc.pk})))

    rows.sort(key=lambda r: r["uploaded_at"], reverse=True)
    # ponytail: loads every readable row unpaginated, like tenant_list; add
    # Django's Paginator if cross-tenant volume gets slow.
    return render(request, "app/document_list.html", {
        "rows": rows,
        "doc_types": sorted(types_seen.items(), key=lambda kv: kv[1]),
        "total": len(rows),
        "can_generate_forms": bool({"mietverwaltung", "admin"} & roles),
    })


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
    allowed = _is_mv(request.user) or (
        document_type == "vertraulichkeitserklaerung" and clearance.is_granter(request.user)
    )
    if caller is None or not allowed:
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
    if (
        document_type == "vertraulichkeitserklaerung"
        and clearance.approved_doc_ids([doc.pk])
    ):
        if getattr(request, "impersonator", None):
            raise PermissionDenied
        try:
            others = clearance.revoke(doc.tenant, doc, caller, note)
        except clearance.ClearanceIPAError as exc:
            logger.exception("Clearance revoke failed for tenant %s", pk)
            messages.error(request, f"Entzug fehlgeschlagen: {exc}")
            return redirect("tenant_detail", pk=pk)
        if others:
            logger.error("Tenant %s still has another approved VE after revoke", pk)
            messages.error(
                request,
                "Es gibt noch eine weitere bestätigte Vertraulichkeitserklärung – "
                "Gruppe wurde trotzdem entzogen. Bitte prüfen.",
            )
        return redirect("tenant_detail", pk=pk)
    model.objects.filter(pk=doc.pk).update(
        revoked_at=now(), revoked_by_id=caller.pk, revoked_note=note,
    )
    return redirect("tenant_detail", pk=pk)


@login_required
@require_POST
def grant_clearance(request, pk, doc_pk):
    caller = _caller(request.user)
    if caller is None or not clearance.is_granter(request.user):
        raise PermissionDenied
    if getattr(request, "impersonator", None):
        raise PermissionDenied
    doc = get_object_or_404(VertraulichkeitserklaerungDocument, pk=doc_pk, tenant_id=pk)
    tenant = doc.tenant
    back = redirect(reverse("tenant_detail", args=[pk]) + "#section-documents")
    if doc.revoked_at is not None:
        messages.error(request, "Die Erklärung ist widerrufen.")
        return back
    if not tenant.intranet_username or not tenant.intranet_uuid:
        messages.error(request, "Kein Intranet-Account vorhanden.")
        return back
    if (request.POST.get("confirm_name") or "").strip() != f"{tenant.first_name} {tenant.last_name}":
        messages.error(request, "Name stimmt nicht überein")
        return back
    try:
        clearance.grant(tenant, doc, caller)
    except clearance.ClearanceIPAError as exc:
        logger.exception("Clearance grant failed for tenant %s", pk)
        messages.error(request, f"Freigabe fehlgeschlagen: {exc}")
        return back
    messages.success(request, "Vertraulichkeitsfreigabe erteilt.")
    return back


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


@login_required
def download_mailbox_list(request):
    """Download the current opted-in Neubau list in the original print format."""
    if not ({"mietverwaltung", "admin"} & global_roles(request.user)):
        raise PermissionDenied
    today = localdate()
    try:
        pdf = generate_mailbox_list(today)
    except NoMailboxResidents:
        messages.info(request, "Aktuell gibt es keine Neubau-Bewohner*innen mit Briefkastenlisten-Zustimmung.")
        return redirect("document_list")
    except MailboxListGenerationError as exc:
        logger.exception("Briefkastenliste generation failed")
        messages.error(request, f"Die Briefkastenliste konnte nicht erstellt werden: {exc}")
        return redirect("document_list")

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="briefkastenliste-{today.isoformat()}.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response
