# CArtei — User Workflow Graph

Functionality organized by **who does the work**, end to end. Roles come from LDAP
groups (`tenant_access.py`): `owner` (tenant on own record), `helper`, `mietverwaltung`
(MV), `belegium`, `cluster`, `admin`. Everyone logs in via LDAP first.

```mermaid
graph LR
    START(["Log in · LDAP"]) --> DASH["Dashboard<br/>open tasks, counts"]

    %% ================= BEWOHNER*IN (owner) =================
    subgraph OWN["👤 Bewohner*in (owner)"]
        direction TB
        O1["Open own profile"] --> O2["Edit own fields<br/>Rufname, Pronomen, E-Mail,<br/>Telefon, FLINTA, Soli-Miete"]
        O1 --> O3["Upload Immatrikulations-<br/>bescheinigung (enrollment proof)"]
        O1 --> O4["Upload signed docs<br/>Datenschutz, Photoerlaubnis, SEPA"]
        O5["AG member: rate<br/>engagement in Abfrage"]
    end

    %% ================= MIETVERWALTUNG =================
    subgraph MV["🏠 Mietverwaltung"]
        direction TB
        M1["Browse Bewohner*innen<br/>list + filters"] --> M2["Open tenant detail"]
        M2 --> M3["Edit contact / housing fields"]
        M2 --> M4["Verify · reject · revert<br/>enrollment proof"]
        M2 --> M5["Manage Mietvertrag,<br/>Mietbedingungen, SEPA docs"]
        M6["Create new tenant"] --> M2
    end

    %% ================= BELEGIUM =================
    subgraph BEL["🗝️ Belegium (room allocation)"]
        direction TB
        B1["Open WG list (as-of date)"] --> B2["WG detail:<br/>rooms + current assignments"]
        B2 --> B3["Assign tenant to room<br/>(move-in window only)"]
        B2 --> B4["Upload Wohnungsgeber-<br/>bescheinigung per assignment"]
        B2 --> B5["Log room / WG damages<br/>+ photos, mark fixed"]
    end

    %% ================= CLUSTER =================
    subgraph CL["📋 Cluster (AG engagement)"]
        direction TB
        C1["Create Abfrage"] --> C2["Abfrage detail<br/>per-AG health + results"]
        C2 --> C3["Review per-tenant<br/>engagement verdict"]
        C2 --> C4["Add cluster notes<br/>on tenants"]
        C1 --> C5["Delete Abfrage"]
    end

    %% ================= ADMIN =================
    subgraph ADM["⚙️ Admin"]
        direction TB
        A1["Provision LDAP account<br/>+ email credentials"]
        A2["Sync users from LDAP"]
        A3["View permission matrix"]
        A4["Session mgmt<br/>revoke / invalidate all / per-user"]
        A5["Edit any field<br/>+ Admin-Kommentare"]
    end

    DASH --> O1 & M1 & B1 & C1 & A1
    DASH --> M6 & O5

    %% cross-links
    M2 -.->|assign| B2
    A1 -.-> M2
```

## Workflow detail

### 👤 Bewohner\*in (own record)
1. **See & edit own profile** — Rufname, Pronomen, contact, FLINTA, Soli-Miete-Wunsch, mailbox opt-in. Sensitive fields (name, DOB) are view-only or MV-editable.
2. **Enrollment proof** — upload Immatrikulationsbescheinigung; MV/admin verifies. (`cartei_vision` will auto-verify Uni-HD signatures.)
3. **Personal documents** — upload signed Datenschutz, Photoerlaubnis, SEPA-Lastschriftmandat.
4. **AG engagement** — as an AG member, rate fellow tenants' engagement inside an open Abfrage (`ag_edit`).

### 🏠 Mietverwaltung
Full tenant lifecycle: create → edit contact/housing → verify enrollment proofs → manage rental docs (Mietvertrag, Mietbedingungen, SEPA). Sees most tenant fields; edits contract-relevant ones.

### 🗝️ Belegium
Room allocation only, and only inside the **move-in window** (future move-ins + first two weeks): assign tenants to rooms via WG detail, upload Wohnungsgeberbescheinigung per assignment, log/fix room & WG damages with photos.

### 📋 Cluster
Run AG engagement cycles: create an Abfrage, review per-AG health and per-tenant verdicts, keep cluster notes. `AGAbfrage.state` (open/grace/closed) is computed from dates.

### ⚙️ Admin
Superset of all views/edits + operational tasks: provision LDAP accounts (emails credentials), sync users from LDAP, inspect the permission matrix, manage/revoke sessions, and edit any field including Admin-Kommentare.

## Cross-cutting
- **Internal notes** — most roles can add notes scoped by `NoteSourceGroup`; used across tenant/assignment views.
- **Documents hub** (`/documents/`) — one place to see every document type and its status.
- **Auditing** — mutations snapshot into `entity_history` (JSONB) via the `Historized` base; actor from request-boundary contextvars.
