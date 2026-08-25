# -*- coding: utf-8 -*-
"""Tests des enregistreurs d'échec runtime et du gate flow (src/bot/gate_flow.py)."""
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.gate_flow import GateFlowMixin, compact_solver_payload
from src.bot.sanity_checker import ActionIntent, GateReason, GateResult
from src.bot.live_execution import LiveExecutionMixin
from src.runtime.session import RuntimeSessionMixin


class Controller(GateFlowMixin, LiveExecutionMixin, RuntimeSessionMixin):
    def __init__(self):
        self.operator_controls = {}
        self.last_decision_summary = {}
        self.last_tracker_snapshot = {}
        self.last_resolved_runtime_state = None
        self.last_valid_frame = np.zeros((4, 4, 3), dtype=np.uint8)
        self.runtime_failure_dataset = SimpleNamespace(record_incident=lambda payload: self.incidents.append(payload))
        self.incidents = []
        self.shadow_calls = []
        self.events = []
        self.incident_history = deque()
        self.metric_snapshot_history = deque()

    def _build_operator_snapshot(self):
        return {"shadow_mode_enabled": bool(self.operator_controls.get("shadow_mode_enabled", False))}

    def _build_runtime_failure_crops(self):
        return {"pot": self.last_valid_frame}

    def _push_runtime_event(self, kind, message, **context):
        self.events.append((kind, message))

    def _push_incident(self, incident_id, severity="warning", **context):
        self.incidents.append(incident_id)

    def _publish_runtime_bridge_state(self, force=False):
        pass


def make_canonical():
    from src.bot.runtime_types import CanonicalTableState

    return CanonicalTableState(
        spot_id="live:TURN:001",
        street="TURN",
        pot=14.0,
        hero_cards=("Ah", "Kd"),
        board=("As", "Kd", "7h", "2c"),
        legal_actions=("FOLD", "CALL"),
        action_buttons=("fold_button", "call_button"),
    )


def test_compact_solver_payload_keeps_only_expected_fields():
    compact = compact_solver_payload(
        {
            "alternatives": [{"action": "FOLD"}, "garbage"],
            "alternatives_complete": [{"action": "CALL"}],
            "ev_by_action": {"FOLD": 0.0},
            "elapsed_ms": 12.5,
            "node_count": 3.7,
            "backend": "pokerstars",
            "warnings": [" a ", "", 42],
            "warning_details": [{"x": 1}],
            "unexpected": "dropped",
        }
    )
    assert compact["alternatives"] == [{"action": "FOLD"}]
    assert compact["alternatives_complete"] == [{"action": "CALL"}]
    assert compact["elapsed_ms"] == 12.5
    assert compact["node_count"] == 3
    assert compact["backend"] == "pokerstars"
    assert compact["warnings"] == [" a ", "42"]
    assert compact["unexpected"] == "dropped"  # les clés inconnues sont conservées telles quelles
    assert compact_solver_payload(None) == {}
    assert compact_solver_payload("nope") == {}


def test_record_runtime_failure_skips_without_dataset():
    c = Controller()
    c.runtime_failure_dataset = None
    c._record_runtime_failure(category="vision", incident_id="ocr_down")
    assert c.incidents == []


def test_record_runtime_failure_records_payload_and_shadow_capture(monkeypatch):
    c = Controller()
    c.operator_controls = {"shadow_mode_enabled": True}
    monkeypatch.setattr(
        Controller,
        "_get_runtime_session_id",
        lambda self: "session-test",
        raising=False,
    )

    class FakeHitl:
        def record_shadow_failure(self, frame, issue_type, reason, context):
            self.calls = (issue_type, reason)

    c.hitl = FakeHitl()
    c._record_runtime_failure(
        category="vision",
        incident_id="ocr_down",
        severity="error",
        context={"reason": "ocr_down"},
    )
    assert len(c.incidents) == 1
    payload = c.incidents[0]
    assert payload["category"] == "vision"
    assert payload["severity"] == "error"
    assert payload["crops"] == {"pot": c.last_valid_frame}
    assert c.hitl.calls[0] == "ocr_down"


def test_record_shadow_mode_failure_ignored_when_disabled():
    c = Controller()

    class FakeHitl:
        called = False

        def record_shadow_failure(self, *args, **kwargs):
            self.called = True

    hitl = FakeHitl()
    c.hitl = hitl
    c._record_shadow_mode_failure(issue_type="sanity_gate_failure", reason="test")
    assert hitl.called is False


def test_on_action_gate_failure_triggers_shadow_capture_for_uncertain_states():
    c = Controller()
    gate_result = GateResult(
        allowed=False,
        status="blocked",
        reasons=[GateReason(code="HERO_CARDS_UNCERTAIN", message="x")],
        confidence=0.1,
    )
    calls = []
    c._record_shadow_mode_failure = lambda **kwargs: calls.append(kwargs)
    intent = ActionIntent.from_payload({"action": "BET"})
    c._on_action_gate_failure(gate_result, make_canonical(), intent)
    assert calls and calls[0]["issue_type"] == "sanity_gate_failure"

    # raison sans capture -> aucun appel
    calls.clear()
    benign_gate = GateResult(allowed=True, status="ok", reasons=[])
    c._on_action_gate_failure(benign_gate, make_canonical(), intent)
    assert calls == []


def test_evaluate_fallback_execution_readiness_blocks_without_window(fast_sleep=None):
    c = Controller()
    c.action_controller = SimpleNamespace(hwnd=0)
    readiness = c._evaluate_fallback_execution_readiness(make_canonical())
    assert readiness["status"] == "blocked"
    assert "window_unbound" in readiness["reasons"]
    assert readiness["score"] < 1.0


def test_handle_stale_live_frame_marks_blocked_gate():
    from src.bot.gate_flow import GateFlowMixin as GFM

    c = Controller()
    c._max_live_frame_age_s = 0.6
    c.action_controller = SimpleNamespace(hwnd=0)
    c.decision_trace_history = []
    c.runtime_history_store = SimpleNamespace(append=lambda *a, **k: None)
    c.tracker = SimpleNamespace(current_hand_actions=[])

    captured = {}

    def fake_clear(canonical_state):
        captured["cleared"] = True
        c.last_decision_summary.clear() if hasattr(c.last_decision_summary, "clear") else None

    c._clear_live_decision_summary = fake_clear
    c.last_decision_summary = {}
    c.last_gate_result = GateResult(allowed=True, status="ready")
    c._handle_stale_live_frame(make_canonical(), frame_age_s=2.5)
    assert captured.get("cleared") is True
    assert c.last_gate_result.allowed is False
    assert c.last_decision_summary["execution"]["status"] == "stale_frame"
