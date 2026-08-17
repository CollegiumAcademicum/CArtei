# Internal Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-purpose `cluster_note` table with a generic `internal_note` table; surface Mietverwaltung notes in the housing section and Clustersprechende notes in the engagement section of the tenant detail page, with add and soft-delete actions.

**Architecture:** Single polymorphic `internal_note` table with `source_group` / `subject_type` / `subject_id` columns. Access filtered by Django group membership. Views for add/delete are generic POST endpoints. The tenant detail page injects two note lists and two write-permission booleans.

**Tech Stack:** SQLAlchemy 2.0 (cartei_db), Alembic migrations, Django 5 (CArtei), pytest, pytest-django

## Global Constraints

- Python 3.14, dependency runner is `uv`. All commands: `uv run <cmd>` inside the relevant sub-repo dir.
- `cartei_db` tests require a live Postgres: `DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest`
- `CArtei` tests use SQLite in-memory via pytest-django. Run: `uv run pytest` inside `CArtei/`.
- Django never owns domain tables. No `manage.py makemigrations` for domain models.
- All domain table changes live in `cartei_db` Alembic migrations only.
- Domain language is German in UI copy; code stays English.
- No commit trailers (no Co-Authored-By, no Claude-Session lines).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `cartei_db/cartei_db/enums.py` | Add `NoteSourceGroup`, `NoteSubjectType` enums |
| Create | `cartei_db/cartei_db/models/internal_note.py` | SQLAlchemy model |
| Modify | `cartei_db/cartei_db/models/__init__.py` | Export `InternalNote`, remove `ClusterNote` |
| Create | `cartei_db/migrations/versions/XXXX_internal_note.py` | Create table, migrate data, drop cluster_note |
| Create | `cartei_db/tests/test_models/test_internal_note.py` | Model smoke test |
| Modify | `CArtei/app/models.py` | Add `InternalNote` + TextChoices, remove `ClusterNote` |
| Create | `CArtei/app/views/notes.py` | `add_note` and `delete_note` views |
| Modify | `CArtei/app/urls.py` | Wire `/notes/add/` and `/notes/<pk>/delete/` |
| Modify | `CArtei/app/views/tenant.py` | Inject notes context, remove ClusterNote import |
| Modify | `CArtei/app/templates/app/tenant_detail.html` | Note sections in housing + engagement |
| Create | `CArtei/tests/test_views_notes.py` | Add/delete permission tests |

---

## Task 1: `cartei_db` — enums, model, migration

**Files:**
- Modify: `cartei_db/cartei_db/enums.py`
- Create: `cartei_db/cartei_db/models/internal_note.py`
- Modify: `cartei_db/cartei_db/models/__init__.py`
- Create: `cartei_db/migrations/versions/XXXX_internal_note.py`
- Create: `cartei_db/tests/test_models/test_internal_note.py`

**Interfaces:**
- Produces: `InternalNote` SQLAlchemy model with columns: `id`, `body`, `source_group`, `subject_type`, `subject_id`, `created_at`, `created_by_id`, `deleted_at`, `deleted_by_id`
- Produces: `NoteSourceGroup` enum with values `"mietverwaltung"`, `"clustersprechende"`
- Produces: `NoteSubjectType` enum with values `"tenant"`, `"cluster"`, `"wg"`

- [ ] **Step 1: Add enums to `cartei_db/cartei_db/enums.py`**

Append after the existing enums:

```python
class NoteSourceGroup(str, Enum):
    mietverwaltung = "mietverwaltung"
    clustersprechende = "clustersprechende"


class NoteSubjectType(str, Enum):
    tenant = "tenant"
    cluster = "cluster"
    wg = "wg"
```

- [ ] **Step 2: Create `cartei_db/cartei_db/models/internal_note.py`**

```python
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from cartei_db.base import Base


class InternalNote(Base):
    __tablename__ = "internal_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_group: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("tenant.id"), nullable=True)
```

- [ ] **Step 3: Update `cartei_db/cartei_db/models/__init__.py`**

