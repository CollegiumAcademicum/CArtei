"""Colour/state logic for the confidentiality_clearance grant (#65)."""
from collections.abc import Iterable

from django.conf import settings

from app.ldap_utils import (  # noqa: F401  (single patch site for views/tests)
    ClearanceIPAError,
    add_clearance_member,
    clearance_member_uuids,
    is_clearance_member,
    remove_clearance_member,
)
from app.models import ClearanceAction, ConfidentialityClearanceEvent

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
