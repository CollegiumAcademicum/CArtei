"""Pure-function tests for the tenant-overview derived columns:
proof status (gültig / Prüfung / fehlt) and the per-survey engagement verdict.

No DB — the helpers only read attributes, so lightweight stand-ins suffice.
"""
from datetime import date, timedelta
from types import SimpleNamespace

from app.views.tenant import _engagement_verdict, _proof_status

TODAY = date(2026, 8, 17)


def _proof(verified=True, needs_review=False, valid_days=+30):
    return SimpleNamespace(
        verified_at=date(2026, 1, 1) if verified else None,
        needs_human_review=needs_review,
        valid_until=TODAY + timedelta(days=valid_days),
    )


# --- _proof_status -----------------------------------------------------------

def test_no_proofs_is_fehlt():
    s = _proof_status([], TODAY)
    assert s.state == "fehlt"


def test_verified_valid_proof_is_gueltig():
    s = _proof_status([_proof()], TODAY)
    assert s.state == "gueltig"


def test_unverified_proof_needs_pruefung():
    s = _proof_status([_proof(verified=False)], TODAY)
    assert s.state == "pruefung"
    assert s.count == 1


def test_needs_human_review_counts_as_pruefung():
    s = _proof_status([_proof(needs_review=True)], TODAY)
    assert s.state == "pruefung"
    assert s.count == 1


def test_pruefung_wins_over_a_valid_proof():
    # A tenant with a valid proof AND a new pending upload still needs action.
    s = _proof_status([_proof(), _proof(verified=False)], TODAY)
    assert s.state == "pruefung"
    assert s.count == 1


def test_expired_verified_proof_is_fehlt():
    s = _proof_status([_proof(valid_days=-1)], TODAY)
    assert s.state == "fehlt"


# --- _engagement_verdict -----------------------------------------------------

def _res(status):
    return SimpleNamespace(status=status)


def test_aktiv_in_one_ag_clears_flag():
    assert _engagement_verdict([_res("AKTIV")]) is False


def test_zu_aktiv_clears_flag():
    assert _engagement_verdict([_res("ZU_AKTIV")]) is False


def test_only_im_gespraech_is_flagged():
    assert _engagement_verdict([_res("IM_GESPRAECH")]) is True


def test_only_nicht_ausreichend_is_flagged():
    assert _engagement_verdict([_res("NICHT_AUSREICHEND")]) is True


def test_no_results_is_flagged():
    assert _engagement_verdict([]) is True


def test_one_aktiv_among_bad_clears_flag():
    assert _engagement_verdict([_res("INAKTIV"), _res("AKTIV")]) is False
