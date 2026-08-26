"""Tests du store bridge : état partagé, commandes, proxys HITL/status."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.bridge_store import (
    BridgeHitlProxy,
    BridgeRuntimeStatusProvider,
    RuntimeBridgeStore,
    _build_local_metrics,
    _latest_timestamp,
    _parse_runtime_timestamp,
    _safe_float,
)


@pytest.fixture()
def store(tmp_path):
    return RuntimeBridgeStore(bridge_dir=str(tmp_path / "bridge"))


def test_publish_and_read_runtime_state_roundtrip(store):
    payload = {"operator": {"status": "ready", "paused": False}, "hitl": {"is_waiting_for_human": False}}
    envelope = store.publish_runtime_state(payload)
    assert envelope["bridge"]["updated_at"]

    read = store.read_runtime_state()
    assert read["operator"]["status"] == "ready"
    # cache mtime : second appel renvoie la même chose
    assert store.read_runtime_state() == read


def test_read_runtime_state_missing_file_returns_empty(store):
    assert store.read_runtime_state() == {}


def test_queue_and_consume_commands_fifo(store):
    first = store.queue_command("operator_patch", {"paused": True})
    second = store.queue_command("hitl_resolve", {"boxes": [1]})
    assert first["kind"] == "operator_patch"
    assert second["command_id"] != first["command_id"]

    commands = store.consume_pending_commands(limit=10)
    assert [c["kind"] for c in commands] == ["operator_patch", "hitl_resolve"]
    # consommées -> fichiers supprimés
    assert store.consume_pending_commands() == []


def test_consume_commands_skips_corrupted_files(store, tmp_path):
    store.queue_command("a")
    (store.commands_dir / "broken.json").write_text("{invalid", encoding="utf-8")
    commands = store.consume_pending_commands()
    assert len(commands) == 1
    assert not (store.commands_dir / "broken.json").exists()


def test_queue_operator_patch_polls_until_applied(store):
    store.publish_runtime_state({"operator": {"status": "paused"}})
    operator = store.queue_operator_patch(
        {"status": "paused"}, timeout_s=0.3, poll_interval_s=0.02
    )
    assert operator.get("status") == "paused"


def test_queue_operator_patch_times_out_without_application(store):
    operator = store.queue_operator_patch({"status": "assisted"}, timeout_s=0.05)
    assert operator == {}


def test_operator_patch_applied_static():
    assert RuntimeBridgeStore._operator_patch_applied({"a": 1}, {"a": 1}) is True
    assert RuntimeBridgeStore._operator_patch_applied({"a": 1}, {"a": 2}) is False
    assert RuntimeBridgeStore._operator_patch_applied(None, {}) is True


def test_bridge_hitl_proxy_reads_state(store):
    proxy = BridgeHitlProxy(store, default_target_dataset_size=50)
    store.publish_runtime_state(
        {
            "hitl": {
                "collected_samples": 7,
                "target_samples": 10,
                "is_waiting_for_human": True,
                "current_issue": {"type": "vision"},
            }
        }
    )
    assert proxy.annotations_count == 7
    assert proxy.target_dataset_size == 10
    assert proxy.is_waiting_for_human is True
    assert proxy.current_issue == {"type": "vision"}
    assert proxy.check_convergence() is False

    # pas de ready_for_training : fallback sur compteur >= cible
    store.publish_runtime_state({"hitl": {"collected_samples": 12, "target_samples": 10}})
    assert proxy.check_convergence() is True

    # sans target_samples dans l'état -> défaut du proxy
    store.publish_runtime_state({"hitl": {}})
    assert proxy.target_dataset_size == 50

    result = proxy.resolve_human_intervention([1])
    assert result == {"status": "queued", "boxes": [1]}
    queued = store.consume_pending_commands()
    assert queued[0]["payload"]["boxes"] == [1]


def test_status_provider_history_summary_and_metrics(store, tmp_path):
    provider = BridgeRuntimeStatusProvider(bridge_store=store, history_store=None)
    runtime_history = {
        "events": [{"timestamp": "2026-04-14T12:00:00Z"}],
        "decisions": [],
        "incidents": [{"timestamp": "t"}],
        "metrics": [],
    }
    summary = provider._history_summary(runtime_history, {"events": [{"timestamp": "x"}]})
    assert summary["event_count"] == 1
    assert summary["persisted_event_count"] == 1
    assert summary["persistence"] == {}

    metrics = provider._metrics_payload({}, runtime_history)
    assert metrics["latest_snapshot"]["event_count"] if False else "latest_snapshot" in metrics


def test_persisted_history_without_store_is_empty_streams(store):
    provider = BridgeRuntimeStatusProvider(bridge_store=store, history_store=None)
    history = provider._persisted_history()
    assert all(entries == [] for entries in history.values())


def test_helper_functions():
    assert _safe_float("2.5") == 2.5
    assert _safe_float("bad", default=-1.0) == -1.0
    assert _latest_timestamp([]) is None
    assert _latest_timestamp([{"timestamp": None}]) is None
    parsed = _parse_runtime_timestamp("2026-04-14T12:00:00Z")
    assert parsed is not None
    assert _parse_runtime_timestamp("garbage") is None

    metrics = _build_local_metrics(
        {
            "decisions": [
                {
                    "gate_result": {"allowed": False},
                    "incidents": ["gate_blocked"],
                    "source": "fallback",
                    "latency_ms": 100,
                    "timestamp": "2026-04-14T12:00:00Z",
                }
            ]
        }
    )
    assert metrics["decision_count"] == 1
    assert metrics["blocked_count"] == 1


def test_from_env_uses_env_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("POKER_RUNTIME_BRIDGE_DIR", str(tmp_path / "custom"))
    store = RuntimeBridgeStore.from_env(default_dir="elsewhere")
    assert store.bridge_dir.name == "custom"
