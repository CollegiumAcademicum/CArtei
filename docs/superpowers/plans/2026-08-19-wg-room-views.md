# WG list & WG detail views — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a WG list (`/wgs/`) and a WG detail (`/wgs/<pk>/`) view over existing housing data, with `as_of` occupancy time-travel and a per-WG engagement rollup.

**Architecture:** Django-only, in the `CArtei` repo. No `cartei_db` schema change and no Django migration — `wg`/`room`/`tenant_room_assignment` are already `managed=False` mirrors. Reuses `residency.py`, `tenant_access.visible_fields`, the `_room_assignment_edit.html` partial, and the engagement verdict. Cross-view helpers (`display`, `engagement_verdict`, `assignment_editable_by`, the assignment-save loop) are extracted from `app/views/tenant.py` into a new `app/views/_shared.py` so both `tenant.py` and the new `rooms.py` import them without a circular dependency.

**Tech Stack:** Python 3.14, Django 5, pytest-django, uv.

**Spec:** `docs/superpowers/specs/2026-08-19-wg-room-views-design.md`

## Global Constraints

- Repo: `CArtei` only. No `cartei_db` edits, no Django migration for domain tables.
- Mirror models stay `managed = False`. Never own domain tables from Django.
- Both views are `@login_required`, open to every authenticated user. No `@require_group`. Tenant-identifying data (occupant name) is shown only when `visible_fields(global_roles(user))` contains `first_name` — same rule as `tenant_list`.
- Engagement rollup shown only to `cluster`/`admin` roles (`bool({"cluster","admin"} & roles)`), matching `tenant_list`'s `show_surveys`.
- Assignment edit perms: `assignment_editable_by(a, roles, today)` — MV/admin always; Belegium only when `a.moved_in >= today - timedelta(days=14)`; everyone else never.
- German UI copy (Bewohner*innen, belegt/frei, Engagement, Zustand & Schäden). Code identifiers stay English.
- `as_of` parsing must never 500: an absent or unparseable value falls back to `date.today()`.
- Tests reuse the existing `tests/conftest.py` session fixture that flips `managed=False` models to managed. Run tests with the live-Postgres-free SQLite path already configured: `uv run pytest`.
- Rooms can have multiple concurrent occupants (sublets/shared); occupancy is always a list, never assumed singular.

---

### Task 1: Extract shared view helpers into `app/views/_shared.py`

Pure refactor — no behaviour change. The existing tenant-view test suite is the safety net. Moves the four cross-view helpers out of `tenant.py` so `rooms.py` can reuse them, and generalizes the per-assignment save loop to accept a scope queryset (tenant-scoped for the tenant page, WG-scoped for the WG page).

**Files:**
- Create: `app/views/_shared.py`
- Modify: `app/views/tenant.py` (remove the moved definitions, import from `_shared`, generalize the housing-save block to call the shared helper)
- Test: existing `tests/` suite (no new test file; the refactor must keep every current test green)

**Interfaces:**
- Consumes: `app.forms.TenantRoomAssignmentForm`, `app.models.TenantRoomAssignment`.
- Produces (imported by Task 3–5 and by `tenant.py`):
  - `ACTIVE_STATES: set[str]` = `{"AKTIV", "ZU_AKTIV"}`
  - `display(tenant) -> str` — `tenant.preferred_name or "First Last"`.
  - `engagement_verdict(results) -> bool` — `True` = flagged (NOT meeting engagement); `False` = met. Met when any result status is in `ACTIVE_STATES`.
  - `BELEGIUM_EDIT_WINDOW: timedelta` = `timedelta(days=14)`
  - `assignment_editable_by(a, roles, today) -> bool`
  - `submitted_assignment_forms(request, roles, today, scope_qs) -> list[tuple[assignment, TenantRoomAssignmentForm]]` — for each `assignment_ids` POST value found in `scope_qs` and editable by `roles`, build a bound `TenantRoomAssignmentForm(request.POST, instance=a, prefix=f"room_{a.pk}")`.

