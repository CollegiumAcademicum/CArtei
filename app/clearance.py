"""Colour/state logic for the confidentiality_clearance grant (#65)."""
from collections.abc import Iterable

from django.conf import settings
from django.db import transaction
from django.utils.timezone import now

from app.ldap_utils import (  # noqa: F401  (single patch site for views/tests)
    ClearanceIPAError,
    add_clearance_member,
    clearance_member_uuids,
    is_clearance_member,
    remove_clearance_member,
)
from app.models import ClearanceAction, ConfidentialityClearanceEvent, Tenant, VertraulichkeitserklaerungDocument

GREEN, YELLOW, RED, BLACK, UNKNOWN = "green", "yellow", "red", "black", "unknown"

TOOLTIP = (
    "Grün: Gruppe confidentiality_clearance + bestätigte Erklärung · "
    "Gelb: Erklärung wartet auf Bestätigung · "
    "Rot: weder Gruppe noch Erklärung · "
    "Schwarz: Gruppe und Erklärung passen nicht zusammen (Gruppe ohne bestätigte Erklärung "
    "oder bestätigte Erklärung ohne Gruppe) · "
    "Grau: Gruppenstatus unbekannt (LDAP nicht erreichbar)"
)


def clearance_color(in_group: bool | None, approved: bool, pending: bool) -> str:
    if in_group is None:
        return UNKNOWN
    if in_group and approved:
        return GREEN
    if in_group or approved:
        return BLACK
    return YELLOW if pending else RED


def approved_doc_ids(doc_ids: Iterable[int]) -> set[int]:
    """Doc ids among doc_ids with a GRANT event. Callers filter out revoked docs."""
    return set(
        ConfidentialityClearanceEvent.objects
        .filter(document_id__in=list(doc_ids), action=ClearanceAction.GRANT)
        .values_list("document_id", flat=True)
    )


def is_granter(user) -> bool:
    names = set(user.groups.values_list("name", flat=True))
    return bool(names.intersection(settings.TENANT_ROLE_GROUPS["granter"]))


def grant(tenant: Tenant, doc: VertraulichkeitserklaerungDocument, actor: Tenant) -> str:
    """Add the tenant to the IPA group, then log the event. Raises ClearanceIPAError before writing."""
    already = ConfidentialityClearanceEvent.objects.filter(
        document=doc, action=ClearanceAction.GRANT
    ).exists()
    action = ClearanceAction.REGRANT if already else ClearanceAction.GRANT
    add_clearance_member(tenant.intranet_username)
    ConfidentialityClearanceEvent.objects.create(
        tenant=tenant, document=doc, action=action, actor=actor, created_at=now()
    )
    return action


def revoke(tenant: Tenant, doc: VertraulichkeitserklaerungDocument, actor: Tenant, note: str) -> bool:
    """Remove the tenant from the IPA group, revoke the doc, log the event.

    Raises ClearanceIPAError before writing. Returns True if another non-revoked
    approved VE of the tenant remains (the group was removed anyway).
    """
    if tenant.intranet_username:
        remove_clearance_member(tenant.intranet_username)
    with transaction.atomic():
        type(doc).objects.filter(pk=doc.pk).update(revoked_at=now(), revoked_by_id=actor.pk, revoked_note=note)
        ConfidentialityClearanceEvent.objects.create(
            tenant=tenant, document=doc, action=ClearanceAction.REVOKE, actor=actor, created_at=now()
        )
    others = (
        VertraulichkeitserklaerungDocument.objects
        .filter(tenant=tenant, revoked_at__isnull=True).exclude(pk=doc.pk)
        .values_list("pk", flat=True)
    )
    return bool(approved_doc_ids(others))
