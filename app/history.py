"""Change timeline for the tenant and WG detail pages (#115).

Two kinds of source, merged newest first:
- edits from entity_history (tenant, room, tenant_room_assignment): each row is
  the state *before* an UPDATE/DELETE; the state after is the entity's next
  snapshot or its live row. INSERTs are not logged.
- events from append-style rows that carry their own timestamps: assignments
  (Einzug/Auszug), documents (uploaded/revoked), proofs (uploaded/verified) and
  damages (recorded/fixed).

Every source is gated by the caller with the same rule as the page section that
shows the data; tenant and assignment fields are filtered per field.
"""
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext, gettext_lazy as _

from app.models import EntityHistory, Room, Tenant, TenantRoomAssignment
from app.tenant_access import SECTIONS
from app.templatetags.tenant_extras import display

ROOM_LABELS = {
    "name": _("Name"), "size_sqm": _("Größe (m²)"), "has_mattress": _("Matratze"),
    "has_bed": _("Bett"), "has_table": _("Tisch"), "has_closet": _("Schrank"),
    "freifinanziert": _("freifinanziert"),
}
ASSIGNMENT_LABELS = {
    "room_id": _("Zimmer"), "moved_in": _("Eingezogen"), "moved_out": _("Ausgezogen"),
    "mailbox_key_received": _("Briefkastenschlüssel erhalten"),
    "mailbox_key_returned": _("Briefkastenschlüssel abgegeben"),
    "key_received": _("Schlüssel erhalten"), "key_returned": _("Schlüssel wieder abgegeben"),
    "is_sublet": _("Untermiete"), "sublet_of_tenant_id": _("Untervermietet von"),
    "deposit_iban": _("Kaution IBAN"),
}
TENANT_LABELS = {f.name: f.label for s in SECTIONS for f in s.fields}
IBAN_READERS = frozenset({"mietverwaltung", "admin"})  # who gets the editable room card


@dataclass
class Event:
    at: datetime
    what: str
    who: str | None = None
    changes: list[tuple[str, str, str]] = field(default_factory=list)
    note: str | None = None


def _at(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return timezone.make_aware(datetime.combine(value, time.min))


def live_snapshot(entity_type, entity_id):
    """The row as it is now, in the same shape the trigger snapshots it; None if deleted."""
    model = next((m for m in apps.get_models() if m._meta.db_table == entity_type), None)
    if model is None:
        return None
    if connection.vendor == "postgresql":
        with connection.cursor() as c:
            c.execute(
                f"SELECT to_jsonb(t) FROM {connection.ops.quote_name(entity_type)} t WHERE id = %s",
                [entity_id],
            )
            row = c.fetchone()
        return (json.loads(row[0]) if isinstance(row[0], str) else row[0]) if row else None
    row = model.objects.filter(pk=entity_id).values().first()
    return json.loads(json.dumps(row, cls=DjangoJSONEncoder)) if row else None


class _Names:
    """Lazy, cached lookups for actor usernames and the ids inside snapshots."""

    def __init__(self, may_see_names):
        self.may_see_names = may_see_names
        self._actors: dict[str, str] = {}
        self._rooms: dict[int, str] = {}
        self._tenants: dict[int, str] = {}

    def actor(self, username):
        if username not in self._actors:
            t = Tenant.objects.filter(intranet_username=username).first()
            self._actors[username] = display(t) if t else username
        return self._actors[username]

    def person(self, tenant):
        return display(tenant) if tenant is not None else None

    def value(self, key, v):
        if v is None or v == "":
            return "—"
        if isinstance(v, bool):
            return gettext("Ja") if v else gettext("Nein")
        if key == "room_id":
            if v not in self._rooms:
                room = Room.objects.filter(pk=v).first()
                self._rooms[v] = room.name if room else str(v)
            return self._rooms[v]
        if key in ("tenant_id", "sublet_of_tenant_id"):
            if not self.may_see_names:
                return gettext("belegt")
            if v not in self._tenants:
                t = Tenant.objects.filter(pk=v).first()
                self._tenants[v] = display(t) if t else str(v)
            return self._tenants[v]
        if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
            try:
                return date_format(date.fromisoformat(v), "d.m.Y")
            except ValueError:
                pass
        return str(v)


def _edits(entity_type, ids, labels, names, what):
    """One Event per entity_history row of these entities, limited to `labels`."""
    rows = list(EntityHistory.objects.filter(entity_type=entity_type, entity_id__in=list(ids))
                .order_by("entity_id", "id"))
    out = []
    for i, h in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) and rows[i + 1].entity_id == h.entity_id else None
        after = nxt.snapshot if nxt else live_snapshot(entity_type, h.entity_id)
        if after is None:
            out.append(Event(h.changed_at, gettext("%(what)s gelöscht") % {"what": what(h)},
                             names.actor(h.changed_by)))
            continue
        changes = [(str(label), names.value(k, h.snapshot.get(k)), names.value(k, after.get(k)))
                   for k, label in labels.items() if k in h.snapshot and h.snapshot.get(k) != after.get(k)]
        if changes:
            out.append(Event(h.changed_at, what(h), names.actor(h.changed_by), changes))
    return out


def _assignment_events(assignments, roles, names, with_tenant):
    labels = {k: v for k, v in ASSIGNMENT_LABELS.items() if k != "deposit_iban" or IBAN_READERS & roles}
    by_id = {a.pk: a for a in assignments}

    def what(a):
        if with_tenant and names.may_see_names:
            return gettext("Belegung %(room)s · %(name)s") % {"room": a.room.name, "name": display(a.tenant)}
        return gettext("Belegung %(room)s") % {"room": a.room.name}

    out = []
    for a in assignments:
        out.append(Event(_at(a.moved_in), gettext("Einzug: %(what)s") % {"what": what(a)}))
        if a.moved_out:
            out.append(Event(_at(a.moved_out), gettext("Auszug: %(what)s") % {"what": what(a)}))
    out += _edits("tenant_room_assignment", by_id, labels, names,
                  lambda h: what(by_id[h.entity_id]))
    return out