- [ ] **Step 1: Create `app/views/_shared.py` with the moved helpers**

```python
"""Cross-view helpers shared by the tenant and WG views. Extracted from
tenant.py so rooms.py can reuse them without a circular import."""
from datetime import timedelta

from app.forms import TenantRoomAssignmentForm
from app.models import TenantRoomAssignment

# Statuses that clear the engagement flag: being reported active in an AG.
ACTIVE_STATES = {"AKTIV", "ZU_AKTIV"}

# Belegium may edit an assignment's room data only for future move-ins and the
# first two weeks after move-in (moved_in >= today - 14d); read-only afterwards.
BELEGIUM_EDIT_WINDOW = timedelta(days=14)


def display(tenant):
    return tenant.preferred_name or f"{tenant.first_name} {tenant.last_name}".strip()


def engagement_verdict(results):
    """True = flagged for the Clustersprechende (not meeting engagement). One
    'aktiv'/'zu aktiv' AG clears it; insufficient/inactive/no report flags it."""
    return not any(r.status in ACTIVE_STATES for r in results)


def assignment_editable_by(a, roles, today):
    """Who may edit an assignment's room data. MV/admin: always. Belegium: only
    inside the move-in window. Everyone else (owner): never."""
    if {"mietverwaltung", "admin"} & roles:
        return True
    if "belegium" in roles:
        return a.moved_in >= today - BELEGIUM_EDIT_WINDOW
    return False


def submitted_assignment_forms(request, roles, today, scope_qs):
    """Bind + authorize a TenantRoomAssignmentForm for each submitted
    assignment_id that lives in scope_qs and is editable by roles."""
    forms = []
    for pk_str in request.POST.getlist("assignment_ids"):
        a = scope_qs.filter(pk=pk_str).first()
        if a and assignment_editable_by(a, roles, today):
            forms.append((a, TenantRoomAssignmentForm(request.POST, instance=a, prefix=f"room_{a.pk}")))
    return forms
```

- [ ] **Step 2: Point `tenant.py` at the shared module**

In `app/views/tenant.py`: delete the local `_ACTIVE_STATES`, `BELEGIUM_EDIT_WINDOW`, `_assignment_editable_by`, `_engagement_verdict`, and the inline `display_name = tenant.preferred_name or ...` computation. Add:

```python
from app.views._shared import (
    ACTIVE_STATES, BELEGIUM_EDIT_WINDOW, assignment_editable_by,
    display, engagement_verdict, submitted_assignment_forms,
)
```

Replace internal references: `_assignment_editable_by(...)` → `assignment_editable_by(...)`, `_engagement_verdict(...)` → `engagement_verdict(...)`, `_ACTIVE_STATES` → `ACTIVE_STATES`, and `display_name = ...` → `display_name = display(tenant)`.

Replace the housing edit-form loop (currently lines ~310-315) with the shared helper, scoped to this tenant:

```python
        a_forms = []
        new_rf = None
        if section_key == "housing" and can_edit_rooms:
            a_forms = submitted_assignment_forms(
                request, roles, today,
                TenantRoomAssignment.objects.filter(tenant=tenant),
            )
            new_rf = TenantRoomAssignmentForm(request.POST, prefix="new_room")
```

Leave the rest of the POST block (new_room handling, validation, save, redirect) unchanged.

- [ ] **Step 3: Run the full suite to prove no regression**

Run: `uv run pytest`
Expected: PASS — same count as before the refactor (baseline is 185). If any tenant test imported `_assignment_editable_by`/`_engagement_verdict` directly, update its import to the new names in `_shared`; otherwise no test changes.

- [ ] **Step 4: Commit**

```bash
git add app/views/_shared.py app/views/tenant.py
git commit -m "Extract shared view helpers (display, engagement, assignment save) into _shared"
```

---

### Task 2: `assignment_active_on(date)` occupancy predicate

The existing `active_assignment_q(d)` only checks the move-out side ("not moved out, or moving out after d"). Time-travel to a past/future date also needs the move-in bound.