Replace the `ClusterNote` import/export with `InternalNote`:

```python
from cartei_db.models.building import Building
from cartei_db.models.wg import WG
from cartei_db.models.room import Room
from cartei_db.models.tenant import Tenant
from cartei_db.models.tenant_room_assignment import TenantRoomAssignment
from cartei_db.models.ag_abfrage import AGAbfrage
from cartei_db.models.ag_abfrage_result import AGAbfrageResult
from cartei_db.models.enrollment_proof import EnrollmentProof
from cartei_db.models.internal_note import InternalNote

__all__ = [
    "Building", "WG", "Room", "Tenant", "TenantRoomAssignment",
    "AGAbfrage", "AGAbfrageResult", "EnrollmentProof", "InternalNote",
]
```

- [ ] **Step 4: Generate and edit the Alembic migration**

Inside `cartei_db/`:

```bash
uv run alembic revision --autogenerate -m "internal_note"
```

Open the generated file. Replace the `upgrade()` and `downgrade()` bodies with:

```python
def upgrade() -> None:
    op.create_table(
        "internal_note",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_group", sa.String(50), nullable=False),
        sa.Column("subject_type", sa.String(50), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=True),
    )
    # Migrate existing cluster_note rows; skip rows whose username has no matching tenant.
    op.get_bind().execute(sa.text("""
        INSERT INTO internal_note
            (body, source_group, subject_type, subject_id, created_at, created_by_id)
        SELECT cn.note, 'clustersprechende', 'tenant', cn.tenant_id, cn.created_at, t.id
        FROM cluster_note cn
        JOIN tenant t ON t.intranet_username = cn.created_by
    """))
    op.drop_table("cluster_note")


def downgrade() -> None:
    op.create_table(
        "cluster_note",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("abfrage_id", sa.Integer(), sa.ForeignKey("ag_abfrage.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
    )
    op.drop_table("internal_note")
```

- [ ] **Step 5: Write the test**

Create `cartei_db/tests/test_models/test_internal_note.py`:

```python
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from cartei_db.models.internal_note import InternalNote
from cartei_db.models.tenant import Tenant


@pytest.fixture
def author(session):
    t = Tenant(
        first_name="Anna", last_name="Schreiber", email="a@ca.de",
        intranet_username="aschreiber", intranet_uuid=uuid.uuid4(),
        is_flinta=False, barrier_free_needed=False, mailbox_key=False,
        mailbox_list_opt_in=False, soli_miete_wunsch=Decimal("0"),
        is_sublet=False, move_in=date(2023, 9, 1),
    )
    session.add(t)
    session.flush()
    return t


def test_create_internal_note(session, author):
    note = InternalNote(
        body="Testnotiz",
        source_group="clustersprechende",
        subject_type="tenant",
        subject_id=author.id,
        created_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
        created_by_id=author.id,
    )
    session.add(note)
    session.flush()
    assert note.id is not None
    assert note.deleted_at is None
    assert note.deleted_by_id is None


def test_soft_delete(session, author):
    note = InternalNote(
        body="Zu löschen",
        source_group="mietverwaltung",
        subject_type="tenant",
        subject_id=author.id,
        created_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
        created_by_id=author.id,
    )
    session.add(note)
    session.flush()
    note.deleted_at = datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc)
    note.deleted_by_id = author.id
    session.flush()
    assert note.deleted_at is not None
```

- [ ] **Step 6: Delete `cartei_db/cartei_db/models/cluster_note.py`**

```bash
rm cartei_db/cartei_db/models/cluster_note.py
```

- [ ] **Step 7: Update `cartei_db/tests/test_models/test_ag.py`**

Remove the `ClusterNote` import and the `test_create_cluster_note` test. The file imports `ClusterNote` on line 7 and has a test starting around line 96. Delete both:

```python
# Remove this import line:
from cartei_db.models.cluster_note import ClusterNote

# Remove the entire test_create_cluster_note function (it references ClusterNote and abfrage).
```

