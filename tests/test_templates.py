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
