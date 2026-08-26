"""Tests des snapshots opérateur étendus : statut runtime, export observation, captures async."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.metrics import MetricsMixin
from src.bot.operator_snapshot import OperatorSnapshotMixin
from src.runtime.session import RuntimeSessionMixin


class Controller(OperatorSnapshotMixin, MetricsMixin, RuntimeSessionMixin):
    def __init__(self):
        self.operator_controls = {}
        self.is_running = True
        self.last_go_live_gate = {"passed": True}
        self.hitl = None
        self.db = SimpleNamespace(
            summarize_observation=lambda limit=5: {"total_hands": 12},
            export_observation_dataset=lambda player_limit=50, hand_limit=100: {"hands": [1, 2, 3]},
        )
        self.observation_dataset = None
        self.runtime_event_history = []
        self.decision_trace_history = []
        self.incident_history = []
        self.metric_snapshot_history = []
        self._last_metrics_snapshot_signature = ()
        self._last_metrics_persisted_at = None
        self.runtime_history_store = FakeStore()
        self.last_decision_summary = {}
        self.last_resolved_runtime_state = {}
        self.go_live_gate_thresholds = {}
        self.last_tracker_snapshot = {}
        self.last_canonical_spot_snapshot = {}
        self.last_gate_result = SimpleNamespace(to_dict=lambda: {})
        self.runtime_api_port = 8080
        self.health_monitor = None
        self.solver_provider = None
        self._loop_stage = ""

    def _copy_table_state(self, state):
        return state

    def _publish_runtime_bridge_state(self, force=False):
        pass


class FakeStore:
    def __init__(self):
        self.appended = []

    def summarize_records(self):
        return {"counts": {}, "latest_at": {}}

    def summarize(self):
        return {}

    def read_recent(self, kind, limit=10):
        return []

    def append(self, kind, payload):
        self.appended.append(kind)


def make_controller():
    c = Controller()
    # status provider minimal pour _get_runtime_status
    c.runtime_status_payload = {
        "is_running": True,
        "session_id": "sess-1",
        "tracker": {},
        "canonical_spot": {},
        "gate": {},
        "decision": {},
        "readiness": {},
        "operator": {},
        "observation": {},
        "history": {
            "events": [],
            "decisions": [],
            "incidents": [],
            "metrics": [],
            "persisted": {"events": [], "decisions": [], "incidents": [], "metrics": []},
        },
        "history_summary": {},
        "metrics": {},
    }
    return c


def test_export_observation_dataset_enriches_payload():
    c = make_controller()
    dataset = c._export_observation_dataset(player_limit=5, hand_limit=7)
    assert dataset["mode_enabled"] is False
    assert dataset["is_running"] is True
    assert dataset["hands"] == [1, 2, 3]


def test_capture_observation_dataset_sample_ignores_collector_errors():
    c = make_controller()

    class BoomCollector:
        def maybe_capture(self, **kwargs):
            raise RuntimeError("boom")

    c.observation_dataset = BoomCollector()
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    # ne doit pas lever : l'erreur est loguée et ignorée
    c._capture_observation_dataset_sample(frame, SimpleNamespace(metadata={}), SimpleNamespace(metadata={}))


def test_capture_observation_dataset_sample_async_runs_once_at_a_time():
    c = make_controller()
    calls = []

    class Collector:
        def maybe_capture(self, **kwargs):
            calls.append(kwargs)

    c.observation_dataset = Collector()
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    canonical = SimpleNamespace(model_copy=lambda deep: canonical_stub())
    detector_state = SimpleNamespace()

    def canonical_stub():
        return SimpleNamespace(metadata={})

    async def scenario():
        await c._capture_observation_dataset_sample_async(frame, canonical, detector_state)
        assert len(calls) == 1
        assert c._observation_capture_task_running is False

    asyncio.run(scenario())


def test_get_runtime_status_builds_full_payload():
    c = make_controller()
    status = c._get_runtime_status()
    assert status["is_running"] is True
    assert status["app_name"] == "PokerMaster"
    assert "rl_ab" in status["history_summary"]
    assert "policy_compare" in status["history_summary"]
    assert "go_live_gate" in status
    assert status["history_summary"]["persistence"] == {}


def test_operator_action_mode_follows_snapshot():
    c = make_controller()
    assert c._operator_action_mode() == "ready"
    c.operator_controls = {"paused": True}
    assert c._operator_action_mode() == "paused"


def test_set_loop_stage_updates_and_publishes():
    c = make_controller()
    published = []
    c._publish_runtime_bridge_state = lambda force=False: published.append(force)
    c._set_loop_stage("decision")
    assert c._loop_stage == "decision"
    assert published == []
    c._set_loop_stage("capture", publish=True)
    assert published == [True]
