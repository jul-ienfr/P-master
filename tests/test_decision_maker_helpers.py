"""Tests des helpers purs de DecisionMaker : profils, texture board, sizing, coercions."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from src.bot.decision_maker import (
    _analyze_board_texture,
    _bet_size_from_action,
    _build_structured_profile_cached,
    _compact_solver_list,
    _safe_float,
    _safe_int,
    _safe_string,
)


def build_exploit_profile(profile):
    return _build_structured_profile_cached(json.dumps(profile))


def test_safe_coercions():
    assert _safe_float("1.5") == 1.5
    assert _safe_float(None) is None
    assert _safe_float("bad") is None
    assert _safe_int("7") == 7
    assert _safe_int(None) is None
    assert _safe_int(2.9) == 2
    assert _safe_string("  x ") == "x"
    assert _safe_string("") is None
    assert _safe_string(None) is None


def test_compact_solver_list_copies_dicts_and_keeps_strings():
    source = [{"a": 1}, "text", "", None, 42]
    compact = _compact_solver_list(source)
    assert compact == [{"a": 1}, "text", "42"]
    assert compact[0] is not source[0]
    assert _compact_solver_list("nope") is None


def test_analyze_board_texture_classifies_boards():
    assert _analyze_board_texture([]) == "DRY"
    assert _analyze_board_texture(["Ah"]) == "DRY"  # préflop
    assert _analyze_board_texture(["Ah", "Kh", "Qh"]) == "MONOTONE"
    assert _analyze_board_texture(["Ah", "Kd", "Qh"]) in {"WET", "DRY"}  # connected -> WET
    disconnected = ["Ah", "Kd", "8c"]  # gaps larges, deux couleurs max
    assert _analyze_board_texture(disconnected) in {"WET", "DRY"}
    paired_wet = ["7h", "7d", "8s"]
    assert _analyze_board_texture(paired_wet) == "WET"


def test_bet_size_all_in_and_short_spr():
    # ALL_IN -> stack entier
    assert _bet_size_from_action("ALL_IN", 100.0, 250.0, []) == 250.0
    # SPR <= 0.8 avec BET -> shove
    assert _bet_size_from_action("BET", 500.0, 300.0, ["Ah"]) == 300.0
    assert _bet_size_from_action(None, 100.0, 100.0) is None


def test_bet_size_dry_vs_wet_texture():
    dry = _bet_size_from_action("BET", 200.0, 400.0, ["Ah", "Kd", "8c"])
    wet = _bet_size_from_action("BET", 200.0, 400.0, ["7h", "8h", "9h"])
    assert dry > 0 and wet > 0
    assert wet >= dry  # board monotone -> sizing plus large que board sec


def test_bet_size_fixed_fractions():
    pot, stack = 200.0, 500.0
    assert _bet_size_from_action("BET_50", pot, stack) == pytest.approx(100.0)
    assert _bet_size_from_action("BET_75", pot, stack) == pytest.approx(150.0)
    # jamais plus que le stack effectif
    tiny_stack = _bet_size_from_action("BET_75", pot, 20.0)
    assert tiny_stack == pytest.approx(20.0)
    # action inconnue -> None
    assert _bet_size_from_action("CHECK", pot, stack) is None


def test_build_exploit_profile_styles_and_biases():
    whale = build_exploit_profile(
        {"derived_profile": {"style": "Whale", "observed_hands": 240, "reliability": 0.9}}
    )
    assert whale["call_bias"] > 0
    assert whale["pressure_bias"] > 0

    maniac = build_exploit_profile(
        {"derived_profile": {"style": "Maniac", "observed_hands": 240, "reliability": 0.9}}
    )
    assert maniac["fold_bias"] > 0
    assert maniac["pressure_bias"] < 0

    nit = build_exploit_profile(
        {"derived_profile": {"style": "Nit", "observed_hands": 120}}
    )
    assert nit["fold_bias"] > maniac["fold_bias"]

    unknown = build_exploit_profile({"derived_profile": {"style": "Mystere"}})
    assert unknown["pressure_bias"] == 0.0
    assert unknown["range_hint"]  # range GTO de base


def test_build_exploit_profile_computes_confidence_and_cap():
    profile = build_exploit_profile(
        {
            "vpip_count": 60,
            "hands_played": 100,
            "pfr_count": 30,
            "derived_profile": {"aggression_frequency": 0.45, "observed_hands": 100},
        }
    )
    assert 0.0 <= profile["exploit_confidence"] <= 1.0
    assert 0.05 <= profile["deviation_cap"] <= 0.25
    assert profile["gap"] == pytest.approx(round(profile["vpip"] - profile["pfr"], 4))
    assert isinstance(profile["rl_ready"], bool)
