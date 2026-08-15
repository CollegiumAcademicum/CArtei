from app.templatetags.proof_extras import middle_truncate


def test_short_name_unchanged():
    assert middle_truncate("proof.pdf") == "proof.pdf"


def test_long_name_keeps_extension_and_head():
    out = middle_truncate("immatrikulationsbescheinigung_ws2025.pdf", 28)
    assert len(out) == 28
    assert "…" in out
    assert out.startswith("immatrik")
    assert out.endswith(".pdf")
