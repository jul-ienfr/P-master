"""Contrat de métriques stratégiques et câblage du gate go-live — spec 011.

Le gate acceptait ``strategy_metrics`` mais aucun appelant ne le fournissait :
les checks stratégiques étaient toujours neutralisés, et la seule condition
(``winrate_bb100 >= 0``) acceptait un résultat non significatif comme preuve.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.runtime.go_live_gate import evaluate_go_live_gate
from src.runtime.strategy_metrics import (
    build_strategy_metrics,
    strategy_metrics_from_artifacts,
)

READY_LOCAL = {
    "decision_count": 100,
    "block_rate": 0.0,
    "fallback_rate": 0.0,
    "rolling_latency_ms": 10.0,
}
READY_METRICS = {"runtime": {"incident_count": 0}}
READY_READINESS = {"state": "actionable", "score": 0.9}
READY_VALIDATION = {"state": "fully_valid"}


def _artifact(
    *,
    winrate: float = 4.0,
    ci_low: float = 2.0,
    ci_high: float = 6.0,
    hands: int = 4000,
    required: int = 312,
    is_production: bool = True,
    status: str = "significant_positive",
) -> dict:
    return {
        "kind": "production_winrate_benchmark",
        "generated_at": "2026-11-20T09:00:00Z",
        "hero_policy": "DecisionMaker.get_best_action",
        "hero_policy_is_production": is_production,
        "hands": hands,
        "required_hands": required,
        "status": status,
        "winrate_bb100": winrate,
        "ci95_low_bb100": ci_low,
        "ci95_high_bb100": ci_high,
    }


# --- Contrat de métriques ---------------------------------------------------


def test_build_strategy_metrics_copies_protocol_fields():
    metrics = build_strategy_metrics(_artifact(), best_response_gap=0.05)
    assert metrics["winrate_bb100"] == 4.0
    assert metrics["best_response_gap"] == 0.05
    assert metrics["winrate_ci_low"] == 2.0
    assert metrics["winrate_ci_high"] == 6.0
    assert metrics["evaluated_hands"] == 4000
    assert metrics["required_hands"] == 312
    assert metrics["hero_policy_is_production"] is True


def test_build_strategy_metrics_empty_without_artifact():
    assert build_strategy_metrics(None) == {}
    assert build_strategy_metrics({}) == {}


def test_strategy_metrics_from_artifacts_missing_file_is_empty(tmp_path: Path):
    missing = tmp_path / "nope.json"
    assert strategy_metrics_from_artifacts(missing) == {}


def test_strategy_metrics_from_artifacts_reads_file(tmp_path: Path):
    target = tmp_path / "production_winrate.json"
    target.write_text(json.dumps(_artifact()), encoding="utf-8")
    metrics = strategy_metrics_from_artifacts(target)
    assert metrics["winrate_bb100"] == 4.0
    assert metrics["evaluated_hands"] == 4000


def test_strategy_metrics_from_artifacts_ignores_corrupt_file(tmp_path: Path):
    target = tmp_path / "broken.json"
    target.write_text("{not json", encoding="utf-8")
    assert strategy_metrics_from_artifacts(target) == {}


# --- Non-régression du gate (contrat Phase 5.18 préservé) -------------------


def test_gate_strategy_checks_neutral_without_artifacts():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
    )
    assert result.passed is True
    assert result.metrics["strategy_evaluated"] == 0.0
    assert result.metrics["strategy_protocol_evaluated"] == 0.0
    assert result.checks["strategy_protocol"]["ok"] is True


def test_gate_legacy_metrics_keep_original_behaviour():
    """``{winrate_bb100, best_response_gap}`` seul : comportement d'origine exact."""
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        strategy_metrics={"winrate_bb100": 4.2, "best_response_gap": 0.05},
    )
    assert result.passed is True
    assert result.metrics["strategy_protocol_evaluated"] == 0.0
    assert result.checks["strategy_protocol"]["ok"] is True


def test_gate_blocks_on_weak_legacy_strategy_artifacts():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        strategy_metrics={"winrate_bb100": -3.5, "best_response_gap": 0.8},
    )
    assert result.passed is False
    assert "winrate_below_threshold" in result.reasons
    assert "exploitability_above_threshold" in result.reasons


# --- Checks de protocole (spec 011) -----------------------------------------


def test_gate_passes_with_complete_protocol():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        strategy_metrics=build_strategy_metrics(_artifact(), best_response_gap=0.05),
    )
    assert result.checks["strategy_protocol"]["ok"] is True
    assert result.checks["strategy_winrate_significant"]["ok"] is True
    assert result.passed is True


def test_gate_blocks_on_significantly_negative_winrate():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        strategy_metrics=build_strategy_metrics(
            _artifact(
                winrate=-4.0,
                ci_low=-8.0,
                ci_high=-1.0,
                status="significant_negative",
            ),
            best_response_gap=0.05,
        ),
    )
    assert result.passed is False
    assert "winrate_significantly_negative" in result.reasons


def test_gate_blocks_on_incomplete_protocol_underpowered():
    """IC contenant zéro et effectif insuffisant : pas une preuve."""
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        strategy_metrics=build_strategy_metrics(
            _artifact(
                winrate=0.1,
                ci_low=-50.0,
                ci_high=50.0,
                hands=100,
                required=312,
                status="underpowered",
            ),
            best_response_gap=0.05,
        ),
    )
    assert result.passed is False
    assert "strategy_protocol_incomplete" in result.reasons
    assert "sample_below_required" in result.checks["strategy_protocol"]["missing"]


def test_gate_blocks_on_heuristic_artifact():
    """Un artefact d'heuristique ne satisfait jamais le protocole."""
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        strategy_metrics=build_strategy_metrics(
            _artifact(is_production=False),
            best_response_gap=0.05,
        ),
    )
    assert result.passed is False
    assert "strategy_protocol_incomplete" in result.reasons
    assert "policy_not_production" in result.checks["strategy_protocol"]["missing"]


def test_gate_blocks_on_unmeasured_artifact():
    result = evaluate_go_live_gate(
        READY_LOCAL,
        READY_METRICS,
        readiness=READY_READINESS,
        validation=READY_VALIDATION,
        strategy_metrics={
            "winrate_ci_low": 0.0,
            "winrate_ci_high": 0.0,
            "evaluated_hands": 0,
            "required_hands": 0,
            "hero_policy_is_production": True,
            "winrate_status": "unmeasured",
        },
    )
    assert result.passed is False
    missing = result.checks["strategy_protocol"]["missing"]
    assert "unmeasured" in missing
    assert "no_evaluated_hands" in missing
