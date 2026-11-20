"""Tests de parité et de contrat du moteur de bankroll (spec 004).

Les valeurs de référence viennent de `docs/probabilites.md` §2 et §6. Le Rust
est la source de vérité : ces tests vérifient que le runtime Python obtient
exactement les mêmes nombres, et que l'enveloppe dégradée reste sûre.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot import bankroll
from src.bot.bankroll import (
    ASSESSMENT_FIELDS,
    BankrollAuditLog,
    SessionLimits,
    evaluate_plan_cash,
)

pytestmark = pytest.mark.skipif(
    not bankroll.NATIVE_BANKROLL_AVAILABLE,
    reason="extension native postflop_solver_py absente",
)


# --------------------------------------------------------------------------- #
# Parité avec les tables du doc
# --------------------------------------------------------------------------- #


def test_ror_cash_matches_doc_6max_wr7_40bi():
    """§6.2 — 6-max WR 7, σ 90, 40 BI → 0,10 %."""
    ror = bankroll.risk_of_ruin_cash(7.0, 90.0, 40.0)
    assert ror is not None
    assert ror == pytest.approx(0.001, abs=5e-5)


def test_ror_cash_matches_doc_hu_wr5_20bi():
    """§6.1 — HU WR 5, σ 70, 20 BI → 1,69 %."""
    assert bankroll.risk_of_ruin_cash(5.0, 70.0, 20.0) == pytest.approx(0.0169, abs=1e-3)


def test_ror_mtt_matches_doc_roi15_50bi():
    """§6.3 — MTT ROI 15 %, σ 1,9 BI, 50 BI → 1,57 %."""
    assert bankroll.risk_of_ruin_mtt(0.15, 1.9, 50.0) == pytest.approx(0.0157, abs=1e-3)


def test_probability_of_profit_matches_doc_50k():
    """§2.2 — 6-max WR 7, σ 90, 50 000 mains → 96 %."""
    assert bankroll.probability_of_profit_cash(7.0, 90.0, 50_000) == pytest.approx(0.96, abs=0.01)


def test_invalid_inputs_return_none():
    assert bankroll.risk_of_ruin_cash(7.0, 0.0, 40.0) is None
    assert bankroll.probability_of_profit_cash(7.0, 0.0, 100) is None
    assert bankroll.kelly_fraction(0.0, 0.81) is None


def test_risk_band_names_are_stable():
    assert bankroll.risk_band(0.0005) == "safe"
    assert bankroll.risk_band(0.03) == "acceptable"
    assert bankroll.risk_band(0.10) == "elevated"
    assert bankroll.risk_band(0.50) == "excessive"


def test_bankroll_for_target_ror_round_trip():
    target = 0.01
    roll = bankroll.bankroll_for_target_ror(0.07, 0.81, target)
    assert roll is not None
    assert bankroll.risk_of_ruin_cash(7.0, 90.0, roll) == pytest.approx(target, abs=1e-4)
    # Le seuil documenté de 40 BI doit ramener le RoR 6-max sous 1 %.
    assert roll < 40.0


def test_assess_cash_exposes_documented_fields():
    assessment = bankroll.assess_cash(7.0, 90.0, 40.0)
    assert assessment is not None
    assert set(ASSESSMENT_FIELDS) <= set(assessment)
    assert assessment["format"] == "cash"
    assert assessment["risk_band"] == "safe"
    assert assessment["ror"] == pytest.approx(0.001, abs=5e-5)


# --------------------------------------------------------------------------- #
# Limites de session
# --------------------------------------------------------------------------- #


def test_session_verdict_matches_python_fallback_semantics():
    limits = SessionLimits()
    assert bankroll.session_verdict(limits, 1.0, 0.0) is None
    assert bankroll.session_verdict(limits, 4.5, 0.0) == "max_duration"
    assert bankroll.session_verdict(limits, 1.0, -3.5) == "stop_loss"
    assert bankroll.session_verdict(limits, 1.0, 12.0) == "stop_win"
    # La durée prime sur le stop-loss.
    assert bankroll.session_verdict(limits, 5.0, -5.0) == "max_duration"


def test_session_verdict_daily_hands_cap():
    limits = SessionLimits(max_hands_per_day=500)
    assert bankroll.session_verdict(limits, 1.0, 0.0, hands_today=499) is None
    assert bankroll.session_verdict(limits, 1.0, 0.0, hands_today=500) == "daily_hands"


def test_default_limits_preserve_session_manager_behaviour():
    """Non-régression : les seuils par défaut sont ceux de `SessionManager`."""
    limits = SessionLimits()
    assert limits.max_hours == 4.0
    assert limits.stop_loss_buyins == 3.0
    assert limits.stop_win_buyins == 10.0
    assert limits.max_hands_per_day == 0


# --------------------------------------------------------------------------- #
# Journal d'audit
# --------------------------------------------------------------------------- #


def test_audit_entry_schema_and_round_trip(tmp_path):
    log_path = tmp_path / "audit" / "bankroll.jsonl"
    audit = BankrollAuditLog(log_path)

    entry = evaluate_plan_cash(
        7.0,
        90.0,
        40.0,
        hours_played=1.0,
        profit_loss_buyins=0.5,
        audit_log=audit,
        now="2026-11-20T00:00:00Z",
    )
    assert entry.decision == "continue"
    assert entry.stop_reason is None
    assert entry.ror is not None

    entries = audit.read_all()
    assert len(entries) == 1
    record = entries[0]
    for field in (
        "timestamp",
        "format",
        "roll_buyins",
        "win_rate_bb_per_100",
        "sigma_bb_per_100",
        "ror",
        "risk_band",
        "kelly",
        "bankroll_for_1pct_ror",
        "decision",
        "stop_reason",
        "limits",
    ):
        assert field in record, field
    assert record["timestamp"] == "2026-11-20T00:00:00Z"
    assert record["risk_band"] == "safe"
    assert record["limits"]["max_hours"] == 4.0


def test_audit_records_stop_reason(tmp_path):
    audit = BankrollAuditLog(tmp_path / "bankroll.jsonl")
    entry = evaluate_plan_cash(
        7.0,
        90.0,
        40.0,
        hours_played=1.0,
        profit_loss_buyins=-4.0,
        audit_log=audit,
    )
    assert entry.decision == "stop"
    assert entry.stop_reason == "stop_loss"
    assert audit.read_all()[0]["stop_reason"] == "stop_loss"


def test_audit_log_appends_without_overwriting(tmp_path):
    audit = BankrollAuditLog(tmp_path / "bankroll.jsonl")
    for _ in range(3):
        evaluate_plan_cash(7.0, 90.0, 40.0, audit_log=audit)
    assert len(audit.read_all()) == 3


def test_audit_read_all_on_missing_file(tmp_path):
    assert BankrollAuditLog(tmp_path / "absent.jsonl").read_all() == []


# --------------------------------------------------------------------------- #
# SessionManager — non-régression et chemin dégradé
# --------------------------------------------------------------------------- #


def test_session_manager_preserves_historical_behaviour(monkeypatch):
    """La règle reste celle de la version historique (4 h, −3, +10 caves)."""
    from src.bot.session_manager import SessionManager

    sm = SessionManager()
    sm.initialize_session(1000.0, 1.0)
    assert sm.check_safety_limits() is False

    sm.update_bankroll(600.0)  # −4 caves
    assert sm.check_safety_limits() is True
    assert "Stop-Loss" in sm.shutdown_reason
    assert sm.is_active is False

    sm2 = SessionManager()
    sm2.initialize_session(1000.0, 1.0)
    sm2.update_bankroll(2100.0)  # +11 caves
    assert sm2.check_safety_limits() is True
    assert "Stop-Win" in sm2.shutdown_reason


def test_session_manager_duration_and_daily_hands():
    import datetime as dt

    from src.bot.session_manager import SessionManager

    sm = SessionManager()
    sm.initialize_session(1000.0, 1.0)
    sm.start_time -= dt.timedelta(hours=5)
    assert sm.check_safety_limits() is True
    assert "Durée de session" in sm.shutdown_reason

    capped = SessionManager(max_hands_per_day=2)
    capped.initialize_session(1000.0, 1.0)
    capped.record_hand()
    capped.record_hand()
    assert capped.check_safety_limits() is True
    assert "Plafond de mains" in capped.shutdown_reason


def test_session_verdict_falls_back_without_native(monkeypatch):
    """Sans extension native, la protection de capital reste identique."""
    monkeypatch.setattr(bankroll, "_native", None)
    limits = SessionLimits()
    assert bankroll.session_verdict(limits, 1.0, 0.0) is None
    assert bankroll.session_verdict(limits, 4.5, 0.0) == "max_duration"
    assert bankroll.session_verdict(limits, 1.0, -3.5) == "stop_loss"
    assert bankroll.session_verdict(limits, 1.0, 12.0) == "stop_win"
    assert bankroll.session_verdict(SessionLimits(max_hands_per_day=5), 1.0, 0.0, 5) == (
        "daily_hands"
    )
    # Les calculs, eux, sont indisponibles : aucun conseil inventé.
    assert bankroll.risk_of_ruin_cash(7.0, 90.0, 40.0) is None
    assert bankroll.assess_cash(7.0, 90.0, 40.0) is None