- [ ] **Step 8: Run the cartei_db tests**

```bash
# Inside cartei_db/
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest tests/test_models/test_internal_note.py -v
```

Expected: 2 tests pass.

- [ ] **Step 9: Run the full cartei_db test suite**

```bash
DATABASE_URL=postgresql+psycopg://cartei:cartei@localhost:5432/cartei uv run pytest -v
```

Expected: all tests pass (ClusterNote test removed, no remaining references).

- [ ] **Step 10: Commit**

```bash
# Inside cartei_db/
git add cartei_db/enums.py cartei_db/models/internal_note.py cartei_db/models/__init__.py migrations/versions/ tests/test_models/test_internal_note.py tests/test_models/test_ag.py
git rm cartei_db/models/cluster_note.py
git commit -m "feat: add internal_note table, migrate cluster_note data"
```

---

## Task 2: Django mirror model

**Files:**
- Modify: `CArtei/app/models.py`

**Interfaces:**
- Consumes: `internal_note` DB table (Task 1)
- Produces: `InternalNote` Django model; `NoteSourceGroup`, `NoteSubjectType` TextChoices

- [ ] **Step 1: Update `CArtei/app/models.py`**

Remove the `ClusterNote` class entirely. Add the following after the `AGStatus` TextChoices class (around line 10):

```python
class NoteSourceGroup(models.TextChoices):
    MIETVERWALTUNG = "mietverwaltung", "Mietverwaltung"
    CLUSTERSPRECHENDE = "clustersprechende", "Clustersprechende"


class NoteSubjectType(models.TextChoices):
    TENANT = "tenant", "Bewohner:in"
    CLUSTER = "cluster", "Cluster"
    WG = "wg", "WG"
```

Add the `InternalNote` model (after `AGAbfrageResult`):

```python
class InternalNote(models.Model):
    body = models.TextField()
    source_group = models.CharField(max_length=50, choices=NoteSourceGroup.choices)
    subject_type = models.CharField(max_length=50, choices=NoteSubjectType.choices)
    subject_id = models.IntegerField()
    created_at = models.DateTimeField()
    created_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        Tenant, on_delete=models.DO_NOTHING, db_constraint=False,
        null=True, blank=True, related_name="+"
    )

    class Meta:
        managed = False
        db_table = "internal_note"
```

- [ ] **Step 2: Run CArtei tests to verify no breakage**

```bash
# Inside CArtei/
uv run pytest -v
```

Expected: all existing tests pass (conftest auto-discovers `InternalNote` as unmanaged and flips it to managed for SQLite).

- [ ] **Step 3: Commit**

```bash
# Inside CArtei/
git add app/models.py
git commit -m "feat: add InternalNote Django mirror model, remove ClusterNote"
```

---

## Task 3: Note views (add + soft-delete)

**Files:**
- Create: `CArtei/app/views/notes.py`
- Modify: `CArtei/app/urls.py`

**Interfaces:**
- Consumes: `InternalNote`, `Tenant` from `app.models`; `settings.TENANT_ROLE_GROUPS` for group mapping
- Produces:
  - `POST /notes/add/` → `add_note(request)` — creates a note, redirects to `next`
  - `POST /notes/<pk>/delete/` → `delete_note(request, pk)` — soft-deletes, redirects to `next`

- [ ] **Step 1: Create `CArtei/app/views/notes.py`**

