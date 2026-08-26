"""Tests des outils d'évaluation scientifique Phase 5 : best-response et Monte-Carlo."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.best_response import measure_corpus_best_response  # noqa: E402
from research.monte_carlo_sim import chen_formula, monte_carlo_equity  # noqa: E402
from research.self_play import (  # noqa: E402
    ReplayDecisionPolicy,
    estimate_local_best_response,
)


def test_chen_formula_orders_hands_sensibly():
    assert chen_formula("AsKs") > chen_formula("AsKd")
    assert chen_formula("AsAd") >= chen_formula("AsKs")
    assert chen_formula("7d2c") < chen_formula("AhKh")


def test_monte_carlo_equity_bounds_and_ranking():
    from random import Random

    rng = Random(42)
    aces = monte_carlo_equity("AsAd", ["7h", "8d", "2c"], samples=80, rng=rng)
    trash = monte_carlo_equity("7d2c", ["Ah", "Kd", "Qc"], samples=80, rng=rng)
    assert 0.0 <= aces <= 1.0
    assert 0.0 <= trash <= 1.0
    assert aces > trash


def test_corpus_best_response_with_fallback_gap_fn():
    spots = [
        {
            "spot_id": "spot-1",
            "oop_range": "QQ+,AKo",
            "ip_range": "AsKs",
            "board": ["Ah", "7d", "2c"],
            "starting_pot": 6.0,
            "effective_stack": 100.0,
            "hero_is_oop": True,
            "policy_action": "check",
        }
    ]
    summary = measure_corpus_best_response(
        spots,
        gap_fn=lambda spot: {
            "policy_action": spot["policy_action"],
            "policy_ev": 2.5,
            "mes_ev": 2.7,
            "best_response_gap": 0.2,
            "backend": "test",
        },
    )

    assert summary["spots"] == 1
    assert summary["mean_best_response_gap"] == 0.2
    assert summary["max_best_response_gap"] == 0.2
    assert summary["results"][0]["spot_id"] == "spot-1"


def test_estimate_local_best_response_reports_fallback_backend():
    class FakeRecord:
        pass

    record = FakeRecord()

    class Decision:
        action = "bet"

        class alt:
            pass

    alternatives = [
        type("Alt", (), {"name": "check", "ev": 3.0})(),
        type("Alt", (), {"name": "bet", "ev": 2.5})(),
    ]
    decision = type("Decision", (), {"action": "bet", "alternatives": alternatives})()
    record.decision = decision
    record.spot = None

    summary = estimate_local_best_response([record], policy=ReplayDecisionPolicy("replay"))

    assert summary["backend"] == "alternatives_fallback"
    assert summary["evaluated_records"] == 1
    # best alternative check=3.0 vs chosen bet=2.5 -> gap 0.5
    assert summary["average_gap"] == 0.5


def test_estimate_local_best_response_uses_solver_gap_fn():
    class Record:
        pass

    record = Record()
    record.decision = type(
        "Decision", (), {"action": "bet", "alternatives": [type("A", (), {"name": "x", "ev": 0})()]}
    )()
    record.spot = None

    calls = []

    def gap_fn(rec):
        calls.append(rec)
        return 0.12

    summary = estimate_local_best_response([record], policy=ReplayDecisionPolicy("r"), solver_gap_fn=gap_fn)

    assert len(calls) == 1
    assert summary["backend"] == "native_mes"
    assert summary["solver_evaluated_records"] == 1
    assert summary["average_gap"] == 0.12
