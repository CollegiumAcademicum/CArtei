# Room & WG Damages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone damage tracker — damages opened against a room or a WG, typed from a catalog, marked fixed (never deleted), with role- and resident-scoped access.

**Architecture:** Schema lives in `cartei_db` (two tables `room_damage` / `wg_damage` sharing a `DamageColumns` mixin, three enums, a `damage_no_delete` DB trigger). `CArtei` mirrors the tables (`managed=False`), centralizes permissions in `app/damages.py`, exposes add/fix POST views, and renders one reusable `_damages.html` partial on the WG detail page (staff) and the tenant detail page (residents).

**Tech Stack:** Python 3.14, `uv`, SQLAlchemy 2.0 + Alembic (cartei_db), Django 5 (CArtei), pytest / pytest-django.

**Spec:** `CArtei/docs/superpowers/specs/2026-08-21-room-wg-damages-design.md`

## Global Constraints

- Schema source of truth is `cartei_db` only. CArtei models are `managed=False` mirrors; **no Django migration** for these domain tables.
- SQLAlchemy 2.0 declarative: `Mapped[...]` + `mapped_column(...)`, explicit type and `nullable=`. Tables singular snake_case, one model per file, re-exported in `models/__init__.py` `__all__`.
- Enums in `cartei_db/enums.py` (`str, Enum`). CArtei choices as `models.TextChoices`.
- FKs in CArtei mirrors: `on_delete=models.DO_NOTHING, db_constraint=False`.
- Damages are **never deleted**; the only lifecycle mutation is `fixed_at` set (fix) or cleared (reopen). Enforced by DB trigger firing for the table owner too.
- Permissions: **staff** = `werkstatt` ∪ `mietverwaltung` ∪ `admin` (view/add/fix, all targets); **residents** (active assignment to that room / living in that WG) = add + view **own** only, no fix; **belegium** = no access.
- cartei_db tests need live Postgres: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest`.
- Domain language German for domain concepts; code keywords English.
- Commit messages: plain, no signatures/trailers.

---

## File Structure

**cartei_db**
- Create `cartei_db/cartei_db/models/damage_base.py` — `DamageColumns` mixin (shared columns).
- Create `cartei_db/cartei_db/models/room_damage.py` — `RoomDamage`.
- Create `cartei_db/cartei_db/models/wg_damage.py` — `WGDamage`.
- Create `cartei_db/cartei_db/damage_triggers.py` — `damage_no_delete` SQL + helpers.
- Modify `cartei_db/cartei_db/enums.py` — add `DamageSize`, `RoomDamageLine`, `WGDamageLine`.
- Modify `cartei_db/cartei_db/models/__init__.py` — import + `__all__`.
- Modify `cartei_db/tests/conftest.py` — apply damage triggers in the engine fixture.
- Create `cartei_db/tests/test_models/test_damage.py` — model + trigger tests.
- Create `cartei_db/migrations/versions/<rev>_room_wg_damages.py` — migration.

**CArtei**
- Modify `CArtei/app/models.py` — `DamageSize`/`RoomDamageLine`/`WGDamageLine` TextChoices, `RoomDamage`, `WGDamage` mirrors.
- Create `CArtei/app/damages.py` — permission helpers + size-option metadata.
- Create `CArtei/app/views/damages.py` — add/fix views.
- Modify `CArtei/app/urls.py` — 4 routes.
- Create `CArtei/app/templates/app/_damages.html` — reusable damage list + add form.
- Modify `CArtei/app/views/rooms.py` (`wg_detail`) + `CArtei/app/templates/app/wg_detail.html` — staff panels.
- Modify `CArtei/app/views/tenant.py` (`tenant_detail`) + `CArtei/app/templates/app/tenant_detail.html` — resident surface.
- Tests: `CArtei/tests/test_damages_perms.py`, `CArtei/tests/test_damages_views.py`, `CArtei/tests/test_damages_ui.py`.

---

## Task 1: cartei_db enums

**Files:**
- Modify: `cartei_db/cartei_db/enums.py` (append at end)
- Test: `cartei_db/tests/test_enums.py` (append)

**Interfaces:**
- Produces: `DamageSize` (LT1/MID/GT), `RoomDamageLine` (18 values), `WGDamageLine` (12 values) — all `str, Enum`, consumed by Tasks 2–4 and mirrored in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `cartei_db/tests/test_enums.py`:

```python
from cartei_db.enums import DamageSize, RoomDamageLine, WGDamageLine


def test_damage_size_values():
    assert [s.value for s in DamageSize] == ["LT1", "MID", "GT"]


def test_room_damage_line_has_furniture_and_surfaces():
    vals = {l.value for l in RoomDamageLine}
    assert {"BODEN_FLECKEN", "WAND_KLEBER", "BETT_LOECHER", "SCHRANK_FLECKEN"} <= vals
    assert len(vals) == 18


def test_wg_damage_line_is_area_by_defect():
    vals = {l.value for l in WGDamageLine}
    assert {"BAD_FLECK", "KUECHE_LOCH", "GEMEINSCHAFT_KLEBER", "GEMEINSCHAFT_SONSTIGES"} <= vals
    assert len(vals) == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_enums.py -k damage -v`
Expected: FAIL with `ImportError` / `cannot import name 'DamageSize'`.

- [ ] **Step 3: Write minimal implementation**

Append to `cartei_db/cartei_db/enums.py`:

```python
class DamageSize(str, Enum):
    LT1 = "LT1"   # < 1 cm
    MID = "MID"   # 1–5 cm
    GT = "GT"     # > 5 cm


class RoomDamageLine(str, Enum):
    BODEN_FLECKEN = "BODEN_FLECKEN"
    BODEN_LOECHER = "BODEN_LOECHER"
    FUSSLEISTE_FLECKEN = "FUSSLEISTE_FLECKEN"
    WAND_FLECKEN = "WAND_FLECKEN"
    WAND_LOECHER = "WAND_LOECHER"
    WAND_KLEBER = "WAND_KLEBER"
    TUER_FLECKEN = "TUER_FLECKEN"
    TUER_LOECHER = "TUER_LOECHER"
    FENSTER_RAHMEN_FLECKEN = "FENSTER_RAHMEN_FLECKEN"
    FENSTER_BANK_FLECKEN = "FENSTER_BANK_FLECKEN"
    FENSTER_KLEBER = "FENSTER_KLEBER"
    BETT_FLECKEN = "BETT_FLECKEN"
    BETT_LOECHER = "BETT_LOECHER"
    MATRATZE_FLECKEN = "MATRATZE_FLECKEN"
    SCHREIBTISCH_FLECKEN = "SCHREIBTISCH_FLECKEN"
    SCHREIBTISCH_LOECHER = "SCHREIBTISCH_LOECHER"
    SCHRANK_FLECKEN = "SCHRANK_FLECKEN"
    SCHRANK_LOECHER = "SCHRANK_LOECHER"


