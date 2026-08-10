# Tenant View — Role-Scoped Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder tenant profile with collapsible sections whose visibility and editability are driven by a declarative field-access matrix keyed on the viewer's roles.

**Architecture:** A module-level matrix in `app/views/tenant.py` maps each Tenant field to `visible_to` / `editable_by` role sets. Per request, effective roles are computed (`public`, `owner`, `admin`, `cluster`, `mietverwaltung` via `settings.TENANT_ROLE_GROUPS`). A field shows if `roles ∩ visible_to` is non-empty; it renders as an input if `roles ∩ editable_by` is non-empty (admin override edits all but system IDs). One dynamic `TenantForm` handles saves. Relational data (rooms, enrollment proofs, engagement, notes) is read-only.

**Tech Stack:** Django 5, pytest-django, native HTML `<details>` for collapsibles. Python 3.14, `uv`. All work is in the `CArtei` repo — no `cartei_db` schema change.

## Global Constraints

- Run everything with `uv run ...` (no bare `python`/`pip`). Tests: `uv run pytest`.
- Mirror models are `managed=False`, matching `db_table` and column names; FKs use `on_delete=DO_NOTHING, db_constraint=False`. Never add a Django migration for a domain table.
- Domain language German for domain concepts (section titles, labels); code keywords English.
- Admin override: admin sees every field and edits every field **except** `intranet_username` and `intranet_uuid`.
- Effective roles = `{public} ∪ ({owner} if own profile) ∪ matched group roles ∪ ({admin} if admin)`. No self-view suppression.
- Server-side editable set is the trust boundary — recompute it on POST; never trust which fields were submitted.
- **Audit gap (accepted):** Django writes bypass `cartei_db`'s SQLAlchemy `Historized` listeners, so edits are not recorded in `entity_history`. Do not attempt to set `changed_by_var`.
- Tests reuse the existing `tests/conftest.py` `django_db_setup` fixture (flips `managed=False` models to managed). Mark DB tests with `@pytest.mark.django_db`.

---

### Task 1: Mirror the relational models

The Housing and Education sections read tables not yet mirrored in Django. Add `managed=False` mirrors so the ORM can query them.

**Files:**
- Modify: `app/models.py` (append after `ClusterNote`, end of file)
- Test: `tests/test_relational_mirrors.py`

**Interfaces:**
- Produces: `Building`, `WG`, `Room`, `TenantRoomAssignment`, `EnrollmentProof` Django models with `objects` managers; `TenantRoomAssignment.tenant` / `.room` FKs, `Room.wg` FK, `WG.building` FK, `EnrollmentProof.tenant` FK.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_relational_mirrors.py
import pytest


@pytest.mark.django_db
def test_relational_mirrors_queryable():
    from app.models import Building, WG, Room, TenantRoomAssignment, EnrollmentProof
    # Tables build under the conftest fixture; empty queries must not raise.
    assert list(Building.objects.all()) == []
    assert list(WG.objects.all()) == []
    assert list(Room.objects.all()) == []
    assert list(TenantRoomAssignment.objects.all()) == []
    assert list(EnrollmentProof.objects.all()) == []


