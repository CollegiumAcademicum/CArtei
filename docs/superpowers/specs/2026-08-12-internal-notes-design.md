# Internal Notes — Design Spec
_2026-08-12_

## Goal

Replace the single-purpose `cluster_note` table with a generic internal note system that different groups (Mietverwaltung, Clustersprechende, more AGs in future) can use to leave notes on different subjects (tenants, clusters, WGs, more in future). Each group sees only its own notes; admins see all.

---

## Schema (`cartei_db`)

New table: **`internal_note`**

| column | type | constraints |
|---|---|---|
| `id` | Integer | PK, autoincrement |
| `body` | Text | not null |
| `source_group` | `NoteSourceGroup` enum | not null |
| `subject_type` | `NoteSubjectType` enum | not null |
| `subject_id` | Integer | not null, no FK constraint |
| `created_at` | DateTime(timezone=True) | not null |
| `created_by_id` | Integer | not null, FK → `tenant.id`, no cascade |
| `deleted_at` | DateTime(timezone=True) | nullable |
| `deleted_by_id` | Integer | nullable, FK → `tenant.id`, no cascade |

New enums in `cartei_db/enums.py`:

```python
class NoteSourceGroup(str, enum.Enum):
    mietverwaltung = "mietverwaltung"
    clustersprechende = "clustersprechende"

class NoteSubjectType(str, enum.Enum):
    tenant = "tenant"
    cluster = "cluster"
    wg = "wg"
```

Adding a new group or subject type = new enum value + one Alembic migration, no new table.

### Migration

1. Create `internal_note` table.
2. Copy rows from `cluster_note` into `internal_note` with `source_group='clustersprechende'`, `subject_type='tenant'`, `created_by_id` resolved by matching `cluster_note.created_by` against `tenant.intranet_username`. Rows with no matching tenant are skipped (data loss acceptable — these would be stale/deleted accounts).
3. Drop `cluster_note`.

---

## Access control (`CArtei`)

A single helper in `app/views/notes.py`:

```python
def notes_for_subject(user, subject_type, subject_id):
    qs = InternalNote.objects.filter(subject_type=subject_type, subject_id=subject_id)
    if user.groups.filter(name="admins").exists():
        return qs
    allowed = _groups_for_user(user)  # maps Django groups → NoteSourceGroup values
    return qs.filter(source_group__in=allowed)
```

`_groups_for_user` maps known Django group names (e.g. `ag.mietverwaltung`, `gr.cluster`) to `NoteSourceGroup` enum values. Unknown groups return an empty list → no notes visible.

Write access: a user may add a note if they belong to the group that owns that section. `source_group` is always a hidden field determined by which section the form lives in — no user selection needed.

---

## Deletion (soft)

Notes are never edited or hard-deleted. Deletion sets `deleted_at` + `deleted_by_id`; the row is preserved. All queries filter `deleted_at IS NULL` by default. Only the owning group (or admins) can delete a note — same permission as writing.

Each note displays:

```
YYYY-MM-DD · Firstname Lastname [· Gruppe]  ← group label only for admins
<body>
```

---

## `created_by_id` resolution

At write time: `Tenant.objects.get(intranet_username=request.user.username)`. This always succeeds because `_ensure_tenant` in `auth.py` creates a tenant row on every login.

---

## UI (first iteration: tenant detail page)

Notes are placed in the section that matches their group — no separate "Interne Notizen" section:

- **Mietverwaltung notes** → inside the Wohnen (housing) section of `tenant_detail.html`
- **Clustersprechende notes** → inside the Engagement section of `tenant_detail.html`

Each section renders:
1. Chronological note list (newest first), shown only to the owning group or admins
2. Textarea + submit button, shown only if the current user belongs to the owning group (or is admin)
3. Delete button per note (small, e.g. ✕), same visibility as write access — POSTs to `POST /notes/<id>/delete/`

POST to `POST /notes/add/` with hidden fields `source_group=<group>`, `subject_type=tenant`, `subject_id=<pk>`. `source_group` is fixed per section — no user selection. On success: redirect back to the tenant page.

Cluster/WG detail pages get the same pattern once those pages exist.

---

## Django mirror model

```python
class InternalNote(models.Model):
    body = models.TextField()
    source_group = models.CharField(max_length=50, choices=NoteSourceGroup.choices)
    subject_type = models.CharField(max_length=50, choices=NoteSubjectType.choices)
    subject_id = models.IntegerField()
    created_at = models.DateTimeField()
    created_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="+")

    class Meta:
        managed = False
        db_table = "internal_note"
```

Remove the `ClusterNote` mirror model.

---

## Out of scope (add when needed)

- Dedicated notes list view per group
- Note editing
- Notes on subjects without a detail page (cluster, WG) — schema supports it, UI deferred
