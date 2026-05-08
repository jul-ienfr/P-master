from pathlib import Path
import sys
import types
import itertools

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.loop import RuntimeLoop


class FakeDB:
    def __init__(self):
        self.connected = False
        self.closed = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed = True


class FakeCamera:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.controller = None
        self.frames_requested = 0

    def start(self, region=None, hwnd=None):
        self.started = True

    def stop(self):
        self.stopped = True

    def get_latest_frame(self):
        self.frames_requested += 1
        if self.controller is not None and self.frames_requested >= 1:
            self.controller.is_running = False
        return None


def test_runtime_loop_starts_and_shuts_down_when_no_frame_is_available():
    events = []
    publish_calls = []
    stages = []
    persist_calls = []

    controller = types.SimpleNamespace(
        db=FakeDB(),
        camera=FakeCamera(),
        action_controller=types.SimpleNamespace(hwnd=None),
        runtime_api_port=8005,
        is_running=False,
        _publish_runtime_bridge_state=lambda force=False: publish_calls.append(force),
        _start_runtime_api_process=lambda: events.append(("api", "start")),
        _stop_runtime_api_process=lambda: events.append(("api", "stop")),
        _push_runtime_event=lambda kind, message, **context: events.append((kind, message, context)),
        _persist_runtime_metrics_snapshot=lambda force=False: persist_calls.append(force),
        _refresh_capture_region=lambda force=False: (0, 0, 100, 100),
        _set_loop_stage=lambda stage, publish=False: stages.append((stage, publish)),
        _process_bridge_commands=lambda: None,
        _operator_action_mode=lambda: "ready",
        _process_frame=None,
        _convert_state_for_tracker=None,
        _handle_stale_live_frame=None,
        _build_gate_tracker_snapshot=None,
        _resolve_live_decision_context=None,
        _run_decision_gate_flow=None,
        _clear_live_decision_summary=None,
        _clear_live_execution_guard=None,
        tracker=None,
        _build_tracker_snapshot=None,
        _record_runtime_transition=None,
        _log_loop_timing=None,
        _max_live_frame_age_s=1.0,
        _log_live_details=lambda canonical_state, state: None,
    )
    controller.camera.controller = controller

    runtime_loop = RuntimeLoop(controller)
    import asyncio
    asyncio.run(runtime_loop.run())

    assert controller.db.connected is True
    assert controller.db.closed is True
    assert controller.camera.started is True
    assert controller.camera.stopped is True
    assert ("api", "start") in events
    assert ("api", "stop") in events
    runtime_events = [entry for entry in events if len(entry) == 3]
    assert any(kind == "lifecycle" and message == "bot_started" for kind, message, _ in runtime_events)
    assert any(stage == "capture_frame" for stage, _ in stages)
    assert publish_calls
    assert persist_calls