class WGDamageLine(str, Enum):
    BAD_FLECK = "BAD_FLECK"
    BAD_LOCH = "BAD_LOCH"
    BAD_KLEBER = "BAD_KLEBER"
    BAD_SONSTIGES = "BAD_SONSTIGES"
    KUECHE_FLECK = "KUECHE_FLECK"
    KUECHE_LOCH = "KUECHE_LOCH"
    KUECHE_KLEBER = "KUECHE_KLEBER"
    KUECHE_SONSTIGES = "KUECHE_SONSTIGES"
    GEMEINSCHAFT_FLECK = "GEMEINSCHAFT_FLECK"
    GEMEINSCHAFT_LOCH = "GEMEINSCHAFT_LOCH"
    GEMEINSCHAFT_KLEBER = "GEMEINSCHAFT_KLEBER"
    GEMEINSCHAFT_SONSTIGES = "GEMEINSCHAFT_SONSTIGES"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_enums.py -k damage -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add cartei_db/enums.py tests/test_enums.py
git commit -m "Add damage enums (DamageSize, RoomDamageLine, WGDamageLine)"
```

---

## Task 2: DamageColumns mixin + RoomDamage / WGDamage models

**Files:**
- Create: `cartei_db/cartei_db/models/damage_base.py`
- Create: `cartei_db/cartei_db/models/room_damage.py`
- Create: `cartei_db/cartei_db/models/wg_damage.py`
- Modify: `cartei_db/cartei_db/models/__init__.py`
- Test: `cartei_db/tests/test_models/test_damage.py`

**Interfaces:**
- Consumes: `DamageSize`, `RoomDamageLine`, `WGDamageLine` (Task 1).
- Produces: `RoomDamage` (`__tablename__="room_damage"`, cols: id, room_id→room, line:RoomDamageLine, size:DamageSize?, note?, created_at, created_by_id→tenant, fixed_at?, fixed_by_id?→tenant) and `WGDamage` (same but `wg_id→wg`, line:WGDamageLine). `fixed_at IS NULL` = open.

- [ ] **Step 1: Write the failing test**

Create `cartei_db/tests/test_models/test_damage.py`:

```python
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from cartei_db.enums import RoomDamageLine, WGDamageLine, DamageSize
from cartei_db.models.building import Building
from cartei_db.models.wg import WG
from cartei_db.models.room import Room
from cartei_db.models.tenant import Tenant
from cartei_db.models.room_damage import RoomDamage
from cartei_db.models.wg_damage import WGDamage


@pytest.fixture
def fixtures(session):
    b = Building(name="Altbau")
    session.add(b)
    session.flush()
    wg = WG(building_id=b.id, name="WG 1")
    session.add(wg)
    session.flush()
    room = Room(wg_id=wg.id, name="1.01")
    session.add(room)
    t = Tenant(
        first_name="Da", last_name="Mage", email="d@example.com",
        intranet_username="dmage", intranet_uuid=uuid.uuid4(),
        is_flinta=False, barrier_free_needed=False,
        mailbox_list_opt_in=False, soli_miete_wunsch=Decimal("0"),
    )
    session.add(t)
    session.flush()
    return {"wg": wg, "room": room, "tenant": t}


def test_room_damage_opens_unfixed(session, fixtures):
    d = RoomDamage(
        room_id=fixtures["room"].id, line=RoomDamageLine.WAND_LOECHER,
        size=DamageSize.LT1, note="neben Fenster",
        created_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        created_by_id=fixtures["tenant"].id,
    )
    session.add(d)
    session.flush()
    fetched = session.get(RoomDamage, d.id)
    assert fetched.fixed_at is None
    assert fetched.line == RoomDamageLine.WAND_LOECHER


def test_wg_damage_persists(session, fixtures):
    d = WGDamage(
        wg_id=fixtures["wg"].id, line=WGDamageLine.BAD_FLECK,
        created_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        created_by_id=fixtures["tenant"].id,
    )
    session.add(d)
    session.flush()
    assert session.get(WGDamage, d.id).size is None
```

Note: check `WG`/`Room`/`Building` constructor kwargs against their model files (`cartei_db/models/wg.py`, `room.py`, `building.py`) and adjust the fixture if column names differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_models/test_damage.py -v`
Expected: FAIL with `ModuleNotFoundError: cartei_db.models.room_damage`.

- [ ] **Step 3: Write minimal implementation**

Create `cartei_db/cartei_db/models/damage_base.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column


class DamageColumns:
    """Shared columns for the damage tables (room_damage, wg_damage). A
    declarative mixin so each concrete table gets its own copy; the target FK
    and the typed `line` column are declared per table. A damage is open while
    fixed_at IS NULL. Rows are never deleted (see damage_triggers.py); the only
    lifecycle mutation is setting fixed_at (fix) or clearing it (reopen)."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    size: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    fixed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fixed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tenant.id"), nullable=True)
```

