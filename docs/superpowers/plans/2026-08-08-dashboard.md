# Dashboard Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/dashboard/` landing page as the central hub for CArtei, with a sidebar showing the current user's tenant info and AGs, and a main panel reminding them of any active engagement check.

**Architecture:** New `app/views/dashboard.py` view fetches the Tenant row and open Abfrage; a new template renders the two-panel layout. URL wiring redirects both the root `/` and the post-login redirect to `/dashboard/`. Navbar updated with a Dashboard link and logo href.

**Tech Stack:** Django 5, pytest-django, Bulma 0.9.4, existing CA inline-style system (`ca.css`)

## Global Constraints

- Language: all user-facing copy in German
- Style: use existing `.ca-card`, `.ca-button`, CSS variables (`--ca-teal`, etc.) and inline styles matching the rest of the codebase — no new CSS classes unless unavoidable
- No new dependencies
- Tests use pytest-django with `@pytest.mark.django_db`; the conftest in `tests/conftest.py` temporarily makes `managed=False` models available in SQLite test DB — no changes needed to conftest

---

### Task 1: Dashboard view, URL wiring, and tests

**Files:**
- Create: `app/views/dashboard.py`
- Create: `app/templates/app/dashboard.html` (minimal — enough to render; flesh out in Task 2)
- Create: `tests/test_views_dashboard.py`
- Modify: `app/urls.py` — add `dashboard/` pattern
- Modify: `cartei/urls.py` — update root redirect from `abfragen_list` to `dashboard`
- Modify: `cartei/settings_test.py` — update `LOGIN_REDIRECT_URL` from `/abfragen/` to `/dashboard/`

**Interfaces:**
- Produces: `dashboard` URL name, used by Task 2's navbar links
- Produces: template context variables: `tenant` (Tenant | None), `user_groups` (list[str]), `active_abfrage` (AGAbfrage | None)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_views_dashboard.py`:

```python
import uuid
from datetime import date, timedelta
import pytest
from django.contrib.auth.models import User, Group
from django.test import Client
from app.models import AGAbfrage, Tenant


def _open_abfrage():
    today = date.today()
    return AGAbfrage.objects.create(
        date=today,
        label="Aktive Abfrage",
        ends_at=today + timedelta(days=7),
        grace_ends_at=today + timedelta(days=14),
    )


def _closed_abfrage():
    today = date.today()
    return AGAbfrage.objects.create(
        date=today - timedelta(days=30),
        ends_at=today - timedelta(days=15),
        grace_ends_at=today - timedelta(days=8),
    )


def _make_tenant(username):
    return Tenant.objects.create(
        intranet_username=username,
        intranet_uuid=uuid.uuid4(),
        first_name="Ada",
        last_name="Lovelace",
        preferred_name="Ada",
    )


@pytest.mark.django_db
def test_dashboard_requires_login():
    client = Client()
    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_dashboard_returns_200():
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_shows_tenant_name():
    user = User.objects.create_user(username="ada")
    _make_tenant("ada")
    client = Client()
    client.force_login(user)
    response = client.get("/dashboard/")
    assert b"Ada" in response.content


@pytest.mark.django_db
def test_dashboard_shows_open_abfrage():
    _open_abfrage()
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert b"Aktive Abfrage" in response.content


@pytest.mark.django_db
def test_dashboard_shows_no_abfrage_message_when_none():
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert b"Keine aktive Abfrage" in response.content


@pytest.mark.django_db
def test_dashboard_shows_no_abfrage_message_when_closed():
    _closed_abfrage()
    client = Client()
    client.force_login(User.objects.create_user(username="viewer"))
    response = client.get("/dashboard/")
    assert b"Keine aktive Abfrage" in response.content


