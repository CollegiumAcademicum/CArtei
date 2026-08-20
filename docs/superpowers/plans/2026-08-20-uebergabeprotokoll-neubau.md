# Übergabeprotokoll (Neubau) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A guided multi-page wizard that lets Mietverwaltung (and its helpers) capture a room's condition at move-in/move-out, renders it to a signable PDF, and stores the re-uploaded signed scan.

**Architecture:** Schema lives in `cartei_db` (header table `uebergabeprotokoll` + normalized child `uebergabeprotokoll_damage` + signed-scan table `uebergabeprotokoll_document`), mirrored `managed=False` in `CArtei`. A single DB-persisted wizard view drives all steps from a `STEPS` config (header `modelform_factory` + damage `modelformset_factory`). WeasyPrint renders the PDF server-side. A new `mietverwaltung_helfer` role gets a narrow, protocol-scoped slice of the room-assignment views.

**Tech Stack:** Python 3.14, `uv`, SQLAlchemy 2.0 + Alembic (cartei_db), Django 5 + pytest-django (CArtei), WeasyPrint, PostgreSQL (cartei_db tests), SQLite (CArtei tests).

**Spec:** `CArtei/docs/superpowers/specs/2026-08-20-uebergabeprotokoll-neubau-design.md`

## Global Constraints

- **Python 3.14, `uv` only** — `uv sync`, `uv run …`. No bare `pip`/`python`.
- **Schema is two coordinated steps:** edit model + Alembic autogenerate in `cartei_db`; then mirror in `CArtei/app/models.py` as `managed=False` with matching `db_table`/column names. Never add a Django migration for a domain table.
- **cartei_db conventions:** SQLAlchemy 2.0 `Mapped[...]` + `mapped_column(...)`, explicit type + `nullable=`; singular snake_case tables; one model per file, re-exported in `models/__init__.py` `__all__`; enums in `enums.py`; enum columns via `SAEnum(EnumClass)`.
- **cartei_db tests:** `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest`. The `session` conftest fixture auto-applies audit triggers to every `Historized` subclass and append-only triggers to every table in `document_triggers.DOCUMENT_TABLES`.
- **CArtei mirror models:** `managed = False`, FKs `on_delete=DO_NOTHING, db_constraint=False`; choice enums as `TextChoices`. The `django_db_setup` conftest fixture auto-manages every `managed=False` model for the SQLite test DB.
- **German domain language** (Übergabeprotokoll, Zwischenwand, Flecken, Löcher, Kleberückstände). Code keywords stay English.
- **HTML forms with optional/collapsed inputs use `novalidate`** + server-side validation (project convention).
- **Commits carry NO Claude/Co-Authored-By trailers.** Work on branch `feat/uebergabeprotokoll-neubau`.
- **`cartei_helfer_mietverwaltung` LDAP cn is a placeholder** — dev-safe default only; real DN set before prod.

**Draft nullability note (refines spec):** `mv_representative_id` and `protocol_at` are **nullable** in the DB so a protocol can exist as a draft before step 1 is filled; presence is enforced by the step-1 form and re-checked before PDF generation.

---

## File Structure

**cartei_db**
- `cartei_db/enums.py` — +5 enums (modify)
- `cartei_db/models/uebergabeprotokoll.py` — header model (create)
- `cartei_db/models/uebergabeprotokoll_damage.py` — child model (create)
- `cartei_db/models/uebergabeprotokoll_document.py` — signed-scan model (create)
- `cartei_db/models/__init__.py` — re-export (modify)
- `cartei_db/document_triggers.py` — add table to `DOCUMENT_TABLES` (modify)
- `migrations/versions/*_uebergabeprotokoll.py` — migration (create)
- `tests/test_uebergabeprotokoll.py` — cartei_db tests (create)

**CArtei**
- `app/models.py` — mirror models + `TextChoices` (modify)
- `app/tenant_access.py` — helper visibility (modify)
- `app/auth.py`, `cartei/settings.py` — helper group wiring (modify)
- `app/uebergabe_steps.py` — `STEPS`, `DAMAGE_META`, helpers (create)
- `app/views/uebergabe.py` — start/step/pdf/scan views (create)
- `app/urls.py` — routes (modify)
- `app/templates/app/uebergabe/step.html`, `pdf.html` — templates (create)
- `app/templates/app/_uebergabe_block.html` — per-card block partial (create)
- `app/views/rooms.py`, `app/views/tenant.py` — context + visibility gate (modify)
- `app/templates/app/wg_detail.html`, `tenant_detail.html` — include block (modify)
- `pyproject.toml` — `weasyprint` (modify)
- `tests/test_uebergabe_*.py` — CArtei tests (create)

**cartei_deployment**
- cartei-web Containerfile — WeasyPrint native libs (modify)

---

## Task 1: cartei_db enums

**Files:**
- Modify: `cartei_db/cartei_db/enums.py`
- Test: `cartei_db/tests/test_uebergabeprotokoll.py`

**Interfaces:**
- Produces: `UebergabeProtokollType{EINZUG,AUSZUG}`, `PartitionPosition{SQM_7,SQM_14}`, `FurnitureSource{GEFRAEST,MOEBELSPENDE,NICHT_VORHANDEN}`, `MattressSource{CA,NICHT_VORHANDEN}`, `DamageLine` (18 members).

- [ ] **Step 1: Write the failing test**

```python
# cartei_db/tests/test_uebergabeprotokoll.py
from cartei_db.enums import (
    DamageLine, FurnitureSource, MattressSource, PartitionPosition, UebergabeProtokollType,
)

def test_enums_have_expected_members():
    assert {e.value for e in UebergabeProtokollType} == {"EINZUG", "AUSZUG"}
    assert {e.value for e in PartitionPosition} == {"SQM_7", "SQM_14"}
    assert {e.value for e in FurnitureSource} == {"GEFRAEST", "MOEBELSPENDE", "NICHT_VORHANDEN"}
    assert {e.value for e in MattressSource} == {"CA", "NICHT_VORHANDEN"}
    assert len(DamageLine) == 18
    assert DamageLine.FENSTER_RAHMEN_FLECKEN.value == "FENSTER_RAHMEN_FLECKEN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cartei_db && DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_uebergabeprotokoll.py::test_enums_have_expected_members -v`
Expected: FAIL — `ImportError` (names not defined).

- [ ] **Step 3: Add the enums**

Append to `cartei_db/cartei_db/enums.py`:

```python
class UebergabeProtokollType(str, Enum):
    EINZUG = "EINZUG"
    AUSZUG = "AUSZUG"


class PartitionPosition(str, Enum):
    SQM_7 = "SQM_7"
    SQM_14 = "SQM_14"


class FurnitureSource(str, Enum):
    GEFRAEST = "GEFRAEST"
    MOEBELSPENDE = "MOEBELSPENDE"
    NICHT_VORHANDEN = "NICHT_VORHANDEN"


class MattressSource(str, Enum):
    CA = "CA"
    NICHT_VORHANDEN = "NICHT_VORHANDEN"


class DamageLine(str, Enum):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd cartei_db && git add cartei_db/enums.py tests/test_uebergabeprotokoll.py
git commit -m "Add Übergabeprotokoll enums"
```

---

## Task 2: Header + damage models

**Files:**
- Create: `cartei_db/cartei_db/models/uebergabeprotokoll.py`
- Create: `cartei_db/cartei_db/models/uebergabeprotokoll_damage.py`
- Modify: `cartei_db/cartei_db/models/__init__.py`
- Test: `cartei_db/tests/test_uebergabeprotokoll.py`

