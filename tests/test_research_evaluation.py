"""Tests des outils d'évaluation scientifique Phase 5 : best-response et Monte-Carlo."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.best_response import (  # noqa: E402
    expand_range,
    make_ranges_disjoint,
    make_spot_ranges_disjoint,
    measure_corpus_best_response,
    measure_spot_best_response,
    ranges_overlap,
    spots_from_replay_records,
)
from research.monte_carlo_sim import chen_formula, monte_carlo_equity  # noqa: E402
from research.self_play import (  # noqa: E402
    ReplayDecisionPolicy,
    estimate_local_best_response,
)
from src.contracts.v2_contracts import build_mock_replay_record  # noqa: E402


def test_chen_formula_orders_hands_sensibly():
    assert chen_formula("AsKs") > chen_formula("AsKd")
    assert chen_formula("AsAd") >= chen_formula("AsKs")
    assert chen_formula("7d2c") < chen_formula("AhKh")


def test_map_policy_action_to_solver_matches_bet_percentage_and_jam():
    from research.best_response import map_policy_action_to_solver

    actions = [
        {"name": "check", "ev": 1.0},
        {"name": "bet_9", "ev": 1.2},
        {"name": "bet_18", "ev": 2.0},
        {"name": "allin_100", "ev": 1.5},
    ]

    mapped = map_policy_action_to_solver(
        "bet_50", actions, starting_pot=36.0, effective_stack=100.0
    )
    jammed = map_policy_action_to_solver(
        "jam", actions, starting_pot=36.0, effective_stack=100.0
    )

    assert mapped["solver_action"] == "bet_18"
    assert mapped["mapping"] == "nearest_size"
    assert jammed["solver_action"] == "allin_100"
    assert jammed["mapping"] == "allin"


def test_heuristic_hero_policy_opens_wide_on_button():
    from research.monte_carlo_sim import View, make_heuristic_hero_policy

    policy = make_heuristic_hero_policy()
    view = View(
        street_index=0,
        hole_cards="AsTd",
        board_cards="",
        pot_amount=1.5,
        to_call=0.0,
        effective_stack=100.0,
        min_raise_to=2.0,
        max_raise_to=100.0,
        can_raise=True,
        is_button=True,
    )

    action, amount = policy(view)

    assert action == "raise_to"
    assert amount is not None and amount >= view.min_raise_to


def test_heuristic_hero_policy_defends_blind_wide_but_folds_trash():
    from research.monte_carlo_sim import View, make_heuristic_hero_policy

    policy = make_heuristic_hero_policy()
    base = {
        "street_index": 0,
        "board_cards": "",
        "pot_amount": 4.0,
        "to_call": 1.5,
        "effective_stack": 100.0,
        "min_raise_to": 4.0,
        "max_raise_to": 100.0,
        "can_raise": True,
        "is_button": False,
    }

    defend, _ = policy(View(hole_cards="Kh9d", **base))
    trash, _ = policy(View(hole_cards="7d2c", **base))

    assert defend == "check_call"
    assert trash == "fold"


def test_monte_carlo_equity_bounds_and_ranking():
    from random import Random

    rng = Random(42)
    aces = monte_carlo_equity("AsAd", ["7h", "8d", "2c"], samples=80, rng=rng)
    trash = monte_carlo_equity("7d2c", ["Ah", "Kd", "Qc"], samples=80, rng=rng)
    assert 0.0 <= aces <= 1.0
    assert 0.0 <= trash <= 1.0
    assert aces > trash


def test_monte_carlo_equity_accepts_board_string_and_list_equivalently():
    from random import Random

    string_result = monte_carlo_equity("AsAd", "7h8d2c", samples=60, rng=Random(7))
    list_result = monte_carlo_equity("AsAd", ["7h", "8d", "2c"], samples=60, rng=Random(7))

    assert 0.0 <= string_result <= 1.0
    assert string_result == list_result


def test_expand_range_handles_plus_and_dash_notation():
    combos = expand_range("22+,A2s+,K9s+,QTo+,88-JJ,A5s-A2s")

    assert {"22", "JJ", "QQ", "AA"} <= combos
    assert {"A2s", "A4s", "AKs"} <= combos
    assert {"K9s", "KQs"} <= combos
    assert {"QTo", "QJo"} <= combos
    assert "72o" not in combos


def test_make_ranges_disjoint_removes_overlap():
    first, second = make_ranges_disjoint("QQ+,AKs", "QQ+,AKs,22")

    assert not ranges_overlap(first, second)
    assert set(first.split(",")) == {"QQ", "KK", "AA", "AKs"}
    assert set(second.split(",")) == {"22"}


def test_make_spot_ranges_disjoint_preserves_the_smaller_range():
    oop, ip = make_spot_ranges_disjoint("22+,A2s+", "QQ+,AKs")

    assert not ranges_overlap(oop, ip)
    assert set(ip.split(",")) == {"QQ", "KK", "AA", "AKs"}
    assert "22" in expand_range(oop)


def test_gap_from_native_rejects_overlapping_ranges_before_solving(monkeypatch):
    import research.best_response as best_response

    class SolverMustNotRun:
        def measure_best_response_gap(self, **kwargs):
            raise AssertionError("le solveur ne doit pas être appelé")

    monkeypatch.setattr(best_response, "postflop_solver_py", SolverMustNotRun())

    spot = {
        "oop_range": "QQ+,AKs",
        "ip_range": "QQ+,AKs",
        "board": ["Ah", "7d", "2c"],
        "starting_pot": 6.0,
        "effective_stack": 100.0,
        "hero_is_oop": True,
        "policy_action": "check",
    }

    with pytest.raises(ValueError, match="non disjointes"):
        best_response._gap_from_native(spot, max_iterations=1)


def test_measure_spot_best_response_normalizes_and_records_overlap(monkeypatch):
    import research.best_response as best_response

    captured = {}

    def fake_gap(spot, *, max_iterations):
        captured.update(spot)
        return {
            "policy_action": spot["policy_action"],
            "policy_ev": 1.0,
            "mes_ev": 1.5,
            "best_response_gap": 0.5,
            "exploitability": 2.0,
            "backend": "native_mes",
        }

    monkeypatch.setattr(best_response, "_gap_from_native", fake_gap)

    result = measure_spot_best_response(
        {
            "oop_range": "QQ+,AKs",
            "ip_range": "QQ+,AKs,22",
            "board": ["Ah", "7d", "2c"],
            "starting_pot": 6.0,
            "effective_stack": 100.0,
            "hero_is_oop": True,
            "policy_action": "check",
        },
        max_iterations=1,
    )

    assert result["removed_overlap"] == ["AA", "AKs", "KK", "QQ"]
    assert not ranges_overlap(captured["oop_range"], captured["ip_range"])
    assert not ranges_overlap(
        result["normalized_oop_range"], result["normalized_ip_range"]
    )
    assert result["best_response_gap"] == 0.5


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


def test_spots_from_replay_records_uses_hero_and_villain_ranges():
    record = build_mock_replay_record()
    spots = spots_from_replay_records([record])

    assert len(spots) == 1
    spot = spots[0]
    assert spot["spot_id"] == "mock-replay-001"
    assert spot["oop_range"] and spot["ip_range"]
    assert spot["oop_range"] != spot["ip_range"]
    assert spot["board"]
    assert spot["starting_pot"] > 0
    assert spot["effective_stack"] > 0
    assert isinstance(spot["hero_is_oop"], bool)
    assert spot["policy_action"]


def test_spots_from_replay_records_keeps_legacy_ranges():
    class Spot:
        ranges = ("AA", "KK")
        board = ["Ah", "7d", "2c"]
        pot = 6.0
        effective_stack = 94.0
        hero_is_oop = False
        spot_id = "legacy"

    class Decision:
        action = "check"

    class Record:
        replay_id = "legacy-1"
        spot = Spot()
        decision = Decision()

    spots = spots_from_replay_records([Record()])

    assert spots == [
        {
            "spot_id": "legacy-1",
            "oop_range": "KK",
            "ip_range": "AA",
            "board": ["Ah", "7d", "2c"],
            "starting_pot": 6.0,
            "effective_stack": 94.0,
            "hero_is_oop": False,
            "policy_action": "check",
        }
    ]


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


def test_gap_from_native_maps_policy_action_to_nearest_solver_size(monkeypatch):
    import research.best_response as best_response

    captured = {}

    class FakeSolver:
        def measure_best_response_gap(self, **kwargs):
            captured.update(kwargs)
            return {
                "policy_action": None,
                "policy_ev": 3.0,
                "mes_ev": 2.5,
                "best_response_gap": 0.0,
                "exploitability": 0.9,
                "actions": [
                    {"name": "check", "ev": 1.0},
                    {"name": "bet_18", "ev": 2.0},
                    {"name": "allin_100", "ev": 2.5},
                ],
            }

    monkeypatch.setattr(best_response, "postflop_solver_py", FakeSolver())

    result = best_response._gap_from_native(
        {
            "oop_range": "QQ+",
            "ip_range": "AsKs",
            "board": ["Ah", "7d", "2c"],
            "starting_pot": 36.0,
            "effective_stack": 100.0,
            "hero_is_oop": True,
            "policy_action": "bet_50",
            "bet_sizes": "50%",
        },
        max_iterations=5,
    )

    assert captured["policy_action"] is None
    assert captured["bet_sizes"] == "50%"
    assert result["solver_action"] == "bet_18"
    assert result["policy_ev"] == 2.0
    assert result["mes_ev"] == 2.5
    assert result["best_response_gap"] == 0.5


def test_corpus_best_response_skips_failed_spots():
    spots = [
        {"spot_id": "ok", "policy_action": "check"},
        {"spot_id": "boom", "policy_action": "check"},
    ]

    def gap_fn(spot):
        if spot["spot_id"] == "boom":
            raise RuntimeError("solveur saturé")
        return {
            "policy_action": "check",
            "policy_ev": 1.0,
            "mes_ev": 1.3,
            "best_response_gap": 0.3,
            "backend": "native_mes",
        }

    summary = measure_corpus_best_response(spots, gap_fn=gap_fn)

    assert summary["spots"] == 2
    assert summary["evaluated_spots"] == 1
    assert summary["unmapped_spots"] == 1
    assert summary["mean_best_response_gap"] == 0.3
    assert summary["results"][1]["backend"] == "native_mes_skipped"
    assert "solveur saturé" in summary["results"][1]["error"]


def test_estimate_solver_best_response_reports_native_backend(monkeypatch):
    import research.best_response as best_response
    from research.rl_lab import build_rl_replay_suite, estimate_solver_best_response

    class FakeSolver:
        def measure_best_response_gap(self, **kwargs):
            return {
                "policy_action": None,
                "policy_ev": 0.0,
                "mes_ev": 0.0,
                "best_response_gap": 0.0,
                "exploitability": 0.5,
                "actions": [
                    {"name": "check", "ev": 0.5},
                    {"name": "bet_2", "ev": 1.5},
                ],
            }

    monkeypatch.setattr(best_response, "postflop_solver_py", FakeSolver())

    summary = estimate_solver_best_response(
        build_rl_replay_suite()[:2], max_iterations=3, bet_sizes="50%"
    )

    assert summary["backend"] == "native_mes"
    assert summary["solver_evaluated_records"] == 1
    assert summary["max_iterations"] == 3
    assert summary["bet_sizes"] == "50%"
    assert summary["corpus"]["spots"] == 2
    assert summary["corpus"]["results"][1]["solver_action"] == "bet_2"
    assert summary["corpus"]["results"][1]["best_response_gap"] == 0.0
