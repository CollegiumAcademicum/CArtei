"""Cross-view helpers shared by the tenant and WG views. Extracted from
tenant.py so rooms.py can reuse them without a circular import."""
import logging
import mimetypes
from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header

from app.forms import TenantRoomAssignmentForm
from app.ldap_utils import set_ldap_mail
from app.models import ASSIGNMENT_DOCUMENT_MODELS, AssignmentDocumentType, Tenant, TenantRoomAssignment

logger = logging.getLogger(__name__)


def write_through_email(form, tenant) -> bool:
    """FreeIPA `mail` is the email SSOT for linked tenants (CArtei#70): push a
    changed address there BEFORE the DB save. On failure flag the field and
    return False — the caller must then not save, or the next cache refresh
    would silently revert the edit. Sets tenant.email_refreshed_at on success."""
    email = form.cleaned_data["email"]
    if not tenant.intranet_username or Tenant.objects.filter(pk=tenant.pk, email=email).exists():
        return True
    try:
        set_ldap_mail(tenant.intranet_username, email)
    except Exception as exc:
        logger.error("Email write-through failed for tenant %s: %s", tenant.pk, exc)
        form.add_error("email", "Konnte nicht ins Intranet (FreeIPA) übernommen werden — nicht gespeichert.")
        return False
    tenant.email_refreshed_at = timezone.now()
    return True


def inline_file_response(doc):
    """Serve stored document/proof bytes inline (opens in the browser tab).
    CSP sandbox neutralises scripts in a crafted PDF so inline viewing can't run
    same-origin JS; content_disposition_header escapes the user-supplied filename.
    Used by the document, assignment-document and enrollment-proof downloads."""
    content_type, _ = mimetypes.guess_type(doc.file_name)
    response = HttpResponse(bytes(doc.file_data), content_type=content_type or "application/octet-stream")
    response["Content-Disposition"] = content_disposition_header(as_attachment=False, filename=doc.file_name)
    response["Content-Security-Policy"] = "sandbox"
    return response

# Statuses that clear the engagement flag: being reported active in an AG.
ACTIVE_STATES = {"AKTIV", "ZU_AKTIV"}

# Belegium may edit an assignment's room data only for future move-ins and the
# first two weeks after move-in (moved_in >= today - 14d); read-only afterwards.
BELEGIUM_EDIT_WINDOW = timedelta(days=14)


def display(tenant):
    return tenant.preferred_name or f"{tenant.first_name} {tenant.last_name}".strip()


def assignment_doc_groups(assignment):
    """Signed documents for one room assignment, grouped by type, newest first,
    with the current active (non-revoked) doc surfaced. Powers the per-card
    Dokumente block in both the tenant and WG detail views."""
    groups = []
    for dtype, model in ASSIGNMENT_DOCUMENT_MODELS.items():
        docs = list(model.objects.filter(assignment=assignment).order_by("-uploaded_at"))
        for d in docs:
            d.doc_type = dtype
        groups.append({
            "type": dtype,
            "label": AssignmentDocumentType(dtype).label,
            "active_doc": next((d for d in docs if d.revoked_at is None), None),
            "docs": docs,
        })
    return groups


def engagement_verdict(results):
    """True = flagged for the Clustersprechende (not meeting engagement). One
    'aktiv'/'zu aktiv' AG clears it; insufficient/inactive/no report flags it."""
    return not any(r.status in ACTIVE_STATES for r in results)


def assignment_editable_by(a, roles, today):
    """Who may edit an assignment's room data. MV/admin: always. Belegium: only
    inside the move-in window. Everyone else (owner): never."""
    if {"mietverwaltung", "admin"} & roles:
        return True
    if "belegium" in roles:
        return a.moved_in >= today - BELEGIUM_EDIT_WINDOW
    return False


def submitted_assignment_forms(request, roles, today, scope_qs):
    """Bind + authorize a TenantRoomAssignmentForm for each submitted
    assignment_id that lives in scope_qs and is editable by roles."""
    forms = []
    for pk_str in request.POST.getlist("assignment_ids"):
        a = scope_qs.filter(pk=pk_str).first()
        if a and assignment_editable_by(a, roles, today):
            forms.append((a, TenantRoomAssignmentForm(request.POST, instance=a, prefix=f"room_{a.pk}")))
    return forms
