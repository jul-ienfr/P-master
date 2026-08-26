"""Micro-tests : hitl snapshot, bridge state avec monitors, crop quality branches."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.operator_snapshot import OperatorSnapshotMixin
from src.runtime.session import RuntimeSessionMixin
from src.vision.crop_quality import analyze_crop_quality


class Controller(OperatorSnapshotMixin, RuntimeSessionMixin):
    def __init__(self):
        self.operator_controls = {}
        self.is_running = True
        self.last_go_live_gate = {"passed": True}
        self.hitl = None
        self.events = []
        self.runtime_event_history = []
        self.decision_trace_history = []
        self.incident_history = []
        self.metric_snapshot_history = []
        self._last_metrics_snapshot_signature = ()
        self._last_metrics_persisted_at = None
        self.runtime_history_store = SimpleNamespace(
            summarize_records=lambda: {"counts": {}, "latest_at": {}},
            summarize=lambda: {},
            read_recent=lambda kind, limit=10: [],
            append=lambda kind, payload: None,
        )
        self.last_decision_summary = {}
        self.last_resolved_runtime_state = {}
        self.go_live_gate_thresholds = {}
        self.health_monitor = SimpleNamespace(
            snapshot=lambda: {"status": "ok"},
            degraded_reasons=lambda: [],
            overall_last_success_at=lambda: "t1",
        )
        self.solver_provider = SimpleNamespace(active_backend=lambda: "native")
        self.runtime_api_port = 8080
        self.last_tracker_snapshot = {}
        self.last_canonical_spot_snapshot = {}
        self.last_gate_result = SimpleNamespace(to_dict=lambda: {})
        self._loop_stage = ""
        self.observation_dataset = None

    def _copy_table_state(self, state):
        return state

    def _push_runtime_event(self, kind, message, **context):
        self.events.append((kind, message))

    def _push_incident(self, incident_id, severity="warning", **context):
        pass

    def _build_local_metrics(self, history):
        return {}

    def _build_persisted_metrics_snapshot(self, local_metrics, history, persistence):
        return {}


def test_build_hitl_snapshot_serializes_issue():
    c = Controller()
    c.hitl = SimpleNamespace(
        current_issue={
            "type": "vision",
            "reason": "low_conf",
            "image_base64": "ZmFrZQ==",
            "width": 320,
            "height": 200,
            "resolution": "720p",
        },
        check_convergence=lambda: False,
        annotations_count=4,
        target_dataset_size=10,
        is_waiting_for_human=True,
    )
    snap = c._build_hitl_snapshot()
    assert snap["is_waiting_for_human"] is True
    assert snap["current_issue"]["type"] == "vision"
    assert snap["collected_samples"] == 4

    # issue non-dict -> sérialisée en None
    c.hitl.current_issue = "garbage"
    assert c._build_hitl_snapshot()["current_issue"] is None


def test_build_hitl_snapshot_without_hitl():
    c = Controller()
    with pytest.raises(AttributeError):
        c._build_hitl_snapshot()


def test_build_runtime_bridge_state_includes_operator_and_health():
    c = Controller()
    c.hitl = SimpleNamespace(
        current_issue=None,
        check_convergence=lambda: True,
        annotations_count=1,
        target_dataset_size=2,
        is_waiting_for_human=False,
    )
    state = c._build_runtime_bridge_state()
    assert state["app_name"] == "PokerMaster"
    assert state["health"] == {"status": "ok"}
    assert state["active_solver_backend"] == "native"
    # le bridge recalcule le go-live gate : avec un historique vide il est bloquant,
    # donc l'opérateur bascule en "go_live_blocked"
    assert state["operator"]["status"] == "go_live_blocked"
    assert state["go_live_gate"]["passed"] is False


def test_apply_bridge_command_hitl_ignored_when_not_waiting():
    c = Controller()
    c.hitl = SimpleNamespace(is_waiting_for_human=False)
    c._apply_bridge_command({"kind": "hitl_resolve", "payload": {"boxes": [1]}, "command_id": "c"})
    assert any(msg == "bridge_hitl_ignored" for _k, msg in c.events)


def test_analyze_crop_quality_rejects_tiny_crop():
    tiny = np.zeros((2, 2), dtype=np.uint8)
    report = analyze_crop_quality("board", tiny)
    assert report.rejected is True
    assert report.reject_reason == "crop_too_small"
