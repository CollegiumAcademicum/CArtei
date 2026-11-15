import re
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.test import Client


def test_no_inline_submit_confirms():
    # base.html's capture-phase form handler POSTs before an inline onsubmit
    # confirm() runs, so "Abbrechen" wouldn't cancel. Use data-confirm instead.
    offenders = [
        str(p) for p in Path("app/templates").rglob("*.html")
        if "onsubmit=" in p.read_text()
    ]
    assert offenders == []


def test_no_inline_event_handlers():
    # The CSP (settings.SECURE_CSP) blocks inline on*= handlers; use data-*
    # attributes wired in app/static/app/ui.js or a nonce'd <script>.
    offenders = [
        str(p) for p in Path("app/templates").rglob("*.html")
        if re.search(r"\son[a-z]+=", p.read_text())
    ]
    assert offenders == []


def test_inline_scripts_carry_csp_nonce():
    # An inline <script> without the nonce is blocked by the CSP.
    offenders = [
        str(p) for p in Path("app/templates").rglob("*.html")
        for tag in re.findall(r"<script\b[^>]*>", p.read_text())
        if "src=" not in tag and 'nonce="{{ csp_nonce }}"' not in tag
    ]
    assert offenders == []


@pytest.mark.django_db
def test_navbar_has_burger_for_authenticated_user():
    c = Client()
    c.force_login(User.objects.create_user(username="nav"))
    html = c.get("/dashboard/").content.decode()
    assert "data-navbar-burger" in html
    assert 'aria-controls="ca-navbar-menu"' in html
    assert 'id="ca-navbar-menu"' in html


def test_burger_toggle_wired_in_ui_js():
    # The navbar sits outside .ca-main, but the toggle must be delegated on
    # document like the other ui.js behaviors.
    js = Path("app/static/app/ui.js").read_text()
    assert "[data-navbar-burger]" in js and "is-active" in js and "aria-expanded" in js


@pytest.mark.django_db
def test_burger_is_a_keyboard_focusable_button():
    # Desktop users zoomed into burger range must reach the menu by keyboard.
    c = Client()
    c.force_login(User.objects.create_user(username="kbd"))
    html = c.get("/dashboard/").content.decode()
    assert '<button type="button" class="navbar-burger"' in html


def test_dev_login_uses_bulma_navbar():
    html = Path("app/templates/app/dev_login.html").read_text()
    assert 'class="navbar ca-navbar"' in html and "navbar-brand" in html


def test_stack_table_cells_have_no_inline_padding():
    # Inline padding beats the ≤768px card rules (e.g. room reserved for the
    # top-right action buttons), so stacked cells must take it from ca.css.
    src = Path("app/templates/app/tenant_detail.html").read_text()
    assert not re.search(r'<td (data-label="[^"]*" |class="ca-stack-actions" )style="padding', src)


def test_nav_focus_keeps_ca_colours():
    # Bulma's a.navbar-item:focus/:focus-within would turn links blue on grey.
    css = Path("app/static/app/ca.css").read_text()
    assert ".ca-navbar a.navbar-item:focus" in css and ".ca-navbar a.navbar-item:focus-within" in css


def test_card_tables_only_scroll_below_600px():
    # display:block on Bulma tables breaks is-fullwidth; keep that fallback to
    # phones so admin tables still span the card on 601–768px tablets.
    css = Path("app/static/app/ca.css").read_text()
    phone = css.split("@media (max-width: 600px) {\n  .ca-card .table", 1)
    assert len(phone) == 2
    tablet = css.split("@media (max-width: 768px)", 1)[1]
    assert ".ca-card .table { display: block" not in tablet
