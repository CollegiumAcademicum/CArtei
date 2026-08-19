# WG list & WG detail views — design

**Date:** 2026-08-19
**Repo:** CArtei (Django only — no `cartei_db` schema change)
**Status:** approved for planning

## Goal

Give staff two views over the housing data that already exists:

1. **WG list** (`/wgs/`) — every room, grouped by Building › WG, with occupancy.
2. **WG detail** (`/wgs/<pk>/`) — the history of who lived in each room of one
   WG, editable room assignments, an engagement rollup for its residents, and a
   seam for damage assessment (built later).

Both views support **time-travel**: an `as_of` date shows occupancy as it was on
that date. This is possible with no new schema because assignments are already
date-scoped (`moved_in` / `moved_out`).

This is **Spec #1 of 2**. Damage catalogue + Übergabeprotokoll tracking (new
tables in `cartei_db`) is deferred to Spec #2; the detail view carries a stub
section where it will plug in.

## Non-goals (deferred)

- Damage catalogue, Übergabeprotokoll damage records, auto-generated damage
  reports (Spec #2).
- Interactive floor plan (far future).
- Room *attribute* history (furniture/size via `entity_history`). Only
  *occupancy* time-travels in this spec.

## What already exists (reused, not rebuilt)

| Piece | Location | Use |
|-------|----------|-----|
| `WG`, `Room`, `Building`, `TenantRoomAssignment` mirrors | `app/models.py` | queried directly |
| `active_assignment_q(date)` | `app/residency.py` | as-of occupancy filter |
| `visible_fields(roles)`, `global_roles(user)` | `app/tenant_access.py` | per-viewer field gating |
| `_display(tenant)` | `app/views/tenant.py` | occupant name/Rufname |
| `_room_assignment_edit.html` | `app/templates/app/` | assignment history + inline edit |
| `_assignment_editable_by(a, roles, today)` | `app/views/tenant.py` | MV/admin-always, Belegium-14d-window edit perm |
| `_engagement_verdict(results)`, `_ACTIVE_STATES` | `app/views/tenant.py` | met/not-met engagement per tenant |

`_display`, `_assignment_editable_by`, `_engagement_verdict` currently live in
`app/views/tenant.py`. To share them without a circular import, move them into a
small helper module (`app/views/_shared.py` or reuse `app/residency.py` /
`app/tenant_access.py` as appropriate) and import from both `tenant.py` and the
new `rooms.py`. Keep the move surgical — no behaviour change, update the tenant
tests' imports if they reference these directly.

## Routes & access

New file `app/views/rooms.py`; two routes in `app/urls.py`:

```
path("wgs/",            rooms.wg_list,   name="wg_list"),
path("wgs/<int:pk>/",   rooms.wg_detail, name="wg_detail"),
```

Both `@login_required`, open to every authenticated user. There is **no**
`@require_group` gate — instead, tenant-identifying data (occupant name, email)
is shown only when `visible_fields(global_roles(user))` grants that field, exactly
like `tenant_list`. A viewer without name access still sees the room and a
**belegt / frei** badge, never the occupant's identity.

### `as_of` parameter

Both views accept `?as_of=YYYY-MM-DD`, default `date.today()`. Parse defensively:
an unparseable value falls back to today (no 500). A native `<input type="date">`
in a GET form drives it. All occupancy on the page reflects `as_of`.

**Active-on-date predicate** (shared helper in `residency.py`):

```python
def assignment_active_on(d):
    # active on date d: moved in on/before d, not yet moved out on d
    return Q(moved_in__lte=d) & active_assignment_q(d)
```

`active_assignment_q(d)` already means "not moved out, or moving out after d".
Adding `moved_in__lte=d` is the missing bound for past/future travel (the
existing helper omits it because live callers assume today ≥ move-in).

## View 1 — WG list (`/wgs/`)

**Query:** all `Building`s → their `WG`s → their `Room`s (ordered
Building.name, WG.name, Room.name). For each room, the assignment active on
`as_of` (at most one expected; if data has overlaps, show the earliest-moved-in
and don't crash).

**Renders:** grouped sections Building › WG (WG heading links to its detail,
carrying the same `as_of`). Per room row: `name`, `size_sqm`, `freifinanziert`
badge, and occupancy — occupant `_display` name if the viewer may see names,
else just **belegt / frei**.

Efficiency: prefetch assignments + tenants to avoid N+1 (`select_related` /
`prefetch_related` or a single grouped query keyed by room_id).

## View 2 — WG detail (`/wgs/<pk>/`)

`get_object_or_404(WG, pk=pk)`. Sections:

1. **Header** — WG name, Building, cluster; the `as_of` date picker (GET form).
2. **Rooms + assignment history** — for each room in the WG: its full
   assignment history (all assignments ever, newest first), rendered with the
   existing `_room_assignment_edit.html` partial and its perms
   (`_assignment_editable_by`). The assignment active on `as_of` is visually
   marked as the current-on-that-date occupant. Editing posts through the
   **existing** assignment-edit endpoint/form — no new write path is introduced
   here; if the current edit POST is bound to the tenant detail page, expose the
   same form action so it round-trips back to the WG detail. (Planning step must
   confirm where the assignment-edit POST currently lives and reuse it.)
3. **Engagement rollup** — over residents active on `as_of`, count how many meet
   engagement via `_engagement_verdict`. This **time-travels too**: the survey
   used is the most recent Abfrage *as of the selected date* — the latest
   `AGAbfrage` whose `date <= as_of` (not the globally latest). Display
   "X von Y erfüllen ihr Engagement (Abfrage <label/date>)". Shown only to roles
   that already see engagement (`cluster` / `admin`), matching `tenant_list`'s
   `show_surveys`.

   Ceiling: the verdict reads that survey's **current** result rows, not their
   values as of `as_of`. `AGAbfrageResult` is `Historized`, so exact
   point-in-time statuses live in `entity_history`, but reading that snapshot is
   deferred (same call as room-attribute history). Selecting the correct survey
   for the date is the meaningful travel; re-reading historical status values is
   a later refinement.
   <!-- ponytail: uses current result rows of the as-of survey, not entity_history snapshots; add history read if point-in-time status values are needed -->

4. **Zustand & Schäden (stub)** — a placeholder card noting damage assessment is
   coming. No logic. This is the Spec #2 seam.

## Data flow

```
request (?as_of) ──▶ parse_as_of() ──▶ assignment_active_on(as_of)
                                          │
        WG/Room/Building query ───────────┤──▶ per-room occupant (as_of)
                                          │
   Abfrage where date<=as_of (latest) ────┴──▶ _engagement_verdict per resident
        + its result rows                        └─▶ rollup count
        visible_fields(roles) ──▶ gate occupant name in both templates
```

## Error handling

- Bad/absent `as_of` → today (never 500).
- WG not found → 404.
- Room with zero or multiple active assignments on `as_of` → render gracefully
  (frei / show earliest), no exception.
- No Abfrage with `date <= as_of` → engagement rollup shows "keine Abfrage"
  rather than dividing by zero.

## Testing (`tests/test_room_views.py`, pytest-django)

Reuse the existing `conftest.py` fixture that flips `managed=False` models to
managed for the SQLite test DB. Cases:

1. **Grouping** — rooms appear under the correct Building › WG on `/wgs/`.
2. **As-of occupancy** — a room with an assignment `[moved_in, moved_out]` shows
   the occupant when `as_of` is inside the window, **frei** outside it (past and
   future dates).
3. **Name gating** — a viewer whose roles don't grant `first_name` sees
   belegt/frei but not the occupant's name; an MV viewer sees the name.
4. **Engagement rollup** — with one resident cleared and one flagged against the
   as-of survey, the WG detail reports "1 von 2".
5. **Engagement time-travel** — two Abfragen (`date` before and after `as_of`);
   the rollup uses the one whose `date <= as_of`, and switching `as_of` across
   the later survey's date changes which survey is counted.
6. **Bad `as_of`** — garbage query value falls back to today, 200 not 500.

## Files touched

- **new** `app/views/rooms.py`
- **new** `app/templates/app/wg_list.html`
- **new** `app/templates/app/wg_detail.html`
- **new** `tests/test_room_views.py`
- **edit** `app/urls.py` (two routes)
- **edit** `app/residency.py` (`assignment_active_on` helper)
- **edit/new** shared-helpers move for `_display` / `_assignment_editable_by` /
  `_engagement_verdict` (+ update `app/views/tenant.py` imports)
- **edit** navigation (add a "WGs" link wherever `tenant_list` is linked, e.g.
  `base.html` / dashboard) — confirm location in planning.

No `cartei_db` change. No Django migration (domain tables stay `managed=False`).