Note: `size` is declared here as generic `Text` so the mixin stays enum-agnostic; each concrete model overrides it with its typed `SAEnum(DamageSize)` column below (SQLAlchemy uses the subclass's column). If overriding a mixin column is awkward in review, instead move `size` out of the mixin and declare it on each concrete model — both models use the same `SAEnum(DamageSize)`.

Create `cartei_db/cartei_db/models/room_damage.py`:

```python
from typing import Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from cartei_db.base import Base
from cartei_db.enums import DamageSize, RoomDamageLine
from cartei_db.models.damage_base import DamageColumns


class RoomDamage(DamageColumns, Base):
    __tablename__ = "room_damage"

    room_id: Mapped[int] = mapped_column(ForeignKey("room.id"), nullable=False)
    line: Mapped[RoomDamageLine] = mapped_column(SAEnum(RoomDamageLine), nullable=False)
    size: Mapped[Optional[DamageSize]] = mapped_column(SAEnum(DamageSize), nullable=True)
```

Create `cartei_db/cartei_db/models/wg_damage.py`:

```python
from typing import Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from cartei_db.base import Base
from cartei_db.enums import DamageSize, WGDamageLine
from cartei_db.models.damage_base import DamageColumns


class WGDamage(DamageColumns, Base):
    __tablename__ = "wg_damage"

    wg_id: Mapped[int] = mapped_column(ForeignKey("wg.id"), nullable=False)
    line: Mapped[WGDamageLine] = mapped_column(SAEnum(WGDamageLine), nullable=False)
    size: Mapped[Optional[DamageSize]] = mapped_column(SAEnum(DamageSize), nullable=True)
```

Add to `cartei_db/cartei_db/models/__init__.py` (import block + `__all__`):

```python
from cartei_db.models.room_damage import RoomDamage
from cartei_db.models.wg_damage import WGDamage
```
and append `"RoomDamage", "WGDamage",` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_models/test_damage.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add cartei_db/models/damage_base.py cartei_db/models/room_damage.py cartei_db/models/wg_damage.py cartei_db/models/__init__.py tests/test_models/test_damage.py
git commit -m "Add RoomDamage / WGDamage models with shared DamageColumns mixin"
```

---

## Task 3: `damage_no_delete` trigger + conftest wiring

**Files:**
- Create: `cartei_db/cartei_db/damage_triggers.py`
- Modify: `cartei_db/tests/conftest.py` (engine fixture)
- Test: `cartei_db/tests/test_models/test_damage.py` (append)

**Interfaces:**
- Consumes: `RoomDamage`, `WGDamage` (Task 2).
- Produces: `damage_no_delete_sql(tables=DAMAGE_TABLES) -> list[str]`, `drop_damage_no_delete_sql(tables=DAMAGE_TABLES) -> list[str]`, `DAMAGE_TABLES = ("room_damage", "wg_damage")`. Used by Task 4 migration and the test conftest.

- [ ] **Step 1: Write the failing test**

Append to `cartei_db/tests/test_models/test_damage.py`:

```python
from datetime import datetime as _dt
from sqlalchemy.exc import DBAPIError


def _open_room_damage(session, fixtures):
    d = RoomDamage(
        room_id=fixtures["room"].id, line=RoomDamageLine.BODEN_FLECKEN,
        created_at=_dt(2026, 8, 22, tzinfo=timezone.utc),
        created_by_id=fixtures["tenant"].id,
    )
    session.add(d)
    session.flush()
    return d


def test_delete_is_rejected(session, fixtures):
    d = _open_room_damage(session, fixtures)
    session.delete(d)
    with pytest.raises(DBAPIError):
        session.flush()


def test_fix_and_reopen_are_allowed(session, fixtures):
    d = _open_room_damage(session, fixtures)
    d.fixed_at = _dt(2026, 8, 23, tzinfo=timezone.utc)
    d.fixed_by_id = fixtures["tenant"].id
    session.flush()
    assert session.get(RoomDamage, d.id).fixed_at is not None
    # reopen
    d.fixed_at = None
    d.fixed_by_id = None
    session.flush()
    assert session.get(RoomDamage, d.id).fixed_at is None


def test_note_edit_is_allowed(session, fixtures):
    d = _open_room_damage(session, fixtures)
    d.note = "Nachtrag"
    session.flush()
    assert session.get(RoomDamage, d.id).note == "Nachtrag"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_models/test_damage.py -k "delete or reopen or note_edit" -v`
Expected: `test_delete_is_rejected` FAILS (no trigger yet → delete succeeds, `DBAPIError` not raised).

- [ ] **Step 3: Write minimal implementation**

Create `cartei_db/cartei_db/damage_triggers.py`:

```python
"""No-delete enforcement for the damage tables (room_damage, wg_damage).

A damage row may never be deleted; the only lifecycle mutation is marking it
fixed (set fixed_at) or reopening it (clear fixed_at), plus ordinary note/size
edits — all UPDATEs pass. The trigger fires for the table owner too (unlike
GRANTs/RLS), so the invariant holds regardless of connecting role. SQL is shared
by the Alembic migration and the test conftest."""

DAMAGE_TABLES = ("room_damage", "wg_damage")

_FUNCTION = """
CREATE OR REPLACE FUNCTION damage_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'damage rows may not be deleted; mark fixed instead';
END;
$$ LANGUAGE plpgsql;
"""


def _trigger_sql(table: str) -> str:
    return (
        f"CREATE OR REPLACE TRIGGER {table}_no_delete "
        f"BEFORE DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION damage_no_delete();"
    )


def damage_no_delete_sql(tables: tuple[str, ...] = DAMAGE_TABLES) -> list[str]:
    return [_FUNCTION] + [_trigger_sql(t) for t in tables]


def drop_damage_no_delete_sql(tables: tuple[str, ...] = DAMAGE_TABLES) -> list[str]:
    return [f"DROP TRIGGER IF EXISTS {t}_no_delete ON {t}" for t in tables] + [
        "DROP FUNCTION IF EXISTS damage_no_delete()"
    ]
```

Modify `cartei_db/tests/conftest.py` — inside the `engine` fixture's `with eng.begin() as conn:` block, after the existing `document_append_only_sql` loop, add:

```python
        from cartei_db.damage_triggers import damage_no_delete_sql
        for stmt in damage_no_delete_sql():
            conn.execute(text(stmt))
```

And in the teardown (after `Base.metadata.drop_all(eng)`), the function is dropped with the tables; add to the existing teardown `with eng.begin() as conn:` block:

```python
        conn.execute(text("DROP FUNCTION IF EXISTS damage_no_delete() CASCADE"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_models/test_damage.py -v`
Expected: PASS (all damage tests, including delete rejected, fix/reopen allowed, note edit allowed).

- [ ] **Step 5: Commit**

```bash
git add cartei_db/damage_triggers.py tests/conftest.py tests/test_models/test_damage.py
git commit -m "Add damage_no_delete trigger; wire into test conftest"
```

---

## Task 4: Alembic migration

**Files:**
- Create: `cartei_db/migrations/versions/<rev>_room_wg_damages.py` (via autogenerate, then hand-edit)

**Interfaces:**
- Consumes: models (Task 2), `damage_no_delete_sql` / `drop_damage_no_delete_sql` (Task 3).
- Produces: a migration chaining onto head `c5d6e7f8a9b0`; creates enum types `roomdamageline`, `wgdamageline`, `damagesize`, tables `room_damage` / `wg_damage`, and the no-delete triggers.

- [ ] **Step 1: Generate the migration**

Run:
```bash
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic revision --autogenerate -m "room wg damages"
```
Expected: a new file in `migrations/versions/` creating both tables + enums. `down_revision` should be `c5d6e7f8a9b0`. If it is not, set it manually to `'c5d6e7f8a9b0'`.

- [ ] **Step 2: Hand-edit — add triggers to the migration**

At the top of the generated file add:
```python
from cartei_db.damage_triggers import damage_no_delete_sql, drop_damage_no_delete_sql
```
At the **end of `upgrade()`** (after both `op.create_table(...)` calls):
```python
    for stmt in damage_no_delete_sql():
        op.execute(stmt)
```
At the **start of `downgrade()`** (before the `op.drop_table(...)` calls):
```python
    for stmt in drop_damage_no_delete_sql():
        op.execute(stmt)
```
Verify `downgrade()` also drops the enum types (autogenerate usually emits `sa.Enum(name='...').drop(op.get_bind())` for each; if missing, add them for `roomdamageline`, `wgdamageline`, `damagesize`).

- [ ] **Step 3: Apply and verify round-trip**

Run:
```bash
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic downgrade -1
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic upgrade head
```
Expected: all three succeed; `alembic heads` shows a single head (the new revision).

- [ ] **Step 4: Confirm autogenerate is now clean**

Run:
```bash
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic revision --autogenerate -m "should be empty" 2>&1 | tail -20
```
Expected: an empty migration (no table/column diffs). **Delete** that throwaway empty file afterwards.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/
git commit -m "Add migration for room_damage / wg_damage tables + triggers"
```

---

## Task 5: CArtei mirror models

**Files:**
- Modify: `CArtei/app/models.py` (append at end)
- Test: `CArtei/tests/test_damages_perms.py` (create file with a smoke test first)

**Interfaces:**
- Consumes: DB tables (Task 4).
- Produces: `RoomDamageLine`, `WGDamageLine`, `DamageSize` (`TextChoices`); `RoomDamage` (fields: `room`→Room, `line`, `size`, `note`, `created_at`, `created_by`→Tenant, `fixed_at`, `fixed_by`→Tenant; `db_table="room_damage"`), `WGDamage` (`wg`→WG, same tracking fields; `db_table="wg_damage"`). Consumed by Tasks 6–9.

- [ ] **Step 1: Write the failing test**

Create `CArtei/tests/test_damages_perms.py`:

```python
import pytest
from datetime import date

from app.models import (
    Building, WG, Room, Tenant, RoomDamage, WGDamage,
    RoomDamageLine, WGDamageLine, DamageSize,
)


@pytest.mark.django_db
def test_room_damage_round_trip():
    b = Building.objects.create(name="Altbau")
    wg = WG.objects.create(building=b, name="WG 1")
    room = Room.objects.create(wg=wg, name="1.01")
    t = Tenant.objects.create(first_name="Da", last_name="Mage", intranet_username="dmage")
    d = RoomDamage.objects.create(
        room=room, line=RoomDamageLine.WAND_LOECHER, size=DamageSize.LT1,
        note="x", created_at="2026-08-22T00:00:00Z", created_by=t,
    )
    assert d.fixed_at is None
    assert RoomDamage.objects.get(pk=d.pk).line == RoomDamageLine.WAND_LOECHER
```

Note: confirm `Building`/`WG`/`Room`/`Tenant` required fields from `app/models.py` and adjust `create(...)` kwargs if needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_damages_perms.py -v`
Expected: FAIL with `ImportError: cannot import name 'RoomDamage'`.

- [ ] **Step 3: Write minimal implementation**

Append to `CArtei/app/models.py`:

```python
class DamageSize(models.TextChoices):
    LT1 = "LT1", "< 1 cm"
    MID = "MID", "1–5 cm"
    GT = "GT", "> 5 cm"


class RoomDamageLine(models.TextChoices):
    BODEN_FLECKEN = "BODEN_FLECKEN", "Boden – Flecken"
    BODEN_LOECHER = "BODEN_LOECHER", "Boden – Löcher"
    FUSSLEISTE_FLECKEN = "FUSSLEISTE_FLECKEN", "Fußleiste – Flecken"
    WAND_FLECKEN = "WAND_FLECKEN", "Wände – Flecken"
    WAND_LOECHER = "WAND_LOECHER", "Wände – Löcher"
    WAND_KLEBER = "WAND_KLEBER", "Wände – Kleberückstände"
    TUER_FLECKEN = "TUER_FLECKEN", "Tür – Flecken"
    TUER_LOECHER = "TUER_LOECHER", "Tür – Löcher"
    FENSTER_RAHMEN_FLECKEN = "FENSTER_RAHMEN_FLECKEN", "Fenster – Flecken Rahmen"
    FENSTER_BANK_FLECKEN = "FENSTER_BANK_FLECKEN", "Fenster – Flecken Fensterbank"
    FENSTER_KLEBER = "FENSTER_KLEBER", "Fenster – Kleberückstände"
    BETT_FLECKEN = "BETT_FLECKEN", "Bett – Flecken"
    BETT_LOECHER = "BETT_LOECHER", "Bett – Löcher"
    MATRATZE_FLECKEN = "MATRATZE_FLECKEN", "Matratze – Flecken"
    SCHREIBTISCH_FLECKEN = "SCHREIBTISCH_FLECKEN", "Schreibtisch – Flecken"
    SCHREIBTISCH_LOECHER = "SCHREIBTISCH_LOECHER", "Schreibtisch – Löcher"
    SCHRANK_FLECKEN = "SCHRANK_FLECKEN", "Schrank – Flecken"
    SCHRANK_LOECHER = "SCHRANK_LOECHER", "Schrank – Löcher"


class WGDamageLine(models.TextChoices):
    BAD_FLECK = "BAD_FLECK", "Bad – Fleck"
    BAD_LOCH = "BAD_LOCH", "Bad – Loch"
    BAD_KLEBER = "BAD_KLEBER", "Bad – Kleberückstände"
    BAD_SONSTIGES = "BAD_SONSTIGES", "Bad – Sonstiges"
    KUECHE_FLECK = "KUECHE_FLECK", "Küche – Fleck"
    KUECHE_LOCH = "KUECHE_LOCH", "Küche – Loch"
    KUECHE_KLEBER = "KUECHE_KLEBER", "Küche – Kleberückstände"
    KUECHE_SONSTIGES = "KUECHE_SONSTIGES", "Küche – Sonstiges"
    GEMEINSCHAFT_FLECK = "GEMEINSCHAFT_FLECK", "Gemeinschaftsfläche – Fleck"
    GEMEINSCHAFT_LOCH = "GEMEINSCHAFT_LOCH", "Gemeinschaftsfläche – Loch"
    GEMEINSCHAFT_KLEBER = "GEMEINSCHAFT_KLEBER", "Gemeinschaftsfläche – Kleberückstände"
    GEMEINSCHAFT_SONSTIGES = "GEMEINSCHAFT_SONSTIGES", "Gemeinschaftsfläche – Sonstiges"


class DamageBase(models.Model):
    size = models.CharField(max_length=8, choices=DamageSize.choices, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()
    created_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="+", db_column="created_by_id",
    )
    fixed_at = models.DateTimeField(null=True, blank=True)
    fixed_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name="+", db_column="fixed_by_id",
    )

    class Meta:
        abstract = True
        managed = False

    @property
    def is_open(self):
        return self.fixed_at is None


class RoomDamage(DamageBase):
    room = models.ForeignKey(
        Room, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="damages", db_column="room_id",
    )
    line = models.CharField(max_length=32, choices=RoomDamageLine.choices)

    class Meta:
        managed = False
        db_table = "room_damage"


class WGDamage(DamageBase):
    wg = models.ForeignKey(
        WG, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="damages", db_column="wg_id",
    )
    line = models.CharField(max_length=32, choices=WGDamageLine.choices)

    class Meta:
        managed = False
        db_table = "wg_damage"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_damages_perms.py -v`
Expected: PASS. (The conftest `django_db_setup` fixture flips these `managed=False` models to managed so SQLite builds them.)

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_damages_perms.py
git commit -m "Mirror RoomDamage / WGDamage models + damage TextChoices"
```

---

## Task 6: Permission helpers + size metadata (`app/damages.py`)

**Files:**
- Create: `CArtei/app/damages.py`
- Test: `CArtei/tests/test_damages_perms.py` (append)

**Interfaces:**
- Consumes: `global_roles` (`app.tenant_access`), `active_assignment_q` (`app.residency`), `TenantRoomAssignment`, `RoomDamageLine`, `WGDamageLine`, `DamageSize` (Task 5).
- Produces:
  - `STAFF_ROLES = {"werkstatt", "mietverwaltung", "admin"}`
  - `can_view_damages(roles: set[str]) -> bool`
  - `can_fix_damage(roles: set[str]) -> bool`
  - `author_for(user) -> Tenant | None`
  - `is_room_resident(tenant, room_id, today) -> bool`
  - `is_wg_resident(tenant, wg_id, today) -> bool`
  - `can_add_room_damage(user, roles, room_id, today) -> bool`
  - `can_add_wg_damage(user, roles, wg_id, today) -> bool`
  - `size_options(line: str) -> list[DamageSize]` (holes → LT1/GT; else all three)

- [ ] **Step 1: Write the failing test**

Append to `CArtei/tests/test_damages_perms.py`:

```python
from app import damages
from app.models import TenantRoomAssignment, RoomDamageLine


def test_role_gates():
    assert damages.can_view_damages({"werkstatt"})
    assert damages.can_view_damages({"mietverwaltung"})
    assert damages.can_view_damages({"admin"})
    assert not damages.can_view_damages({"belegium"})
    assert not damages.can_view_damages({"public"})
    assert damages.can_fix_damage({"admin"})
    assert not damages.can_fix_damage({"werkstatt", "belegium"} - {"werkstatt"})


@pytest.mark.django_db
def test_resident_scoping():
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01")
    other = Room.objects.create(wg=wg, name="1.02")
    t = Tenant.objects.create(first_name="R", last_name="es", intranet_username="res")
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2026, 1, 1))
    today = date(2026, 8, 22)
    assert damages.is_room_resident(t, room.id, today)
    assert not damages.is_room_resident(t, other.id, today)
    assert damages.is_wg_resident(t, wg.id, today)


def test_size_options():
    assert damages.size_options(RoomDamageLine.WAND_LOECHER) == [DamageSize.LT1, DamageSize.GT]
    assert damages.size_options(RoomDamageLine.WAND_FLECKEN) == [DamageSize.LT1, DamageSize.MID, DamageSize.GT]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_damages_perms.py -k "role_gates or resident_scoping or size_options" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.damages'`.

- [ ] **Step 3: Write minimal implementation**

Create `CArtei/app/damages.py`:

```python
"""Central permission + catalog rules for room/WG damages, so views and
templates never re-derive them. Staff (werkstatt/mietverwaltung/admin) manage
all damages; residents may add + view damages on their own room/WG only and may
not mark them fixed; belegium has no access."""
from app.models import Tenant, TenantRoomAssignment, DamageSize
from app.residency import active_assignment_q

STAFF_ROLES = {"werkstatt", "mietverwaltung", "admin"}


def can_view_damages(roles: set[str]) -> bool:
    return bool(STAFF_ROLES & roles)


def can_fix_damage(roles: set[str]) -> bool:
    return bool(STAFF_ROLES & roles)


def author_for(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


def is_room_resident(tenant, room_id, today) -> bool:
    if tenant is None:
        return False
    return (
        TenantRoomAssignment.objects.filter(tenant=tenant, room_id=room_id)
        .filter(active_assignment_q(today)).exists()
    )


def is_wg_resident(tenant, wg_id, today) -> bool:
    if tenant is None:
        return False
    return (
        TenantRoomAssignment.objects.filter(tenant=tenant, room__wg_id=wg_id)
        .filter(active_assignment_q(today)).exists()
    )


def can_add_room_damage(user, roles, room_id, today) -> bool:
    if STAFF_ROLES & roles:
        return True
    return is_room_resident(author_for(user), room_id, today)


def can_add_wg_damage(user, roles, wg_id, today) -> bool:
    if STAFF_ROLES & roles:
        return True
    return is_wg_resident(author_for(user), wg_id, today)


def size_options(line: str) -> list:
    """Holes take only two sizes (<1 cm / >1 cm); stains/kleber/sonstiges take
    all three. Size stays optional in the form."""
    if line.endswith("LOECHER") or line.endswith("LOCH"):
        return [DamageSize.LT1, DamageSize.GT]
    return [DamageSize.LT1, DamageSize.MID, DamageSize.GT]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_damages_perms.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/damages.py tests/test_damages_perms.py
git commit -m "Add damages permission helpers + size-option metadata"
```

---

## Task 7: Add/fix views + routes

**Files:**
- Create: `CArtei/app/views/damages.py`
- Modify: `CArtei/app/urls.py`
- Test: `CArtei/tests/test_damages_views.py`

**Interfaces:**
- Consumes: `app.damages` helpers (Task 6), models (Task 5), `global_roles`.
- Produces routes (names): `room_damage_add`, `wg_damage_add`, `room_damage_fix`, `wg_damage_fix`. Add/fix are `POST`-only, redirect to `next`.

- [ ] **Step 1: Write the failing test**

Create `CArtei/tests/test_damages_views.py`:

```python
import pytest
from datetime import date
from django.contrib.auth.models import User, Group
from django.utils.timezone import now

from app.models import (
    Building, WG, Room, Tenant, TenantRoomAssignment,
    RoomDamage, WGDamage, RoomDamageLine, WGDamageLine,
)


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01")
    return {"wg": wg, "room": room}


def _login(client, username, group=None):
    u = User.objects.create_user(username=username, password="x")
    if group:
        g, _ = Group.objects.get_or_create(name=group)
        u.groups.add(g)
    Tenant.objects.create(first_name=username, last_name="T", intranet_username=username)
    client.force_login(u)
    return u


def test_staff_add_room_damage(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.WAND_LOECHER, "size": "LT1", "note": "x", "next": "/"},
    )
    assert r.status_code == 302
    assert RoomDamage.objects.filter(room=world["room"], line=RoomDamageLine.WAND_LOECHER).count() == 1


def test_resident_add_own_room(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/"},
    )
    assert r.status_code == 302
    assert RoomDamage.objects.filter(room=world["room"]).count() == 1


def test_nonresident_add_denied(client, world):
    _login(client, "stranger")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/"},
    )
    assert r.status_code == 403
    assert RoomDamage.objects.count() == 0


def test_belegium_add_denied(client, world):
    _login(client, "beleg", "gr.belegium")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": RoomDamageLine.BODEN_FLECKEN, "next": "/"},
    )
    assert r.status_code == 403


def test_invalid_line_rejected(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.post(
        f"/rooms/{world['room'].id}/damages/add/",
        {"line": "NOT_A_LINE", "next": "/"},
    )
    assert r.status_code == 403
    assert RoomDamage.objects.count() == 0


def test_fix_and_reopen_staff_only(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    d = RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN, created_at=now(), created_by=t,
    )
    # resident cannot fix
    r = client.post(f"/damages/room/{d.id}/fix/", {"next": "/"})
    assert r.status_code == 403
    assert RoomDamage.objects.get(pk=d.id).fixed_at is None
    # staff can fix, then reopen
    _login(client, "cartei_mietverwaltung", "cartei_mietverwaltung")
    client.post(f"/damages/room/{d.id}/fix/", {"next": "/"})
    assert RoomDamage.objects.get(pk=d.id).fixed_at is not None
    client.post(f"/damages/room/{d.id}/fix/", {"next": "/"})
    assert RoomDamage.objects.get(pk=d.id).fixed_at is None
```

Note: the group→role mapping comes from `settings_test.py` `TENANT_ROLE_GROUPS`; `cartei_werkstatt`→werkstatt, `cartei_mietverwaltung`→mietverwaltung, `gr.belegium`→belegium already exist there. Confirm and add any missing mapping to `settings_test.py` if a test login yields no role.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_damages_views.py -v`
Expected: FAIL (404s — routes don't exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `CArtei/app/views/damages.py`:

```python
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app import damages as perms
from app.models import (
    Room, WG, RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, DamageSize,
)
from app.tenant_access import global_roles


def _clean_size(raw):
    return raw if raw in DamageSize.values else None


def _add(request, *, model, target_kwarg, target_id, line_choices, allowed):
    roles = global_roles(request.user)
    if not allowed(request.user, roles, target_id, date.today()):
        raise PermissionDenied
    author = perms.author_for(request.user)
    if author is None:
        raise PermissionDenied
    line = request.POST.get("line", "")
    if line not in line_choices.values:
        raise PermissionDenied
    model.objects.create(
        **{target_kwarg: target_id},
        line=line,
        size=_clean_size(request.POST.get("size", "")),
        note=(request.POST.get("note", "").strip() or None),
        created_at=now(),
        created_by=author,
    )
    return redirect(request.POST.get("next", "/"))


@login_required
@require_POST
def room_damage_add(request, room_pk):
    get_object_or_404(Room, pk=room_pk)
    return _add(
        request, model=RoomDamage, target_kwarg="room_id", target_id=room_pk,
        line_choices=RoomDamageLine, allowed=perms.can_add_room_damage,
    )


@login_required
@require_POST
def wg_damage_add(request, wg_pk):
    get_object_or_404(WG, pk=wg_pk)
    return _add(
        request, model=WGDamage, target_kwarg="wg_id", target_id=wg_pk,
        line_choices=WGDamageLine, allowed=perms.can_add_wg_damage,
    )


def _fix(request, model, pk):
    if not perms.can_fix_damage(global_roles(request.user)):
        raise PermissionDenied
    author = perms.author_for(request.user)
    if author is None:
        raise PermissionDenied
    d = get_object_or_404(model, pk=pk)
    if d.fixed_at is None:
        model.objects.filter(pk=pk).update(fixed_at=now(), fixed_by=author)
    else:
        model.objects.filter(pk=pk).update(fixed_at=None, fixed_by=None)
    return redirect(request.POST.get("next", "/"))


@login_required
@require_POST
def room_damage_fix(request, pk):
    return _fix(request, RoomDamage, pk)


@login_required
@require_POST
def wg_damage_fix(request, pk):
    return _fix(request, WGDamage, pk)
```

Modify `CArtei/app/urls.py` — add `damages` to the `from app.views import ...` line, and add these routes to `urlpatterns`:

```python
    path("rooms/<int:room_pk>/damages/add/", damages.room_damage_add, name="room_damage_add"),
    path("wgs/<int:wg_pk>/damages/add/", damages.wg_damage_add, name="wg_damage_add"),
    path("damages/room/<int:pk>/fix/", damages.room_damage_fix, name="room_damage_fix"),
    path("damages/wg/<int:pk>/fix/", damages.wg_damage_fix, name="wg_damage_fix"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_damages_views.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add app/views/damages.py app/urls.py tests/test_damages_views.py
git commit -m "Add room/WG damage add + fix views and routes"
```

---

## Task 8: `wg_detail` staff panels

**Files:**
- Create: `CArtei/app/templates/app/_damages.html`
- Modify: `CArtei/app/views/rooms.py` (`wg_detail`, ~lines 116–261)
- Modify: `CArtei/app/templates/app/wg_detail.html`
- Test: `CArtei/tests/test_damages_ui.py`

**Interfaces:**
- Consumes: models + `app.damages` (Tasks 5–6), routes (Task 7).
- Produces: reusable partial `app/_damages.html` expecting context vars `damages` (iterable of damage rows), `add_url` (resolved URL string), `lines` (list of `(value, label)`), `sizes` (list of `(value, label)`), `can_fix` (bool), `next` (string). Consumed again by Task 9.

- [ ] **Step 1: Write the failing test**

Create `CArtei/tests/test_damages_ui.py`:

```python
import pytest
from datetime import date
from django.contrib.auth.models import User, Group

from app.models import Building, WG, Room, Tenant, RoomDamage, WGDamage, RoomDamageLine


def _login(client, username, group=None):
    u = User.objects.create_user(username=username, password="x")
    if group:
        g, _ = Group.objects.get_or_create(name=group)
        u.groups.add(g)
    Tenant.objects.create(first_name=username, last_name="T", intranet_username=username)
    client.force_login(u)
    return u


@pytest.fixture
def world(db):
    b = Building.objects.create(name="B")
    wg = WG.objects.create(building=b, name="W")
    room = Room.objects.create(wg=wg, name="1.01")
    return {"wg": wg, "room": room}


def test_staff_sees_damage_panels(client, world):
    _login(client, "cartei_werkstatt", "cartei_werkstatt")
    r = client.get(f"/wgs/{world['wg'].id}/")
    assert r.status_code == 200
    assert b"Sch\xc3\xa4den" in r.content  # "Schäden" heading present


def test_belegium_sees_no_damage_panels(client, world):
    _login(client, "beleg", "gr.belegium")
    r = client.get(f"/wgs/{world['wg'].id}/")
    assert r.status_code == 200
    assert b"damages/add" not in r.content  # no add form action rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_damages_ui.py -k wg -v`
Expected: `test_staff_sees_damage_panels` FAILS (no "Schäden" panel yet). If `world` fixture / group mapping needs `settings_test.py` entries, add them.

- [ ] **Step 3: Write minimal implementation**

Create `CArtei/app/templates/app/_damages.html`:

```django
{% comment %} Reusable damage list + add form. Context: damages, add_url, lines,
sizes, can_fix, next. Read-only list when can_fix is false and no add_url. {% endcomment %}
<div class="ca-damages">
  <p style="font-weight:500;margin:.4rem 0 .25rem;">Schäden</p>
  {% for d in damages %}
    <div style="font-size:.9rem;margin:.15rem 0;{% if not d.is_open %}color:#888;{% endif %}">
      {{ d.get_line_display }}{% if d.size %} ({{ d.get_size_display }}){% endif %}{% if d.note %} — {{ d.note }}{% endif %}
      {% if d.is_open %}<span style="color:#b00;">· offen</span>{% else %}<span>· behoben</span>{% endif %}
      {% if can_fix %}
        <form method="post" action="{% if d.wg_id %}{% url 'wg_damage_fix' d.pk %}{% else %}{% url 'room_damage_fix' d.pk %}{% endif %}" style="display:inline;">
          {% csrf_token %}<input type="hidden" name="next" value="{{ next }}">
          <button type="submit" class="ca-link-btn">{% if d.is_open %}als behoben markieren{% else %}wieder öffnen{% endif %}</button>
        </form>
      {% endif %}
    </div>
  {% empty %}
    <p style="color:#888;font-size:.85rem;margin:.15rem 0;">Keine Schäden erfasst.</p>
  {% endfor %}
  {% if add_url %}
    <form method="post" action="{{ add_url }}" style="margin-top:.3rem;">
      {% csrf_token %}<input type="hidden" name="next" value="{{ next }}">
      <select name="line" required>
        {% for value, label in lines %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
      </select>
      <select name="size">
        <option value="">– Größe –</option>
        {% for value, label in sizes %}<option value="{{ value }}">{{ label }}</option>{% endfor %}
      </select>
      <input type="text" name="note" placeholder="Notiz (optional)" maxlength="500">
      <button type="submit">Schaden erfassen</button>
    </form>
  {% endif %}
</div>
```

Modify `wg_detail` in `CArtei/app/views/rooms.py`. Add imports at top:
```python
from app.models import RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, DamageSize
from app.damages import can_view_damages
```
Inside `wg_detail`, after `roles = global_roles(request.user)`:
```python
    show_damages = can_view_damages(roles)
```
When building each room's card data (where `a.doc_groups` etc. are attached, in the per-room loop), attach open-first damages to the room:
```python
        if show_damages:
            room.damage_list = list(
                RoomDamage.objects.filter(room=room).order_by("fixed_at", "-created_at")
            )
```
Before `return render(...)`, attach WG-level damages and catalogs to context:
```python
    wg_damage_list = (
        list(WGDamage.objects.filter(wg=wg).order_by("fixed_at", "-created_at"))
        if show_damages else []
    )
```
Add to the `render(...)` context dict:
```python
        "show_damages": show_damages,
        "wg_damage_list": wg_damage_list,
        "room_damage_lines": RoomDamageLine.choices,
        "wg_damage_lines": WGDamageLine.choices,
        "damage_sizes": DamageSize.choices,
```

Modify `CArtei/app/templates/app/wg_detail.html`. At the WG level (near the top of the WG block, after the WG heading) add — resolve the add URL into a variable first (`{% url %}` needs the pk), then include:
```django
{% if show_damages %}
  {% url 'wg_damage_add' wg.id as wg_add_url %}
  {% include "app/_damages.html" with damages=wg_damage_list add_url=wg_add_url lines=wg_damage_lines sizes=damage_sizes can_fix=True next=request.path %}
{% endif %}
```
Inside each room card (the `{% for c in r.cards %}` / room rendering block), add:
```django
{% if show_damages %}
  {% url 'room_damage_add' r.room.id as room_add_url %}
  {% include "app/_damages.html" with damages=r.room.damage_list add_url=room_add_url lines=room_damage_lines sizes=damage_sizes can_fix=True next=request.path %}
{% endif %}
```
Confirm the room loop variable name (`r.room` vs `room`) against the existing template and match it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_damages_ui.py -k wg -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/app/_damages.html app/views/rooms.py app/templates/app/wg_detail.html tests/test_damages_ui.py
git commit -m "Show damage panels on WG detail for staff"
```

---

## Task 9: `tenant_detail` resident surface

**Files:**
- Modify: `CArtei/app/views/tenant.py` (`tenant_detail`, ~lines 310–440)
- Modify: `CArtei/app/templates/app/tenant_detail.html` (assignment card area, ~lines 79–94)
- Test: `CArtei/tests/test_damages_ui.py` (append)

**Interfaces:**
- Consumes: `_damages.html` partial (Task 8), models + `app.damages` (Tasks 5–6), routes (Task 7).
- Produces: on the resident's own assignment card, a room add-form + a WG add-form and read-only open-damage lists (no fix control).

- [ ] **Step 1: Write the failing test**

Append to `CArtei/tests/test_damages_ui.py`:

```python
from app.models import TenantRoomAssignment


def test_resident_sees_report_form_on_own_card(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    r = client.get(f"/tenants/{t.id}/")
    assert r.status_code == 200
    assert f"/rooms/{world['room'].id}/damages/add/".encode() in r.content
    assert f"/wgs/{world['wg'].id}/damages/add/".encode() in r.content


def test_resident_has_no_fix_button(client, world):
    u = _login(client, "resi")
    t = Tenant.objects.get(intranet_username="resi")
    TenantRoomAssignment.objects.create(tenant=t, room=world["room"], moved_in=date(2026, 1, 1))
    RoomDamage.objects.create(
        room=world["room"], line=RoomDamageLine.BODEN_FLECKEN,
        created_at="2026-08-22T00:00:00Z", created_by=t,
    )
    r = client.get(f"/tenants/{t.id}/")
    assert b"als behoben markieren" not in r.content
```

Confirm the tenant detail URL pattern (`/tenants/<pk>/` name `tenant_detail`) against `app/urls.py` and adjust the paths in the test if different.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_damages_ui.py -k resident -v`
Expected: FAIL (no report form rendered on the card).

- [ ] **Step 3: Write minimal implementation**

In `CArtei/app/views/tenant.py`, add imports:
```python
from app.models import RoomDamage, WGDamage, RoomDamageLine, WGDamageLine, DamageSize
```
Inside `tenant_detail`, when iterating the tenant's active assignments (where `a.doc_groups` is attached), and only for the viewer's own record (the `owner` role) — attach the resident damage data to each active assignment:
```python
    if "owner" in roles:
        for a in active_assignments:
            a.room_damage_list = list(
                RoomDamage.objects.filter(room_id=a.room_id, fixed_at__isnull=True)
                .order_by("-created_at")
            )
            a.wg_damage_list = list(
                WGDamage.objects.filter(wg_id=a.room.wg_id, fixed_at__isnull=True)
                .order_by("-created_at")
            )
```
Add to the `ctx` dict (near the other ctx assignments):
```python
    ctx["room_damage_lines"] = RoomDamageLine.choices
    ctx["wg_damage_lines"] = WGDamageLine.choices
    ctx["damage_sizes"] = DamageSize.choices
    ctx["show_resident_damages"] = "owner" in roles
```

In `CArtei/app/templates/app/tenant_detail.html`, inside the active-assignment loop (after `{% include "app/_room_assignment_edit.html" %}`, ~line 80):
```django
{% if show_resident_damages %}
  {% url 'room_damage_add' assignment.room_id as room_add_url %}
  {% include "app/_damages.html" with damages=assignment.room_damage_list add_url=room_add_url lines=room_damage_lines sizes=damage_sizes can_fix=False next=request.path %}
  {% url 'wg_damage_add' assignment.room.wg_id as wg_add_url %}
  {% include "app/_damages.html" with damages=assignment.wg_damage_list add_url=wg_add_url lines=wg_damage_lines sizes=damage_sizes can_fix=False next=request.path %}
{% endif %}
```
Confirm the loop variable (`assignment` vs `a`) matches the existing template and that `assignment.room_id` / `assignment.room.wg_id` resolve (they do on the mirror model).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_damages_ui.py -v`
Expected: PASS (all UI tests).

- [ ] **Step 5: Run the full CArtei suite (regression)**

Run: `cd CArtei && uv run pytest -q`
Expected: PASS (no regressions in tenant/room views).

- [ ] **Step 6: Commit**

```bash
git add app/views/tenant.py app/templates/app/tenant_detail.html tests/test_damages_ui.py
git commit -m "Let residents report + view damages on their own room/WG"
```

---

## Self-Review Notes (author checklist — verify during execution)

- **Spec coverage:** two tables + shared mixin (Task 2), two enums + size (Task 1), no-delete-with-reopen trigger (Task 3), migration (Task 4), mirror models (Task 5), permissions incl. resident scoping + belegium exclusion (Tasks 6–7), staff UI on WG detail (Task 8), resident UI on tenant detail (Task 9). ✔ all spec sections mapped.
- **Verify against real code during execution** (flagged inline): `Building/WG/Room/Tenant` constructor kwargs; the `wg_detail` room-loop variable name; the `tenant_detail` assignment-loop variable name; `settings_test.py` `TENANT_ROLE_GROUPS` has werkstatt/mietverwaltung/belegium mappings; tenant detail URL shape.
- **Type consistency:** `size_options` / `_clean_size` operate on raw enum string values; `line` validated against `*.values`; `is_open` property used in template + views consistently; `fixed_at IS NULL` = open used uniformly.
- **Ceiling (from spec):** not `Historized` — reopening clears `fixed_by/fixed_at`, only latest fix retained. Acceptable per design.
