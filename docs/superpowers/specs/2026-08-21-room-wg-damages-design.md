# Room & WG Damages — Design

**Date:** 2026-08-21
**Status:** Approved design, ready for implementation plan
**Repos touched:** `cartei_db` (schema), `CArtei` (app)

## Purpose

A standalone damage tracker, fully decoupled from the (now-removed)
Übergabeprotokoll. A damage is a **ticket**: it is opened against a room or a
WG, carries a typed defect from a catalog, and lives until someone marks it
**fixed**. Damages are never deleted — only fixed (and, if closed by mistake,
reopened).

This replaces the old per-handover, size-bucket *wear count* with a
target-scoped, open-until-fixed *tracking* model.

## Non-goals (YAGNI — add only when asked)

Photos/attachments, severity/priority, assignment to a specific worker,
notifications/reminders, PDF export, a dedicated damages dashboard or
cross-target list view.

## Requirements (decided during brainstorming)

1. Damages live **outside** Übergaben.
2. A damage attaches to **either a room or a WG** (two separate concepts →
   two tables, two catalogs).
3. The defect is **typed from a catalog**, not free text (holes, stains, etc.
   are stored structurally). Optional size and optional free-text note.
4. A damage can be **marked fixed, never deleted**. Reopening a fixed damage
   is allowed. Enforced at the **database** level.
5. **Who can do what:**
   - **Staff** = `werkstatt` ∪ `mietverwaltung` ∪ `admin`: view, add,
     mark-fixed and reopen, on **all** rooms/WGs.
   - **Residents** (a tenant with an active assignment to that room, or living
     in that WG): **add + view** damages on **their own** room/WG only. They
     **cannot** mark fixed/reopen.
   - **Belegium**: no access to damages at all.

## Data model — `cartei_db`

### Shared column mixin

New declarative mixin in `cartei_db/models/damage_base.py`, mirroring
`DocumentColumns`. Each concrete table gets its own copy of these columns; only
the target FK and the typed `line` column differ per table.

`DamageColumns`:

| column          | type                              | notes |
|-----------------|-----------------------------------|-------|
| `id`            | Integer PK, autoincrement         | |
| `size`          | `Enum(DamageSize)`, nullable      | optional; `NULL` = unspecified |
| `note`          | Text, nullable                    | optional free text |
| `created_at`    | DateTime(timezone=True), NOT NULL | |
| `created_by_id` | FK → `tenant.id`, NOT NULL        | who reported |
| `fixed_at`      | DateTime(timezone=True), nullable | **`NULL` = open**, non-NULL = fixed |
| `fixed_by_id`   | FK → `tenant.id`, nullable        | who fixed (cleared on reopen) |

`line` is **not** in the mixin — its enum type differs per table, so each
concrete table declares its own.

### Concrete tables

`cartei_db/models/room_damage.py` — `RoomDamage(DamageColumns, Base)`:
- `__tablename__ = "room_damage"`
- `room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), nullable=False)`
- `line: Mapped[RoomDamageLine] = mapped_column(SAEnum(RoomDamageLine), nullable=False)`

`cartei_db/models/wg_damage.py` — `WGDamage(DamageColumns, Base)`:
- `__tablename__ = "wg_damage"`
- `wg_id: Mapped[int] = mapped_column(ForeignKey("wg.id"), nullable=False)`
- `line: Mapped[WGDamageLine] = mapped_column(SAEnum(WGDamageLine), nullable=False)`

Re-export both in `models/__init__.py` (`__all__`).

**Not `Historized`.** The no-delete trigger plus `created_*`/`fixed_*` columns
are the audit story (consistent with the document tables, which are also not
`Historized`). Known ceiling: reopening a damage clears `fixed_by/fixed_at`, so
only the latest fix is retained, not a full fix/reopen history. Upgrade path:
inherit `Historized` if a full trail is ever needed.

### Enums — `cartei_db/enums.py`

```python
class DamageSize(str, Enum):
    LT1 = "LT1"   # < 1 cm
    MID = "MID"   # 1–5 cm
    GT  = "GT"    # > 5 cm

class RoomDamageLine(str, Enum):
    # surfaces
    BODEN_FLECKEN, BODEN_LOECHER
    FUSSLEISTE_FLECKEN
    WAND_FLECKEN, WAND_LOECHER, WAND_KLEBER
    TUER_FLECKEN, TUER_LOECHER
    FENSTER_RAHMEN_FLECKEN, FENSTER_BANK_FLECKEN, FENSTER_KLEBER
    # furniture
    BETT_FLECKEN, BETT_LOECHER
    MATRATZE_FLECKEN
    SCHREIBTISCH_FLECKEN, SCHREIBTISCH_LOECHER
    SCHRANK_FLECKEN, SCHRANK_LOECHER

class WGDamageLine(str, Enum):
    # common areas × surface defect
    KUECHE_BODEN_*, KUECHE_WAND_*, KUECHE_FENSTER_* ...
    BAD_BODEN_*, BAD_WAND_*, BAD_FENSTER_* ...
    FLUR_*, TREPPENHAUS_*, GEMEINSCHAFT_* ...
```

`RoomDamageLine` reuses the old room catalog verbatim. `WGDamageLine` is the
proposed common-area set. **Open item:** exact `WGDamageLine` values to be
finalized with the user during implementation (see Open Items). The two are
distinct enums / distinct Postgres enum types (`roomdamageline`,
`wgdamageline`, `damagesize`).

### No-delete trigger — `cartei_db/damage_triggers.py`

Parallel to `document_triggers.py`. One shared plpgsql function, one trigger
per damage table, applied to both `room_damage` and `wg_damage`. Fires for the
table owner too (unlike GRANT/RLS), so the invariant holds regardless of
connecting role.