**Files:**
- Modify: `app/residency.py`
- Test: `tests/test_residency.py` (create if absent)

**Interfaces:**
- Consumes: `django.db.models.Q`, existing `active_assignment_q`.
- Produces: `assignment_active_on(d) -> Q` — an assignment is active on date `d` when `moved_in <= d` AND (`moved_out` is null OR `moved_out > d`). Used by Task 3 and Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_residency.py
import datetime
from app.residency import assignment_active_on


def _filters_to_sql(q):
    from app.models import TenantRoomAssignment
    return str(TenantRoomAssignment.objects.filter(q).query)


def test_active_on_bounds_both_sides():
    d = datetime.date(2026, 6, 1)
    sql = _filters_to_sql(assignment_active_on(d))
    assert "moved_in" in sql and "moved_out" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_residency.py -v`
Expected: FAIL with `ImportError: cannot import name 'assignment_active_on'`.

- [ ] **Step 3: Implement the helper**

Add to `app/residency.py`:

```python
def assignment_active_on(d):
    """An assignment is active on date d: moved in on/before d and not yet moved
    out on d. The move-in bound is what makes point-in-time (past/future) travel
    correct — active_assignment_q(d) alone only checks the move-out side."""
    return Q(moved_in__lte=d) & active_assignment_q(d)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_residency.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/residency.py tests/test_residency.py
git commit -m "Add assignment_active_on(date) point-in-time occupancy predicate"
```

---

### Task 3: WG list view (`/wgs/`)

All rooms grouped Building › WG, with as-of occupancy. Links each WG to its detail.

**Files:**
- Create: `app/views/rooms.py`
- Create: `app/templates/app/wg_list.html`
- Modify: `app/urls.py` (add route + import), `app/templates/app/base.html` (nav link)
- Test: `tests/test_room_views.py`

**Interfaces:**
- Consumes: `assignment_active_on` (Task 2); `display` (Task 1); `global_roles`, `visible_fields` from `app.tenant_access`.
- Produces: `wg_list(request)` view, url name `wg_list`; `parse_as_of(request) -> date` helper (also used by Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_room_views.py
import datetime
import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from app.models import Building, Room, Tenant, TenantRoomAssignment, WG

pytestmark = pytest.mark.django_db


def _login(client, *groups):
    u = User.objects.create_user("staff", password="x")
    for g in groups:
        u.groups.add(Group.objects.get_or_create(name=g)[0])
    client.force_login(u)
    return u


def _housing():
    b = Building.objects.create(name="Haus A")
    wg = WG.objects.create(building=b, name="WG 1", cluster="1A")
    room = Room.objects.create(wg=wg, name="Zimmer 1", size_sqm=15)
    t = Tenant.objects.create(
        first_name="Mira", last_name="Muster", email="m@x.de",
        intranet_username="mira", intranet_uuid="00000000-0000-0000-0000-000000000001",
    )
    return b, wg, room, t


def test_list_groups_rooms_under_wg(client):
    _login(client, "mietverwaltung")
    b, wg, room, t = _housing()
    resp = client.get(reverse("wg_list"))
    assert resp.status_code == 200
    assert b"Haus A" in resp.content and b"WG 1" in resp.content and b"Zimmer 1" in resp.content


def test_list_asof_occupancy(client):
    _login(client, "mietverwaltung")
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room,
        moved_in=datetime.date(2026, 1, 1), moved_out=datetime.date(2026, 3, 1),
    )
    inside = client.get(reverse("wg_list"), {"as_of": "2026-02-01"})
    assert b"Mira" in inside.content
    after = client.get(reverse("wg_list"), {"as_of": "2026-06-01"})
    assert b"Mira" not in after.content  # frei on that date


def test_list_hides_name_without_permission(client):
    _login(client, "cluster")  # cluster does not grant first_name
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    resp = client.get(reverse("wg_list"))
    assert b"Mira" not in resp.content
    assert b"belegt" in resp.content


def test_list_bad_as_of_falls_back(client):
    _login(client, "mietverwaltung")
    _housing()
    resp = client.get(reverse("wg_list"), {"as_of": "not-a-date"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_room_views.py -v`
