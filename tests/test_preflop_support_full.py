"""Tests du fast-path preflop (src/bot/preflop_support.py)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.preflop_support import (
    BASE_GTO_RANGE,
    PREFLOP_FAST_3BET_RANGE,
    cached_range_items,
    combo_in_range,
    combo_matches_range_token,
    hero_combo_notation,
    normalize_action_name,
    normalize_hero_hand_string,
    normalize_preflop_position,
    run_preflop_fast_path,
)


def test_normalize_action_name_and_position():
    assert normalize_action_name(" fold ") == "FOLD"
    assert normalize_action_name(None) is None
    assert normalize_preflop_position("btn") == "BTN"
    assert normalize_preflop_position("UTG") == "UTG"
    assert normalize_preflop_position("middle") is None


def test_normalize_hero_hand_string_orders_by_rank():
    assert normalize_hero_hand_string("7dAs") == "As7d"
    assert normalize_hero_hand_string("ah kd") == "AhKd"
    # main invalide : renvoyée brute
    assert normalize_hero_hand_string("XX") == "XX"
    assert normalize_hero_hand_string("") == ""


def test_hero_combo_notation_pairs_suited_offsuit():
    assert hero_combo_notation("AhAd") == "AA"
    assert hero_combo_notation("AhKh") == "AKs"
    assert hero_combo_notation("AhKd") == "AKo"
    assert hero_combo_notation("bad") == ""


def test_cached_range_items_splits_and_ignores_empty():
    items = cached_range_items("55+, A2s+ , , K5s+")
    assert items == ("55+", "A2s+", "K5s+")


def test_combo_matches_range_token_pairs():
    assert combo_matches_range_token("55", "55+") is True
    assert combo_matches_range_token("44", "55+") is False
    assert combo_matches_range_token("AA", "TT") is False
    assert combo_matches_range_token("TT", "TT") is True
    assert combo_matches_range_token("AK", "QQ+") is True  # paire >= seuil
    assert combo_matches_range_token("", "") is False


def test_combo_matches_range_token_suited_offsuit():
    assert combo_matches_range_token("AKs", "A2s+") is True
    assert combo_matches_range_token("A5s", "A2s+") is True
    assert combo_matches_range_token("A4s", "A5s+") is False
    assert combo_matches_range_token("AKo", "ATo+") is True
    assert combo_matches_range_token("AKs", "ATo+") is False  # mauvais flag suited
    assert combo_matches_range_token("KAo", "ATo+") is False  # ordre inversé


def test_combo_in_range_base_gto():
    # les combos sont en notation 3 caractères (sortie de hero_combo_notation)
    assert combo_in_range("AKo", BASE_GTO_RANGE) is True  # ATo+
    assert combo_in_range("QJo", BASE_GTO_RANGE) is True  # QJo
    assert combo_in_range("72o", BASE_GTO_RANGE) is False
    assert combo_in_range("AA", BASE_GTO_RANGE) is True


def make_manager(in_range=True):
    return SimpleNamespace(
        get_hero_range=lambda position, facing_raise: (
            "AA,KK,QQ,JJ" if in_range else "32o"
        )
    )


def test_run_preflop_fast_path_open_raise_in_range():
    manager = make_manager(in_range=True)
    action, response = run_preflop_fast_path(
        hero_hand="AhAd",
        legal_actions=["FOLD", "RAISE"],
        hero_position="BTN",
        effective_stack=200.0,
        pot=30.0,
        preflop_manager=manager,
        facing_raise=False,
        aggressive_action="RAISE",
    )
    assert action == "RAISE"
    assert response["backend"] == "preflop_fast_path"
    assert response["decision_confidence"] == 0.94
    # stack < 15x pot (200 < 450) -> shove du stack entier
    assert response["dynamic_amount"] == pytest.approx(200.0)


def test_run_preflop_fast_path_short_stack_shoves():
    manager = make_manager(in_range=True)
    action, response = run_preflop_fast_path(
        hero_hand="AhAd",
        legal_actions=["FOLD", "ALL_IN"],
        hero_position="SB",
        effective_stack=100.0,
        pot=200.0,
        preflop_manager=manager,
        facing_raise=False,
        aggressive_action="ALL_IN",
    )
    assert action == "ALL_IN"
    assert response["dynamic_amount"] == 100.0  # stack < 15x pot -> shove


def test_run_preflop_fast_path_facing_raise_three_bets_with_premium():
    manager = make_manager(in_range=True)
    action, response = run_preflop_fast_path(
        hero_hand="AhAd",
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="BB",
        effective_stack=200.0,
        pot=40.0,
        preflop_manager=manager,
        facing_raise=True,
        aggressive_action="RAISE",
    )
    assert action == "RAISE"
    assert response["dynamic_amount"] == pytest.approx(40.0 * 3.2)
    assert response["solve_mode"] == "preflop_fast_path"


def test_run_preflop_fast_path_folds_junk_facing_raise():
    manager = make_manager(in_range=False)
    action, response = run_preflop_fast_path(
        hero_hand="7h2d",
        legal_actions=["FOLD", "CALL"],
        hero_position="UTG",
        effective_stack=200.0,
        pot=40.0,
        preflop_manager=manager,
        facing_raise=True,
        aggressive_action=None,
    )
    assert action == "FOLD"
    assert response["decision_confidence"] == 0.78
    assert response["dynamic_amount"] is None


def test_run_preflop_fast_path_checks_when_out_of_range_no_bet():
    manager = make_manager(in_range=False)
    action, _response = run_preflop_fast_path(
        hero_hand="7h2d",
        legal_actions=["CHECK", "FOLD"],
        hero_position="BB",
        effective_stack=200.0,
        pot=10.0,
        preflop_manager=manager,
        facing_raise=False,
        aggressive_action=None,
    )
    assert action == "CHECK"


def test_fast_3bet_range_constant_shape():
    assert "TT+" in PREFLOP_FAST_3BET_RANGE
    assert "AKo" in PREFLOP_FAST_3BET_RANGE