```python
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils.timezone import now
from django.views.decorators.http import require_POST

from app.models import InternalNote, Tenant

# Maps viewer role name → NoteSourceGroup value. Extend here to add more groups.
_ROLE_TO_SOURCE_GROUP = {
    "mietverwaltung": "mietverwaltung",
    "cluster": "clustersprechende",
}


def _user_source_groups(user):
    """Return list of source_group values the user may write/delete."""
    group_names = set(user.groups.values_list("name", flat=True))
    if "admins" in group_names:
        return list(_ROLE_TO_SOURCE_GROUP.values())
    result = []
    for role, cns in settings.TENANT_ROLE_GROUPS.items():
        if group_names.intersection(cns) and role in _ROLE_TO_SOURCE_GROUP:
            result.append(_ROLE_TO_SOURCE_GROUP[role])
    return result


def _author(user):
    return Tenant.objects.filter(intranet_username=user.username).first()


@login_required
@require_POST
def add_note(request):
    source_group = request.POST.get("source_group", "")
    subject_type = request.POST.get("subject_type", "")
    subject_id = request.POST.get("subject_id", "")
    body = request.POST.get("body", "").strip()
    next_url = request.POST.get("next", "/")

    allowed = _user_source_groups(request.user)
    if source_group not in allowed or not body or not subject_id:
        raise PermissionDenied

    author = _author(request.user)
    if author is None:
        raise PermissionDenied

    InternalNote.objects.create(
        body=body,
        source_group=source_group,
        subject_type=subject_type,
        subject_id=int(subject_id),
        created_at=now(),
        created_by=author,
    )
    return redirect(next_url)


@login_required
@require_POST
def delete_note(request, pk):
    note = get_object_or_404(InternalNote, pk=pk)
    next_url = request.POST.get("next", "/")

    allowed = _user_source_groups(request.user)
    if note.source_group not in allowed:
        raise PermissionDenied

    author = _author(request.user)
    InternalNote.objects.filter(pk=note.pk).update(deleted_at=now(), deleted_by=author)
    return redirect(next_url)
```

- [ ] **Step 2: Update `CArtei/app/urls.py`**

Add the two note routes and the import:

```python
from django.urls import path

from app.views import abfragen, admin_views, dashboard, notes, tenant

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("abfragen/", abfragen.abfragen_list, name="abfragen_list"),
    path("abfragen/new/", abfragen.abfrage_new, name="abfrage_new"),
    path("abfragen/<int:pk>/", abfragen.abfrage_detail, name="abfrage_detail"),
    path("abfragen/<int:pk>/ag/<str:ag_name>/", abfragen.ag_edit, name="ag_edit"),
    path("abfragen/<int:pk>/tenants/", abfragen.abfrage_tenants, name="abfrage_tenants"),
    path("abfragen/<int:pk>/delete/", abfragen.abfrage_delete, name="abfrage_delete"),
    path("cluster/", abfragen.cluster, name="cluster"),
    path("tenants/<int:pk>/", tenant.tenant_detail, name="tenant_detail"),
    path("notes/add/", notes.add_note, name="note_add"),
    path("notes/<int:pk>/delete/", notes.delete_note, name="note_delete"),
    path("admin/", admin_views.admin_portal, name="admin_portal"),
    path("admin/sync-from-ldap/", admin_views.sync_from_ldap, name="sync_from_ldap"),
    path("admin/permissions/", admin_views.permission_matrix, name="permission_matrix"),
]
```

- [ ] **Step 3: Commit**

```bash
# Inside CArtei/
git add app/views/notes.py app/urls.py
git commit -m "feat: add note add/delete views"
```

---

## Task 4: Tenant detail page integration

**Files:**
- Modify: `CArtei/app/views/tenant.py`
- Modify: `CArtei/app/templates/app/tenant_detail.html`

**Interfaces:**
- Consumes: `InternalNote` from `app.models`; `roles` set already computed by `tenant_detail`
- Produces context keys: `mv_notes` (list), `cluster_notes` (list), `can_write_mv` (bool), `can_write_cluster` (bool)

- [ ] **Step 1: Update imports in `CArtei/app/views/tenant.py`**

Replace the import line that references `ClusterNote`:

```python
# Old:
from app.models import (
    AGAbfrageResult, ClusterNote, EnrollmentProof, Tenant, TenantRoomAssignment,
)

# New:
from app.models import (
    AGAbfrageResult, EnrollmentProof, InternalNote, Tenant, TenantRoomAssignment,
)
```

- [ ] **Step 2: Replace the cluster_notes context block in `tenant_detail`**