Expected: FAIL — `NoReverseMatch: 'wg_list'` (route not defined yet).

- [ ] **Step 3: Implement the view**

```python
# app/views/rooms.py
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
from django.shortcuts import render

from app.models import Building, Room, TenantRoomAssignment
from app.residency import assignment_active_on
from app.tenant_access import global_roles, visible_fields
from app.views._shared import display


def parse_as_of(request: HttpRequest) -> date:
    """?as_of=YYYY-MM-DD, defaulting to today. Never raises on bad input."""
    raw = request.GET.get("as_of")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def _occupants_by_room(as_of, may_see_names):
    """room_id -> list of occupant labels active on as_of."""
    out: dict[int, list[str]] = {}
    qs = (
        TenantRoomAssignment.objects.filter(assignment_active_on(as_of))
        .select_related("tenant")
    )
    for a in qs:
        out.setdefault(a.room_id, []).append(display(a.tenant) if may_see_names else "belegt")
    return out


@login_required
def wg_list(request: HttpRequest):
    roles = global_roles(request.user)
    may_see_names = "first_name" in visible_fields(roles)
    as_of = parse_as_of(request)
    occ = _occupants_by_room(as_of, may_see_names)

    buildings = []
    for b in Building.objects.order_by("name"):
        wgs = []
        for wg in b.wg_set.order_by("name"):
            rooms = []
            for room in Room.objects.filter(wg=wg).order_by("name"):
                rooms.append({"room": room, "occupants": occ.get(room.id, [])})
            wgs.append({"wg": wg, "rooms": rooms})
        buildings.append({"building": b, "wgs": wgs})

    return render(request, "app/wg_list.html", {
        "buildings": buildings, "as_of": as_of, "may_see_names": may_see_names,
    })
```

Note: `b.wg_set` / `Room.objects.filter(wg=wg)` rely on the default reverse manager; if the mirror FK defines a different related name, use `WG.objects.filter(building=b)`. Verify against `app/models.py` when implementing and adjust the two loops accordingly.

- [ ] **Step 4: Create the template**

```django
{% extends "app/base.html" %}
{% block content %}
<h1 style="font-size:1.4rem;font-weight:700;">WGs & Zimmer</h1>
<form method="get" style="margin:.5rem 0 1rem;">
  <label>Stichtag <input type="date" name="as_of" value="{{ as_of|date:'Y-m-d' }}"></label>
  <button type="submit" class="ca-button">Anzeigen</button>
</form>
{% for b in buildings %}
  <h2 style="font-size:1.1rem;font-weight:700;margin-top:1rem;">{{ b.building.name }}</h2>
  {% for w in b.wgs %}
    <h3 style="font-size:1rem;"><a href="{% url 'wg_detail' w.wg.pk %}?as_of={{ as_of|date:'Y-m-d' }}">{{ w.wg.name }}</a>{% if w.wg.cluster %} · Cluster {{ w.wg.cluster }}{% endif %}</h3>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr><th style="text-align:left;">Zimmer</th><th style="text-align:left;">m²</th><th style="text-align:left;">Belegung</th></tr></thead>
      <tbody>
      {% for r in w.rooms %}
        <tr>
          <td>{{ r.room.name }}{% if r.room.freifinanziert %} <span class="ca-room-badge">freifinanziert</span>{% endif %}</td>
          <td>{{ r.room.size_sqm }}</td>
          <td>
            {% if r.occupants %}
              {% if may_see_names %}{{ r.occupants|join:", " }}{% else %}belegt ({{ r.occupants|length }}){% endif %}
            {% else %}frei{% endif %}
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  {% endfor %}
{% endfor %}
{% endblock %}
```

- [ ] **Step 5: Wire the route and nav link**

In `app/urls.py`: import `rooms` alongside the other view modules and add:

```python
    path("wgs/", rooms.wg_list, name="wg_list"),
```

In `app/templates/app/base.html`, after the Bewohner*innen nav link (line ~22):

