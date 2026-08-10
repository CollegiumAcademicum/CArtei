# Tenant view — role-scoped expandable sections

Date: 2026-08-10
Repo: `CArtei` (no schema change — stays entirely in Django)

## Goal

Replace the placeholder `tenant_detail.html` with a sectioned tenant profile.
Sections are collapsible. What a viewer sees and may edit depends on their
role(s). The profile owner can self-edit a small set of fields; Mietverwaltung
manages housing/contact/education; Cluster sees engagement; admin sees/edits
everything.

## Access model

A **declarative field matrix** drives both visibility and editability. Each
field declares *who can see it* and *who can edit it*. A viewer holds a set of
roles; a field is visible if `roles ∩ field.visible_to` is non-empty, editable
if `roles ∩ field.editable_by` is non-empty. Sections are groupings only — a
section with zero visible fields for a viewer is hidden entirely.

### Roles

Computed per request against the tenant being viewed:

- `owner` — `request.user`'s tenant (`intranet_username`) is this tenant
- `admin` — Django group `admins`
- `cluster` — group(s) in `TENANT_ROLE_GROUPS["cluster"]`
- `mietverwaltung` — group(s) in `TENANT_ROLE_GROUPS["mietverwaltung"]`
- `finanzierung` — group(s) in `TENANT_ROLE_GROUPS["finanzierung"]` (payments unmodeled → no visible fields this build)
- `public` — implicit; every authenticated tenant has it

Effective roles = `{public} ∪ ({owner} if own profile) ∪ matched group roles ∪ ({admin} if admin)`.
No self-view suppression — your group roles apply on your own profile too.

**Admin override:** admin sees every field and may edit every field except the
system identity columns `intranet_username` and `intranet_uuid`.

### Matrix

| Field | Visible to | Editable by |
|---|---|---|
| `preferred_name`, `pronouns` | public | owner |
| `first_name`, `last_name` | owner | admin |
| `email`, `phone`, `is_flinta`, `mailbox_list_opt_in` | owner, mietverwaltung | owner, mietverwaltung |
| `date_of_birth` | owner, mietverwaltung | mietverwaltung |
| `study_subject`, `apprenticeship_field`, `educational_institution` | owner, mietverwaltung | mietverwaltung |
| `move_in`, `move_out` | owner, mietverwaltung | mietverwaltung |
| `data_priv_signed_at`, `photo_allowance_signed_at` | owner, mietverwaltung | mietverwaltung |
| `barrier_free_needed` | owner, mietverwaltung | mietverwaltung |
| `is_sublet`, `sublet_from`, `sublet_to`, `sublet_of` | mietverwaltung | mietverwaltung |
| `mailbox_key` | mietverwaltung | mietverwaltung |
| `soli_miete_wunsch`, `comments` | admin | admin |

Admin is implicitly in every `editable_by` via the override — not listed per row.

### Relational / read-only content

Shown per-section but **not editable this build** (each needs its own
form/upload flow — deferred):

- `enrollment_proof` list — visible to owner, mietverwaltung, admin
- Room assignment (`TenantRoomAssignment` → `Room`/`WG`/`Building`, incl. key
  handover, deposit IBAN) — visible to mietverwaltung, admin
- Engagement records (`AGAbfrageResult` rows for this tenant) — visible to
  owner, cluster, admin
- `ClusterNote` internal notes — visible to cluster, admin only

The editable set therefore = Tenant scalar columns only.

## Sections (UI)

Collapsible via native `<details>`/`<summary>` — no JS library.

1. **Persönliche Informationen** — preferred_name, pronouns, first_name, last_name, email, phone, is_flinta, mailbox_list_opt_in, date_of_birth
2. **Ausbildung & Studium** — study_subject, apprenticeship_field, educational_institution, enrollment_proof list
3. **Wohnen** — room assignment (read-only), is_sublet, sublet_*, mailbox_key, move_in, move_out
4. **Rechtliches** — data_priv_signed_at, photo_allowance_signed_at, soli_miete_wunsch, barrier_free_needed
5. **Engagement** — AGAbfrageResult rows; ClusterNote block (cluster/admin only)

Section renders only the fields the viewer can see; empty section is omitted.
A non-owner with no other role sees only section 1 with preferred_name +
pronouns (the "public card").

## Implementation

### `app/views/tenant.py`

- Module-level matrix data: field → `(label, visible_to, editable_by)`, grouped
  into the section order above. One source of truth for view + template.
- `_viewer_roles(request, tenant) -> set[str]` — resolves effective roles using
  `current_tenant` (context already resolves it via `intranet_username`) and
  `settings.TENANT_ROLE_GROUPS`.
- `_visible_fields(roles)` / `_editable_fields(roles)` — apply matrix +
  admin override; the override excludes `intranet_username`/`intranet_uuid`.
- `tenant_detail(request, pk)`:
  - `@login_required` only (any tenant may open any profile — at minimum the
    public card). `get_object_or_404(Tenant, pk=pk)`.
  - **GET**: build section context — for each visible field, whether it renders
    as an editable input or static text.
  - **POST**: recompute the editable set server-side (trust boundary — never
    trust which fields the form posted), instantiate `TenantForm` trimmed to
    that set, validate, save. Set `changed_by_var` / `change_source_var`
    contextvars to `request.user.username` before save so `Historized` records
    the actor. Re-render with success/error.

### Form

One `TenantForm(ModelForm)` over all editable-capable Tenant columns, with
`email = forms.EmailField(required=True)` explicitly declared so email format is
validated (the model column is a plain `CharField`). `__init__(allowed_fields)`
pops any field not in the viewer's editable set. A single dynamic form is
simpler than reconciling owner/mietverwaltung/admin form unions.

### `app/templates/app/tenant_detail.html`

Extends `base.html`. One `<form method="post">` wraps the sections. Each section
is a `<details>` with the section title in `<summary>`. Fields the viewer may
edit render as inputs (from the bound form); everything else renders as static
label/value. Submit button shown only when the viewer has ≥1 editable field.
Relational blocks (enrollment proofs, room assignment, engagement, notes) render
as read-only lists. Reuse existing `ca-card` styling.

### `settings.py`

```python
TENANT_ROLE_GROUPS = {
    "cluster": ["cluster"],
    "mietverwaltung": ["ag.mietverwaltung"],   # placeholder cn suffix — adjust
    "finanzierung": ["ag.finanzierung"],       # placeholder cn suffix — adjust
}
```

`admins` stays special-cased (already used across views); not in this dict.

## Testing

`tests/test_tenant_detail.py` (pytest-django, reuse the conftest fixture that
flips `managed=False` models to managed). Assert the matrix:

- Owner sees their fields; edit form exposes exactly the 6 owner-editable fields.
- A different plain tenant sees only preferred_name + pronouns (public card);
  no other section renders; no edit inputs.
- Mietverwaltung member (via a group in `TENANT_ROLE_GROUPS`) sees + can edit
  housing/contact/education/dob; can edit `date_of_birth`.
- Cluster member sees the Engagement section incl. ClusterNote; a non-cluster
  owner sees engagement records but **not** ClusterNote.
- Admin edit form exposes all editable fields but not `intranet_username`.
- POST of a field the viewer may not edit is ignored (value unchanged).
- POST of a malformed email is rejected with a form error.

## Out of scope (future specs)

- Per-group internal-comment authoring (structured, would need a `cartei_db`
  schema change).
- Rental-payments section (Finanzierung) — not modeled yet.
- Editing relational data: enrollment-proof upload, room-assignment CRUD,
  engagement/note authoring.