Find this block (around line 139):

```python
    if {"cluster", "admin"} & roles:
        ctx["cluster_notes"] = list(ClusterNote.objects.filter(tenant=tenant).order_by("-created_at"))
    else:
        ctx["cluster_notes"] = []
```

Replace with:

```python
    can_write_mv = bool({"mietverwaltung", "admin"} & roles)
    can_write_cluster = bool({"cluster", "admin"} & roles)
    ctx["can_write_mv"] = can_write_mv
    ctx["can_write_cluster"] = can_write_cluster

    _note_qs = InternalNote.objects.filter(
        subject_type="tenant", subject_id=tenant.pk, deleted_at__isnull=True
    ).select_related("created_by").order_by("-created_at")

    ctx["mv_notes"] = list(_note_qs.filter(source_group="mietverwaltung")) if can_write_mv else []
    ctx["cluster_notes"] = list(_note_qs.filter(source_group="clustersprechende")) if can_write_cluster else []
```

- [ ] **Step 3: Add Mietverwaltung notes block to `tenant_detail.html` — housing section**

Find this block (it closes the housing section, around line 131):

```html
    {% if section.key == "housing" and past_assignments %}
    ...
    {% endif %}
  </details>
  {% endfor %}
```

Insert the MV notes block immediately before `</details>` in the housing section. Locate the line:

```html
    {% if section.key == "housing" and past_assignments %}
```

Add after the closing `{% endif %}` of that block, still inside `{% if section.key == "housing" %}` ... wait, the template uses `{% if section.key == "housing" %}` guards per sub-block. Add a new sub-block:

```html
    {% if section.key == "housing" and can_write_mv %}
    <hr style="margin:.75rem 0;border:none;border-top:1px solid #eee;">
    <p style="font-weight:500;margin:.25rem 0 .4rem;">Interne Notizen (Mietverwaltung)</p>
    {% if mv_notes %}
    <ul style="font-size:.9rem;margin:.25rem 0 .75rem;">
      {% for n in mv_notes %}
      <li style="margin-bottom:.25rem;display:flex;align-items:baseline;gap:.5rem;">
        <span style="color:#7a7a7a;white-space:nowrap;">{{ n.created_at|date:"Y-m-d" }} · {{ n.created_by.first_name }} {{ n.created_by.last_name }}:</span>
        <span>{{ n.body }}</span>
        <form method="post" action="{% url 'note_delete' n.pk %}" style="margin-left:auto;">
          {% csrf_token %}
          <input type="hidden" name="next" value="{{ request.path }}">
          <button type="submit" style="background:none;border:none;color:#b00;cursor:pointer;font-size:.8rem;padding:0;">✕</button>
        </form>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p style="color:#888;font-size:.9rem;margin:.25rem 0 .5rem;">Keine Notizen.</p>
    {% endif %}
    <form method="post" action="{% url 'note_add' %}">
      {% csrf_token %}
      <input type="hidden" name="source_group" value="mietverwaltung">
      <input type="hidden" name="subject_type" value="tenant">
      <input type="hidden" name="subject_id" value="{{ tenant.pk }}">
      <input type="hidden" name="next" value="{{ request.path }}">
      <textarea name="body" rows="2" style="width:100%;font-size:.9rem;border:1px solid #ddd;border-radius:4px;padding:.3rem .5rem;" placeholder="Notiz hinzufügen…"></textarea>
      <button type="submit" class="ca-button" style="margin-top:.3rem;padding:.2rem .75rem;font-size:.82rem;">Speichern</button>
    </form>
    {% endif %}
```

Place this block just before `  </details>` that closes the `{% for section in sections %}` loop — specifically after the `{% if section.key == "housing" and past_assignments %}...{% endif %}` block.

- [ ] **Step 4: Update engagement section for Clustersprechende notes**

Find the existing `{% if cluster_notes %}` block in the engagement section (around line 180):