```django
    <a href="{% url 'wg_list' %}" class="ca-navbar-admin">WGs</a>
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_room_views.py -v`
Expected: PASS (all four list tests).

- [ ] **Step 7: Commit**

```bash
git add app/views/rooms.py app/templates/app/wg_list.html app/urls.py app/templates/app/base.html tests/test_room_views.py
git commit -m "Add WG list view (/wgs/) with as-of occupancy and name gating"
```

---

### Task 4: WG detail — history, as-of highlight, engagement rollup, damage stub

Read side of the detail page: every room's full assignment history, the assignment(s) active on `as_of` visually marked, an engagement rollup counted against the most-recent-as-of-date survey, and a "Zustand & Schäden" stub.

**Files:**
- Modify: `app/views/rooms.py` (add `wg_detail` + `_engagement_rollup`), `app/urls.py` (route)
- Create: `app/templates/app/wg_detail.html`
- Test: `tests/test_room_views.py` (add cases)

**Interfaces:**
- Consumes: `parse_as_of`, `assignment_active_on`, `engagement_verdict` (Task 1), `assignment_editable_by` (Task 1 — used to compute the per-assignment `aform` in Task 5; here pass `None`), `global_roles`/`visible_fields`.
- Produces: `wg_detail(request, pk)` view, url name `wg_detail`; `_engagement_rollup(tenant_ids, as_of) -> dict | None` returning `{"met": int, "total": int, "abfrage": AGAbfrage}` or `None` when no survey qualifies.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_room_views.py
from app.models import AGAbfrage, AGAbfrageResult


def test_detail_shows_history_and_asof_marker(client):
    _login(client, "mietverwaltung")
    b, wg, room, t = _housing()
    TenantRoomAssignment.objects.create(
        tenant=t, room=room,
        moved_in=datetime.date(2026, 1, 1), moved_out=datetime.date(2026, 3, 1),
    )
    resp = client.get(reverse("wg_detail", args=[wg.pk]), {"as_of": "2026-02-01"})
    assert resp.status_code == 200
    assert b"Zimmer 1" in resp.content
    assert b"wg-current" in resp.content  # active-on-date marker present


def test_detail_engagement_rollup_time_travels(client):
    _login(client, "admin")
    b, wg, room, t = _housing()
    t2 = Tenant.objects.create(
        first_name="Ada", last_name="Test", email="a@x.de",
        intranet_username="ada", intranet_uuid="00000000-0000-0000-0000-000000000002",
    )
    room2 = Room.objects.create(wg=wg, name="Zimmer 2", size_sqm=12)
    for tt, rr in ((t, room), (t2, room2)):
        TenantRoomAssignment.objects.create(tenant=tt, room=rr, moved_in=datetime.date(2026, 1, 1), moved_out=None)
    old = AGAbfrage.objects.create(date=datetime.date(2026, 1, 15), ends_at=datetime.date(2026, 2, 1), grace_ends_at=datetime.date(2026, 2, 8))
    new = AGAbfrage.objects.create(date=datetime.date(2026, 5, 15), ends_at=datetime.date(2026, 6, 1), grace_ends_at=datetime.date(2026, 6, 8))
    # In the old survey only Mira is active; in the new survey nobody is.
    AGAbfrageResult.objects.create(abfrage=old, ag_name="Garten", tenant=t, status="AKTIV")
    # as_of before the new survey -> uses `old` -> 1 von 2 met
    resp = client.get(reverse("wg_detail", args=[wg.pk]), {"as_of": "2026-03-01"})
    assert b"1 von 2" in resp.content
    # as_of after the new survey -> uses `new` -> 0 von 2 met
    resp2 = client.get(reverse("wg_detail", args=[wg.pk]), {"as_of": "2026-07-01"})
    assert b"0 von 2" in resp2.content


