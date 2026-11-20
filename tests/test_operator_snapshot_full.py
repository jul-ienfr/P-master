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


# --- SLO exposé par le bridge (spec 008, US2) --------------------------------
# Ce contrôleur calcule de **vraies** métriques (MetricsMixin) : les SLO sont
# évalués sur l'historique réel, jamais sur un stub.


def _decision(latency_ms: float, *, source: str = "GTO_RUST") -> dict:
    return {
        "timestamp": "2026-11-20T10:00:00+00:00",
        "latency_ms": latency_ms,
        "source": source,
        "gate_result": {"allowed": True},
        "metadata": {"stages_ms": {"solver": latency_ms / 2.0}},
    }


def _slo_controller() -> Controller:
    c = make_controller()
    c.hitl = SimpleNamespace(
        current_issue=None,
        check_convergence=lambda: True,
        annotations_count=0,
        target_dataset_size=1,
        is_waiting_for_human=False,
    )
    c.events = []
    c._push_runtime_event = lambda kind, message, **context: c.events.append((kind, message))
    return c


def test_bridge_state_exposes_an_slo_block_over_real_metrics():
    c = _slo_controller()
    c.decision_trace_history = [_decision(120.0), _decision(140.0)]
    slo = c._build_runtime_bridge_state()["slo"]
    assert slo["metrics"]["decision_count"] == 2
    assert slo["metrics"]["latency_p95_ms"] == 140.0
    assert slo["objectives"]  # évalué, non vide
    assert c.last_slo_evaluation["evaluated_at"]


def test_slo_breach_is_signalled_once_not_per_snapshot():
    c = _slo_controller()
    c.decision_trace_history = [_decision(100.0) for _ in range(5)]  # sain
    c._build_runtime_bridge_state()  # première observation : aucun événement
    assert [kind for kind, _msg in c.events if kind.startswith("slo_")] == []

    # Cinq décisions sur cinq en fallback : le taux dépasse la cible de 0,1.
    c.decision_trace_history = [_decision(100.0, source="FALLBACK") for _ in range(5)]
    c._build_runtime_bridge_state()
    assert [kind for kind, _msg in c.events if kind == "slo_breached"] == ["slo_breached"]
    c._build_runtime_bridge_state()  # même ensemble franchi : aucun bruit
    assert [kind for kind, _msg in c.events if kind == "slo_breached"] == ["slo_breached"]


def test_slo_recovery_is_signalled_when_the_objective_holds_again():
    c = _slo_controller()
    c.decision_trace_history = [_decision(100.0) for _ in range(5)]
    c._build_runtime_bridge_state()  # première observation : sain
    c.decision_trace_history = [_decision(100.0, source="FALLBACK") for _ in range(5)]
    c._build_runtime_bridge_state()
    assert any(kind == "slo_breached" for kind, _msg in c.events)
    c.decision_trace_history = [_decision(100.0) for _ in range(5)]
    c._build_runtime_bridge_state()
    assert any(kind == "slo_recovered" for kind, _msg in c.events)


def test_empty_slo_configuration_disables_objectives_without_false_alert():
    c = _slo_controller()
    c.config = {"bot": {"slo": []}}
    c.decision_trace_history = [_decision(100.0, source="FALLBACK")] * 6
    slo = c._build_runtime_bridge_state()["slo"]
    assert slo["objectives"] == []
    assert slo["alerts"] == []
    assert [kind for kind, _msg in c.events if kind.startswith("slo_")] == []


def test_slo_evaluation_does_not_touch_the_go_live_gate_verdict():
    c = _slo_controller()
    c.decision_trace_history = [_decision(100.0, source="FALLBACK")] * 6
    state = c._build_runtime_bridge_state()
    assert state["slo"]["alerts"]  # un SLO est bien franchi
    # Le gate garde son propre verdict, nommé séparément (FR-009).
    assert state["go_live_gate"]["verdict"] == c.last_go_live_gate["verdict"]


def test_runtime_status_exposes_slo_without_pushing_an_event():
    c = _slo_controller()
    c.decision_trace_history = [_decision(100.0, source="FALLBACK")] * 6
    status = c._get_runtime_status()
    assert "slo" in status
    assert status["slo"]["metrics"]["decision_count"] == 6
    # La lecture de statut n'écrit rien : aucun événement poussé.
    assert [kind for kind, _msg in c.events if kind.startswith("slo_")] == []