**Interfaces:**
- Consumes: enums from Task 1; `Base`, `Historized` from `cartei_db.base`.
- Produces: `UebergabeProtokoll` (table `uebergabeprotokoll`, `Historized`) and `UebergabeProtokollDamage` (table `uebergabeprotokoll_damage`, unique `(protocol_id, line)`), re-exported from `cartei_db.models`.

- [ ] **Step 1: Write the failing test**

```python
# append to cartei_db/tests/test_uebergabeprotokoll.py
from datetime import date, datetime, timezone

from cartei_db.models import (
    Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll, UebergabeProtokollDamage, WG,
)
from cartei_db.enums import DamageLine, UebergabeProtokollType


def _assignment(session):
    b = Building(name="Neubau"); session.add(b); session.flush()
    wg = WG(building_id=b.id, name="NB 1"); session.add(wg); session.flush()
    room = Room(wg_id=wg.id, name="1.01", size_sqm=14); session.add(room); session.flush()
    t = Tenant(first_name="A", last_name="B", intranet_username="ab"); session.add(t); session.flush()
    a = TenantRoomAssignment(tenant_id=t.id, room_id=room.id, moved_in=date(2026, 1, 1))
    session.add(a); session.flush()
    return a, t


def test_protocol_and_damage_round_trip(session):
    a, t = _assignment(session)
    p = UebergabeProtokoll(
        tenant_room_assignment_id=a.id, protocol_type=UebergabeProtokollType.EINZUG,
        created_at=datetime.now(timezone.utc),
    )
    session.add(p); session.flush()
    d = UebergabeProtokollDamage(protocol_id=p.id, line=DamageLine.BODEN_FLECKEN, count_lt1=2, note="Ecke")
    session.add(d); session.flush()
    assert d.count_mid == 0 and d.count_gt == 0
    assert session.get(UebergabeProtokoll, p.id).damages[0].line == DamageLine.BODEN_FLECKEN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cartei_db && DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_uebergabeprotokoll.py::test_protocol_and_damage_round_trip -v`
Expected: FAIL — `ImportError` on `UebergabeProtokoll`.

- [ ] **Step 3: Write the header model**

```python
# cartei_db/cartei_db/models/uebergabeprotokoll.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cartei_db.base import Base, Historized
from cartei_db.enums import (
    FurnitureSource, MattressSource, PartitionPosition, UebergabeProtokollType,
)


class UebergabeProtokoll(Historized, Base):
    __tablename__ = "uebergabeprotokoll"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_room_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("tenant_room_assignment.id"), nullable=False
    )
    protocol_type: Mapped[UebergabeProtokollType] = mapped_column(
        SAEnum(UebergabeProtokollType), nullable=False
    )
    # Draft-nullable: filled on step 1, required before PDF generation.
    mv_representative_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tenant.id"), nullable=True
    )
    protocol_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    partition_position: Mapped[Optional[PartitionPosition]] = mapped_column(
        SAEnum(PartitionPosition), nullable=True
    )
    barrierefrei: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bed_source: Mapped[Optional[FurnitureSource]] = mapped_column(SAEnum(FurnitureSource), nullable=True)
    mattress_source: Mapped[Optional[MattressSource]] = mapped_column(SAEnum(MattressSource), nullable=True)
    desk_source: Mapped[Optional[FurnitureSource]] = mapped_column(SAEnum(FurnitureSource), nullable=True)
    closet_source: Mapped[Optional[FurnitureSource]] = mapped_column(SAEnum(FurnitureSource), nullable=True)

    sonstige_schaeden: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sonstige_moebel: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kueche_schaeden: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bad_schaeden: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gemeinschaftsflaeche: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    damages: Mapped[list["UebergabeProtokollDamage"]] = relationship(
        back_populates="protocol", order_by="UebergabeProtokollDamage.line",
    )
```

- [ ] **Step 4: Write the damage model**

```python
# cartei_db/cartei_db/models/uebergabeprotokoll_damage.py
from typing import Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cartei_db.base import Base
from cartei_db.enums import DamageLine


class UebergabeProtokollDamage(Base):
    __tablename__ = "uebergabeprotokoll_damage"
    __table_args__ = (
        UniqueConstraint("protocol_id", "line", name="uq_uebergabeprotokoll_damage"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("uebergabeprotokoll.id"), nullable=False)
    line: Mapped[DamageLine] = mapped_column(SAEnum(DamageLine), nullable=False)
    # Buckets: Flecken/Kleber use lt1/mid/gt (<1cm, 1-5cm, >5cm);
    # Löcher use lt1/gt only (<1cm, >1cm), mid stays 0.
    count_lt1: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count_mid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    count_gt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    protocol: Mapped["UebergabeProtokoll"] = relationship(back_populates="damages")
```

- [ ] **Step 5: Re-export both models**

In `cartei_db/cartei_db/models/__init__.py`, add imports and `__all__` entries (follow the existing style):

```python
from cartei_db.models.uebergabeprotokoll import UebergabeProtokoll
from cartei_db.models.uebergabeprotokoll_damage import UebergabeProtokollDamage
```
Add `"UebergabeProtokoll"`, `"UebergabeProtokollDamage"` to `__all__`.

- [ ] **Step 6: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd cartei_db && git add cartei_db/models/ tests/test_uebergabeprotokoll.py
git commit -m "Add uebergabeprotokoll header + damage models"
```

---

## Task 3: Signed-scan model + append-only trigger

**Files:**
- Create: `cartei_db/cartei_db/models/uebergabeprotokoll_document.py`
- Modify: `cartei_db/cartei_db/models/__init__.py`, `cartei_db/cartei_db/document_triggers.py`
- Test: `cartei_db/tests/test_uebergabeprotokoll.py`

**Interfaces:**
- Consumes: `RoomAssignmentDocumentColumns` from `cartei_db.models.document_base`.
- Produces: `UebergabeProtokollDocument` (table `uebergabeprotokoll_document`) with extra FK `uebergabeprotokoll_id`; table added to `DOCUMENT_TABLES` so the append-only trigger covers it.

- [ ] **Step 1: Write the failing test**

```python
# append to cartei_db/tests/test_uebergabeprotokoll.py
import pytest
from sqlalchemy.exc import InternalError

from cartei_db.models import UebergabeProtokollDocument


def test_scan_is_append_only(session):
    a, t = _assignment(session)
    p = UebergabeProtokoll(tenant_room_assignment_id=a.id,
                           protocol_type=UebergabeProtokollType.AUSZUG,
                           created_at=datetime.now(timezone.utc))
    session.add(p); session.flush()
    doc = UebergabeProtokollDocument(
        tenant_room_assignment_id=a.id, uebergabeprotokoll_id=p.id,
        file_name="scan.pdf", file_data=b"%PDF-1.4",
        uploaded_at=datetime.now(timezone.utc), uploaded_by_id=t.id,
    )
    session.add(doc); session.flush()
    doc.revoked_at = datetime.now(timezone.utc); doc.revoked_by_id = t.id
    doc.revoked_note = "falsch"
    session.flush()  # single revocation allowed
    with pytest.raises(InternalError):
        doc.file_name = "other.pdf"; session.flush()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cartei_db && DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_uebergabeprotokoll.py::test_scan_is_append_only -v`
Expected: FAIL — `ImportError` on `UebergabeProtokollDocument`.

- [ ] **Step 3: Write the model**

```python
# cartei_db/cartei_db/models/uebergabeprotokoll_document.py
from typing import Optional

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from cartei_db.base import Base
from cartei_db.models.document_base import RoomAssignmentDocumentColumns


class UebergabeProtokollDocument(RoomAssignmentDocumentColumns, Base):
    __tablename__ = "uebergabeprotokoll_document"

    uebergabeprotokoll_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("uebergabeprotokoll.id"), nullable=True
    )
