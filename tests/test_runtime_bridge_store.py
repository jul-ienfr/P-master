from src.runtime.bridge_store import BridgeHitlProxy, BridgeRuntimeStatusProvider, RuntimeBridgeStore
from src.runtime.history_store import RuntimeHistoryStore


def test_runtime_bridge_store_publishes_and_reads_state(tmp_path):
    store = RuntimeBridgeStore(str(tmp_path / "bridge"))
    payload = {
        "session_id": "runtime-test",
        "is_running": True,
        "tracker": {"street": "FLOP"},
        "operator": {"status": "ready"},
    }

    store.publish_runtime_state(payload)
    loaded = store.read_runtime_state()

    assert loaded["session_id"] == "runtime-test"
    assert loaded["is_running"] is True
    assert loaded["tracker"]["street"] == "FLOP"
    assert loaded["operator"]["status"] == "ready"
    assert "bridge" in loaded


def test_runtime_bridge_store_queues_and_consumes_commands(tmp_path):
    store = RuntimeBridgeStore(str(tmp_path / "bridge"))

    store.queue_command("operator_patch", {"paused": True})
    store.queue_command("hitl_resolve", {"boxes": [{"x": 1}]})

    commands = store.consume_pending_commands(limit=10)

    assert [command["kind"] for command in commands] == ["operator_patch", "hitl_resolve"]
    assert commands[0]["payload"]["paused"] is True
    assert commands[1]["payload"]["boxes"] == [{"x": 1}]
    assert store.consume_pending_commands(limit=10) == []


def test_runtime_bridge_store_retries_windows_replace_lock(tmp_path, monkeypatch):
    store = RuntimeBridgeStore(str(tmp_path / "bridge"))
    payload = {"session_id": "runtime-lock", "is_running": True}
    real_replace = __import__("os").replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("file is locked")
        return real_replace(src, dst)

    monkeypatch.setattr("src.runtime.bridge_store.os.replace", flaky_replace)

    store.publish_runtime_state(payload)
    loaded = store.read_runtime_state()

    assert attempts["count"] == 3
    assert loaded["session_id"] == "runtime-lock"
    assert loaded["is_running"] is True


def test_bridge_runtime_status_provider_combines_runtime_and_persisted_history(tmp_path):
    bridge_store = RuntimeBridgeStore(str(tmp_path / "bridge"))
    history_store = RuntimeHistoryStore(
        enabled=True,
        file_path=str(tmp_path / "runtime_history.jsonl"),
        session_id="persisted-session",
    )
    history_store.append(
        "events",
        {"timestamp": "2026-04-13T10:00:00Z", "session_id": "persisted-session", "message": "persisted-event"},
    )
    history_store.append(
        "decisions",
        {
            "timestamp": "2026-04-13T10:00:01Z",
            "session_id": "persisted-session",
            "source": "fallback",
            "latency_ms": 42,
            "gate_result": {"allowed": False},
            "incidents": ["gate_blocked"],
        },
    )

    bridge_store.publish_runtime_state(
        {
            "session_id": "runtime-session",
            "is_running": True,
            "tracker": {"state_confidence": 0.91},
            "decision": {"action": "CHECK"},
            "health": {
                "solver": {
                    "status": "degraded",
                    "last_success_at": None,
                    "last_error_at": "2026-04-13T10:00:03Z",
                    "error_count": 2,
                    "cooldown_until": None,
                    "reasons": ["http_solver_unavailable"],
                }
            },
            "active_solver_backend": "gto_server",
            "degraded_reasons": ["solver:http_solver_unavailable"],
            "last_success_at": "2026-04-13T10:00:05Z",
            "operator": {"status": "assisted", "assisted_mode_enabled": True},
            "observation": {"mode_enabled": False, "collecting": True},
            "history": {
                "events": [{"timestamp": "2026-04-13T10:00:02Z", "message": "runtime-event"}],
                "decisions": [{"timestamp": "2026-04-13T10:00:03Z", "source": "solver", "latency_ms": 18}],
                "incidents": [],
                "metrics": [{"timestamp": "2026-04-13T10:00:04Z", "decision_count": 1}],
            },
        }
    )

    provider = BridgeRuntimeStatusProvider(bridge_store=bridge_store, history_store=history_store)
    status = provider.get_status()

    assert status["is_running"] is True
    assert status["operator"]["status"] == "assisted"
    assert status["history"]["events"][0]["message"] == "runtime-event"
    assert status["history"]["persisted"]["events"][0]["message"] == "persisted-event"
    assert status["history_summary"]["event_count"] == 1
    assert status["history_summary"]["persisted_event_count"] == 1
    assert status["metrics"]["decision_count"] == 1
    assert status["metrics"]["latest_snapshot"]["decision_count"] == 1
    assert status["health"]["solver"]["status"] == "degraded"
    assert status["active_solver_backend"] == "gto_server"
    assert status["degraded_reasons"] == ["solver:http_solver_unavailable"]
    assert status["last_success_at"] == "2026-04-13T10:00:05Z"


def test_bridge_hitl_proxy_reads_runtime_state_and_queues_resolution(tmp_path):
    store = RuntimeBridgeStore(str(tmp_path / "bridge"))
    store.publish_runtime_state(
        {
            "hitl": {
                "ready_for_training": False,
                "collected_samples": 7,
                "target_samples": 12,
                "is_waiting_for_human": True,
                "current_issue": {"type": "bbox", "reason": "need_help"},
            }
        }
    )

    proxy = BridgeHitlProxy(store)

    assert proxy.annotations_count == 7
    assert proxy.target_dataset_size == 12
    assert proxy.is_waiting_for_human is True
    assert proxy.current_issue == {"type": "bbox", "reason": "need_help"}
    assert proxy.check_convergence() is False

    proxy.resolve_human_intervention([{"x": 10, "y": 20}])
    commands = store.consume_pending_commands(limit=5)
    assert commands[0]["kind"] == "hitl_resolve"
    assert commands[0]["payload"]["boxes"] == [{"x": 10, "y": 20}]