def _document_events(docs, label, names):
    out = []
    for d in docs:
        out.append(Event(d.uploaded_at, gettext("%(type)s hochgeladen: %(file)s") % {"type": label, "file": d.file_name},
                         names.person(d.uploaded_by)))
        if d.revoked_at:
            out.append(Event(d.revoked_at, gettext("%(type)s widerrufen: %(file)s") % {"type": label, "file": d.file_name},
                             names.person(d.revoked_by), note=d.revoked_note))
    return out


def _damage_events(damages, place, names):
    out = []
    for d in damages:
        label = f"{d.get_line_display()} ({place(d)})"
        out.append(Event(d.created_at, gettext("Schaden erfasst: %(what)s") % {"what": label},
                         names.person(d.created_by), note=d.note))
        if d.fixed_at:
            out.append(Event(d.fixed_at, gettext("Schaden behoben: %(what)s") % {"what": label},
                             names.person(d.fixed_by)))
    return out


HISTORY_PAGE = 30


def history_page(request, events) -> dict:
    """Template context: the newest HISTORY_PAGE events, or all with ?verlauf=alle."""
    show_all = request.GET.get("verlauf") == "alle"
    return {"history": events if show_all else events[:HISTORY_PAGE],
            "history_total": len(events), "history_all": show_all}


def _sorted(events):
    return sorted(events, key=lambda e: _at(e.at), reverse=True)


def tenant_timeline(tenant, roles, visible, *, assignments=False, assignment_docs=False,
                    proofs=False, doc_readable=lambda dtype: False):
    """Timeline for one tenant. `visible` is visible_fields(roles); the flags
    mirror the tenant detail sections the viewer may see."""
    from app.models import (
        ASSIGNMENT_DOCUMENT_MODELS, DOCUMENT_MODELS, AssignmentDocumentType, DocumentType, EnrollmentProof,
    )

    names = _Names("first_name" in visible)
    labels = {k: v for k, v in TENANT_LABELS.items() if k in visible}
    events = _edits("tenant", [tenant.pk], labels, names, lambda h: gettext("Profil"))
    if assignments:
        rows = list(TenantRoomAssignment.objects.filter(tenant=tenant).select_related("room", "tenant"))
        events += _assignment_events(rows, roles, names, with_tenant=False)
        if assignment_docs:
            for dtype, model in ASSIGNMENT_DOCUMENT_MODELS.items():
                docs = model.objects.filter(assignment__in=rows).select_related("uploaded_by", "revoked_by")
                events += _document_events(docs, AssignmentDocumentType(dtype).label, names)
    for dtype, model in DOCUMENT_MODELS.items():
        if doc_readable(dtype):
            docs = model.objects.filter(tenant=tenant).select_related("uploaded_by", "revoked_by")
            events += _document_events(docs, DocumentType(dtype).label, names)
    if proofs:
        for p in EnrollmentProof.objects.filter(tenant=tenant).select_related("uploaded_by", "verified_by"):
            events.append(Event(p.uploaded_at, gettext("Nachweis hochgeladen: %(file)s") % {"file": p.file_name},
                                names.person(p.uploaded_by)))
            if p.verified_at:
                events.append(Event(p.verified_at, gettext("Nachweis geprüft: %(file)s") % {"file": p.file_name},
                                    names.person(p.verified_by)))
    return _sorted(events)


def wg_timeline(wg, roles, *, may_see_names, assignments=False, assignment_docs=False,
                damages=False, own_room_ids=(), own_tenant=None, resident=False):
    """Timeline for one WG: room edits for everyone who sees the page; the other
    sources mirror the WG detail gates (staff, or a resident's own room)."""
    from app.models import ASSIGNMENT_DOCUMENT_MODELS, AssignmentDocumentType, RoomDamage, WGDamage

    names = _Names(may_see_names)
    rooms = {r.pk: r for r in Room.objects.filter(wg=wg)}
    events = _edits("room", rooms, ROOM_LABELS, names,
                    lambda h: gettext("Zimmer %(room)s") % {"room": rooms[h.entity_id].name})
    rows = []
    if assignments:
        rows = list(TenantRoomAssignment.objects.filter(room__wg=wg).select_related("room", "tenant"))
    elif own_tenant is not None:
        rows = list(TenantRoomAssignment.objects.filter(room__wg=wg, tenant=own_tenant).select_related("room", "tenant"))
    events += _assignment_events(rows, roles, names, with_tenant=True)
    if assignment_docs:
        for dtype, model in ASSIGNMENT_DOCUMENT_MODELS.items():
            docs = model.objects.filter(assignment__room__wg=wg).select_related("uploaded_by", "revoked_by")
            events += _document_events(docs, AssignmentDocumentType(dtype).label, names)
    if damages or resident:
        room_qs = RoomDamage.objects.filter(room__wg=wg).select_related("room", "created_by", "fixed_by")
        if not damages:
            room_qs = room_qs.filter(room_id__in=list(own_room_ids))
        events += _damage_events(room_qs, lambda d: d.room.name, names)
        events += _damage_events(WGDamage.objects.filter(wg=wg).select_related("created_by", "fixed_by"),
                                 lambda d: gettext("Gemeinschaftsflächen"), names)
    return _sorted(events)
