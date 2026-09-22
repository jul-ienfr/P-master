"""Validation plan 6(h) — go_live_gate : couverture blueprint + rapport de
calibration de la tolérance de quantification bloquants quand fournis."""

from __future__ import annotations

from datetime import UTC, datetime

from src.runtime.go_live_gate import evaluate_go_live_gate

READY_LOCAL = {
    "decision_count": 100,
    "block_rate": 0.0,
    "fallback_rate": 0.0,
    "rolling_latency_ms": 10.0,
}
READY_METRICS = {"runtime": {"incident_count": 0}}
# Le gate exige readiness.actionable (score ≥ 0.6) : sans ces artifacts le verdict
# resterait no_go quel que soit le blueprint (règle pré-existante, pas Phase 0.6/0.7).
READY_READINESS = {"state": "actionable", "score": 0.9}
READY_VALIDATION = {"state": "fully_valid"}


def _blueprint_metrics(coverage: float, report_present: bool = True) -> dict:
    return {
        "current_format": "heads_up_cash",
        "formats": {
            "heads_up_cash": {
                "coverage": coverage,
                "coverage_target": 1.0,
            }
        },
        "bet_tolerance_report": {
            "present": report_present,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
        },
    }


def test_full_coverage_and_fresh_report_pass():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        blueprint_metrics=_blueprint_metrics(1.0),
    )
    assert result.checks["blueprint_coverage"]["ok"] is True
    assert result.checks["bet_tolerance_report"]["ok"] is True
    assert result.passed is True


def test_coverage_below_target_blocks_go_live():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        blueprint_metrics=_blueprint_metrics(0.5),
    )
    assert result.checks["blueprint_coverage"]["ok"] is False
    assert result.passed is False
    assert "blueprint_coverage_below_1" in result.reasons


def test_missing_tolerance_report_blocks_go_live():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        blueprint_metrics=_blueprint_metrics(1.0, report_present=False),
    )
    assert result.checks["bet_tolerance_report"]["ok"] is False
    assert result.passed is False
    assert "bet_tolerance_report_missing_or_stale" in result.reasons


def test_no_blueprint_metrics_keeps_checks_neutral():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
    )
    assert result.checks["blueprint_coverage"]["ok"] is True
    assert result.checks["bet_tolerance_report"]["ok"] is True
    assert result.passed is True
