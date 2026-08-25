# -*- coding: utf-8 -*-
"""Tests des métriques runtime extraites dans src/bot/metrics.py."""
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.metrics import MetricsMixin
from src.runtime.session import RuntimeSessionMixin


class FakeHistoryStore:
    def __init__(self):
        self.appended = []

    def summarize_records(self):
        return {
            "counts": {"events": 7, "decisions": 9, "incidents": 1, "metrics": 3},
            "latest_at": {
                "events": "2026-04-14T12:00:05Z",
                "decisions": "2026-04-14T12:00:06Z",
                "incidents": "2026-04-14T12:00:07Z",
                "metrics": "2026-04-14T12:00:08Z",
            },
        }

    def summarize(self):
        return {"path": "log/runtime_history.jsonl", "available": True, "size_bytes": 42}

    def read_recent(self, kind, limit=10):
        return []

    def append(self, kind, payload):
        self.appended.append((kind, payload))


def make_controller():
    class Controller(MetricsMixin, RuntimeSessionMixin):
        def __init__(self):
            self.runtime_history_store = FakeHistoryStore()
            self.runtime_event_history = [{"timestamp": "2026-04-14T12:00:00Z", "kind": "x"}]
            self.decision_trace_history = deque([{"timestamp": "2026-04-14T12:00:01Z"}])
            self.incident_history = deque()
            self.metric_snapshot_history = deque()
            self._last_metrics_snapshot_signature = ()
            self._last_metrics_persisted_at = None
            self.bridge_publishes = 0

        def _publish_runtime_bridge_state(self, force=False):
            self.bridge_publishes += 1

    return Controller()


def test_build_local_metrics_counts_blocks_fallbacks_and_latency():
    c = make_controller()
    history = {
        "decisions": [
            {
                "timestamp": "2026-04-14T12:00:00Z",
                "gate_result": {"allowed": True},
                "incidents": [],
                "source": "solver",
                "latency_ms": 120,
            },
            {
                "timestamp": "2026-04-14T12:01:00Z",
                "gate_result": {"allowed": False},
                "incidents": ["gate_blocked"],
                "source": "fallback",
                "latency_ms": 220,
            },
            {
                "timestamp": "not-a-date",
                "gate_result": {},
                "incidents": [],
                "source": "fallback",
                "latency_ms": "bad",
            },
        ]
    }
    m = c._build_local_metrics(history)
    assert m["decision_count"] == 3
    assert m["blocked_count"] == 1
    assert m["fallback_count"] == 2
    assert m["block_rate"] == round(1 / 3, 3)
    assert m["fallback_rate"] == round(2 / 3, 3)
    assert m["rolling_latency_ms"] == round(sum([120, 220]) / 2, 1)
    # deux timestamps valides espacés de 60s -> 3 décisions / minute
    assert m["decision_rate"] == 3.0
    assert m["window_size"] == 3


def test_build_local_metrics_handles_empty_history():
    c = make_controller()
    m = c._build_local_metrics({})
    assert m["decision_count"] == 0
    assert m["decision_rate"] == 0.0
    assert m["rolling_latency_ms"] == 0.0


def test_latest_timestamp_returns_first_entry_timestamp():
    assert MetricsMixin._latest_timestamp([{"timestamp": "t1"}, {"timestamp": "t2"}]) == "t1"
    assert MetricsMixin._latest_timestamp([]) is None
    assert MetricsMixin._latest_timestamp(["nope"]) is None


def test_parse_runtime_timestamp_accepts_z_suffix_and_rejects_garbage():
    parsed = MetricsMixin._parse_runtime_timestamp("2026-04-14T12:00:00Z")
    assert parsed is not None and parsed.isoformat().startswith("2026-04-14T12:00:00")
    assert MetricsMixin._parse_runtime_timestamp(None) is None
    assert MetricsMixin._parse_runtime_timestamp("") is None
    assert MetricsMixin._parse_runtime_timestamp("garbage") is None


def test_build_persisted_metrics_snapshot_merges_local_and_store_summaries():
    c = make_controller()
    local = {
        "decision_count": 5,
        "blocked_count": 1,
        "fallback_count": 2,
        "block_rate": 0.2,
        "fallback_rate": 0.4,
        "rolling_latency_ms": 150.0,
        "decision_rate": 6.0,
        "window_size": 5,
    }
    snapshot = c._build_persisted_metrics_snapshot(
        local,
        {},
        {"path": "log/runtime_history.jsonl", "available": True, "size_bytes": 42},
    )
    assert snapshot["decision_count"] == 5
    assert snapshot["runtime"]["event_count"] == 0
    assert snapshot["persisted"]["event_count"] == 7
    assert snapshot["persisted"]["metrics_count"] == 3
    assert snapshot["persisted"]["latest_decision_at"] == "2026-04-14T12:00:06Z"
    assert snapshot["storage"]["available"] is True
    assert snapshot["storage"]["path"] == "log/runtime_history.jsonl"
    assert snapshot["storage"]["size_bytes"] == 42


def test_persist_runtime_metrics_snapshot_persists_once_per_signature():
    c = make_controller()
    first = c._persist_runtime_metrics_snapshot(force=False)
    assert len(c.runtime_history_store.appended) == 1
    assert c.runtime_history_store.appended[0][0] == "metrics"
    assert c.metric_snapshot_history[0] is first
    assert c.bridge_publishes == 1

    # même signature et moins de 30s -> pas de nouvelle persistance
    second = c._persist_runtime_metrics_snapshot(force=False)
    assert second is first or len(c.runtime_history_store.appended) == 1
    assert len(c.runtime_history_store.appended) == 1

    # force=True persiste à nouveau
    c._persist_runtime_metrics_snapshot(force=True)
    assert len(c.runtime_history_store.appended) == 2
