"""Tests hors-ligne du benchmark Slumbot (parseur, légalité, statistiques)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from research.monte_carlo_sim import make_heuristic_hero_policy  # noqa: E402
from research.slumbot_benchmark import (  # noqa: E402
    ParsedState,
    choose_increment,
    parse_action,
    summarize,
)


def test_parse_preflop_and_flop_from_bb():
    state = parse_action("b200c/kk/kb400", client_pos=0)

    assert state.street == 2
    assert state.hero_total == 200
    assert state.bot_total == 600
    assert state.hero_street == 0
    assert state.bot_street == 400
    assert state.pot == 800
    assert state.to_call == 400
    assert state.hero_turn is True
    assert state.raise_window() == (800, 19_800)


def test_parse_all_in_hand_is_terminal():
    state = parse_action("b20000c///", client_pos=0)

    assert state.pot == 40_000
    assert state.to_call == 0
    assert state.effective_stack == 0
    assert state.raise_window() == (None, None)


def test_effective_stack_is_the_call_when_villain_is_all_in():
    # Héros 157 bb derrière, adversaire all-in, 157 bb à payer pour suivre.
    state = ParsedState(
        hero_total=4_300,
        bot_total=20_000,
        hero_street=0,
        bot_street=15_700,
        level=15_700,
        to_call=15_700,
    )
    assert state.bot_stack == 0
    assert state.to_call == 15_700
    assert state.effective_stack == 15_700
    assert state.raise_window() == (None, None)

    # Un tapis terminal (personne ne peut plus miser) reste à zéro.
    terminal = ParsedState(hero_total=20_000, bot_total=20_000)
    assert terminal.effective_stack == 0


def test_parse_empty_action_gives_turn_to_small_blind_hero():
    state = parse_action("", client_pos=1)

    assert state.street == 0
    assert state.hero_total == 50
    assert state.bot_total == 100
    assert state.to_call == 50
    assert state.hero_turn is True
    assert state.raise_window() == (200, 20_000)


def test_parse_completed_street_hands_turn_to_big_blind():
    state = parse_action("b200c/", client_pos=1)

    assert state.street == 1
    assert state.hero_turn is False


class _StubPolicy:
    def __init__(self, action: str, amount: float | None = None):
        self.action = action
        self.amount = amount
        self.view = None

    def __call__(self, view):
        self.view = view
        return self.action, self.amount


def test_choose_increment_maps_call_and_check():
    state = ParsedState(street=1, level=400, hero_street=0, bot_street=400, to_call=400)
    state.hero_total = 200
    state.bot_total = 600

    assert choose_increment(state, ["As", "Kd"], ["2c", "7h", "9s"], _StubPolicy("check_call")) == "c"

    no_bet = ParsedState(street=1, level=0, hero_street=0, bot_street=0, to_call=0)
    assert choose_increment(no_bet, ["As", "Kd"], ["2c", "7h", "9s"], _StubPolicy("check_call")) == "k"


def test_choose_increment_clamps_raise_to_legal_window():
    state = ParsedState(
        street=2,
        level=400,
        hero_street=0,
        bot_street=400,
        to_call=400,
        last_increment=400,
    )
    state.hero_total = 200
    state.bot_total = 600

    policy = _StubPolicy("raise_to", 7.0)
    increment = choose_increment(state, ["As", "Kd"], ["2c", "7h", "9s", "4d"], policy)

    assert increment == "b800"
    assert policy.view is not None
    assert policy.view.pot_amount == 8.0
    assert policy.view.to_call == 4.0


def test_choose_increment_feeds_policy_view_in_big_blinds():
    state = parse_action("b200", client_pos=0)

    assert choose_increment(
        state,
        ["Ad", "7d"],
        [],
        make_heuristic_hero_policy(),
    ) == "c"


def test_choose_increment_uses_button_position_preflop():
    small_blind = parse_action("", client_pos=1)
    big_blind = parse_action("b200", client_pos=0)

    assert choose_increment(
        small_blind,
        ["As", "Td"],
        [],
        make_heuristic_hero_policy(),
        is_button=True,
    ).startswith("b")
    assert choose_increment(
        big_blind,
        ["7d", "2c"],
        [],
        make_heuristic_hero_policy(),
    ) == "f"


def test_choose_increment_never_folds_when_check_is_free():
    state = ParsedState(street=1, level=0, hero_street=0, bot_street=0, to_call=0)

    assert choose_increment(state, ["As", "Kd"], ["2c", "7h", "9s"], _StubPolicy("fold")) == "k"


def test_choose_increment_falls_back_when_raise_window_closed():
    state = ParsedState(street=0, level=20_000, hero_street=20_000, bot_street=20_000, to_call=0)
    state.hero_total = 20_000
    state.bot_total = 20_000

    assert choose_increment(state, ["As", "Kd"], [], _StubPolicy("raise_to", 100.0)) == "k"


def test_summarize_computes_winrate_and_confidence_interval():
    rows = [
        {"winnings_bb": 2.0, "decision_ms": [10.0, 20.0], "hand_ms": 1000.0},
        {"winnings_bb": -1.0, "decision_ms": [30.0], "hand_ms": 1000.0},
        {"winnings_bb": 0.0, "decision_ms": [], "hand_ms": 1000.0},
        {"winnings_bb": 1.0, "decision_ms": [40.0], "hand_ms": 1000.0},
    ]

    summary = summarize(rows)

    assert summary["hands"] == 4
    assert summary["total_winnings_bb"] == 2.0
    assert summary["winrate_bb100"] == 50.0
    assert summary["wins"] == 2
    assert summary["losses"] == 1
    assert summary["ties"] == 1
    assert summary["decisions"] == 4
    assert summary["ci95_bb100"] > 0
    assert summary["hands_per_minute"] == pytest.approx(60.0)
