"""Compare two dates (#120): occupancy, paperwork and damages as of each date.

Rebuilt from the rows' own timestamps (moved_in/out, uploaded_at/revoked_at,
verified_at, created_at/fixed_at), not entity_history — so it is exact for any
date, but a hard-deleted row leaves no trace. A proof's needs_human_review flag
has no timestamp and is ignored for past states. Field-level diffs: #137.
"""
from datetime import date

from django.db.models import Count, Q
from django.utils.translation import gettext

from app.models import DOCUMENT_MODELS, EnrollmentProof, Room, TenantRoomAssignment
from app.residency import assignment_active_on

DOC_SHORT = {
    "datenschutz": "DS", "photoerlaubnis": "FoE", "vertraulichkeitserklaerung": "VE",
    "mietvertrag": "MVt", "mietbedingungen": "AMB",
    "sepa_lastschriftmandat": "SEPA", "bescheid_ausbildungsstelle": "Bes",
    "selbstverpflichtung_engagement": "SVE",
}


def parse_date(raw) -> date | None:
    """ISO date from a query parameter, or None for missing/bad input."""
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _ordered(a: date, b: date) -> tuple[date, date]:
    return (a, b) if a <= b else (b, a)


def rooms_at(d: date) -> dict[int, set[int]]:
    """tenant_id -> ids of the rooms they held on d."""
    out: dict[int, set[int]] = {}
    for tid, rid in TenantRoomAssignment.objects.filter(assignment_active_on(d)).values_list("tenant_id", "room_id"):
        out.setdefault(tid, set()).add(rid)
    return out


def occupants_at(d: date) -> dict[int, set[int]]:
    """room_id -> ids of the tenants holding it on d."""
    out: dict[int, set[int]] = {}
    for tid, rid in TenantRoomAssignment.objects.filter(assignment_active_on(d)).values_list("tenant_id", "room_id"):
        out.setdefault(rid, set()).add(tid)
    return out


def docs_at(d: date, doc_types) -> dict[int, set[str]]:
    """tenant_id -> document types present (uploaded, not yet revoked) on d."""
    out: dict[int, set[str]] = {}
    for dt in doc_types:
        for tid in DOCUMENT_MODELS[dt].objects.filter(
            Q(revoked_at__isnull=True) | Q(revoked_at__date__gt=d), uploaded_at__date__lte=d,
        ).values_list("tenant_id", flat=True):
            out.setdefault(tid, set()).add(dt)
    return out


def proofs_at(d: date) -> dict[int, str]:
    """tenant_id -> proof verdict on d, same priority as the list column:
    unverified upload ("pruefung") beats a valid proof ("gueltig"); else "fehlt"."""
    out: dict[int, str] = {}
    for p in EnrollmentProof.objects.filter(uploaded_at__date__lte=d):
        verified = p.verified_at is not None and p.verified_at.date() <= d
        state = "pruefung" if not verified else ("gueltig" if p.valid_until >= d else None)
        if state == "pruefung" or (state and out.get(p.tenant_id) != "pruefung"):
            out[p.tenant_id] = state
    return out


def tenant_changes(a: date, b: date, *, occupancy=False, rooms=False, doc_types=(), proofs=False) -> dict[int, list[str]]:
    """tenant_id -> human-readable changes from the earlier to the later date,
    limited to what the caller gates in. Tenants without a change are absent."""
    a, b = _ordered(a, b)
    out: dict[int, list[str]] = {}

    def add(tid, text):
        out.setdefault(tid, []).append(text)

    if occupancy or rooms:
        before, after = rooms_at(a), rooms_at(b)
        names = dict(Room.objects.filter(pk__in=set().union(*before.values(), *after.values()))
                     .values_list("pk", "name"))
        for tid in sorted(before.keys() | after.keys()):
            old, new = before.get(tid, set()), after.get(tid, set())
            if old == new:
                continue
            if not old:
                add(tid, gettext("eingezogen"))
            elif not new:
                add(tid, gettext("ausgezogen"))
            elif rooms:
                add(tid, gettext("Zimmerwechsel %(old)s → %(new)s") % {
                    "old": ", ".join(sorted(names[r] for r in old)),
                    "new": ", ".join(sorted(names[r] for r in new)),
                })

    if doc_types:
        before, after = docs_at(a, doc_types), docs_at(b, doc_types)
        for tid in sorted(before.keys() | after.keys()):
            old, new = before.get(tid, set()), after.get(tid, set())
            if added := [DOC_SHORT[dt] for dt in DOC_SHORT if dt in new - old]:
                add(tid, "+ " + ", ".join(added))
            if removed := [DOC_SHORT[dt] for dt in DOC_SHORT if dt in old - new]:
                add(tid, "– " + ", ".join(removed))

    if proofs:
        labels = {"gueltig": gettext("gültig"), "pruefung": gettext("Prüfung"), "fehlt": gettext("fehlt")}
        before, after = proofs_at(a), proofs_at(b)
        for tid in sorted(before.keys() | after.keys()):
            old, new = before.get(tid, "fehlt"), after.get(tid, "fehlt")
            if old != new:
                add(tid, gettext("Nachweis %(old)s → %(new)s") % {"old": labels[old], "new": labels[new]})
    return out


def damage_delta(model, group_field: str, a: date, b: date) -> dict[int, tuple[int, int]]:
    """{group_id: (new, fixed)}: damages recorded / fixed after the earlier date,
    up to and including the later one. Groups without either are absent."""
    a, b = _ordered(a, b)
    created = Q(created_at__date__gt=a, created_at__date__lte=b)
    fixed = Q(fixed_at__date__gt=a, fixed_at__date__lte=b)
    rows = model.objects.filter(created | fixed).values(group_field).annotate(
        n_new=Count("pk", filter=created), n_fixed=Count("pk", filter=fixed),
    )
    return {r[group_field]: (r["n_new"], r["n_fixed"]) for r in rows}
