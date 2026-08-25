"""Tests des snapshots opérateur et du bridge runtime (src/bot/operator_snapshot.py)."""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.operator_snapshot import OperatorSnapshotMixin
from src.runtime.session import RuntimeSessionMixin


def make_controller(controls=None):
    class Controller(OperatorSnapshotMixin, RuntimeSessionMixin):
        def __init__(self):
            self.operator_controls = controls or {}
            self.is_running = True
            self.last_go_live_gate = {"passed": True}
            self.hitl = None
            self.published = []
            self.applied = []
            self.events = []
            self.incidents = []

        def _push_runtime_event(self, kind, message, **context):
            self.events.append((kind, message, context))

        def _push_incident(self, incident_id, severity="warning", **context):
            self.incidents.append(incident_id)

        def _publish_runtime_bridge_state(self, force=False):
            self.published.append(force)

    return Controller()


def test_operator_snapshot_status_priority():
    c = make_controller()
    assert c._build_operator_snapshot()["status"] == "ready"

    c.is_running = False
    assert c._build_operator_snapshot()["status"] == "offline"

    c = make_controller({"paused": True})
    assert c._build_operator_snapshot()["status"] == "paused"

    c = make_controller({"manual_override_enabled": True})
    assert c._build_operator_snapshot()["status"] == "manual_override"

    c = make_controller({"observation_mode_enabled": True})
    assert c._build_operator_snapshot()["status"] == "observation"

    c = make_controller({"shadow_mode_enabled": True})
    assert c._build_operator_snapshot()["status"] == "shadow"

    c = make_controller({"assisted_mode_enabled": True})
    assert c._build_operator_snapshot()["status"] == "assisted"

    c = make_controller({})
    c.is_running = True
    c.last_go_live_gate = {"passed": False}
    assert c._build_operator_snapshot()["status"] == "go_live_blocked"


def test_update_operator_controls_enforces_exclusive_modes():
    c = make_controller({"assisted_mode_enabled": False})
    snapshot = c.update_operator_controls({"assistedModeEnabled": True})
    assert snapshot["assisted_mode_enabled"] is True
    assert snapshot["observation_mode_enabled"] is False
    controls = c.operator_controls
    assert controls["observation_mode_enabled"] is False
    assert controls["shadow_mode_enabled"] is False
    assert controls["manual_override_enabled"] is False
    assert any(kind == "operator" for kind, _msg, _ctx in c.events)


def test_update_operator_controls_rejects_empty_patch():
    c = make_controller()
    before = dict(c.operator_controls)
    snapshot = c.update_operator_controls("garbage")
    assert snapshot["status"] == "ready"
    assert "updated_at" not in c.operator_controls or c.operator_controls == before


def test_apply_bridge_command_routes_operator_patch_and_hitl(monkeypatch):
    waiting_hitl = SimpleNamespace(
        is_waiting_for_human=True,
        resolve_human_intervention=lambda boxes: applied.append(list(boxes)),
    )
    c = make_controller()
    c.hitl = waiting_hitl
    applied = []

    def fake_resolve(boxes):
        applied.append(list(boxes))

    waiting_hitl.resolve_human_intervention = fake_resolve

    c._apply_bridge_command(
        {"kind": "operator_patch", "payload": {"paused": True}, "command_id": "cmd-1"}
    )
    assert c.operator_controls.get("paused") in (True, False)
    assert c.published  # état du bridge republié après patch opérateur

    c.events.clear()
    c._apply_bridge_command(
        {"kind": "hitl_resolve", "payload": {"boxes": [1, 2]}, "command_id": "cmd-2"}
    )
    assert applied == [[1, 2]]
    assert any(msg == "bridge_hitl_resolved" for _k, msg, _c in c.events)

    c.events.clear()
    c._apply_bridge_command({"kind": "unknown_kind", "payload": {}, "command_id": "cmd-3"})
    assert c.incidents == ["bridge_unknown_command"]


def test_process_bridge_commands_without_bridge_is_noop():
    c = make_controller()
    c.operator_bridge = None
    c._process_bridge_commands()
    c._start_runtime_api_process()
    c._stop_runtime_api_process()