def test_detail_engagement_hidden_for_non_cluster(client):
    _login(client, "mietverwaltung")  # not cluster/admin
    b, wg, room, t = _housing()
    resp = client.get(reverse("wg_detail", args=[wg.pk]))
    assert b"erf\xc3\xbcllen ihr Engagement" not in resp.content
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_room_views.py -k detail -v`
Expected: FAIL — `NoReverseMatch: 'wg_detail'`.

- [ ] **Step 3: Implement `_engagement_rollup` and `wg_detail`**

Add to `app/views/rooms.py`:

```python
from django.shortcuts import get_object_or_404
from app.models import AGAbfrage, AGAbfrageResult, WG
from app.views._shared import assignment_editable_by, engagement_verdict


def _engagement_rollup(tenant_ids, as_of):
    """met/total over tenant_ids against the most recent Abfrage as of as_of
    (latest AGAbfrage.date <= as_of). None when no survey qualifies."""
    if not tenant_ids:
        return None
    ab = AGAbfrage.objects.filter(date__lte=as_of).order_by("-date").first()
    if ab is None:
        return None
    results = AGAbfrageResult.objects.filter(abfrage=ab, tenant_id__in=tenant_ids)
    by_tenant: dict[int, list] = {tid: [] for tid in tenant_ids}
    for r in results:
        by_tenant[r.tenant_id].append(r)
    met = sum(0 if engagement_verdict(rs) else 1 for rs in by_tenant.values())
    return {"met": met, "total": len(tenant_ids), "abfrage": ab}


@login_required
def wg_detail(request: HttpRequest, pk: int):
    wg = get_object_or_404(WG, pk=pk)
    roles = global_roles(request.user)
    may_see_names = "first_name" in visible_fields(roles)
    show_engagement = bool({"cluster", "admin"} & roles)
    as_of = parse_as_of(request)
    today = date.today()

    active_pks = set(
        TenantRoomAssignment.objects.filter(assignment_active_on(as_of), room__wg=wg)
        .values_list("id", flat=True)
    )

    rooms = []
    active_tenant_ids: set[int] = set()
    for room in Room.objects.filter(wg=wg).order_by("name"):
        assignments = list(
            TenantRoomAssignment.objects.filter(room=room)
            .select_related("tenant", "room__wg__building", "sublet_of_tenant")
            .order_by("-moved_in")
        )
        cards = []
        for a in assignments:
            a.active_on_asof = a.id in active_pks
            if a.active_on_asof:
                active_tenant_ids.add(a.tenant_id)
            # aform stays None here; Task 5 fills it in for editable assignments.
            cards.append({"assignment": a, "aform": None})
        rooms.append({"room": room, "cards": cards})

    rollup = _engagement_rollup(list(active_tenant_ids), as_of) if show_engagement else None

    return render(request, "app/wg_detail.html", {
        "wg": wg, "as_of": as_of, "rooms": rooms,
        "show_engagement": show_engagement, "rollup": rollup,
        "may_see_names": may_see_names,
    })
```

- [ ] **Step 4: Create the template**

```django
{% extends "app/base.html" %}
{% block content %}
<h1 style="font-size:1.4rem;font-weight:700;">{{ wg.name }}</h1>
<p style="color:#666;">{% if wg.cluster %}Cluster {{ wg.cluster }}{% endif %}</p>
<form method="get" style="margin:.5rem 0 1rem;">
  <label>Stichtag <input type="date" name="as_of" value="{{ as_of|date:'Y-m-d' }}"></label>
  <button type="submit" class="ca-button">Anzeigen</button>
</form>

{% if show_engagement %}
<div class="ca-card" style="margin-bottom:1rem;">
  {% if rollup %}
    <strong>{{ rollup.met }} von {{ rollup.total }}</strong> erfüllen ihr Engagement
    <span style="color:#888;">(Abfrage {{ rollup.abfrage.label|default:rollup.abfrage.date }})</span>
  {% else %}
    <span style="color:#888;">Kein Engagement auswertbar (keine Abfrage / keine Bewohner*innen am Stichtag).</span>
  {% endif %}
</div>
{% endif %}