```html
    {% if cluster_notes %}
    <hr class="ca-divider">
    <p class="ca-label">Interne Notizen (Cluster)</p>
    <ul style="font-size:.9rem;margin-top:.25rem;">
      {% for n in cluster_notes %}
      <li style="margin-bottom:.25rem;"><span style="color:#7a7a7a;">{{ n.created_at|date:"Y-m-d" }} · {{ n.created_by }}:</span> {{ n.note }}</li>
      {% endfor %}
    </ul>
    {% endif %}
```

Replace it with the full cluster notes block (list + add form + delete):

```html
    {% if can_write_cluster %}
    <hr style="margin:.75rem 0;border:none;border-top:1px solid #eee;">
    <p style="font-weight:500;margin:.25rem 0 .4rem;">Interne Notizen (Clustersprechende)</p>
    {% if cluster_notes %}
    <ul style="font-size:.9rem;margin:.25rem 0 .75rem;">
      {% for n in cluster_notes %}
      <li style="margin-bottom:.25rem;display:flex;align-items:baseline;gap:.5rem;">
        <span style="color:#7a7a7a;white-space:nowrap;">{{ n.created_at|date:"Y-m-d" }} · {{ n.created_by.first_name }} {{ n.created_by.last_name }}:</span>
        <span>{{ n.body }}</span>
        <form method="post" action="{% url 'note_delete' n.pk %}" style="margin-left:auto;">
          {% csrf_token %}
          <input type="hidden" name="next" value="{{ request.path }}">
          <button type="submit" style="background:none;border:none;color:#b00;cursor:pointer;font-size:.8rem;padding:0;">✕</button>
        </form>
      </li>
      {% endfor %}
    </ul>
    {% else %}
    <p style="color:#888;font-size:.9rem;margin:.25rem 0 .5rem;">Keine Notizen.</p>
    {% endif %}
    <form method="post" action="{% url 'note_add' %}">
      {% csrf_token %}
      <input type="hidden" name="source_group" value="clustersprechende">
      <input type="hidden" name="subject_type" value="tenant">
      <input type="hidden" name="subject_id" value="{{ tenant.pk }}">
      <input type="hidden" name="next" value="{{ request.path }}">
      <textarea name="body" rows="2" style="width:100%;font-size:.9rem;border:1px solid #ddd;border-radius:4px;padding:.3rem .5rem;" placeholder="Notiz hinzufügen…"></textarea>
      <button type="submit" class="ca-button" style="margin-top:.3rem;padding:.2rem .75rem;font-size:.82rem;">Speichern</button>
    </form>
    {% endif %}
```

- [ ] **Step 5: Run CArtei tests**

```bash
uv run pytest -v
```