def test_runtime_loop_updates_tracker_before_logging_and_decision():
    call_order = []

    class _ActionButtons(list):
        pass

    class OneFrameCamera(FakeCamera):
        def get_latest_frame(self):
            self.frames_requested += 1
            if self.frames_requested > 1 and self.controller is not None:
                self.controller.is_running = False
                return None
            return "frame"

    canonical_state = types.SimpleNamespace(
        hero_cards=("Ah", "Kd"),
        legal_actions=("CHECK", "BET"),
        street="PREFLOP",
        spot_id="live:PREFLOP:test",
        pot=1.5,
        board=(),
        players=(),
        action_buttons=(),
        state_confidence=0.8,
        metadata={},
        to_dict=lambda: {"street": "PREFLOP", "hero_cards": ["Ah", "Kd"], "legal_actions": ["CHECK", "BET"]},
        to_tracker_payload=lambda: {"street": "PREFLOP", "hero_cards": ["Ah", "Kd"], "legal_actions": ["CHECK", "BET"], "spot_id": "live:PREFLOP:test"},
    )
    resolved_state = types.SimpleNamespace(
        hero_cards=("Ah", "Kd"),
        legal_actions=("CHECK", "BET"),
        street="FLOP",
        pot=1.5,
        board=(),
        to_tracker_payload=lambda: {"street": "FLOP", "hero_cards": ["Ah", "Kd"], "legal_actions": ["CHECK", "BET"], "spot_id": "live:FLOP:test"},
    )
    tracker = types.SimpleNamespace(
        update_from_vision=None,
        current_hand_actions=[],
    )

    async def _update_from_vision(_payload):
        call_order.append("tracker_update")

    tracker.update_from_vision = _update_from_vision

    async def _run_decision_gate_flow(**kwargs):
        call_order.append(f"decision:{kwargs['canonical_state'].street}")
        controller.is_running = False
        return {"gate_result": types.SimpleNamespace(allowed=True)}

    async def _process_frame(_frame):
        return types.SimpleNamespace(action_buttons=_ActionButtons())

    controller = types.SimpleNamespace(
        db=FakeDB(),
        camera=OneFrameCamera(),
        action_controller=types.SimpleNamespace(hwnd=None),
        runtime_api_port=8005,
        is_running=False,
        _publish_runtime_bridge_state=lambda force=False: None,
        _start_runtime_api_process=lambda: None,
        _stop_runtime_api_process=lambda: None,
        _push_runtime_event=lambda kind, message, **context: None,
        _persist_runtime_metrics_snapshot=lambda force=False: None,
        _refresh_capture_region=lambda force=False: (0, 0, 100, 100),
        _set_loop_stage=lambda stage, publish=False: None,
        _process_bridge_commands=lambda: None,
        _operator_action_mode=lambda: "ready",
        _process_frame=_process_frame,
        _convert_state_for_tracker=lambda state, frame: canonical_state,
        _build_resolved_runtime_state=lambda state: resolved_state,
        _handle_stale_live_frame=lambda canonical_state, frame_age_s: None,
        _build_gate_tracker_snapshot=lambda canonical_state: {},
        _resolve_live_decision_context=lambda canonical_state: (types.SimpleNamespace(name="villain", has_button=False), 50.0),
        _run_decision_gate_flow=_run_decision_gate_flow,
        _clear_live_decision_summary=lambda canonical_state: None,
        _clear_live_execution_guard=lambda: None,
        tracker=tracker,
        _build_tracker_snapshot=lambda tracker_data: {"street": "FLOP"},
        _record_runtime_transition=lambda tracker_snapshot: call_order.append(f"transition:{tracker_snapshot['street']}"),
        _log_loop_timing=lambda **kwargs: None,
        _max_live_frame_age_s=1.0,
        _log_live_details=lambda canonical_state, state: call_order.append(f"log:{canonical_state.street}"),
        _push_incident=lambda *args, **kwargs: None,
        _get_live_loop_sleep_interval=lambda actionable_spot: 0.01 if actionable_spot else 0.05,
        last_tracker_snapshot={},
        last_canonical_spot_snapshot=None,
        _debounce_state_hash=hash(("FLOP", 1.5, ("Ah", "Kd"), (), ("CHECK", "BET"))),
        _debounce_start_time=0.0,
        _live_debounce_stable_window_s=0.0,
    )
    controller.camera.controller = controller

    import asyncio
    asyncio.run(RuntimeLoop(controller).run())

    assert call_order[:4] == ["tracker_update", "log:FLOP", "transition:FLOP", "decision:FLOP"]


def test_live_loop_sleep_interval_slows_down_when_decision_is_locked():
    from src.main import SuperBotController

    controller = object.__new__(SuperBotController)
    controller._locked_spot_poll_interval_s = 0.1
    controller.last_decision_summary = {"execution": {"status": "decision_locked", "reason": "same_spot_unconfirmed"}}

    assert controller._get_live_loop_sleep_interval(True) == 0.1
    assert controller._get_live_loop_sleep_interval(False) == 0.05

    controller.last_decision_summary = {"execution": {"status": "suppressed_recent_execution"}}
    assert controller._get_live_loop_sleep_interval(True) == 0.01