@pytest.mark.django_db
def test_dashboard_handles_missing_tenant():
    # User exists in auth but has no Tenant row — must not crash
    client = Client()
    client.force_login(User.objects.create_user(username="ghost"))
    response = client.get("/dashboard/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_shows_user_ags():
    user = User.objects.create_user(username="member")
    g, _ = Group.objects.get_or_create(name="kueche")
    user.groups.add(g)
    client = Client()
    client.force_login(user)
    response = client.get("/dashboard/")
    assert b"kueche" in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/philipp/git-repos/cartei_project/CArtei
uv run pytest tests/test_views_dashboard.py -v 2>&1 | head -30
```

Expected: errors like `NoReverseMatch` or `404` — dashboard route doesn't exist yet.

- [ ] **Step 3: Create the view**

Create `app/views/dashboard.py`:

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from app.models import AGAbfrage, Tenant

_SYSTEM_GROUPS = {"admins", "cluster"}


@login_required
def dashboard(request):
    try:
        tenant = Tenant.objects.get(intranet_username=request.user.username)
    except Tenant.DoesNotExist:
        tenant = None

    user_groups = sorted(
        g for g in request.user.groups.values_list("name", flat=True)
        if g not in _SYSTEM_GROUPS
    )

    latest = AGAbfrage.objects.order_by("-date").first()
    active_abfrage = latest if latest and latest.state in ("open", "grace") else None

    return render(request, "app/dashboard.html", {
        "tenant": tenant,
        "user_groups": user_groups,
        "active_abfrage": active_abfrage,
    })
```

- [ ] **Step 4: Add URL to `app/urls.py`**

```python
from django.urls import path

from app.views import abfragen, admin_views, dashboard

urlpatterns = [
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    path("abfragen/", abfragen.abfragen_list, name="abfragen_list"),
    path("abfragen/new/", abfragen.abfrage_new, name="abfrage_new"),
    path("abfragen/<int:pk>/", abfragen.abfrage_detail, name="abfrage_detail"),
    path("abfragen/<int:pk>/ag/<str:ag_name>/", abfragen.ag_edit, name="ag_edit"),
    path("abfragen/<int:pk>/tenants/", abfragen.abfrage_tenants, name="abfrage_tenants"),
    path("admin/", admin_views.admin_portal, name="admin_portal"),
    path("admin/sync-from-ldap/", admin_views.sync_from_ldap, name="sync_from_ldap"),
]
```

- [ ] **Step 5: Update root redirect in `cartei/urls.py`**

Change `_root` to redirect to `"dashboard"`:

```python
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path


def _root(request):
    return redirect("dashboard")


urlpatterns = [
    path("", _root),
    path("login/", auth_views.LoginView.as_view(template_name="app/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("app.urls")),
]
```

- [ ] **Step 6: Update `LOGIN_REDIRECT_URL` in `cartei/settings_test.py`**

Change line 39:
```python
LOGIN_REDIRECT_URL = "/dashboard/"
```

- [ ] **Step 7: Create minimal template**

Create `app/templates/app/dashboard.html`:

```html
{% extends "app/base.html" %}
{% block title %}Dashboard — CArtei{% endblock %}
{% block content %}
<div style="display:flex;gap:1.5rem;align-items:flex-start;">

  <div class="ca-card" style="width:260px;flex-shrink:0;">
    <h2 style="font-size:1rem;font-weight:700;margin-bottom:1rem;">Mein Profil</h2>
    <p style="font-weight:600;">
      {% if tenant %}
        {{ tenant.preferred_name|default:tenant.first_name }} {{ tenant.last_name }}
      {% else %}
        {{ request.user.username }}
      {% endif %}
    </p>
    {% if tenant.pronouns %}
      <p style="font-size:0.85rem;color:#7a7a7a;">{{ tenant.pronouns }}</p>
    {% endif %}
    {% if user_groups %}
      <div style="margin-top:1rem;">
        <p style="font-size:0.85rem;font-weight:600;color:#7a7a7a;margin-bottom:0.5rem;">Meine AGs</p>
        {% for g in user_groups %}
          <span style="display:block;font-size:0.9rem;">{{ g }}</span>
        {% endfor %}
      </div>
    {% endif %}
  </div>

  <div style="flex:1;">
    {% if active_abfrage %}
      <div class="ca-card">
        <h2 style="font-size:1rem;font-weight:700;margin-bottom:0.5rem;">Aktive Engagement-Abfrage</h2>
        <p>{{ active_abfrage.label|default:active_abfrage.date }} — endet am {{ active_abfrage.ends_at }}</p>
        {% if user_groups %}
          <div style="margin-top:1rem;display:flex;gap:0.5rem;flex-wrap:wrap;">
            {% for g in user_groups %}
              <a href="{% url 'ag_edit' active_abfrage.pk g %}" class="ca-button" style="text-decoration:none;">{{ g }} ausfüllen</a>
            {% endfor %}
          </div>
        {% endif %}
      </div>
    {% else %}
      <div class="ca-card" style="color:#7a7a7a;">
        Keine aktive Abfrage.
      </div>
    {% endif %}
  </div>

</div>
{% endblock %}
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd /Users/philipp/git-repos/cartei_project/CArtei
uv run pytest tests/test_views_dashboard.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 9: Run full test suite to check for regressions**

```bash
uv run pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 10: Commit**

```bash
git add app/views/dashboard.py app/templates/app/dashboard.html \
        tests/test_views_dashboard.py app/urls.py \
        cartei/urls.py cartei/settings_test.py
git commit -m "feat: add /dashboard/ landing page with tenant sidebar and Abfrage reminder"
```

---

### Task 2: Navbar updates

**Files:**
- Modify: `app/templates/app/base.html` — logo href → `dashboard`; add Dashboard nav link

**Interfaces:**
- Consumes: `dashboard` URL name from Task 1

- [ ] **Step 1: Update logo href and add nav link in `app/templates/app/base.html`**

In the `<nav>` section, make two changes:

1. Logo link: change `href="{% url 'abfragen_list' %}"` → `href="{% url 'dashboard' %}"`
2. Add a "Dashboard" nav link before "Abfragen" inside `.ca-navbar-right`:

```html
<a href="{% url 'dashboard' %}" class="ca-navbar-admin">Dashboard</a>
```

Full updated nav block:

```html
<nav class="ca-navbar">
  <a class="ca-navbar-logo" href="{% url 'dashboard' %}">
    <img src="https://collegiumacademicum.de/img/logo-small.png" alt="Collegium Academicum">
  </a>
  {% if request.user.is_authenticated %}
  <div class="ca-navbar-right">
    <a href="{% url 'dashboard' %}" class="ca-navbar-admin">Dashboard</a>
    <a href="{% url 'abfragen_list' %}" class="ca-navbar-admin">Abfragen</a>
    <a href="{% url 'admin_portal' %}" class="ca-navbar-admin">Admin</a>
    <span class="ca-navbar-user">{{ request.user.get_full_name|default:request.user.username }}</span>
    <form method="post" action="{% url 'logout' %}">
      {% csrf_token %}
      <button type="submit" class="ca-logout">Abmelden</button>
    </form>
  </div>
  {% endif %}
</nav>
```

- [ ] **Step 2: Run full test suite**

```bash
cd /Users/philipp/git-repos/cartei_project/CArtei
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/templates/app/base.html
git commit -m "feat: update navbar — logo and Dashboard link point to /dashboard/"
```