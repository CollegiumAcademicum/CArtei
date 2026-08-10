    # Dashboard Landing Page — Design Spec

**Date:** 2026-08-08  
**Status:** Approved

## Goal

Add a `/dashboard/` route as the central entry point for CArtei. Currently the app drops users straight into `/abfragen/`. The dashboard gives each user a personal context pane and surfaces any active engagement check that needs their attention.

## Architecture

| Layer | Change |
|---|---|
| URL | New `dashboard/` pattern in `app/urls.py`; root `/` redirect updated to `dashboard` |
| View | `app/views/dashboard.py` — new file, single `dashboard` view |
| Template | `app/templates/app/dashboard.html` |
| Navbar | Logo href → `dashboard`; add "Dashboard" nav link next to "Abfragen" |

## Layout

Two-panel sidebar layout (same card/CSS system as existing pages):

```
┌─────────────────────────────────────────────────┐
│  Navbar                                          │
├───────────────┬─────────────────────────────────┤
│  Sidebar      │  Main panel                      │
│  (~25%)       │  (~75%)                          │
│               │                                  │
│  Name         │  Active Abfrage reminder card    │
│  Pronouns     │  — or —                          │
│  AGs list     │  "Keine aktive Abfrage"          │
│               │                                  │
└───────────────┴─────────────────────────────────┘
```

## Data

### Sidebar

- `Tenant` row fetched by `intranet_username=request.user.username`
- Display: `preferred_name` if set, else `first_name + last_name`; pronouns if set
- AGs: `request.user.groups` minus system groups (`admins`, `cluster`)
- If no Tenant record exists: show username only, no crash

### Main panel

- Fetch latest `AGAbfrage.objects.order_by("-date").first()`
- Call `.state` property (Python-side: `open` / `grace` / `closed`)
- **Open or grace:** reminder card with abfrage label/date, deadline (`ends_at`), and per-AG links to `ag_edit` for each of the user's AGs
- **Closed or none:** quiet "Keine aktive Abfrage" message

## Permissions

`@login_required` only — same as `abfragen_list`. No role restriction; sidebar and reminder adapt to whatever groups the user has.

## Out of scope (add later)

- Multiple simultaneous open Abfragen shown at once
- Widget grid / pluggable cards
- Tenant profile editing