```
CREATE FUNCTION damage_no_delete() RETURNS trigger:
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'damage rows may not be deleted; mark fixed instead';
    END IF;
    RETURN NEW;              -- all UPDATEs pass (fix, reopen, note edit)

CREATE TRIGGER <table>_no_delete
    BEFORE DELETE ON <table> FOR EACH ROW EXECUTE FUNCTION damage_no_delete();
```

Expose `damage_no_delete_sql(tables)` / `drop_damage_no_delete_sql(tables)`
helpers (used by both the migration and the test conftest), mirroring
`document_triggers.py`.

### Migration

One Alembic revision (`…_room_wg_damages`) chaining onto the current head
(`c5d6e7f8a9b0_drop_uebergabeprotokoll`). Creates the two enum types, both
tables, and the no-delete triggers. `downgrade()` drops triggers, tables, and
enum types.

## Django mirror + permissions — `CArtei`

### Mirror models (`app/models.py`, `managed = False`)

`RoomDamage`, `WGDamage` with `db_table` matching; FKs use
`on_delete=DO_NOTHING, db_constraint=False`. A shared abstract base
`DamageBase(models.Model)` (abstract, `managed = False`) can hold the common
fields to avoid duplication, mirroring the cartei_db mixin. `RoomDamageLine`,
`WGDamageLine`, `DamageSize` as `models.TextChoices`.

### Permission helper — `app/damages.py`

Single module centralizing the rules, so views and templates never re-derive
them:

- `STAFF_ROLES = {"werkstatt", "mietverwaltung", "admin"}`
- `can_view_damages(roles) -> bool` — staff.
- `is_room_resident(user, room, today)` / `is_wg_resident(user, wg, today)` —
  via `has_active_assignment` / `TenantRoomAssignment` on the target.
- `can_add_room_damage(user, roles, room)` = staff **or** room resident.
- `can_add_wg_damage(user, roles, wg)` = staff **or** WG resident.
- `can_fix_damage(roles)` = staff only.

Every view re-checks server-side against the **specific** target; residents are
scoped to their own room/WG (never a blanket `@require_group`).

### Views + routes (`app/views/damages.py`, `app/urls.py`)

| route | view | permission |
|-------|------|------------|
| `POST rooms/<room_pk>/damages/add/` | `add_room_damage` | staff or room resident |
| `POST wgs/<wg_pk>/damages/add/`      | `add_wg_damage`   | staff or WG resident |
| `POST damages/room/<pk>/fix/`        | `fix_room_damage` | staff (toggles fixed/reopen) |
| `POST damages/wg/<pk>/fix/`          | `fix_wg_damage`   | staff |

`fix` views set `fixed_at`/`fixed_by` (or clear them to reopen); they never
delete. Invalid `line` for the target type is rejected server-side (the two
`TextChoices` are the whitelist).

## UI surfaces

### `wg_detail.html` (staff)

Since rooms render as cards inside `wg_detail` and there is no separate room
page, staff manage everything here:
- A **WG-level** damages panel: list of `WGDamage` (open first, then fixed) with
  an add form and a per-row fixed/reopen toggle.
- A **per-room-card** damages list with add form + toggle, on each room card.
- Rendered only when `can_view_damages(roles)`. Belegium sees nothing.
- Add forms filter the catalog by target: room cards offer `RoomDamageLine`,
  the WG panel offers `WGDamageLine`. Size options gated per line kind (see
  below).

### `tenant_detail.html` (residents)

On the resident's own assignment card:
- "Schaden melden" for **their room** (`RoomDamageLine`) and **their WG**
  (`WGDamageLine`).
- A read-only list of open damages on that room / WG.
- No fixed/reopen control (staff-only).

### Size gating (form metadata, CArtei only)

Carried over from the old `DAMAGE_META` `kind`: a mapping `line → kind`
(`flecken` / `kleber` → offer LT1/MID/GT; `loecher` → offer LT1/GT). Size stays
optional. This lives in `app/damages.py`, not the DB.

## Testing

**cartei_db** (`tests/`, live Postgres):
- `damage_no_delete` trigger rejects `DELETE` on both tables; allows fix,
  reopen, and note edits.
- Enum round-trip for `RoomDamageLine`, `WGDamageLine`, `DamageSize`.
- `fixed_at IS NULL` = open semantics.

**CArtei** (`tests/`, pytest-django; reuse the `managed=False→managed`
conftest fixture):
- Permission matrix: staff (each of werkstatt/mietverwaltung/admin) vs resident
  vs belegium vs unrelated tenant, for view / add / fix on both target types.
- Resident scoping: resident of room A cannot add/view damages on room B or on
  a WG they don't live in.
- Mark-fixed is staff-only; residents get `PermissionDenied` / no-op.
- Add on both target types persists correct `line`/`size`/`note`/`created_by`.
- Fix sets `fixed_at`/`fixed_by`; reopen clears them.
- Invalid `line` for target rejected.

## Cross-repo coordination

Per the project's one rule (schema lives in `cartei_db` only):
1. `cartei_db`: models + enums + trigger module + autogenerated migration
   (reviewed), tests pass against live Postgres.
2. `CArtei`: mirror models (`managed=False`, matching `db_table`/columns),
   permission helper, views, routes, templates, tests. No Django migration for
   these domain tables.

## Open items (resolve during implementation)

1. **Exact `WGDamageLine` values.** Design proposes Küche / Bad / Flur /
   Treppenhaus / Gemeinschaftsfläche × surface defects; confirm the precise
   line list (and German labels) with the user before finalizing the enum.
2. Confirm resident capability once more if it changes: current decision is
   **add + view own, no fix**.
