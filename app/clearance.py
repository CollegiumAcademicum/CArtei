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

STATUS_TEXT = {
    GREEN: "Freigegeben: in Gruppe confidentiality_clearance, Erklärung bestätigt",
    YELLOW: "Erklärung liegt vor, wartet auf Bestätigung",
    RED: "Keine Freigabe: weder Gruppe noch Erklärung",
    BLACK: "Inkonsistent: Gruppe ohne bestätigte Erklärung oder bestätigte Erklärung ohne Gruppe",
    UNKNOWN: "Gruppenstatus unbekannt (LDAP nicht erreichbar)",
}
_COLOUR_NAME = {GREEN: "Grün", YELLOW: "Gelb", RED: "Rot", BLACK: "Schwarz", UNKNOWN: "Grau"}
# (colour name, meaning) per status, for the .ca-hint legend on the tenant page.
LEGEND = [(_COLOUR_NAME[c], text) for c, text in STATUS_TEXT.items()]


def tooltip(colour: str) -> str:
    """Hover text for the VE pill: current status first, then the full legend (one per line)."""
    legend = "\n".join(f"{_COLOUR_NAME[c]}: {text}" for c, text in STATUS_TEXT.items())
    return f"Vertraulichkeitserklärung – {STATUS_TEXT[colour]}\n\n{legend}"


def clearance_color(in_group: bool | None, approved: bool, pending: bool) -> str:
    if in_group is None:
        return UNKNOWN
    if in_group and approved:
        return GREEN
    if in_group or approved:
        return BLACK
    return YELLOW if pending else RED


def confirm_name_for(tenant: Tenant) -> str:
    """The exact name a granter must type (and is shown) to confirm a grant."""
    return f"{tenant.first_name.strip()} {tenant.last_name.strip()}".strip()


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