def test_runtime_loop_updates_fast_pot_snapshot_before_main_pipeline():
    call_order = []

    class OneFrameCamera(FakeCamera):
        def get_latest_frame(self):
            self.frames_requested += 1
            if self.frames_requested > 1 and self.controller is not None:
                self.controller.is_running = False
                return None
            return __import__("numpy").zeros((120, 160, 3), dtype="uint8")

    async def _process_frame(_frame):
        call_order.append("process_frame")
        controller.is_running = False
        return types.SimpleNamespace(action_buttons=[], metadata={})

    tracker = types.SimpleNamespace(update_from_vision=None, current_hand_actions=[])

    async def _update_from_vision(_payload):
        call_order.append("tracker_update")

    tracker.update_from_vision = _update_from_vision

    controller = types.SimpleNamespace(
        db=FakeDB(),
        camera=OneFrameCamera(),
        action_controller=types.SimpleNamespace(hwnd=None),
        runtime_api_port=8005,
        is_running=False,
        frame_pipeline=types.SimpleNamespace(_read_live_pot_fast=lambda frame, pot_box: {"value": 1234.0, "observed_at_monotonic": 1.0}),
        _update_fast_pot_snapshot=lambda snapshot: call_order.append(f"fast_pot:{snapshot['value']}"),
        _publish_runtime_bridge_state=lambda force=False: None,
        _start_runtime_api_process=lambda: None,
        _stop_runtime_api_process=lambda: None,
        _push_runtime_event=lambda kind, message, **context: None,
        _persist_runtime_metrics_snapshot=lambda force=False: None,
        _refresh_capture_region=lambda force=False: (0, 0, 100, 100),
        _set_loop_stage=lambda stage, publish=False: None,
        _process_bridge_commands=lambda: None,
        _operator_action_mode=lambda: "ready",
        _process_frame=_process_frame,
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(to_dict=lambda: {}, to_tracker_payload=lambda: {}, hero_cards=(), legal_actions=(), street="IDLE"),
        _build_resolved_runtime_state=lambda state: types.SimpleNamespace(hero_cards=(), legal_actions=(), street="IDLE", pot=0.0, board=(), metadata={}),
        _handle_stale_live_frame=lambda canonical_state, frame_age_s: None,
        _build_gate_tracker_snapshot=lambda canonical_state: {},
        _resolve_live_decision_context=lambda canonical_state: (None, 0.0),
        _run_decision_gate_flow=None,
        _clear_live_decision_summary=lambda canonical_state: None,
        _clear_live_execution_guard=lambda: None,
        tracker=tracker,
        _build_tracker_snapshot=lambda tracker_data: {"street": "IDLE", "pot": 1234.0},
        _record_runtime_transition=lambda tracker_snapshot: None,
        _log_loop_timing=lambda **kwargs: None,
        _max_live_frame_age_s=1.0,
        _log_live_details=lambda canonical_state, state: None,
        _push_incident=lambda *args, **kwargs: None,
        _get_live_loop_sleep_interval=lambda actionable_spot: 0.01,
        last_tracker_snapshot={},
        last_canonical_spot_snapshot=None,
        observation_dataset=types.SimpleNamespace(enabled=False),
    )
    controller.camera.controller = controller

    import asyncio
    asyncio.run(RuntimeLoop(controller).run())

    assert call_order[0] == "fast_pot:1234.0"
    assert "process_frame" in call_order


def test_runtime_loop_uses_fast_pixel_probe_to_trigger_hitl_without_turn_layout():
    class OneFrameCamera(FakeCamera):
        def get_latest_frame(self):
            self.frames_requested += 1
            if self.frames_requested > 1 and self.controller is not None:
                self.controller.is_running = False
                return None
            return np.zeros((120, 160, 3), dtype="uint8")

    hitl_calls = []

    class FakeHITL:
        is_waiting_for_human = False

        async def request_intervention_async(self, frame, issue_type, reason):
            hitl_calls.append((issue_type, reason, frame.shape))
            controller.is_running = False

        def record_anomaly_silently(self, frame, issue_type, reason):
            hitl_calls.append((issue_type, reason, frame.shape))

    async def _process_frame(_frame):
        return types.SimpleNamespace(action_buttons=[], hero_cards=[], metadata={})

    tracker = types.SimpleNamespace(update_from_vision=None, current_hand_actions=[], hero_cards=[])

    async def _update_from_vision(_payload):
        return None

    tracker.update_from_vision = _update_from_vision

    controller = types.SimpleNamespace(
        db=FakeDB(),
        camera=OneFrameCamera(),
        action_controller=types.SimpleNamespace(hwnd=None),
        runtime_api_port=8005,
        is_running=False,
        frame_pipeline=types.SimpleNamespace(_read_live_pot_fast=lambda frame, pot_box: {}),
        pixel_probe=types.SimpleNamespace(is_our_turn=lambda frame: True),
        hitl=FakeHITL(),
        _publish_runtime_bridge_state=lambda force=False: None,
        _start_runtime_api_process=lambda: None,
        _stop_runtime_api_process=lambda: None,
        _push_runtime_event=lambda kind, message, **context: None,
        _persist_runtime_metrics_snapshot=lambda force=False: None,
        _refresh_capture_region=lambda force=False: (0, 0, 100, 100),
        _set_loop_stage=lambda stage, publish=False: None,
        _process_bridge_commands=lambda: None,
        _operator_action_mode=lambda: "ready",
        _process_frame=_process_frame,
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(to_dict=lambda: {}, to_tracker_payload=lambda: {}, hero_cards=(), legal_actions=(), street="IDLE", spot_id="live:IDLE:test", pot=0.0, board=(), players=(), action_buttons=(), state_confidence=0.0, metadata={}),
        _build_resolved_runtime_state=lambda state: types.SimpleNamespace(hero_cards=(), legal_actions=(), street="IDLE", pot=0.0, board=(), metadata={}),
        _handle_stale_live_frame=lambda canonical_state, frame_age_s: None,
        _build_gate_tracker_snapshot=lambda canonical_state: {},
        _resolve_live_decision_context=lambda canonical_state: (None, 0.0),
        _run_decision_gate_flow=None,
        _clear_live_decision_summary=lambda canonical_state: None,
        _clear_live_execution_guard=lambda: None,
        tracker=tracker,
        _build_tracker_snapshot=lambda tracker_data: {"street": "IDLE", "pot": 0.0},
        _record_runtime_transition=lambda tracker_snapshot: None,
        _log_loop_timing=lambda **kwargs: None,
        _max_live_frame_age_s=1.0,
        _log_live_details=lambda canonical_state, state: None,
        _push_incident=lambda *args, **kwargs: None,
        _get_live_loop_sleep_interval=lambda actionable_spot: 0.01,
        last_tracker_snapshot={},
        last_canonical_spot_snapshot=None,
        observation_dataset=types.SimpleNamespace(enabled=False),
    )
    controller.camera.controller = controller

    import asyncio
    asyncio.run(RuntimeLoop(controller).run())

    assert hitl_calls
    assert hitl_calls[0][0] == "yolo_failure"
    assert controller._last_turn_probe_snapshot["is_our_turn"] is True