```

- [ ] **Step 4: Register the table**

- In `models/__init__.py`: `from cartei_db.models.uebergabeprotokoll_document import UebergabeProtokollDocument` and add to `__all__`.
- In `document_triggers.py`, append `"uebergabeprotokoll_document"` to the `DOCUMENT_TABLES` tuple.

- [ ] **Step 5: Run test to verify it passes**

Run: same as Step 2. Expected: PASS (conftest applies the append-only trigger to the new table automatically).

- [ ] **Step 6: Commit**

```bash
cd cartei_db && git add cartei_db/models/ cartei_db/document_triggers.py tests/test_uebergabeprotokoll.py
git commit -m "Add uebergabeprotokoll_document (append-only signed scan)"
```

---

## Task 4: Alembic migration

**Files:**
- Create: `cartei_db/migrations/versions/*_uebergabeprotokoll.py`

**Interfaces:**
- Consumes: models from Tasks 2–3, trigger helpers `create_audit_trigger_sql`/`drop_audit_trigger_sql` (`cartei_db.base`) and `document_append_only_sql`/`drop_document_append_only_sql` (`cartei_db.document_triggers`).

- [ ] **Step 1: Autogenerate**

Run: `cd cartei_db && DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic revision --autogenerate -m "uebergabeprotokoll"`

- [ ] **Step 2: Review + hand-edit the migration**

Verify it creates the three enums (`uebergabeprotokolltype`, `partitionposition`, `furnituresource`, `mattresssource`, `damageline`), the three tables, the FKs, and `uq_uebergabeprotokoll_damage`. Then add trigger wiring by hand:

In `upgrade()` after `op.create_table('uebergabeprotokoll', …)`:
```python
    op.execute(create_audit_trigger_sql('uebergabeprotokoll', set()))
```
After `op.create_table('uebergabeprotokoll_document', …)`, re-apply the shared append-only function + trigger for the new table:
```python
    for stmt in document_append_only_sql(("uebergabeprotokoll_document",)):
        op.execute(stmt)
```
In `downgrade()` (before dropping tables), mirror the teardown:
```python
    for stmt in drop_document_append_only_sql(("uebergabeprotokoll_document",)):
        op.execute(stmt)
    op.execute(drop_audit_trigger_sql('uebergabeprotokoll'))
```
Ensure `downgrade()` drops the enums with `sa.Enum(name='…').drop(op.get_bind())` after the tables (match the `aghealth` migration pattern). Add the imports at the top:
```python
from cartei_db.base import create_audit_trigger_sql, drop_audit_trigger_sql
from cartei_db.document_triggers import document_append_only_sql, drop_document_append_only_sql
```

- [ ] **Step 3: Verify upgrade/downgrade round-trips**

Run against a scratch DB:
```bash
cd cartei_db
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic downgrade -1
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run alembic upgrade head
```
Expected: all succeed with no errors; a second `--autogenerate` would produce an empty migration (no drift).

- [ ] **Step 4: Commit**

```bash
cd cartei_db && git add migrations/versions/
git commit -m "Migration: uebergabeprotokoll tables + triggers"
```

---

## Task 5: CArtei mirror models

**Files:**
- Modify: `CArtei/app/models.py`
- Test: `CArtei/tests/test_uebergabe_models.py`

**Interfaces:**
- Produces: mirror models `UebergabeProtokoll`, `UebergabeProtokollDamage`, `UebergabeProtokollDocument`; `TextChoices` `UebergabeProtokollType`, `PartitionPosition`, `FurnitureSource`, `MattressSource`, `DamageLine`.

- [ ] **Step 1: Write the failing test**

```python
# CArtei/tests/test_uebergabe_models.py
import datetime
import pytest
from app.models import (
    Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll,
    UebergabeProtokollDamage, WG, DamageLine, UebergabeProtokollType,
)

@pytest.mark.django_db
def test_protocol_mirror_round_trips():
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="ab")
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))
    p = UebergabeProtokoll.objects.create(
        assignment=a, protocol_type=UebergabeProtokollType.EINZUG,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    d = UebergabeProtokollDamage.objects.create(protocol=p, line=DamageLine.BODEN_FLECKEN, count_lt1=1)
    assert d.count_mid == 0
    assert p.damages.first().line == DamageLine.BODEN_FLECKEN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_models.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Add TextChoices + mirror models**

In `CArtei/app/models.py` (after the existing enums / near the assignment-document models):

```python
class UebergabeProtokollType(models.TextChoices):
    EINZUG = "EINZUG", "Einzug"
    AUSZUG = "AUSZUG", "Auszug"


class PartitionPosition(models.TextChoices):
    SQM_7 = "SQM_7", "7 m²"
    SQM_14 = "SQM_14", "14 m²"


class FurnitureSource(models.TextChoices):
    GEFRAEST = "GEFRAEST", "Gefräst"
    MOEBELSPENDE = "MOEBELSPENDE", "Möbelspende"
    NICHT_VORHANDEN = "NICHT_VORHANDEN", "Nicht vorhanden"


class MattressSource(models.TextChoices):
    CA = "CA", "CA"
    NICHT_VORHANDEN = "NICHT_VORHANDEN", "Nicht vorhanden"


class DamageLine(models.TextChoices):
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


class UebergabeProtokoll(models.Model):
    assignment = models.ForeignKey(
        TenantRoomAssignment, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="uebergabeprotokolle", db_column="tenant_room_assignment_id",
    )
    protocol_type = models.CharField(max_length=16, choices=UebergabeProtokollType.choices)
    mv_representative = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name="+", db_column="mv_representative_id",
    )
    protocol_at = models.DateTimeField(null=True, blank=True)
    partition_position = models.CharField(max_length=8, choices=PartitionPosition.choices, null=True, blank=True)
    barrierefrei = models.BooleanField(default=False)
    bed_source = models.CharField(max_length=16, choices=FurnitureSource.choices, null=True, blank=True)
    mattress_source = models.CharField(max_length=16, choices=MattressSource.choices, null=True, blank=True)
    desk_source = models.CharField(max_length=16, choices=FurnitureSource.choices, null=True, blank=True)
    closet_source = models.CharField(max_length=16, choices=FurnitureSource.choices, null=True, blank=True)
    sonstige_schaeden = models.TextField(null=True, blank=True)
    sonstige_moebel = models.TextField(null=True, blank=True)
    kueche_schaeden = models.TextField(null=True, blank=True)
    bad_schaeden = models.TextField(null=True, blank=True)
    gemeinschaftsflaeche = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField()
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "uebergabeprotokoll"


class UebergabeProtokollDamage(models.Model):
    protocol = models.ForeignKey(
        UebergabeProtokoll, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="damages", db_column="protocol_id",
    )
    line = models.CharField(max_length=32, choices=DamageLine.choices)
    count_lt1 = models.IntegerField(default=0)
    count_mid = models.IntegerField(default=0)
    count_gt = models.IntegerField(default=0)
    note = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "uebergabeprotokoll_damage"


class UebergabeProtokollDocument(RoomAssignmentDocumentBase):
    protocol = models.ForeignKey(
        UebergabeProtokoll, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True,
        related_name="scans", db_column="uebergabeprotokoll_id",
    )

    class Meta:
        managed = False
        db_table = "uebergabeprotokoll_document"
```

- [ ] **Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd CArtei && git add app/models.py tests/test_uebergabe_models.py
git commit -m "Mirror uebergabeprotokoll models"
```

---

## Task 6: Helper role group wiring

**Files:**
- Modify: `CArtei/cartei/settings.py`, `CArtei/app/auth.py`
- Test: `CArtei/tests/test_uebergabe_perms.py`

**Interfaces:**
- Produces: `settings.CARTEI_HELFER_MIETVERWALTUNG_GROUP`; `TENANT_ROLE_GROUPS["mietverwaltung_helfer"]`; marker group `cartei_helfer_mietverwaltung` mapped in `_sync_groups`. `global_roles(user)` returns `"mietverwaltung_helfer"` for members.

- [ ] **Step 1: Write the failing test**

```python
# CArtei/tests/test_uebergabe_perms.py
import pytest
from django.contrib.auth.models import Group, User
from app.tenant_access import global_roles

@pytest.mark.django_db
def test_helper_group_maps_to_role():
    u = User.objects.create(username="helper")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    assert "mietverwaltung_helfer" in global_roles(u)
    assert "mietverwaltung" not in global_roles(u)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_perms.py::test_helper_group_maps_to_role -v`
Expected: FAIL — role not present.

- [ ] **Step 3: Wire settings + role map**

In `cartei/settings.py`, after `CARTEI_MIETVERWALTUNG_GROUP`:
```python
CARTEI_HELFER_MIETVERWALTUNG_GROUP = os.environ.get(
    "CARTEI_HELFER_MIETVERWALTUNG_GROUP",
    "cn=cartei_helfer_mietverwaltung,cn=groups,cn=accounts,dc=intranet,dc=ca-hd,dc=de",
)
```
In the `TENANT_ROLE_GROUPS` dict, add:
```python
    "mietverwaltung_helfer": _group_list("TENANT_GROUP_MIETVERWALTUNG_HELFER", "cartei_helfer_mietverwaltung"),
```
In `app/auth.py` `_sync_groups`, add alongside the other DN checks:
```python
        helper_dn = getattr(settings, "CARTEI_HELFER_MIETVERWALTUNG_GROUP", "").lower()
        # ... inside the `for dn in member_of:` loop, independent check:
                if dn_l == helper_dn:
                    desired.add("cartei_helfer_mietverwaltung")
```

- [ ] **Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd CArtei && git add cartei/settings.py app/auth.py tests/test_uebergabe_perms.py
git commit -m "Add mietverwaltung_helfer role group"
```

---

## Task 7: Helper-scoped field visibility

**Files:**
- Modify: `CArtei/app/tenant_access.py`
- Test: `CArtei/tests/test_uebergabe_perms.py`

**Interfaces:**
- Consumes: role `mietverwaltung_helfer` (Task 6).
- Produces: `visible_fields({"mietverwaltung_helfer"})` includes `first_name`, `last_name`, `room_assignments_view`, `ersteinzug`, `auszug`; excludes `email`, `phone`, `date_of_birth`.

- [ ] **Step 1: Write the failing test**

```python
# append to CArtei/tests/test_uebergabe_perms.py
from app.tenant_access import visible_fields

def test_helper_sees_names_and_rooms_only():
    v = visible_fields({"mietverwaltung_helfer"})
    assert {"first_name", "last_name", "room_assignments_view", "ersteinzug", "auszug"} <= v
    assert not ({"email", "phone", "date_of_birth"} & v)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_perms.py::test_helper_sees_names_and_rooms_only -v`
Expected: FAIL.

- [ ] **Step 3: Add the helper to the four fields**

In `app/tenant_access.py`, add a shorthand and widen only those fields' `visible_to`:
```python
_HELPER = "mietverwaltung_helfer"
```
- `first_name`: `_OWN_MV` → `_OWN_MV | {_HELPER}`
- `last_name`: `_OWN_MV` → `_OWN_MV | {_HELPER}`
- `ersteinzug`, `auszug`: `_OWN_MV_BELEGIUM` → `_OWN_MV_BELEGIUM | {_HELPER}`
- `room_assignments_view`: `_OWN_MV_ADMIN | {"belegium"}` → `_OWN_MV_ADMIN | {"belegium", _HELPER}`

(These pass a set to `_f`, which wraps in `frozenset` — fine.)

- [ ] **Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd CArtei && git add app/tenant_access.py tests/test_uebergabe_perms.py
git commit -m "Scope helper visibility to names + room assignments"
```

---

## Task 8: STEPS config + start view

**Files:**
- Create: `CArtei/app/uebergabe_steps.py`, `CArtei/app/views/uebergabe.py`
- Modify: `CArtei/app/urls.py`
- Test: `CArtei/tests/test_uebergabe_wizard.py`

**Interfaces:**
- Produces:
  - `uebergabe_steps.STEPS: list[dict]` — each `{"slug","title","header":[field names], "lines":[DamageLine values]}` (keys optional). Order matches spec sections 1–15.
  - `uebergabe_steps.DAMAGE_META: dict[str, tuple[str, str]]` — `line value -> (label, kind)` where kind ∈ `{"flecken","loecher","kleber"}`.
  - `uebergabe_steps.protocol_lines() -> list[str]` — the 18 line values in a fixed order.
  - `views.uebergabe.can_do_uebergabe(user) -> bool`.
  - View `uebergabe_start(request, assignment_pk, protocol_type)` (POST): creates draft `UebergabeProtokoll` + one `UebergabeProtokollDamage` per line, redirects to `uebergabe_step` step 0. URL name `uebergabe_start`.

- [ ] **Step 1: Write the failing test**

```python
# CArtei/tests/test_uebergabe_wizard.py
import datetime
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from app.models import (Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll, WG)

@pytest.fixture
def assignment(db):
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="ab")
    return TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))

@pytest.fixture
def helper(db):
    u = User.objects.create_user("helper", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    return u

@pytest.mark.django_db
def test_start_creates_draft_with_damage_rows(client, assignment, helper):
    client.force_login(helper)
    resp = client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)
    assert p.protocol_type == "EINZUG"
    assert p.damages.count() == 18
    assert resp.status_code == 302 and f"/uebergabe/{p.pk}/step/0/" in resp.url

@pytest.mark.django_db
def test_start_forbidden_for_outsider(client, assignment, db):
    client.force_login(User.objects.create_user("nobody", password="x"))
    resp = client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_wizard.py -v`
Expected: FAIL — `NoReverseMatch`.

- [ ] **Step 3: Write `uebergabe_steps.py`**

```python
# CArtei/app/uebergabe_steps.py
from app.models import DamageLine

# line value -> (short label, kind). kind drives which buckets show.
DAMAGE_META = {
    DamageLine.BODEN_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.BODEN_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.FUSSLEISTE_FLECKEN.value: ("Flecken Fußleiste", "flecken"),
    DamageLine.WAND_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.WAND_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.WAND_KLEBER.value: ("Kleberückstände", "kleber"),
    DamageLine.TUER_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.TUER_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.FENSTER_RAHMEN_FLECKEN.value: ("Flecken Fensterrahmen", "flecken"),
    DamageLine.FENSTER_BANK_FLECKEN.value: ("Flecken Fensterbank", "flecken"),
    DamageLine.FENSTER_KLEBER.value: ("Kleberückstände", "kleber"),
    DamageLine.BETT_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.BETT_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.MATRATZE_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.SCHREIBTISCH_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.SCHREIBTISCH_LOECHER.value: ("Löcher", "loecher"),
    DamageLine.SCHRANK_FLECKEN.value: ("Flecken", "flecken"),
    DamageLine.SCHRANK_LOECHER.value: ("Löcher", "loecher"),
}

# Bucket column -> label, per kind. loecher hides count_mid.
BUCKETS = {
    "flecken": [("count_lt1", "<1 cm"), ("count_mid", "1–5 cm"), ("count_gt", ">5 cm")],
    "kleber":  [("count_lt1", "<1 cm"), ("count_mid", "1–5 cm"), ("count_gt", ">5 cm")],
    "loecher": [("count_lt1", "<1 cm"), ("count_gt", ">1 cm")],
}

_D = DamageLine
STEPS = [
    {"slug": "allgemein", "title": "Allgemeine Angaben", "header": ["mv_representative", "protocol_at"]},
    {"slug": "zwischenwand", "title": "Position der Zwischenwand", "header": ["partition_position", "barrierefrei"]},
    {"slug": "boden", "title": "Zimmer – Boden", "lines": [_D.BODEN_FLECKEN.value, _D.BODEN_LOECHER.value, _D.FUSSLEISTE_FLECKEN.value]},
    {"slug": "waende", "title": "Zimmer – Wände", "lines": [_D.WAND_FLECKEN.value, _D.WAND_LOECHER.value, _D.WAND_KLEBER.value]},
    {"slug": "tuer", "title": "Zimmer – Tür", "lines": [_D.TUER_FLECKEN.value, _D.TUER_LOECHER.value]},
    {"slug": "fenster", "title": "Zimmer – Fenster", "lines": [_D.FENSTER_RAHMEN_FLECKEN.value, _D.FENSTER_BANK_FLECKEN.value, _D.FENSTER_KLEBER.value]},
    {"slug": "bett", "title": "Zimmer – Bett", "header": ["bed_source"], "lines": [_D.BETT_FLECKEN.value, _D.BETT_LOECHER.value]},
    {"slug": "matratze", "title": "Matratze", "header": ["mattress_source"], "lines": [_D.MATRATZE_FLECKEN.value]},
    {"slug": "schreibtisch", "title": "Schreibtisch", "header": ["desk_source"], "lines": [_D.SCHREIBTISCH_FLECKEN.value, _D.SCHREIBTISCH_LOECHER.value]},
    {"slug": "schrank", "title": "Schrank", "header": ["closet_source"], "lines": [_D.SCHRANK_FLECKEN.value, _D.SCHRANK_LOECHER.value]},
    {"slug": "sonstige_schaeden", "title": "Sonstige Schäden", "header": ["sonstige_schaeden"]},
    {"slug": "sonstige_moebel", "title": "Sonstige Möbel", "header": ["sonstige_moebel"]},
    {"slug": "kueche", "title": "Küche – Schäden", "header": ["kueche_schaeden"]},
    {"slug": "bad", "title": "Bad – Schäden", "header": ["bad_schaeden"]},
    {"slug": "gemeinschaftsflaeche", "title": "Gemeinschaftsfläche", "header": ["gemeinschaftsflaeche"]},
]


def protocol_lines():
    return list(DAMAGE_META.keys())
```

- [ ] **Step 4: Write the start view + permission helper**

```python
# CArtei/app/views/uebergabe.py
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import (
    Tenant, TenantRoomAssignment, UebergabeProtokoll, UebergabeProtokollDamage,
    UebergabeProtokollType,
)
from app.tenant_access import global_roles
from app.uebergabe_steps import protocol_lines

UEBERGABE_ROLES = {"mietverwaltung", "admin", "mietverwaltung_helfer"}


def can_do_uebergabe(user):
    return bool(UEBERGABE_ROLES & global_roles(user))


def _caller(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


@login_required
@require_POST
def uebergabe_start(request, assignment_pk, protocol_type):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    if protocol_type not in UebergabeProtokollType.values:
        return HttpResponseBadRequest()
    assignment = get_object_or_404(TenantRoomAssignment, pk=assignment_pk)
    p = UebergabeProtokoll.objects.create(
        assignment=assignment, protocol_type=protocol_type, created_at=now(),
    )
    UebergabeProtokollDamage.objects.bulk_create(
        [UebergabeProtokollDamage(protocol=p, line=line) for line in protocol_lines()]
    )
    return redirect("uebergabe_step", pk=p.pk, step=0)
```

- [ ] **Step 5: Add URLs**

In `app/urls.py`, import `uebergabe` in the views import line and add:
```python
    path("assignments/<int:assignment_pk>/uebergabe/<str:protocol_type>/start/", uebergabe.uebergabe_start, name="uebergabe_start"),
    path("uebergabe/<int:pk>/step/<int:step>/", uebergabe.uebergabe_step, name="uebergabe_step"),
```
(The `uebergabe_step` view is added in Task 9; add the route now so the redirect resolves — the test in this task only checks the redirect URL string via `resp.url`, so define a stub `uebergabe_step` returning `HttpResponse("")` now and flesh it out in Task 9. Add `from django.http import HttpResponse` and:)
```python
@login_required
def uebergabe_step(request, pk, step):
    return HttpResponse("")  # implemented in Task 9
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_wizard.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
cd CArtei && git add app/uebergabe_steps.py app/views/uebergabe.py app/urls.py tests/test_uebergabe_wizard.py
git commit -m "Add Übergabeprotokoll STEPS config + start view"
```

---

## Task 9: Step view (header form + damage formset)

**Files:**
- Modify: `CArtei/app/views/uebergabe.py`
- Create: `CArtei/app/templates/app/uebergabe/step.html`
- Test: `CArtei/tests/test_uebergabe_wizard.py`

**Interfaces:**
- Consumes: `STEPS`, `DAMAGE_META`, `BUCKETS` (Task 8); `can_do_uebergabe`.
- Produces: `uebergabe_step(request, pk, step)` — GET renders the step; POST saves the header `modelform_factory` fields and the damage `modelformset_factory` rows for the step, then redirects to `step±1` per `direction` (`weiter`/`zurueck`), clamped to `[0, len(STEPS)-1]`.

- [ ] **Step 1: Write the failing test**

```python
# append to CArtei/tests/test_uebergabe_wizard.py
from app.models import DamageLine, UebergabeProtokollDamage

@pytest.mark.django_db
def test_step_saves_and_advances(client, assignment, helper):
    client.force_login(helper)
    client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)

    # Step 2 (index 2) = Boden: 3 damage rows.
    rows = list(p.damages.filter(line__in=["BODEN_FLECKEN", "BODEN_LOECHER", "FUSSLEISTE_FLECKEN"]).order_by("line"))
    data = {
        "direction": "weiter",
        "form-TOTAL_FORMS": "3", "form-INITIAL_FORMS": "3",
        "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
    }
    for i, r in enumerate(rows):
        data[f"form-{i}-id"] = str(r.pk)
        data[f"form-{i}-count_lt1"] = "3"
        data[f"form-{i}-count_mid"] = "0"
        data[f"form-{i}-count_gt"] = "0"
        data[f"form-{i}-note"] = ""
    resp = client.post(reverse("uebergabe_step", args=[p.pk, 2]), data)
    assert resp.status_code == 302 and resp.url.endswith("/step/3/")
    assert UebergabeProtokollDamage.objects.get(pk=rows[0].pk).count_lt1 == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_wizard.py::test_step_saves_and_advances -v`
Expected: FAIL (stub returns empty 200, no save/redirect).

- [ ] **Step 3: Implement the step view**

Replace the stub `uebergabe_step` in `app/views/uebergabe.py`:

```python
from django.forms import modelform_factory, modelformset_factory
from django.shortcuts import render

from app.uebergabe_steps import BUCKETS, DAMAGE_META, STEPS


def _header_form_cls(fields):
    return modelform_factory(UebergabeProtokoll, fields=fields)


_DamageFormSet = modelformset_factory(
    UebergabeProtokollDamage, fields=["count_lt1", "count_mid", "count_gt", "note"], extra=0,
)


@login_required
def uebergabe_step(request, pk, step):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    p = get_object_or_404(UebergabeProtokoll, pk=pk)
    if not 0 <= step < len(STEPS):
        return HttpResponseBadRequest()
    cfg = STEPS[step]
    header_fields = cfg.get("header", [])
    line_values = cfg.get("lines", [])
    damage_qs = p.damages.filter(line__in=line_values).order_by("line") if line_values else p.damages.none()

    if request.method == "POST":
        hform = _header_form_cls(header_fields)(request.POST, instance=p) if header_fields else None
        fset = _DamageFormSet(request.POST, queryset=damage_qs) if line_values else None
        ok = (hform is None or hform.is_valid()) and (fset is None or fset.is_valid())
        if ok:
            if hform is not None:
                hform.save()
            if fset is not None:
                fset.save()
            delta = 1 if request.POST.get("direction") == "weiter" else -1
            nxt = min(max(step + delta, 0), len(STEPS) - 1)
            return redirect("uebergabe_step", pk=p.pk, step=nxt)
    else:
        hform = _header_form_cls(header_fields)(instance=p) if header_fields else None
        fset = _DamageFormSet(queryset=damage_qs) if line_values else None

    # Pair each damage form with its label + bucket config for the template.
    damage_rows = []
    if fset is not None:
        for form in fset:
            label, kind = DAMAGE_META[form.instance.line]
            damage_rows.append({"form": form, "label": label, "buckets": BUCKETS[kind]})

    return render(request, "app/uebergabe/step.html", {
        "protocol": p, "assignment": p.assignment, "step": step, "steps": STEPS,
        "cfg": cfg, "hform": hform, "fset": fset, "damage_rows": damage_rows,
        "is_last": step == len(STEPS) - 1,
    })
```

- [ ] **Step 4: Write `step.html`**

```html
{# CArtei/app/templates/app/uebergabe/step.html #}
{% extends "app/base.html" %}
{% block content %}
<h1>Übergabeprotokoll ({{ protocol.get_protocol_type_display }})</h1>
<p>Zimmer {{ assignment.room.name }} — {{ assignment.tenant.first_name }} {{ assignment.tenant.last_name }}</p>
<p>Schritt {{ step|add:1 }} / {{ steps|length }}: {{ cfg.title }}</p>

<form method="post" novalidate>
  {% csrf_token %}
  {% if hform %}{{ hform.as_p }}{% endif %}
  {% if damage_rows %}
    {{ fset.management_form }}
    {% for row in damage_rows %}
      <fieldset>
        <legend>{{ row.label }}</legend>
        {{ row.form.id }}
        {% for col, blabel in row.buckets %}
          <label>{{ blabel }}
            {% if col == "count_lt1" %}{{ row.form.count_lt1 }}
            {% elif col == "count_mid" %}{{ row.form.count_mid }}
            {% else %}{{ row.form.count_gt }}{% endif %}
          </label>
        {% endfor %}
        <label>Bemerkung {{ row.form.note }}</label>
      </fieldset>
    {% endfor %}
  {% endif %}

  {% if step > 0 %}<button name="direction" value="zurueck">Zurück</button>{% endif %}
  {% if is_last %}
    <a href="{% url 'uebergabe_pdf' protocol.pk %}">PDF erzeugen</a>
    <button name="direction" value="weiter">Speichern</button>
  {% else %}
    <button name="direction" value="weiter">Weiter</button>
  {% endif %}
</form>
{% endblock %}
```

(Note: `{% url 'uebergabe_pdf' %}` is added in Task 10; add that route before running the full suite, or temporarily hardcode the path. The step-save test here doesn't render the last step, so it passes independently.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_wizard.py::test_step_saves_and_advances -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd CArtei && git add app/views/uebergabe.py app/templates/app/uebergabe/step.html tests/test_uebergabe_wizard.py
git commit -m "Implement Übergabeprotokoll wizard step view"
```

---

## Task 10: PDF generation (WeasyPrint)

**Files:**
- Modify: `CArtei/pyproject.toml`, `CArtei/app/views/uebergabe.py`, `CArtei/app/urls.py`
- Create: `CArtei/app/templates/app/uebergabe/pdf.html`
- Test: `CArtei/tests/test_uebergabe_wizard.py`

**Interfaces:**
- Produces: `uebergabe_pdf(request, pk)` (GET) → `HttpResponse(content_type="application/pdf")`; sets `finalized_at` on first call; `HttpResponseBadRequest` when `mv_representative`/`protocol_at` missing. URL name `uebergabe_pdf`.

- [ ] **Step 1: Add the dependency**

Run: `cd CArtei && uv add weasyprint`
(Dev machine needs native libs: `brew install pango gdk-pixbuf libffi`. Container libs handled in Task 15.)

- [ ] **Step 2: Write the failing test**

```python
# append to CArtei/tests/test_uebergabe_wizard.py
import datetime as _dt

@pytest.mark.django_db
def test_pdf_requires_header_then_renders(client, assignment, helper):
    client.force_login(helper)
    client.post(reverse("uebergabe_start", args=[assignment.pk, "EINZUG"]))
    p = UebergabeProtokoll.objects.get(assignment=assignment)
    # Missing mv_representative/protocol_at -> 400.
    assert client.get(reverse("uebergabe_pdf", args=[p.pk])).status_code == 400
    p.mv_representative = assignment.tenant
    p.protocol_at = _dt.datetime(2026, 1, 2, 10, 0, tzinfo=_dt.timezone.utc)
    p.save()
    resp = client.get(reverse("uebergabe_pdf", args=[p.pk]))
    assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    p.refresh_from_db()
    assert p.finalized_at is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_wizard.py::test_pdf_requires_header_then_renders -v`
Expected: FAIL — `NoReverseMatch`.

- [ ] **Step 4: Implement the PDF view**

Add to `app/views/uebergabe.py`:
```python
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML

from app.uebergabe_steps import DAMAGE_META


@login_required
def uebergabe_pdf(request, pk):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    p = get_object_or_404(UebergabeProtokoll, pk=pk)
    if p.mv_representative_id is None or p.protocol_at is None:
        return HttpResponseBadRequest("Vertretung und Datum/Uhrzeit sind erforderlich.")
    damages = [(DAMAGE_META[d.line][0], d) for d in p.damages.all()]
    html = render_to_string("app/uebergabe/pdf.html",
                            {"protocol": p, "assignment": p.assignment, "damages": damages})
    if p.finalized_at is None:
        p.finalized_at = now()
        p.save(update_fields=["finalized_at"])
    pdf = HTML(string=html).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="uebergabeprotokoll_{p.pk}.pdf"'
    return resp
```
Add the route in `app/urls.py`:
```python
    path("uebergabe/<int:pk>/pdf/", uebergabe.uebergabe_pdf, name="uebergabe_pdf"),
```

- [ ] **Step 5: Write `pdf.html`**

```html
{# CArtei/app/templates/app/uebergabe/pdf.html #}
<html><head><meta charset="utf-8"><style>
  body { font-family: sans-serif; font-size: 11pt; }
  table { border-collapse: collapse; width: 100%; }
  td, th { border: 1px solid #999; padding: 2px 4px; }
  .sig { margin-top: 40px; }
</style></head><body>
  <h1>Übergabeprotokoll – {{ protocol.get_protocol_type_display }}</h1>
  <p>Zimmer {{ assignment.room.name }} ({{ assignment.room.wg.name }})<br>
     Mieter*in: {{ assignment.tenant.first_name }} {{ assignment.tenant.last_name }}<br>
     Vertretung Mietverwaltung: {{ protocol.mv_representative.first_name }} {{ protocol.mv_representative.last_name }}<br>
     Datum/Uhrzeit: {{ protocol.protocol_at }}</p>
  <p>Zwischenwand: {{ protocol.get_partition_position_display|default:"—" }},
     barrierefrei: {% if protocol.barrierefrei %}ja{% else %}nein{% endif %}</p>
  <table><tr><th>Schaden</th><th>&lt;1 cm</th><th>1–5 cm</th><th>&gt;5 / &gt;1 cm</th><th>Bemerkung</th></tr>
    {% for label, d in damages %}
      <tr><td>{{ d.get_line_display }}</td><td>{{ d.count_lt1 }}</td><td>{{ d.count_mid }}</td><td>{{ d.count_gt }}</td><td>{{ d.note|default:"" }}</td></tr>
    {% endfor %}
  </table>
  <p>Bett: {{ protocol.get_bed_source_display|default:"—" }} · Matratze: {{ protocol.get_mattress_source_display|default:"—" }}
     · Schreibtisch: {{ protocol.get_desk_source_display|default:"—" }} · Schrank: {{ protocol.get_closet_source_display|default:"—" }}</p>
  <p><b>Sonstige Schäden:</b> {{ protocol.sonstige_schaeden|default:"—" }}<br>
     <b>Sonstige Möbel:</b> {{ protocol.sonstige_moebel|default:"—" }}<br>
     <b>Küche:</b> {{ protocol.kueche_schaeden|default:"—" }}<br>
     <b>Bad:</b> {{ protocol.bad_schaeden|default:"—" }}<br>
     <b>Gemeinschaftsfläche:</b> {{ protocol.gemeinschaftsflaeche|default:"—" }}</p>
  <div class="sig">_______________________  &nbsp;&nbsp; _______________________<br>
     Mieter*in &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; Mietverwaltung</div>
</body></html>
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_wizard.py::test_pdf_requires_header_then_renders -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd CArtei && git add pyproject.toml uv.lock app/views/uebergabe.py app/urls.py app/templates/app/uebergabe/pdf.html tests/test_uebergabe_wizard.py
git commit -m "Add WeasyPrint PDF rendering for Übergabeprotokoll"
```

---

## Task 11: Signed-scan upload / download / revoke

**Files:**
- Modify: `CArtei/app/views/uebergabe.py`, `CArtei/app/urls.py`
- Test: `CArtei/tests/test_uebergabe_scan.py`

**Interfaces:**
- Consumes: `can_do_uebergabe`, `_caller`; `app.uploads.upload_error`.
- Produces: `uebergabe_scan_upload(request, pk)` (POST) creates `UebergabeProtokollDocument`; `uebergabe_scan_download(request, pk, doc_pk)` (GET) returns bytes; `uebergabe_scan_revoke(request, pk, doc_pk)` (POST) sets `revoked_at/by/note`. URL names `uebergabe_scan_upload`, `uebergabe_scan_download`, `uebergabe_scan_revoke`.

- [ ] **Step 1: Write the failing test**

```python
# CArtei/tests/test_uebergabe_scan.py
import datetime
import pytest
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from app.models import (Building, Room, Tenant, TenantRoomAssignment, UebergabeProtokoll,
                        UebergabeProtokollDocument, WG)

@pytest.fixture
def protocol(db):
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="helper")
    a = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))
    return UebergabeProtokoll.objects.create(assignment=a, protocol_type="AUSZUG",
                                             created_at=datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc))

@pytest.fixture
def helper(db):
    u = User.objects.create_user("helper", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    return u

@pytest.mark.django_db
def test_scan_upload_and_download(client, protocol, helper):
    client.force_login(helper)
    f = SimpleUploadedFile("scan.pdf", b"%PDF-1.4 data", content_type="application/pdf")
    resp = client.post(reverse("uebergabe_scan_upload", args=[protocol.pk]), {"document_file": f})
    assert resp.status_code in (302, 200)
    doc = UebergabeProtokollDocument.objects.get(protocol=protocol)
    dl = client.get(reverse("uebergabe_scan_download", args=[protocol.pk, doc.pk]))
    assert dl.status_code == 200 and b"%PDF" in dl.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_scan.py -v`
Expected: FAIL — `NoReverseMatch`.

- [ ] **Step 3: Implement the views**

Add to `app/views/uebergabe.py`:
```python
from django.contrib import messages
from django.utils.timezone import now
from app.models import UebergabeProtokollDocument
from app.uploads import upload_error


@login_required
@require_POST
def uebergabe_scan_upload(request, pk):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    p = get_object_or_404(UebergabeProtokoll, pk=pk)
    caller = _caller(request.user)
    f = request.FILES.get("document_file")
    if not f or caller is None:
        return HttpResponseBadRequest()
    err = upload_error(f)
    if err:
        messages.error(request, err)
        return redirect("uebergabe_step", pk=p.pk, step=0)
    UebergabeProtokollDocument.objects.create(
        assignment=p.assignment, protocol=p, file_name=f.name, file_data=f.read(),
        uploaded_at=now(), uploaded_by=caller,
    )
    messages.success(request, "Unterschriebenes Protokoll hochgeladen.")
    return redirect("uebergabe_step", pk=p.pk, step=0)


@login_required
def uebergabe_scan_download(request, pk, doc_pk):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    doc = get_object_or_404(UebergabeProtokollDocument, pk=doc_pk, protocol_id=pk)
    resp = HttpResponse(bytes(doc.file_data), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{doc.file_name}"'
    return resp


@login_required
@require_POST
def uebergabe_scan_revoke(request, pk, doc_pk):
    if not can_do_uebergabe(request.user):
        raise PermissionDenied
    doc = get_object_or_404(UebergabeProtokollDocument, pk=doc_pk, protocol_id=pk)
    note = (request.POST.get("revoked_note") or "").strip()
    if not note:
        messages.error(request, "Begründung erforderlich.")
        return redirect("uebergabe_step", pk=pk, step=0)
    doc.revoked_at = now(); doc.revoked_by = _caller(request.user); doc.revoked_note = note
    doc.save()
    return redirect("uebergabe_step", pk=pk, step=0)
```
Add routes in `app/urls.py`:
```python
    path("uebergabe/<int:pk>/scan/upload/", uebergabe.uebergabe_scan_upload, name="uebergabe_scan_upload"),
    path("uebergabe/<int:pk>/scan/<int:doc_pk>/download/", uebergabe.uebergabe_scan_download, name="uebergabe_scan_download"),
    path("uebergabe/<int:pk>/scan/<int:doc_pk>/revoke/", uebergabe.uebergabe_scan_revoke, name="uebergabe_scan_revoke"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_scan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd CArtei && git add app/views/uebergabe.py app/urls.py tests/test_uebergabe_scan.py
git commit -m "Add signed-scan upload/download/revoke for Übergabeprotokoll"
```

---

## Task 12: Card block on WG + tenant detail

**Files:**
- Create: `CArtei/app/templates/app/_uebergabe_block.html`
- Modify: `CArtei/app/views/rooms.py`, `CArtei/app/views/tenant.py`, `CArtei/app/templates/app/wg_detail.html`, `CArtei/app/templates/app/tenant_detail.html`
- Test: `CArtei/tests/test_uebergabe_block.py`

**Interfaces:**
- Consumes: `can_do_uebergabe` (Task 8); `visible_fields` (Task 7).
- Produces: both detail views pass `can_do_uebergabe` and attach `a.protocols` (that assignment's `UebergabeProtokoll` rows, newest first, each with `active_scan`) to each assignment card; `tenant.py` includes `mietverwaltung_helfer` in the assignment-fetch role gate. The block partial renders start buttons / resume / PDF / scan upload+list.

- [ ] **Step 1: Write the failing test**

```python
# CArtei/tests/test_uebergabe_block.py
import datetime
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse
from app.models import Building, Room, Tenant, TenantRoomAssignment, WG

@pytest.fixture
def wg_setup(db):
    b = Building.objects.create(name="Neubau")
    wg = WG.objects.create(building=b, name="NB 1")
    room = Room.objects.create(wg=wg, name="1.01", size_sqm=14)
    t = Tenant.objects.create(first_name="Alice", last_name="B", intranet_username="ab")
    TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=datetime.date(2026, 1, 1))
    return wg

@pytest.fixture
def helper(db):
    u = User.objects.create_user("helper", password="x")
    u.groups.add(Group.objects.create(name="cartei_helfer_mietverwaltung"))
    return u

@pytest.mark.django_db
def test_helper_sees_protocol_block_not_contracts(client, wg_setup, helper):
    client.force_login(helper)
    html = client.get(reverse("wg_detail", args=[wg_setup.pk])).content.decode()
    assert "Übergabeprotokoll" in html          # protocol block present
    assert "Alice" in html                        # occupant name visible
    assert "Mietvertrag" not in html              # MV-only docs hidden
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_block.py -v`
Expected: FAIL — "Übergabeprotokoll" not in HTML.

- [ ] **Step 3: Add view context**

In `app/views/rooms.py` `wg_detail`: compute
```python
from app.views.uebergabe import can_do_uebergabe
...
can_do_uebergabe_flag = can_do_uebergabe(request.user)
```
When building each `a` (assignment) in the card loop, attach:
```python
if can_do_uebergabe_flag:
    a.protocols = list(UebergabeProtokoll.objects.filter(assignment=a).order_by("-created_at"))
    for pr in a.protocols:
        pr.active_scan = pr.scans.filter(revoked_at__isnull=True).order_by("-uploaded_at").first()
```
Import `UebergabeProtokoll`. Add `"can_do_uebergabe": can_do_uebergabe_flag` to the render context.

In `app/views/tenant.py` `tenant_detail`: add `"mietverwaltung_helfer"` to the role set that fetches room assignments (`{"owner", "mietverwaltung", "admin", "belegium"}`), attach `a.protocols` the same way when `can_do_uebergabe(request.user)`, and pass `can_do_uebergabe` into the context.

- [ ] **Step 4: Write the block partial**

```html
{# CArtei/app/templates/app/_uebergabe_block.html #}
{% if can_do_uebergabe %}
<div class="uebergabe-block">
  <strong>Übergabeprotokoll</strong>
  <form method="post" action="{% url 'uebergabe_start' a.pk 'EINZUG' %}" style="display:inline">{% csrf_token %}<button>Einzug</button></form>
  <form method="post" action="{% url 'uebergabe_start' a.pk 'AUSZUG' %}" style="display:inline">{% csrf_token %}<button>Auszug</button></form>
  <ul>
    {% for pr in a.protocols %}
      <li>{{ pr.get_protocol_type_display }} ({{ pr.created_at|date:"Y-m-d" }})
        <a href="{% url 'uebergabe_step' pr.pk 0 %}">bearbeiten</a>
        <a href="{% url 'uebergabe_pdf' pr.pk %}">PDF</a>
        {% if pr.active_scan %}
          <a href="{% url 'uebergabe_scan_download' pr.pk pr.active_scan.pk %}">unterschrieben</a>
        {% else %}
          <form method="post" action="{% url 'uebergabe_scan_upload' pr.pk %}" enctype="multipart/form-data" style="display:inline">
            {% csrf_token %}<input type="file" name="document_file"><button>Hochladen</button>
          </form>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
</div>
{% endif %}
```

- [ ] **Step 5: Include the block in both detail templates**

In `app/templates/app/wg_detail.html` and `app/templates/app/tenant_detail.html`, inside each assignment card's markup add:
```html
{% include "app/_uebergabe_block.html" with a=a can_do_uebergabe=can_do_uebergabe %}
```
(Match the loop variable name used in each template — in `wg_detail.html` the card object is `card.assignment`; pass `a=card.assignment`. In `tenant_detail.html` use the template's assignment loop variable.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd CArtei && uv run pytest tests/test_uebergabe_block.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full CArtei suite (regression)**

Run: `cd CArtei && uv run pytest -q`
Expected: PASS (no regressions in tenant/WG views).

- [ ] **Step 8: Commit**

```bash
cd CArtei && git add app/views/rooms.py app/views/tenant.py app/templates/app/_uebergabe_block.html app/templates/app/wg_detail.html app/templates/app/tenant_detail.html tests/test_uebergabe_block.py
git commit -m "Surface Übergabeprotokoll block on room-assignment cards"
```

---

## Task 13: Deployment — WeasyPrint native libs

**Files:**
- Modify: cartei-web Containerfile in `cartei_deployment/` (locate with `grep -rl cartei-web cartei_deployment` / the image build file)

**Interfaces:** none (infra).

- [ ] **Step 1: Add the runtime libraries**

In the cartei-web image build, install WeasyPrint's native deps. For a Debian/Ubuntu base:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev libcairo2 \
 && rm -rf /var/lib/apt/lists/*
```
For an Alpine base use: `apk add --no-cache pango gdk-pixbuf cairo ttf-dejavu`.

- [ ] **Step 2: Verify the image builds and can render**

Run (from `cartei_deployment/`): `podman compose build web` then in the container `python -c "import weasyprint; weasyprint.HTML(string='<b>x</b>').write_pdf()"`.
Expected: builds; the render command exits 0.

- [ ] **Step 3: Commit**

```bash
cd cartei_deployment && git add -A
git commit -m "Add WeasyPrint native libs to cartei-web image"
```

---

## Self-Review

**Spec coverage:**
- 15 wizard sections → `STEPS` (Task 8) + step view (Task 9). ✓
- Count + note per damage line → `uebergabeprotokoll_damage` (Task 2), buckets rendered per kind (Task 9). ✓
- Wide→normalized child table decision → Tasks 2, 5. ✓
- Einzug/Auszug type → enum + start view (Tasks 1, 8). ✓
- Room/tenant computed from assignment → FK + templates (Tasks 2, 9, 10). ✓
- `mietverwaltung_helfer` role, protocol-only + assignment read → Tasks 6, 7, 12. ✓
- Helper-scoped card (no contracts/notes/edit) → Task 12 test asserts. ✓
- Signed scan via `RoomAssignmentDocumentColumns`, own block, not in `ASSIGNMENT_DOCUMENT_MODELS` → Tasks 3, 11, 12. ✓
- Server PDF via WeasyPrint, printed/signed/re-uploaded → Tasks 10, 11. ✓
- Append-only trigger on scan table → Task 3 + migration Task 4. ✓
- Historized header auditing → Task 2 (inherits `Historized`; conftest + migration apply trigger). ✓
- Deployment native libs → Task 13. ✓

**Placeholder scan:** No TBD/TODO; every code step has concrete content. The Task 8/9 note about a temporary `uebergabe_step` stub and the `uebergabe_pdf` URL ordering is an explicit sequencing instruction, not a placeholder.

**Type consistency:** `can_do_uebergabe` (Task 8) reused in 9/10/11/12; `protocol_lines()`/`DAMAGE_META`/`BUCKETS` names consistent across 8/9/10; mirror field names (`assignment`, `mv_representative`, `protocol_at`, `damages`, `scans`, `protocol`) consistent across 5/8/9/10/11/12; damage columns `count_lt1/count_mid/count_gt/note` consistent 2/5/9/10.

**Known ceiling (ponytail):** one generic `step.html` renders every step instead of 15 partials; damage buckets are three columns with `count_mid` unused for Löcher (documented on the model). Upgrade path: add a step slug + `DAMAGE_META` entry, never new columns.
