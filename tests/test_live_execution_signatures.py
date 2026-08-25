# -*- coding: utf-8 -*-
"""Tests des signatures et gardes de décision live (src/bot/live_execution.py)."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.live_execution import LiveExecutionMixin
from src.bot.runtime_types import CanonicalTableState
from src.vision.table_geometry import detection_center


def make_controller():
    class Controller(LiveExecutionMixin):
        def __init__(self):
            self.last_tracker_snapshot = {"hero_seat_id": "seat_2"}
            self._locked_spot_log_interval_s = 1.0
            self._decision_cache_ttl_s = 60.0

    _center = staticmethod(detection_center)
    Controller._center = staticmethod(detection_center)
    return Controller()


def canonical(**overrides):
    base = dict(
        spot_id="live:TURN:001",
        street="TURN",
        pot=14.0,
        hero_cards=("Ah", "Kd"),
        board=("As", "Kd", "7h", "2c"),
        legal_actions=("FOLD", "CALL"),
        action_buttons=("fold_button", "call_button"),
        state_confidence=0.95,
        metadata={},
    )
    base.update(overrides)
    return CanonicalTableState(**base)


def test_normalize_helpers():
    assert LiveExecutionMixin._normalize_live_execution_pot(None) == 0.0
    assert LiveExecutionMixin._normalize_live_execution_pot("12.35") == 12.3
    assert LiveExecutionMixin._normalize_live_execution_pot(-5) == 0.0
    assert LiveExecutionMixin._normalize_live_execution_actions(["fold", " FOLD ", "call"]) == ("FOLD", "CALL")
    assert LiveExecutionMixin._normalize_live_execution_buttons(["Call_Button", "fold_button"]) == ("call_button", "fold_button")


def test_extract_actionable_runtime_buttons_filters_generic_labels():
    buttons = ("fold_button", "resume_hand", "im_back", "bet_button", "table_info")
    assert LiveExecutionMixin._extract_actionable_runtime_buttons(buttons) == ("fold_button", "bet_button")


def test_material_signature_covers_spot_street_cards_pot_buttons_and_seat():
    c = make_controller()
    state = canonical()
    sig = c._build_live_execution_material_signature(state)
    assert sig[0] == "live:TURN:001"
    assert sig[1] == "TURN"
    assert sig[2] == ("Ah", "Kd")
    assert sig[7] == "seat_2"

    other_seat = canonical(metadata={"hero_seat_id": "seat_3"})
    assert c._build_live_execution_material_signature(other_seat)[7] == "seat_3"
    assert c._build_live_decision_signature(state) == sig


def test_remember_and_suppress_duplicate_live_action():
    c = make_controller()
    state = canonical()
    c._remember_live_execution(state, "bet", "executed")
    assert c._should_suppress_duplicate_live_action(state, "BET") is True
    assert c._should_suppress_duplicate_live_action(state, "FOLD") is False
    # spot différent -> pas de doublon
    assert c._should_suppress_duplicate_live_action(canonical(pot=20.0), "BET") is False


def test_suppress_recent_execution_timeout_vs_guard():
    c = make_controller()
    state = canonical()
    c._remember_live_execution(state, "FOLD", "executed", settle_status="timeout")
    assert c._should_suppress_recent_live_execution(state) is True

    c._remember_live_execution(state, "FOLD", "executed", settle_status="")
    assert c._should_suppress_recent_live_execution(state) is True

    c._clear_live_execution_guard()
    assert c._should_suppress_recent_live_execution(state) is False
    assert c._last_live_execution_signature == ()
    assert c._last_locked_decision_signature == ()
    assert c._last_decision_payload is None


def test_cached_live_decision_roundtrip_with_ttl():
    c = make_controller()
    state = canonical()
    decision = {"action": "CHECK", "confidence": 0.9}
    assert c._get_cached_live_decision(state) is None
    c._remember_cached_live_decision(state, decision)
    cached = c._get_cached_live_decision(state)
    assert cached == decision
    assert cached is not decision
    # autre spot -> cache manqué
    assert c._get_cached_live_decision(canonical(spot_id="other")) is None


def test_locked_decision_skip_flow():
    c = make_controller()
    state = canonical()
    assert c._build_locked_decision_skip(state) is None
    c._remember_locked_decision(state, "check", "same_spot_locked")
    skip = c._build_locked_decision_skip(state)
    assert skip is not None
    assert skip["action"] == "CHECK"
    assert skip["reason"] == "same_spot_locked"
    assert isinstance(skip["log_now"], bool)


def test_build_minimal_skipped_decision_shape():
    c = make_controller()
    c.last_decision_summary = {
        "confidence": 0.8,
        "fallback_used": True,
        "fallback_reason": "no_solver",
        "profile": {"a": 1},
        "solver": {"b": 2},
        "confidence_details": {"c": 3},
    }
    decision = c._build_minimal_skipped_decision(canonical(), "fold", "same_spot_locked")
    assert decision["action"] == "FOLD"
    assert decision["source"] == "LOCKED_SPOT_SKIP"
    assert decision["backend"] == "locked_skip"
    assert decision["cache_hit"] is True
    assert decision["incidents"] == ["same_spot_locked"]
    assert decision["metadata"]["profile"] == {"a": 1}
