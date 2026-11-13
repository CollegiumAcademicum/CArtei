import re
from pathlib import Path


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
