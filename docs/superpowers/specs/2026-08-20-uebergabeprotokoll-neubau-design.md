# Übergabeprotokoll (Neubau) — Design

**Date:** 2026-08-20
**Repos touched:** `cartei_db` (schema), `CArtei` (app), `cartei_deployment` (WeasyPrint native libs)

## Goal

Every move-in and move-out of a Neubau room needs an *Übergabeprotokoll*
(handover protocol). The Mietverwaltung and its helpers capture the room's
condition through a guided multi-page wizard reached from the room-assignment
cards. The finished protocol is rendered to a PDF, printed, signed on paper, and
the signed scan is re-uploaded like the other room-assignment documents.

## Scope

- New structured data captured per protocol (15 wizard sections).
- One protocol per (assignment, direction): move-in and move-out each get one.
- Room + tenant are **computed** from the room assignment, never entered.
- New permission role `mietverwaltung_helfer` may create/edit protocols.
- Server-generated PDF (WeasyPrint) for print/sign; signed scan re-uploaded
  through the existing assignment-document pipeline.

Out of scope: digital signatures, comparing move-in vs move-out side by side,
protocols for Altbau/other buildings, editing a protocol after its signed scan
is uploaded (the scan is the source of truth once present).

## Decisions (confirmed)

| Question | Decision |
|----------|----------|
| Damage fields (`___ <1cm ___ 1-5cm ___ >5cm`) | Integer **count** per bucket + one free-text **note** per damage line |
| Storage of damage lines | **Normalized child table**, not wide columns |
| Move-in vs move-out | One table, `protocol_type` enum (`EINZUG`/`AUSZUG`) |
| Output | **Server-generated PDF via WeasyPrint**; printed, signed, re-uploaded as an assignment document |

## Data model (`cartei_db`)

### `uebergabeprotokoll` (header, `Historized`)

The per-protocol header + all non-repeating fields.

| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | |
| `tenant_room_assignment_id` | FK `tenant_room_assignment.id`, not null | Source of room + tenant (computed) |
| `protocol_type` | enum `UebergabeProtokollType` (`EINZUG`/`AUSZUG`), not null | |
| `mv_representative_id` | FK `tenant.id`, not null | Mietverwaltung rep present at handover |
| `protocol_at` | DateTime(tz), not null | Date **and** time of the handover |
| `partition_position` | enum `PartitionPosition` (`SQM_7`/`SQM_14`), nullable | Position der Zwischenwand |
| `barrierefrei` | bool, not null, default False | |
| `bed_source` | enum `FurnitureSource` (`GEFRAEST`/`MOEBELSPENDE`/`NICHT_VORHANDEN`), nullable | Bett |
| `mattress_source` | enum `MattressSource` (`CA`/`NICHT_VORHANDEN`), nullable | Matratze |
| `desk_source` | enum `FurnitureSource`, nullable | Schreibtisch |
| `closet_source` | enum `FurnitureSource`, nullable | Schrank |
| `sonstige_schaeden` | Text, nullable | Section 11 |
| `sonstige_moebel` | Text, nullable | Section 12 |
| `kueche_schaeden` | Text, nullable | Section 13 |
| `bad_schaeden` | Text, nullable | Section 14 |
| `gemeinschaftsflaeche` | Text, nullable | Section 15 |
| `created_at` | DateTime(tz), not null | |
| `finalized_at` | DateTime(tz), nullable | Set when the PDF is first generated; informational |

Inherits `Historized` (audit updates/deletes into `entity_history`).

### `uebergabeprotokoll_damage` (child, not historized)

One row per damage line of a protocol. Rows are pre-created for all applicable
lines when the protocol is created, so the wizard binds a fixed formset.

| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | |
| `protocol_id` | FK `uebergabeprotokoll.id`, not null | |
| `line` | enum `DamageLine`, not null | Which surface+damage line (see below) |
| `count_lt1` | int, not null, default 0 | `<1 cm` bucket |
| `count_mid` | int, not null, default 0 | `1-5 cm` bucket — unused (0) for Löcher lines |
| `count_gt` | int, not null, default 0 | `>5 cm` (Flecken/Kleber) or `>1 cm` (Löcher) |
| `note` | Text, nullable | Free-text remark for this line |