def test_runtime_loop_measures_actionable_frame_age_from_state_ready_time(monkeypatch):
    monotonic_values = itertools.count(start=1000.0, step=0.6)
    monkeypatch.setattr("src.runtime.loop.time.monotonic", lambda: next(monotonic_values))

    stale_calls = []

    class OneFrameCamera(FakeCamera):
        def get_latest_frame(self):
            self.frames_requested += 1
            if self.frames_requested > 1 and self.controller is not None:
                self.controller.is_running = False
                return None
            return np.zeros((40, 40, 3), dtype="uint8")

    async def _process_frame(_frame):
        return types.SimpleNamespace(action_buttons=[], hero_cards=[], metadata={})

    canonical_state = types.SimpleNamespace(
        hero_cards=("Tc", "2s"),
        legal_actions=("CALL",),
        street="PREFLOP",
        spot_id="live:PREFLOP:test",
        pot=1.0,
        board=(),
        players=(),
        action_buttons=("call_button",),
        state_confidence=0.8,
        metadata={},
        to_dict=lambda: {},
        to_tracker_payload=lambda: {"street": "PREFLOP", "hero_cards": ["Tc", "2s"], "legal_actions": ["CALL"], "spot_id": "live:PREFLOP:test"},
    )

    tracker = types.SimpleNamespace(current_hand_actions=[])

    async def _update_from_vision(_payload):
        return None

    tracker.update_from_vision = _update_from_vision

    controller = types.SimpleNamespace(
        db=FakeDB(),
        camera=OneFrameCamera(),
        action_controller=types.SimpleNamespace(hwnd=None),
        runtime_api_port=8005,
        is_running=False,
        frame_pipeline=types.SimpleNamespace(_read_live_pot_fast=lambda frame, pot_box: {}),
        _publish_runtime_bridge_state=lambda force=False: None,
        _start_runtime_api_process=lambda: None,
        _stop_runtime_api_process=lambda: None,
        _push_runtime_event=lambda kind, message, **context: None,
        _persist_runtime_metrics_snapshot=lambda force=False: None,
        _refresh_capture_region=lambda force=False: (0, 0, 100, 100),
        _set_loop_stage=lambda stage, publish=False: None,
        _process_bridge_commands=lambda: None,
        _operator_action_mode=lambda: "ready",
        _process_frame=_process_frame,
        _convert_state_for_tracker=lambda state, frame: canonical_state,
        _build_resolved_runtime_state=lambda state: canonical_state,
        _handle_stale_live_frame=lambda canonical_state, frame_age_s: stale_calls.append(frame_age_s),
        _build_gate_tracker_snapshot=lambda canonical_state: {},
        _resolve_live_decision_context=lambda canonical_state: (types.SimpleNamespace(name="villain", has_button=False), 10.0),
        _run_decision_gate_flow=None,
        _clear_live_decision_summary=lambda canonical_state: None,
        _clear_live_execution_guard=lambda: None,
        tracker=tracker,
        _build_tracker_snapshot=lambda tracker_data: {"street": "PREFLOP", "pot": 1.0},
        _record_runtime_transition=lambda tracker_snapshot: None,
        _log_loop_timing=lambda **kwargs: None,
        _max_live_frame_age_s=1.25,
        _log_live_details=lambda canonical_state, state: None,
        _push_incident=lambda *args, **kwargs: None,
        _get_live_loop_sleep_interval=lambda actionable_spot: 0.01,
        _capture_context_recently_changed=lambda: False,
        last_tracker_snapshot={},
        last_canonical_spot_snapshot=None,
        _debounce_state_hash=hash(("PREFLOP", 1.0, ("Tc", "2s"), (), ("CALL",))),
        _debounce_start_time=0.0,
        _live_debounce_stable_window_s=0.0,
        observation_dataset=types.SimpleNamespace(enabled=False),
    )
    controller.camera.controller = controller

    import asyncio
    asyncio.run(RuntimeLoop(controller).run())

    assert stale_calls == []