Expected: all tests pass (the old `cluster_notes` context key is replaced; existing tests don't assert on note content).

- [ ] **Step 6: Commit**

```bash
# Inside CArtei/
git add app/views/tenant.py app/templates/app/tenant_detail.html
git commit -m "feat: show MV and cluster notes on tenant detail page"
```

---

## Task 5: Tests for note add/delete

**Files:**
- Create: `CArtei/tests/test_views_notes.py`

**Interfaces:**
- Consumes: `add_note` at `/notes/add/`, `delete_note` at `/notes/<pk>/delete/`
- Consumes: `InternalNote`, `Tenant` from `app.models`
- Consumes: `_tenant`, `_login` helpers — copy these from `tests/test_tenant_detail.py` (they are module-level helpers, not fixtures, so they won't conflict)

- [ ] **Step 1: Write the tests**

Create `CArtei/tests/test_views_notes.py`:

```python
import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.utils.timezone import now

from app.models import InternalNote, Tenant


def _tenant(username="t1", **kw):
    return Tenant.objects.create(
        first_name=kw.get("first_name", "Test"),
        last_name="User",
        email=f"{username}@ca.de",
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
    )


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)
    return user


def _note(tenant, source_group="clustersprechende", author=None):
    if author is None:
        author = tenant
    return InternalNote.objects.create(
        body="Testnotiz",
        source_group=source_group,
        subject_type="tenant",
        subject_id=tenant.pk,
        created_at=now(),
        created_by=author,
    )


@pytest.mark.django_db
def test_cluster_user_can_add_note():
    subject = _tenant("subject1")
    author_tenant = _tenant("author1")
    c = Client()
    _login(c, "author1", groups=["gr.cluster"])
    resp = c.post("/notes/add/", {
        "source_group": "clustersprechende",
        "subject_type": "tenant",
        "subject_id": subject.pk,
        "body": "Gute Beteiligung",
        "next": f"/tenants/{subject.pk}/",
    })
    assert resp.status_code == 302
    assert InternalNote.objects.filter(body="Gute Beteiligung", source_group="clustersprechende").exists()


@pytest.mark.django_db
def test_mv_user_can_add_note():
    subject = _tenant("subject2")
    _tenant("author2")
    c = Client()
    _login(c, "author2", groups=["ag.mietverwaltung"])
    resp = c.post("/notes/add/", {
        "source_group": "mietverwaltung",
        "subject_type": "tenant",
        "subject_id": subject.pk,
        "body": "Miete ausstehend",
        "next": f"/tenants/{subject.pk}/",
    })
    assert resp.status_code == 302
    assert InternalNote.objects.filter(body="Miete ausstehend", source_group="mietverwaltung").exists()


@pytest.mark.django_db
def test_cluster_user_cannot_add_mv_note():
    subject = _tenant("subject3")
    _tenant("author3")
    c = Client()
    _login(c, "author3", groups=["gr.cluster"])
    resp = c.post("/notes/add/", {
        "source_group": "mietverwaltung",
        "subject_type": "tenant",
        "subject_id": subject.pk,
        "body": "Versuch",
        "next": "/",
    })
    assert resp.status_code == 403
    assert not InternalNote.objects.filter(body="Versuch").exists()


@pytest.mark.django_db
def test_cluster_user_can_delete_cluster_note():
    subject = _tenant("subject4")
    author = _tenant("author4")
    note = _note(subject, "clustersprechende", author)
    c = Client()
    _login(c, "author4", groups=["gr.cluster"])
    resp = c.post(f"/notes/{note.pk}/delete/", {"next": "/"})
    assert resp.status_code == 302
    note.refresh_from_db()
    assert note.deleted_at is not None


@pytest.mark.django_db
def test_cluster_user_cannot_delete_mv_note():
    subject = _tenant("subject5")
    author = _tenant("author5")
    note = _note(subject, "mietverwaltung", author)
    c = Client()
    _login(c, "author5", groups=["gr.cluster"])
    resp = c.post(f"/notes/{note.pk}/delete/", {"next": "/"})
    assert resp.status_code == 403
    note.refresh_from_db()
    assert note.deleted_at is None


@pytest.mark.django_db
def test_admin_can_delete_any_note():
    subject = _tenant("subject6")
    author = _tenant("author6")
    mv_note = _note(subject, "mietverwaltung", author)
    c = Client()
    _login(c, "admin6", groups=["admins"])
    resp = c.post(f"/notes/{mv_note.pk}/delete/", {"next": "/"})
    assert resp.status_code == 302
    mv_note.refresh_from_db()
    assert mv_note.deleted_at is not None


@pytest.mark.django_db
def test_unauthenticated_cannot_add_note():
    subject = _tenant("subject7")
    c = Client()
    resp = c.post("/notes/add/", {
        "source_group": "clustersprechende",
        "subject_type": "tenant",
        "subject_id": subject.pk,
        "body": "Anonym",
        "next": "/",
    })
    assert resp.status_code == 302  # redirect to login
    assert not InternalNote.objects.filter(body="Anonym").exists()
```

- [ ] **Step 2: Run the note tests**

```bash
# Inside CArtei/
uv run pytest tests/test_views_notes.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
# Inside CArtei/
git add tests/test_views_notes.py
git commit -m "test: add note add/delete permission tests"
```