Unique constraint `(protocol_id, line)`. Not `Historized`: rows churn as drafts;
the signed PDF is the record of truth. The bucket meaning per line is fixed and
known from `line` (Löcher lines use only `count_lt1` + `count_gt`).

`DamageLine` enum values (18), grouped by wizard section:

- Boden: `BODEN_FLECKEN`, `BODEN_LOECHER`, `FUSSLEISTE_FLECKEN`
- Wände: `WAND_FLECKEN`, `WAND_LOECHER`, `WAND_KLEBER`
- Tür: `TUER_FLECKEN`, `TUER_LOECHER`
- Fenster: `FENSTER_RAHMEN_FLECKEN`, `FENSTER_BANK_FLECKEN`, `FENSTER_KLEBER`
- Bett: `BETT_FLECKEN`, `BETT_LOECHER`
- Matratze: `MATRATZE_FLECKEN`
- Schreibtisch: `SCHREIBTISCH_FLECKEN`, `SCHREIBTISCH_LOECHER`
- Schrank: `SCHRANK_FLECKEN`, `SCHRANK_LOECHER`

### `uebergabeprotokoll_document` (signed scan)

Uses the existing `RoomAssignmentDocumentColumns` mixin (append-only, single
revocation enforced by the shared trigger in `document_triggers.py`), plus:

| Column | Type | Notes |
|--------|------|-------|
| `uebergabeprotokoll_id` | FK `uebergabeprotokoll.id`, nullable | Links scan back to its structured protocol |

Same storage pattern as the other assignment-document tables, but surfaced
through the helper-accessible Übergabeprotokoll block (see Permissions), **not**
the MV-only general Dokumente block — so it is not registered in
`ASSIGNMENT_DOCUMENT_MODELS`.

### New enums (`cartei_db/enums.py`)

`UebergabeProtokollType`, `PartitionPosition`, `FurnitureSource`,
`MattressSource`, `DamageLine`.

### Migration & triggers

- One autogenerated Alembic migration (both tables + enums), reviewed.
- Add the append-only revoke trigger for `uebergabeprotokoll_document` in
  `document_triggers.py`, matching the other assignment-document tables.
- New model files under `cartei_db/models/`, re-exported in `models/__init__.py`.

## Permissions

New role `mietverwaltung_helfer`:

1. `settings.py`: `CARTEI_HELFER_MIETVERWALTUNG_GROUP` env var (LDAP DN,
   dev-safe default `cn=cartei_helfer_mietverwaltung,...`).
2. `auth.CustomLDAPBackend._sync_groups`: map that DN to marker group
   `cartei_helfer_mietverwaltung` (independent check, like the MV mapping).
3. `TENANT_ROLE_GROUPS`: `"mietverwaltung_helfer": _group_list(
   "TENANT_GROUP_MIETVERWALTUNG_HELFER", "cartei_helfer_mietverwaltung")`.

The real LDAP cn is a **placeholder to confirm before prod** (same caveat as the
existing tenant-role groups).

Protocol wizard + PDF + signed-scan upload are gated to
`{"mietverwaltung", "admin", "mietverwaltung_helfer"}`. The helper role grants
**only** the protocol workflow — it does not widen access to contracts, notes, or
other MV-only features.

### Helper-scoped visibility (read of current room assignments)

To find the right assignment and to upload the signed scan, helpers need to
*see* the current room assignments — but nothing else on those pages. This is a
narrow, documented slice, not the MV tier:

1. Access matrix (`tenant_access.py`): add `mietverwaltung_helfer` to the
   `visible_to` of **only** `first_name`, `last_name` (so `may_see_names` is
   true — needed to identify the tenant), `room_assignments_view`, and the
   housing `ersteinzug`/`auszug` fields. It is **not** added to `email`,
   `phone`, `date_of_birth`, notes, or any editable set.
2. `wg_detail` / `tenant_detail`: add the helper to the assignment-visibility
   gate so the room cards render for them.