@pytest.mark.django_db
def test_room_assignment_relations():
    from app.models import Building, WG, Room, Tenant, TenantRoomAssignment
    import uuid
    from datetime import date
    b = Building.objects.create(name="Haupthaus")
    wg = WG.objects.create(building=b, name="WG 1", cluster="1A")
    room = Room.objects.create(wg=wg, name="Z1", size_sqm=12, has_bed=True)
    t = Tenant.objects.create(first_name="A", last_name="B", intranet_username="ab", intranet_uuid=uuid.uuid4())
    tra = TenantRoomAssignment.objects.create(tenant=t, room=room, moved_in=date(2026, 1, 1))
    assert tra.room.wg.building.name == "Haupthaus"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_relational_mirrors.py -v`
Expected: FAIL with `ImportError` (models not defined).

- [ ] **Step 3: Add the mirror models**

Append to `app/models.py`. Match `cartei_db` columns exactly; `managed=False`.

```python
class Building(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        managed = False
        db_table = "building"

    def __str__(self) -> str:
        return self.name


class WG(models.Model):
    building = models.ForeignKey(Building, on_delete=models.DO_NOTHING, db_constraint=False)
    name = models.CharField(max_length=255)
    cluster = models.CharField(max_length=3, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "wg"

    def __str__(self) -> str:
        return self.name


class Room(models.Model):
    wg = models.ForeignKey(WG, on_delete=models.DO_NOTHING, db_constraint=False)
    name = models.CharField(max_length=255)
    size_sqm = models.DecimalField(max_digits=8, decimal_places=2)
    has_mattress = models.BooleanField(default=False)
    has_bed = models.BooleanField(default=False)
    has_table = models.BooleanField(default=False)
    has_closet = models.BooleanField(default=False)
    freifinanziert = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = "room"

    def __str__(self) -> str:
        return self.name


class TenantRoomAssignment(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False)
    room = models.ForeignKey(Room, on_delete=models.DO_NOTHING, db_constraint=False)
    moved_in = models.DateField()
    moved_out = models.DateField(null=True, blank=True)
    key_handed_over = models.BooleanField(default=False)
    deposit_iban = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "tenant_room_assignment"


class EnrollmentProof(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.DO_NOTHING, db_constraint=False)
    enrollment_type = models.CharField(max_length=50)
    enrollment_name = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    submitted_at = models.DateTimeField()
    valid_until = models.DateField()

    class Meta:
        managed = False
        db_table = "enrollment_proof"
```

Note: `EnrollmentProof.file_data` (LargeBinary) is intentionally omitted from the mirror — it is not displayed and would pull blobs into every query.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_relational_mirrors.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_relational_mirrors.py
git commit -m "feat: mirror room/wg/building/assignment/enrollment models"
```

---

### Task 2: The access matrix and role resolution

Pure logic, no DB and no HTTP. This is the heart of the feature.

**Files:**
- Create: `app/tenant_access.py`
- Modify: `app/models.py` — nothing; `cartei/settings.py` — add `TENANT_ROLE_GROUPS`
- Test: `tests/test_tenant_access.py`

**Interfaces:**
- Produces:
  - `SECTIONS: list[Section]` where `Section = namedtuple("Section", "key title fields")` and each field is `Field(name, label, visible_to: frozenset[str], editable_by: frozenset[str])`.
  - `EDITABLE_COLUMNS: list[str]` — every Tenant column that appears in any `editable_by` (used to build the form).
  - `SYSTEM_ID_FIELDS = {"intranet_username", "intranet_uuid"}`.
  - `viewer_roles(user, tenant, current_tenant) -> set[str]`
  - `visible_fields(roles) -> set[str]` and `editable_fields(roles) -> set[str]` (both apply the admin override).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tenant_access.py
from app.tenant_access import (
    viewer_roles, visible_fields, editable_fields, EDITABLE_COLUMNS, SYSTEM_ID_FIELDS,
)


class _GroupsShim:
    def __init__(self, names): self._names = list(names)
    def values_list(self, field, flat=False): return list(self._names)


class FakeUser:
    def __init__(self, group_names, username="u"):
        self.username = username
        self.groups = _GroupsShim(group_names)


class FakeTenant:
    def __init__(self, pk): self.pk = pk


def test_owner_roles():
    user = FakeUser([], username="me")
    t = FakeTenant(1)
    roles = viewer_roles(user, tenant=t, current_tenant=t)
    assert "owner" in roles and "public" in roles and "admin" not in roles


def test_public_only_for_stranger():
    user = FakeUser([], username="x")
    roles = viewer_roles(user, tenant=FakeTenant(1), current_tenant=FakeTenant(2))
    assert roles == {"public"}


def test_admin_sees_and_edits_all_but_system_ids():
    roles = {"public", "admin"}
    vis = visible_fields(roles)
    edt = editable_fields(roles)
    assert "soli_miete_wunsch" in vis and "comments" in vis
    assert "email" in edt
    assert SYSTEM_ID_FIELDS.isdisjoint(edt)


def test_owner_edits_exactly_six():
    edt = editable_fields({"public", "owner"})
    assert edt == {"email", "phone", "is_flinta", "mailbox_list_opt_in", "preferred_name", "pronouns"}


def test_stranger_sees_only_public_card():
    assert visible_fields({"public"}) == {"preferred_name", "pronouns"}


def test_mietverwaltung_can_edit_dob_and_contact():
    edt = editable_fields({"public", "mietverwaltung"})
    assert {"date_of_birth", "email", "move_in", "mailbox_key"} <= edt
    assert "soli_miete_wunsch" not in edt  # admin-only


def test_editable_columns_are_real_tenant_fields():
    from app.models import Tenant
    names = {f.name for f in Tenant._meta.get_fields()}
    assert set(EDITABLE_COLUMNS) <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tenant_access.py -v`
Expected: FAIL with `ModuleNotFoundError: app.tenant_access`.

- [ ] **Step 3: Add `TENANT_ROLE_GROUPS` to settings**

In `cartei/settings.py`, near the other CARTEI_* config, add:

```python
# Maps a section role to the LDAP-synced Django group name(s) that grant it.
# cn suffixes are placeholders — adjust to the real intranet group names.
TENANT_ROLE_GROUPS = {
    "cluster": ["cluster"],
    "mietverwaltung": ["ag.mietverwaltung"],
    "finanzierung": ["ag.finanzierung"],
}
```

- [ ] **Step 4: Write `app/tenant_access.py`**

```python
from collections import namedtuple

from django.conf import settings

Field = namedtuple("Field", "name label visible_to editable_by")
Section = namedtuple("Section", "key title fields")

SYSTEM_ID_FIELDS = frozenset({"intranet_username", "intranet_uuid"})

# Role shorthands
_PUBLIC = frozenset({"public"})
_OWNER = frozenset({"owner"})
_OWN_MV = frozenset({"owner", "mietverwaltung"})
_MV = frozenset({"mietverwaltung"})
_ADMIN = frozenset({"admin"})
_OWN_CLU = frozenset({"owner", "cluster"})


def _f(name, label, visible_to, editable_by):
    return Field(name, label, frozenset(visible_to), frozenset(editable_by))


SECTIONS = [
    Section("personal", "Persönliche Informationen", [
        _f("preferred_name", "Rufname", _PUBLIC, _OWNER),
        _f("pronouns", "Pronomen", _PUBLIC, _OWNER),
        _f("first_name", "Vorname", _OWNER, _ADMIN),
        _f("last_name", "Nachname", _OWNER, _ADMIN),
        _f("email", "E-Mail", _OWN_MV, _OWN_MV),
        _f("phone", "Telefon", _OWN_MV, _OWN_MV),
        _f("is_flinta", "FLINTA", _OWN_MV, _OWN_MV),
        _f("mailbox_list_opt_in", "Briefkastenabfrage", _OWN_MV, _OWN_MV),
        _f("date_of_birth", "Geburtsdatum", _OWN_MV, _MV),
    ]),
    Section("education", "Ausbildung & Studium", [
        _f("study_subject", "Studienfach", _OWN_MV, _MV),
        _f("apprenticeship_field", "Ausbildungsbereich", _OWN_MV, _MV),
        _f("educational_institution", "Bildungseinrichtung", _OWN_MV, _MV),
    ]),
    Section("housing", "Wohnen", [
        _f("is_sublet", "Untermiete", _MV, _MV),
        _f("sublet_from", "Untermiete von", _MV, _MV),
        _f("sublet_to", "Untermiete bis", _MV, _MV),
        _f("mailbox_key", "Briefkastenschlüssel", _MV, _MV),
        _f("move_in", "Einzug", _OWN_MV, _MV),
        _f("move_out", "Auszug", _OWN_MV, _MV),
    ]),
    Section("legal", "Rechtliches", [
        _f("data_priv_signed_at", "Datenschutz unterschrieben", _OWN_MV, _MV),
        _f("photo_allowance_signed_at", "Fotoerlaubnis unterschrieben", _OWN_MV, _MV),
        _f("barrier_free_needed", "Barrierefreiheit benötigt", _OWN_MV, _MV),
        _f("soli_miete_wunsch", "Soli-Miete-Wunsch", _ADMIN, _ADMIN),
        _f("comments", "Interne Kommentare", _ADMIN, _ADMIN),
    ]),
]

# All Tenant columns that any role may edit (admin override edits these too).
EDITABLE_COLUMNS = sorted({
    f.name for s in SECTIONS for f in s.fields if f.editable_by
})

_ALL_FIELDS = [f for s in SECTIONS for f in s.fields]


def viewer_roles(user, tenant, current_tenant) -> set[str]:
    roles = {"public"}
    if current_tenant is not None and current_tenant.pk == tenant.pk:
        roles.add("owner")
    group_names = set(user.groups.values_list("name", flat=True))
    if "admins" in group_names:
        roles.add("admin")
    for role, cns in settings.TENANT_ROLE_GROUPS.items():
        if group_names.intersection(cns):
            roles.add(role)
    return roles


def visible_fields(roles: set[str]) -> set[str]:
    if "admin" in roles:
        return {f.name for f in _ALL_FIELDS}
    r = frozenset(roles)
    return {f.name for f in _ALL_FIELDS if r & f.visible_to}


def editable_fields(roles: set[str]) -> set[str]:
    if "admin" in roles:
        return {f.name for f in _ALL_FIELDS} - SYSTEM_ID_FIELDS
    r = frozenset(roles)
    return {f.name for f in _ALL_FIELDS if r & f.editable_by}
```

Note: the `_GroupsShim` in the test stands in for Django's group manager; real code calls `user.groups.values_list("name", flat=True)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_tenant_access.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add app/tenant_access.py cartei/settings.py tests/test_tenant_access.py
git commit -m "feat: tenant field-access matrix and role resolution"
```

---

### Task 3: The dynamic edit form

**Files:**
- Create: `app/forms.py` (or append if it exists)
- Test: `tests/test_tenant_form.py`

**Interfaces:**
- Consumes: `EDITABLE_COLUMNS` from `app.tenant_access`; `Tenant` model.
- Produces: `TenantForm(models.ModelForm)` accepting `allowed_fields: set[str]` kwarg; trims `self.fields` to that set; `email` validated as a proper email.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tenant_form.py
import pytest


@pytest.mark.django_db
def test_form_trims_to_allowed_fields():
    from app.forms import TenantForm
    form = TenantForm(allowed_fields={"email", "phone"})
    assert set(form.fields) == {"email", "phone"}


@pytest.mark.django_db
def test_form_rejects_bad_email():
    from app.forms import TenantForm
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de",
                              intranet_username="ab", intranet_uuid=uuid.uuid4())
    form = TenantForm(data={"email": "not-an-email"}, instance=t, allowed_fields={"email"})
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_form_saves_allowed_field():
    from app.forms import TenantForm
    from app.models import Tenant
    import uuid
    t = Tenant.objects.create(first_name="A", last_name="B", email="a@b.de",
                              intranet_username="cd", intranet_uuid=uuid.uuid4())
    form = TenantForm(data={"email": "new@b.de"}, instance=t, allowed_fields={"email"})
    assert form.is_valid(), form.errors
    form.save()
    t.refresh_from_db()
    assert t.email == "new@b.de"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tenant_form.py -v`
Expected: FAIL with `ModuleNotFoundError: app.forms` (or ImportError).

- [ ] **Step 3: Write `app/forms.py`**

```python
from django import forms

from app.models import Tenant
from app.tenant_access import EDITABLE_COLUMNS


class TenantForm(forms.ModelForm):
    # Model column is a plain CharField; declare EmailField so format is validated.
    email = forms.EmailField(required=True)

    class Meta:
        model = Tenant
        fields = EDITABLE_COLUMNS

    def __init__(self, *args, allowed_fields=None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = set(allowed_fields or [])
        for name in list(self.fields):
            if name not in allowed:
                del self.fields[name]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tenant_form.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add app/forms.py tests/test_tenant_form.py
git commit -m "feat: dynamic TenantForm trimmed to editable fields"
```

---

### Task 4: The view — GET rendering and POST save

**Files:**
- Modify: `app/views/tenant.py` (replace `tenant_detail`)
- Test: `tests/test_tenant_detail.py`

**Interfaces:**
- Consumes: `viewer_roles`, `visible_fields`, `editable_fields`, `SECTIONS` from `app.tenant_access`; `TenantForm`; mirror models from Task 1.
- Produces: `tenant_detail(request, pk)` handling GET + POST; context keys `tenant`, `sections`, `form`, `can_edit`, `room_assignments`, `enrollment_proofs`, `engagement`, `cluster_notes`.

Context-building helper: build `sections` for the template as a list of dicts
`{"key", "title", "rows": [{"label", "name", "value", "editable"}]}`, skipping
sections with no visible rows. `value` is the raw attribute; `editable` marks
which rows render as a form widget.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tenant_detail.py
import uuid
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from app.models import Tenant


def _tenant(username="owner", **kw):
    return Tenant.objects.create(
        first_name=kw.get("first_name", "Owner"), last_name="Test",
        email="owner@ca.de", intranet_username=username,
        intranet_uuid=uuid.uuid4(), preferred_name=kw.get("preferred_name", "Owzy"),
        pronouns="sie/ihr",
    )


def _login(client, username, groups=()):
    user = User.objects.create_user(username=username, password="x")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        user.groups.add(grp)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_owner_sees_edit_inputs_for_six_fields():
    t = _tenant("owner")
    c = Client()
    _login(c, "owner")
    resp = c.get(f"/tenants/{t.pk}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    for name in ["email", "phone", "is_flinta", "mailbox_list_opt_in", "preferred_name", "pronouns"]:
        assert f'name="{name}"' in body
    assert 'name="date_of_birth"' not in body  # owner sees DOB read-only


@pytest.mark.django_db
def test_stranger_sees_only_public_card():
    t = _tenant("owner")
    c = Client()
    _login(c, "stranger")
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert "Owzy" in body and "sie/ihr" in body
    assert "owner@ca.de" not in body  # email not visible to strangers
    assert 'name="preferred_name"' not in body  # no edit inputs


@pytest.mark.django_db
def test_owner_post_updates_only_allowed_field():
    t = _tenant("owner")
    c = Client()
    _login(c, "owner")
    resp = c.post(f"/tenants/{t.pk}/", {
        "email": "changed@ca.de", "phone": "123", "preferred_name": "Owzy",
        "pronouns": "sie/ihr", "is_flinta": "on", "mailbox_list_opt_in": "",
        "soli_miete_wunsch": "999",  # not editable by owner — must be ignored
    })
    assert resp.status_code in (200, 302)
    t.refresh_from_db()
    assert t.email == "changed@ca.de"
    assert str(t.soli_miete_wunsch) == "0.00"  # unchanged


@pytest.mark.django_db
def test_owner_post_bad_email_rejected():
    t = _tenant("owner")
    c = Client()
    _login(c, "owner")
    resp = c.post(f"/tenants/{t.pk}/", {
        "email": "nope", "phone": "", "preferred_name": "Owzy",
        "pronouns": "sie/ihr", "is_flinta": "", "mailbox_list_opt_in": "",
    })
    assert resp.status_code == 200
    t.refresh_from_db()
    assert t.email == "owner@ca.de"  # unchanged


@pytest.mark.django_db
def test_mietverwaltung_can_edit_dob(settings):
    settings.TENANT_ROLE_GROUPS = {"cluster": ["cluster"], "mietverwaltung": ["ag.mietverwaltung"], "finanzierung": ["ag.finanzierung"]}
    t = _tenant("someone")
    c = Client()
    _login(c, "mv", groups=["ag.mietverwaltung"])
    body = c.get(f"/tenants/{t.pk}/").content.decode()
    assert 'name="date_of_birth"' in body  # editable input for MV
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tenant_detail.py -v`
Expected: FAIL — current view renders only name; assertions on inputs fail.

- [ ] **Step 3: Rewrite `app/views/tenant.py`**

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from app.forms import TenantForm
from app.models import (
    AGAbfrageResult, ClusterNote, EnrollmentProof, Tenant, TenantRoomAssignment,
)
from app.tenant_access import SECTIONS, editable_fields, viewer_roles, visible_fields


def _current_tenant(request):
    return Tenant.objects.filter(intranet_username=request.user.username).first()


def _build_sections(tenant, form, visible, editable):
    out = []
    for section in SECTIONS:
        rows = []
        for f in section.fields:
            if f.name not in visible:
                continue
            rows.append({
                "label": f.label,
                "name": f.name,
                "value": getattr(tenant, f.name),
                "field": form[f.name] if (f.name in editable and f.name in form.fields) else None,
            })
        if rows:
            out.append({"key": section.key, "title": section.title, "rows": rows})
    return out


@login_required
def tenant_detail(request: HttpRequest, pk: int):
    tenant = get_object_or_404(Tenant, pk=pk)
    roles = viewer_roles(request.user, tenant, _current_tenant(request))
    visible = visible_fields(roles)
    editable = editable_fields(roles)

    if request.method == "POST":
        if not editable:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect("tenant_detail", pk=pk)
        form = TenantForm(request.POST, instance=tenant, allowed_fields=editable)
        if form.is_valid():
            form.save()
            messages.success(request, "Gespeichert.")
            return redirect("tenant_detail", pk=pk)
    else:
        form = TenantForm(instance=tenant, allowed_fields=editable)

    ctx = {
        "tenant": tenant,
        "sections": _build_sections(tenant, form, visible, editable),
        "form": form,
        "can_edit": bool(editable),
        "roles": roles,
    }
    # Relational read-only blocks, gated by role.
    if "housing" in {s["key"] for s in ctx["sections"]} or "mietverwaltung" in roles or "admin" in roles:
        ctx["room_assignments"] = list(
            TenantRoomAssignment.objects.filter(tenant=tenant).select_related("room__wg__building")
        ) if ("mietverwaltung" in roles or "admin" in roles) else []
    else:
        ctx["room_assignments"] = []
    if {"owner", "mietverwaltung", "admin"} & roles:
        ctx["enrollment_proofs"] = list(EnrollmentProof.objects.filter(tenant=tenant))
    else:
        ctx["enrollment_proofs"] = []
    if {"owner", "cluster", "admin"} & roles:
        ctx["engagement"] = list(
            AGAbfrageResult.objects.filter(tenant=tenant).select_related("abfrage")
        )
    else:
        ctx["engagement"] = []
    if {"cluster", "admin"} & roles:
        ctx["cluster_notes"] = list(ClusterNote.objects.filter(tenant=tenant).order_by("-created_at"))
    else:
        ctx["cluster_notes"] = []

    return render(request, "app/tenant_detail.html", ctx)
```

- [ ] **Step 4: Run tests (template does not exist yet — expect template error, not assertion error)**

Run: `uv run pytest tests/test_tenant_detail.py -v`
Expected: FAIL with `TemplateDoesNotExist` / render error. (Template is Task 5.) This confirms the view wiring runs. Proceed to Task 5 before re-running.

- [ ] **Step 5: Commit the view**

```bash
git add app/views/tenant.py
git commit -m "feat: role-scoped tenant_detail view with edit handling"
```

---

### Task 5: The template

**Files:**
- Modify: `app/templates/app/tenant_detail.html` (replace)
- Test: reuse `tests/test_tenant_detail.py` from Task 4 (now expected to pass).

**Interfaces:**
- Consumes: context from Task 4 (`tenant`, `sections`, `form`, `can_edit`, `room_assignments`, `enrollment_proofs`, `engagement`, `cluster_notes`).

- [ ] **Step 1: Write the template**

```html
{% extends "app/base.html" %}
{% block title %}{{ tenant.preferred_name|default:tenant.first_name }} {{ tenant.last_name }} — CArtei{% endblock %}
{% block content %}
<div class="ca-card" style="max-width:900px;margin:1.5rem auto;">
  <h1 style="font-size:1.4rem;font-weight:700;margin-bottom:1rem;">
    {{ tenant.preferred_name|default:tenant.first_name }} {{ tenant.last_name }}
  </h1>

  <form method="post">
    {% csrf_token %}
    {% for section in sections %}
    <details open style="margin-bottom:1rem;border:1px solid #ddd;border-radius:8px;padding:.5rem 1rem;">
      <summary style="font-weight:600;cursor:pointer;">{{ section.title }}</summary>
      <dl style="margin-top:.75rem;">
        {% for row in section.rows %}
        <dt style="font-weight:500;">{{ row.label }}</dt>
        <dd style="margin:0 0 .75rem 0;">
          {% if row.field %}
            {{ row.field }}
            {% if row.field.errors %}<div style="color:#b00;font-size:.85rem;">{{ row.field.errors }}</div>{% endif %}
          {% else %}
            {{ row.value|default:"—" }}
          {% endif %}
        </dd>
        {% endfor %}
      </dl>
    </details>
    {% endfor %}

    {% if can_edit %}
    <button type="submit" class="ca-btn" style="margin-top:.5rem;">Speichern</button>
    {% endif %}
  </form>

  {% if enrollment_proofs %}
  <details open style="margin-top:1rem;border:1px solid #ddd;border-radius:8px;padding:.5rem 1rem;">
    <summary style="font-weight:600;cursor:pointer;">Immatrikulationsnachweise</summary>
    <ul>
      {% for p in enrollment_proofs %}
      <li>{{ p.enrollment_name }} ({{ p.enrollment_type }}) — gültig bis {{ p.valid_until }}</li>
      {% endfor %}
    </ul>
  </details>
  {% endif %}

  {% if room_assignments %}
  <details open style="margin-top:1rem;border:1px solid #ddd;border-radius:8px;padding:.5rem 1rem;">
    <summary style="font-weight:600;cursor:pointer;">Zimmerzuordnung</summary>
    <ul>
      {% for a in room_assignments %}
      <li>{{ a.room.wg.building.name }} · {{ a.room.wg.name }} · Zimmer {{ a.room.name }}
          — {{ a.moved_in }}{% if a.moved_out %} bis {{ a.moved_out }}{% endif %}
          {% if a.key_handed_over %}· Schlüssel übergeben{% endif %}</li>
      {% endfor %}
    </ul>
  </details>
  {% endif %}

  {% if engagement %}
  <details open style="margin-top:1rem;border:1px solid #ddd;border-radius:8px;padding:.5rem 1rem;">
    <summary style="font-weight:600;cursor:pointer;">Engagement</summary>
    <ul>
      {% for r in engagement %}
      <li>{{ r.abfrage }} · {{ r.ag_name }} · {{ r.status }}</li>
      {% endfor %}
    </ul>
    {% if cluster_notes %}
    <p style="font-weight:500;margin-top:.75rem;">Interne Notizen (Belegium)</p>
    <ul>
      {% for n in cluster_notes %}
      <li>{{ n.created_at|date:"Y-m-d" }} · {{ n.created_by }}: {{ n.note }}</li>
      {% endfor %}
    </ul>
    {% endif %}
  </details>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 2: Run the Task 4 test suite to verify it passes**

Run: `uv run pytest tests/test_tenant_detail.py -v`
Expected: PASS (all five tests).

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 4: Commit**

```bash
git add app/templates/app/tenant_detail.html
git commit -m "feat: sectioned tenant_detail template with collapsibles"
```

---

## Self-Review

**Spec coverage:**
- Access matrix → Task 2 (`SECTIONS`, `visible_fields`, `editable_fields`). ✓
- Roles + `TENANT_ROLE_GROUPS` → Task 2. ✓
- Admin override excluding system IDs → Task 2 `editable_fields`, tested. ✓
- Public card (preferred_name + pronouns only) → Task 2 test + Task 4/5 test. ✓
- Owner edits exactly 6 → Task 2 + Task 4 tests. ✓
- Mietverwaltung edits what it sees incl. DOB → Task 2 + Task 4 tests. ✓
- Engagement owner-visible, notes cluster-only → Task 4 context gating + template. ✓
- Relational read-only (rooms, proofs, engagement, notes) → Task 1 mirrors + Task 4/5. ✓
- Collapsible native `<details>` → Task 5. ✓
- Email format validation → Task 3 test. ✓
- Trust-boundary editable recompute on POST → Task 4 (`editable` from `editable_fields(roles)`, form trimmed). ✓
- Audit gap accepted → Global Constraints, no contextvar code. ✓

**Placeholder scan:** No TBD/TODO; all steps carry runnable code and explicit expected results.

**Type consistency:** `viewer_roles(user, tenant, current_tenant)`, `visible_fields(roles)`, `editable_fields(roles)`, `TenantForm(..., allowed_fields=...)`, context keys — names identical across Tasks 2–5.

**Known follow-ups (out of scope, per spec):** per-group comment authoring; payments/Finanzierung section; editing enrollment proofs and room assignments; wiring writes through cartei_db for `entity_history` audit.
