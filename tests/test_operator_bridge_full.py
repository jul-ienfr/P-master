# -*- coding: utf-8 -*-
"""Tests de l'OperatorBridge (publication, commandes, process API) et du RuntimeLoop."""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.operator_bridge import OperatorBridge


class RecordingHealth:
    def __init__(self):
        self.events = []

    def record_success(self, component):
        self.events.append(("success", component))

    def record_error(self, component, reason, **kwargs):
        self.events.append(("error", component, reason))


@pytest.fixture()
def bridge(tmp_path):
    from src.runtime.bridge_store import RuntimeBridgeStore

    store = RuntimeBridgeStore(str(tmp_path / "bridge"))
    history_store = types.SimpleNamespace(file_path=str(tmp_path / "history.jsonl"))
    health = RecordingHealth()
    bridge = OperatorBridge(
        root=tmp_path,
        bridge_store=store,
        history_store=history_store,
        runtime_api_port=8765,
        build_state=lambda: {"operator": {"status": "ready"}},
        apply_command=lambda command: applied.append(command),
        push_incident=lambda *args, **kwargs: incidents.append((args, kwargs)),
        health_monitor=health,
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )
    return bridge


applied = []
incidents = []
sleeps = []


def test_publish_state_throttles_then_forces(tmp_path):
    from src.runtime.bridge_store import RuntimeBridgeStore

    store = RuntimeBridgeStore(str(tmp_path / "b1"))
    calls = []

    class Bridge(RuntimeBridgeStore):
        pass

    health = RecordingHealth()
    bridge = OperatorBridge(
        root=tmp_path,
        bridge_store=store,
        history_store=types.SimpleNamespace(file_path="h"),
        runtime_api_port=8000,
        build_state=lambda: calls.append(1) or {"operator": {}},
        apply_command=lambda c: None,
        push_incident=lambda *a, **k: None,
        health_monitor=health,
    )
    bridge.publish_state(force=True)
    assert calls == [1]
    assert ("success", "bridge") in health.events
    # pas forcé et dans l'intervalle -> ignoré
    bridge.publish_state()
    assert calls == [1]


def test_publish_state_records_error_on_failure(tmp_path):
    from src.runtime.bridge_store import RuntimeBridgeStore

    store = RuntimeBridgeStore(str(tmp_path / "b2"))

    def broken_build():
        raise RuntimeError("disk full")

    health = RecordingHealth()
    bridge = OperatorBridge(
        root=tmp_path,
        bridge_store=store,
        history_store=None,
        runtime_api_port=8000,
        build_state=broken_build,
        apply_command=lambda c: None,
        push_incident=lambda *a, **k: None,
        health_monitor=health,
    )
    bridge.publish_state(force=True)
    assert health.events[0][0] == "error"


def test_process_pending_commands_applies_and_reports_errors(bridge):
    global applied
    bridge.bridge_store.queue_command("operator_patch", {"paused": True})

    def failing_apply(command):
        if command["kind"] == "operator_patch":
            raise RuntimeError("apply failed")

    bridge.apply_command = failing_apply
    bridge.process_pending_commands()
    assert incidents and incidents[0][1]["kind"] == "operator_patch"
    assert incidents[0][1]["severity"] == "error"

    # file vide : rien ne casse
    bridge.process_pending_commands()


def test_start_api_process_missing_entrypoint_raises(tmp_path):
    from src.runtime.bridge_store import RuntimeBridgeStore

    store = RuntimeBridgeStore(str(tmp_path / "b3"))
    bridge = OperatorBridge(
        root=tmp_path / "nowhere",
        bridge_store=store,
        history_store=None,
        runtime_api_port=8000,
        build_state=dict,
        apply_command=lambda c: None,
        push_incident=lambda *a, **k: None,
    )
    with pytest.raises(RuntimeError):
        bridge.start_api_process()


def test_start_api_process_already_running_is_noop(tmp_path):
    from src.runtime.bridge_store import RuntimeBridgeStore

    store = RuntimeBridgeStore(str(tmp_path / "b4"))
    health = RecordingHealth()
    bridge = OperatorBridge(
        root=tmp_path,
        bridge_store=store,
        history_store=None,
        runtime_api_port=8000,
        build_state=dict,
        apply_command=lambda c: None,
        push_incident=lambda *a, **k: None,
        health_monitor=health,
    )
    bridge.api_process = types.SimpleNamespace(poll=lambda: None)
    bridge.start_api_process()
    assert ("success", "api") in health.events


def test_stop_api_process_terminates_and_closes_handles(tmp_path):
    from src.runtime.bridge_store import RuntimeBridgeStore

    store = RuntimeBridgeStore(str(tmp_path / "b5"))
    health = RecordingHealth()
    bridge = OperatorBridge(
        root=tmp_path,
        bridge_store=store,
        history_store=None,
        runtime_api_port=8000,
        build_state=dict,
        apply_command=lambda c: None,
        push_incident=lambda *a, **k: None,
        health_monitor=health,
    )
    terminated = []
    bridge.api_process = types.SimpleNamespace(
        terminate=lambda: terminated.append("t"),
        wait=lambda timeout=2.0: 0,
    )
    closed = []
    handle = types.SimpleNamespace(close=lambda: closed.append(1))
    bridge._api_stdout_handle = handle
    bridge.stop_api_process()
    assert terminated == ["t"]
    assert closed == [1]
    assert bridge.api_process is None