Everything else on those pages is already gated by explicit role sets that do
**not** include the helper (assignment editing, furniture, Belegung notes,
Mietvertrag/other assignment documents, personal-info sections), so it stays
hidden with no extra work. Define once:

```python
can_do_uebergabe = bool({"mietverwaltung", "admin", "mietverwaltung_helfer"} & roles)
helper_only = "mietverwaltung_helfer" in roles and not {"mietverwaltung", "admin"} & roles
```

For a `helper_only` user the card shows: room, occupant name, and the
**Übergabeprotokoll block** (below) — and nothing else.

### Übergabeprotokoll block on the assignment card

The signed scan (`uebergabeprotokoll_document`) is surfaced in its **own**
per-card block gated to `can_do_uebergabe`, **not** mixed into the MV-only
general "Dokumente" block (which stays `{"mietverwaltung","admin"}` and keeps
Mietvertrag etc. out of helper view). This block lists the assignment's
protocols with their state:

- No protocol yet → "Übergabeprotokoll — Einzug / Auszug" start buttons.
- Draft protocol → "Weiter bearbeiten" (resume wizard) + "PDF erzeugen".
- PDF generated, awaiting signed scan → upload the signed scan.
- Signed scan present → download / revoke (append-only, same trigger as other
  assignment docs).

Upload/download/revoke of the signed scan use protocol-scoped views gated to
`can_do_uebergabe` (parallel to the existing assignment-document views, but with
the wider gate). `uebergabeprotokoll` is therefore **not** registered in
`ASSIGNMENT_DOCUMENT_MODELS` (which drives the MV-only general block) — its
storage still uses the `RoomAssignmentDocumentColumns` mixin + append-only
trigger, it just isn't surfaced through that block.

## Wizard (`CArtei`)

### Entry points

On each assignment card in `wg_detail.html` and `tenant_detail.html` (shown to
the gated roles): "Übergabeprotokoll — Einzug" / "Auszug" actions. Each POSTs to
a start view that creates the draft header + pre-creates the 18 damage rows,
then redirects into step 1.

### One view, DB-persisted, no wizard dependency

A module-level `STEPS` config drives a single `uebergabe_step(pk, step)` view.
Each step declares which header fields and/or which `DamageLine` rows it edits:

```python
STEPS = [
  {"slug": "allgemein",   "header": ["mv_representative", "protocol_at"]},
  {"slug": "zwischenwand","header": ["partition_position", "barrierefrei"]},
  {"slug": "boden",       "lines": [BODEN_FLECKEN, BODEN_LOECHER, FUSSLEISTE_FLECKEN]},
  {"slug": "waende",      "lines": [WAND_FLECKEN, WAND_LOECHER, WAND_KLEBER]},
  {"slug": "tuer",        "lines": [TUER_FLECKEN, TUER_LOECHER]},
  {"slug": "fenster",     "lines": [FENSTER_RAHMEN_FLECKEN, FENSTER_BANK_FLECKEN, FENSTER_KLEBER]},
  {"slug": "bett",        "header": ["bed_source"],     "lines": [BETT_FLECKEN, BETT_LOECHER]},
  {"slug": "matratze",    "header": ["mattress_source"],"lines": [MATRATZE_FLECKEN]},
  {"slug": "schreibtisch","header": ["desk_source"],    "lines": [SCHREIBTISCH_FLECKEN, SCHREIBTISCH_LOECHER]},
  {"slug": "schrank",     "header": ["closet_source"],  "lines": [SCHRANK_FLECKEN, SCHRANK_LOECHER]},
  {"slug": "sonstige_schaeden",   "header": ["sonstige_schaeden"]},
  {"slug": "sonstige_moebel",     "header": ["sonstige_moebel"]},
  {"slug": "kueche",              "header": ["kueche_schaeden"]},
  {"slug": "bad",                 "header": ["bad_schaeden"]},
  {"slug": "gemeinschaftsflaeche","header": ["gemeinschaftsflaeche"]},
]
```

- Header fields → `modelform_factory(UebergabeProtokoll, fields=step["header"])`.
- Damage lines → `modelformset_factory(UebergabeProtokollDamage, fields=[counts, note], extra=0)`
  bound to `queryset=damage.filter(line__in=step["lines"])`.
