from pathlib import Path


def test_no_inline_submit_confirms():
    # base.html's capture-phase form handler POSTs before an inline onsubmit
    # confirm() runs, so "Abbrechen" wouldn't cancel. Use data-confirm instead.
    offenders = [
        str(p) for p in Path("app/templates").rglob("*.html")
        if "onsubmit=" in p.read_text()
    ]
    assert offenders == []
