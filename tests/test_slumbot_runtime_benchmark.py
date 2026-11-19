"""Tests hors-ligne du benchmark runtime Slumbot (mapping décision → incrément)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.slumbot_benchmark import parse_action  # noqa: E402
from research.slumbot_runtime_benchmark import (  # noqa: E402
    _desired_total,
    action_history_from_log,
    hero_position_for,
    legal_actions_for,
    runtime_increment,
    summarize_runtime,
)


def test_legal_actions_preflop_facing_raise():
    state = parse_action("b200", client_pos=0)

    assert legal_actions_for(state) == ["fold", "call", "raise"]


def test_legal_actions_preflop_option_allows_check_and_raise():
    state = parse_action("c", client_pos=0)

    assert legal_actions_for(state) == ["check", "raise"]


def test_legal_actions_postflop_no_bet_gives_solver_sizes():
    state = parse_action("b200c/", client_pos=0)

    assert legal_actions_for(state) == ["check", "bet_50", "bet_75", "allin"]


def test_hero_position_switches_between_streets():
    assert hero_position_for(client_pos=1, street=0) == "btn"
    assert hero_position_for(client_pos=1, street=1) == "ip"
    assert hero_position_for(client_pos=0, street=0) == "bb"
    assert hero_position_for(client_pos=0, street=2) == "oop"


def test_action_history_uses_current_street_only():
    state = parse_action("b200c/b400c", client_pos=0)

    history = action_history_from_log(state)

    assert history == [
        {"player": "hero", "actor": "hero", "action": "bet", "amount": 4.0, "street": "FLOP"},
        {
            "player": "villain",
            "actor": "villain",
            "action": "call",
            "amount": 0.0,
            "street": "FLOP",
        },
    ]


def test_action_history_keeps_preflop_raise_for_facing_detection():
    state = parse_action("b200", client_pos=0)

    history = action_history_from_log(state)

    assert history == [
        {
            "player": "villain",
            "actor": "villain",
            "action": "raise",
            "amount": 2.0,
            "street": "PREFLOP",
        }
    ]


def test_action_history_amounts_are_totals_in_bb():
    state = parse_action("b200c/b400b1200", client_pos=0)

    history = action_history_from_log(state)

    assert [(item["action"], item["amount"]) for item in history] == [
        ("bet", 4.0),
        ("raise", 12.0),
    ]


def test_action_history_empty_at_street_start():
    state = parse_action("b200c/", client_pos=0)

    assert action_history_from_log(state) == []


def test_runtime_increment_maps_fold_and_call():
    facing_bet = parse_action("b200", client_pos=0)
    no_bet = parse_action("b200c/", client_pos=0)

    assert runtime_increment(facing_bet, {"action": "FOLD"}) == "f"
    assert runtime_increment(facing_bet, {"action": "CALL"}) == "c"
    assert runtime_increment(no_bet, {"action": "CHECK"}) == "k"


def test_runtime_increment_never_folds_when_check_is_free():
    no_bet = parse_action("b200c/", client_pos=0)

    assert runtime_increment(no_bet, {"action": "FOLD"}) == "k"


def test_runtime_increment_postflop_bet_uses_solver_size():
    state = parse_action("b200c/", client_pos=0)
    result = {
        "action": "BET",
        "bet_size": 1.0,
        "details": [{"name": "bet_3", "size": 3.0, "is_recommended": True}],
    }

    assert _desired_total(state, result) == 300
    assert runtime_increment(state, result) == "b300"


def test_runtime_increment_preflop_raise_uses_dynamic_amount():
    state = parse_action("", client_pos=1)
    result = {"action": "RAISE", "bet_size": 2.5}

    assert _desired_total(state, result) == 250
    assert runtime_increment(state, result) == "b250"


def test_runtime_increment_all_in_jams_clamped_maximum():
    state = parse_action("b200c/", client_pos=0)
    result = {"action": "ALL_IN"}

    assert runtime_increment(state, result) == "b19800"


def test_runtime_increment_raise_facing_bet_uses_raise_to_total():
    state = parse_action("b200c/kb200", client_pos=0)
    result = {
        "action": "RAISE",
        "details": [{"name": "raise_8", "size": 8.0, "is_recommended": True}],
    }

    assert _desired_total(state, result) == 800
    assert runtime_increment(state, result) == "b800"


def test_runtime_increment_raise_facing_bet_adds_min_raise():
    state = parse_action("b400", client_pos=0)
    result = {"action": "RAISE", "bet_size": 2.0}

    increment = runtime_increment(state, result)
    assert increment.startswith("b")
    target = int(increment[1:])
    minimum, maximum = state.raise_window()
    assert minimum <= target <= maximum


def test_summarize_runtime_counts_sources_and_fallbacks():
    rows = [
        {
            "winnings_bb": 1.0,
            "hand_ms": 2000.0,
            "decision_ms": [10.0, 900.0],
            "decisions": [
                {
                    "source": "GTO_PREFLOP_FAST",
                    "backend": "preflop_precomputed",
                    "fallback_used": False,
                    "cache_hit": True,
                    "elapsed_ms": 0,
                },
                {
                    "source": "GTO_RUST",
                    "backend": "native_solver",
                    "fallback_used": True,
                    "cache_hit": False,
                    "elapsed_ms": 900,
                },
            ],
        }
    ]

    summary = summarize_runtime(rows)

    assert summary["hands"] == 1
    assert summary["sources"] == {"GTO_PREFLOP_FAST": 1, "GTO_RUST": 1}
    assert summary["fallbacks"] == 1
    assert summary["cache_hits"] == 1
    assert summary["solver_decisions"] == 1
    assert summary["solver_elapsed_ms_p50"] == 900.0