{% for r in rooms %}
  <h3 style="font-size:1rem;margin-top:1rem;">{{ r.room.name }}</h3>
  {% for c in r.cards %}
    <div class="{% if c.assignment.active_on_asof %}wg-current{% endif %}">
      {% include "app/_room_assignment_edit.html" with assignment=c.assignment aform=c.aform %}
    </div>
  {% empty %}
    <p style="color:#888;">Keine Belegung erfasst.</p>
  {% endfor %}
{% endfor %}

<details class="ca-collapse" style="margin-top:1.5rem;border:1px solid #ddd;border-radius:8px;padding:.5rem 1rem;">
  <summary style="font-weight:700;">Zustand & Schäden</summary>
  <p style="color:#888;">Schadenskatalog und Übergabeprotokolle folgen in einem späteren Schritt.</p>
</details>
{% endblock %}
```

- [ ] **Step 5: Wire the route**

In `app/urls.py`, after the `wgs/` list route:

```python
    path("wgs/<int:pk>/", rooms.wg_detail, name="wg_detail"),
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_room_views.py -v`
Expected: PASS (list + detail cases). If `_room_assignment_edit.html` references a context var not passed (it guards `can_see_assignment_docs`/`show_assignment_notes` with `{% if %}`, so absent = off), no change needed.

- [ ] **Step 7: Commit**

```bash
git add app/views/rooms.py app/templates/app/wg_detail.html app/urls.py tests/test_room_views.py
git commit -m "Add WG detail view: history, as-of marker, time-traveling engagement rollup, damage stub"
```

---

### Task 5: WG detail — inline assignment editing

Make the assignment cards editable in place, reusing the exact tenant-page mechanism: the partial's field widgets attach to a per-card `<form>` that POSTs (no `action`) back to `wg_detail`, which authorizes and saves via the shared helper scoped to this WG.

**Files:**
- Modify: `app/views/rooms.py` (`wg_detail`: build `aform` per editable assignment; handle POST)
- Test: `tests/test_room_views.py` (add cases)

**Interfaces:**
- Consumes: `submitted_assignment_forms`, `assignment_editable_by` (Task 1); `TenantRoomAssignmentForm` from `app.forms`.
- Produces: no new symbols; `wg_detail` now accepts POST.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_room_views.py
from app.forms import TenantRoomAssignmentForm  # noqa: F401  (ensures import path is valid)


def test_detail_mv_can_edit_assignment(client):
    _login(client, "mietverwaltung")
    b, wg, room, t = _housing()
    a = TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    resp = client.post(reverse("wg_detail", args=[wg.pk]), {
        "section": "housing",
        "assignment_ids": str(a.pk),
        f"room_{a.pk}-room": str(room.pk),
        f"room_{a.pk}-moved_in": "2026-01-05",
        f"room_{a.pk}-is_sublet": "",
    })
    assert resp.status_code in (200, 302)
    a.refresh_from_db()
    assert a.moved_in == datetime.date(2026, 1, 5)


def test_detail_owner_cannot_edit(client):
    _login(client, "cluster")  # neither MV/admin nor belegium
    b, wg, room, t = _housing()
    a = TenantRoomAssignment.objects.create(
        tenant=t, room=room, moved_in=datetime.date(2026, 1, 1), moved_out=None,
    )
    client.post(reverse("wg_detail", args=[wg.pk]), {
        "section": "housing", "assignment_ids": str(a.pk),
        f"room_{a.pk}-room": str(room.pk), f"room_{a.pk}-moved_in": "2026-02-02",
    })
    a.refresh_from_db()
    assert a.moved_in == datetime.date(2026, 1, 1)  # unchanged — read-only for this role
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_room_views.py -k "edit or cannot" -v`
Expected: FAIL — the MV edit test fails because `moved_in` is unchanged (no POST handling yet).

- [ ] **Step 3: Implement editing in `wg_detail`**

At the top of `wg_detail` (after computing `roles`, `today`), add POST handling that saves and redirects back to the same page + as_of:

```python
    from django.contrib import messages
    from django.shortcuts import redirect

    can_edit_rooms = bool({"mietverwaltung", "admin", "belegium"} & roles)
    if request.method == "POST":
        if not can_edit_rooms:
            messages.error(request, "Keine Berechtigung zum Bearbeiten.")
            return redirect(f"{request.path}?as_of={parse_as_of(request):%Y-%m-%d}")
        a_forms = submitted_assignment_forms(
            request, roles, today,
            TenantRoomAssignment.objects.filter(room__wg=wg),
        )
        if all(rf.is_valid() for _, rf in a_forms):
            for _, rf in a_forms:
                rf.save()
            messages.success(request, "Gespeichert.")
            return redirect(f"{request.path}?as_of={parse_as_of(request):%Y-%m-%d}")
        messages.error(request, "Bitte Eingaben prüfen.")
        # fall through to re-render; failed forms are re-bound below by pk match
        failed = {a.pk: rf for a, rf in a_forms}
    else:
        failed = {}
```

Then, where each card is built, attach an editable form for authorized assignments (re-using a failed bound form when present):

```python
        for a in assignments:
            a.active_on_asof = a.id in active_pks
            if a.active_on_asof:
                active_tenant_ids.add(a.tenant_id)
            if can_edit_rooms and assignment_editable_by(a, roles, today):
                aform = failed.get(a.pk) or TenantRoomAssignmentForm(instance=a, prefix=f"room_{a.pk}")
            else:
                aform = None
            cards.append({"assignment": a, "aform": aform})
```

Move the `messages`/`redirect` imports to the module top with the other imports rather than inline (inline shown only to localize the change).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_room_views.py -v`
Expected: PASS — MV edit persists `moved_in`; cluster role leaves it unchanged.

- [ ] **Step 5: Full-suite regression**

Run: `uv run pytest`
Expected: PASS across the whole suite (baseline 185 + the new room-view tests).

- [ ] **Step 6: Commit**

```bash
git add app/views/rooms.py tests/test_room_views.py
git commit -m "Enable inline assignment editing on WG detail (WG-scoped, existing perms)"
```

---

## Self-Review

**Spec coverage:**
- `/wgs/` list grouped Building › WG, as-of occupancy, name gating → Task 3. ✅
- `/wgs/<pk>/` detail with room assignment history → Task 4. ✅
- `as_of` on both views, never-500 parsing → Task 3 (`parse_as_of`, bad-input test) + Task 2 (`assignment_active_on`). ✅
- Multiple concurrent occupants (list, not singular) → `_occupants_by_room` returns lists (Task 3); detail marks every active assignment (Task 4); engagement counts distinct residents via a set (Task 4). ✅
- Engagement rollup time-travels to most-recent-as-of-date survey, distinct residents, cluster/admin-only → Task 4 (`_engagement_rollup`, time-travel + hidden-for-non-cluster tests). ✅
- Reuse edit partial + existing perms (MV/admin always, Belegium 14-day window) → Task 5 reuses `_room_assignment_edit.html` + `assignment_editable_by`; edit + read-only tests. ✅
- Zustand & Schäden stub seam → Task 4 template `<details>`. ✅
- No schema change / no migration → Global Constraints; nothing in any task touches `cartei_db` or `manage.py migrate`. ✅
- Ceiling: engagement uses current result rows, not `entity_history` snapshot → matches spec's `ponytail:` note; not implemented by design. ✅

**Placeholder scan:** No TBD/TODO; every code step carries runnable content. Two implementer-verification notes are explicit and bounded (reverse-manager name for `b.wg_set`; moving inline imports to module top) rather than vague "handle appropriately" gaps.

**Type consistency:** `engagement_verdict` returns `True`=flagged everywhere (Task 1 definition; Task 4 computes `met = 0 if verdict else 1`). `assignment_editable_by(a, roles, today)` signature identical in Tasks 1, 4, 5. `parse_as_of(request)` defined in Task 3, reused in Task 4/5. `submitted_assignment_forms(request, roles, today, scope_qs)` signature identical in Task 1 (definition + tenant.py caller) and Task 5 caller. `wg_list`/`wg_detail` url names consistent between views, urls, templates, and tests.