- A step may have both (Bett/Matratze/Schreibtisch/Schrank): both are validated
  and saved together.
- **Weiter** saves and → step+1; **Zurück** → step−1. State lives in the DB row,
  so refresh/back/leave-and-return are all safe. No `django-formtools`.

Step 1 shows room + tenant read-only (computed from the assignment). Loose
bucket counts inside collapsed sections must not silently block submit — forms
use `novalidate` + server-side validation (per existing project convention).

### PDF (WeasyPrint)

`uebergabe_pdf(pk)` renders `templates/app/uebergabe/pdf.html` → PDF via
WeasyPrint, returned as `application/pdf` download; sets `finalized_at` on first
generation. The template lays out all 15 sections with the room/tenant/rep
header and a signature line. The MV or helper prints, signs, scans, and
re-uploads the signed scan via the protocol block's upload
(gated to `can_do_uebergabe`).

**Dependency:** add `weasyprint` to CArtei (`uv`). It needs native libs
(pango, cairo, gobject, harfbuzz) in the `cartei-web` runtime image — a
`cartei_deployment` change (Containerfile/setup). Flag for the deployment step.

## Files touched

**cartei_db**
- `enums.py` — 5 new enums.
- `models/uebergabeprotokoll.py`, `models/uebergabeprotokoll_damage.py`,
  `models/uebergabeprotokoll_document.py` — new.
- `models/__init__.py` — re-export + `__all__`.
- `document_triggers.py` — trigger for the new doc table.
- `migrations/versions/*_uebergabeprotokoll.py` — autogenerated, reviewed.

**CArtei**
- `app/models.py` — mirror models (`managed=False`), `TextChoices` for the enums.
  (`uebergabeprotokoll_document` is **not** added to `ASSIGNMENT_DOCUMENT_MODELS`.)
- `app/tenant_access.py` — add `mietverwaltung_helfer` to `visible_to` of
  `first_name`, `last_name`, `room_assignments_view`, `ersteinzug`, `auszug` only.
- `app/views/uebergabe.py` — new: start, step, pdf, and signed-scan upload/download/revoke views.
- `app/urls.py` — routes.
- `app/templates/app/uebergabe/` — wizard base + 15 step partials + `pdf.html`.
- `app/views/rooms.py`, `app/views/tenant.py` — add helper to the assignment-visibility
  gate; compute `can_do_uebergabe`/`helper_only`; pass the protocol block context.
- `app/templates/app/wg_detail.html`, `tenant_detail.html` — Übergabeprotokoll block on cards
  (start buttons / resume / PDF / signed-scan upload), helper-only stripped card.
- `cartei/settings.py`, `app/auth.py` — helper group wiring.
- `pyproject.toml` — `weasyprint`.

**cartei_deployment**
- Containerfile / setup for cartei-web — WeasyPrint native libs.

## Testing

- **cartei_db** (live Postgres): create protocol + damage rows; `Historized`
  snapshot on header update; append-only/revoke trigger on the doc table.
- **CArtei** (pytest-django, reuse the `managed=False`→managed conftest fixture):
  - permission gating: helper can start/save/generate/upload; outsider → 403.
  - helper-only scoping: a helper (no MV/admin) sees the room card with occupant
    name + Übergabeprotokoll block, but **not** Mietvertrag/other docs, Belegung
    notes, assignment editing, furniture editing, or personal-info fields
    (email/phone/DOB).
  - room + tenant computed correctly from the assignment; both `EINZUG` and `AUSZUG`.
  - step navigation persists header fields and damage counts/notes across Weiter/Zurück.
  - PDF view returns `application/pdf` and sets `finalized_at`.
  - signed-scan upload registers under the new assignment-document type and
    appears in the card's Dokumente group.

## Known ceiling / notes

- Damage-line bucket semantics are encoded by `line` (Löcher = 2 buckets in 3
  columns, `count_mid` unused). If a future line needs different bucketing, add
  the line to the enum, not new columns.
- Protocols remain editable until a signed scan exists; no hard lock. If a lock
  is later required, gate the wizard on absence of an active
  `uebergabeprotokoll_document` for that protocol.
