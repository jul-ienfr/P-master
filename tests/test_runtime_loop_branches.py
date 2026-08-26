# -*- coding: utf-8 -*-
"""Tests des branches restantes du RuntimeLoop : pause, probe, HITL, time bank, erreurs."""
import asyncio
import sys
import types
from pathlib import Path

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
    def __init__(self, frames):
        self.frames = list(frames)
        self.controller = None
        self.started = False
        self.stopped = False

    def start(self, region=None, hwnd=None):
        self.started = True

    def stop(self):
        self.stopped = True

    def get_latest_frame(self):
        if not self.frames:
            if self.controller is not None:
                self.controller.is_running = False
            return None
        frame = self.frames.pop(0)
        if len(self.frames) == 0 and self.controller is not None:
            self.controller.is_running = False
        return frame


def make_controller(**overrides):
    events = []

    def build():
        controller = types.SimpleNamespace(
            db=FakeDB(),
            camera=None,
            action_controller=types.SimpleNamespace(hwnd=None),
            runtime_api_port=8005,
            is_running=False,
            _publish_runtime_bridge_state=lambda force=False: None,
            _start_runtime_api_process=lambda: None,
            _stop_runtime_api_process=lambda: None,
            _push_runtime_event=lambda kind, message, **context: events.append(
                (kind, message, context)
            ),
            _persist_runtime_metrics_snapshot=lambda force=False: None,
            _refresh_capture_region=lambda force=False: (0, 0, 100, 100),
            _set_loop_stage=lambda stage, publish=False: None,
            _process_bridge_commands=lambda: None,
            _operator_action_mode=lambda: "ready",
            tracker=types.SimpleNamespace(update_from_vision=None, current_hand_actions=[], hero_cards=[]),
            _build_tracker_snapshot=lambda data: {},
            _record_runtime_transition=lambda snapshot: None,
            _log_loop_timing=lambda **kwargs: None,
            _max_live_frame_age_s=1.0,
            _log_live_details=lambda canonical_state, state: None,
            _push_incident=lambda *a, **k: events.append(("incident", a, k)),
            _get_live_loop_sleep_interval=lambda actionable_spot: 0.0,
            last_tracker_snapshot={},
            last_canonical_spot_snapshot=None,
            pixel_probe=None,
            observation_dataset=None,
            hitl=None,
            _debounce_state_hash=None,
            _debounce_start_time=0.0,
            _live_debounce_stable_window_s=0.0,
            frame_pipeline=types.SimpleNamespace(
                _read_live_pot_fast=lambda frame, pot_box: {}
            ),
        )
        return controller

    controller = build()
    for key, value in overrides.items():
        setattr(controller, key, value)
    return controller, events


FRAME = np.zeros((40, 60, 3), dtype=np.uint8)


def test_runtime_loop_paused_operator_skips_capture(tmp_path):
    stages = []
    modes = iter(["paused", "ready"])

    def mode():
        return next(modes, "ready")

    controller, _events = make_controller(
        camera=FakeCamera([FRAME, None]),
        is_running=True,
        _operator_action_mode=mode,
        _set_loop_stage=lambda stage, publish=False: stages.append(stage),
    )
    controller.camera.controller = controller
    asyncio.run(RuntimeLoop(controller).run())
    assert "paused" in stages
    assert "capture_frame" in stages  # reprise après la pause


def test_runtime_loop_probe_failure_records_error_snapshot():
    class ExplodingProbe:
        def is_our_turn(self, frame):
            raise RuntimeError("probe down")

    async def _process_frame(_frame):
        controller.is_running = False
        return types.SimpleNamespace(action_buttons=[], hero_cards=[])

    controller, _events = make_controller(
        camera=FakeCamera([FRAME, None]),
        is_running=True,
        pixel_probe=ExplodingProbe(),
        action_controller=types.SimpleNamespace(hwnd=None),
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(
            metadata={}, spot_id="s", street="IDLE", pot=0.0, board=(), hero_cards=(),
            players=(), legal_actions=(), action_buttons=[], state_confidence=0.9,
            to_tracker_payload=lambda: {}, to_dict=lambda: {},
        ),
        tracker=types.SimpleNamespace(update_from_vision=None, current_hand_actions=[]),
        _build_resolved_runtime_state=lambda observed: observed,
        _clear_live_decision_summary=lambda canonical_state: None,
        _process_frame=_process_frame,
    )
    controller.camera.controller = controller
    asyncio.run(RuntimeLoop(controller).run())
    snapshot = dict(getattr(controller, "_last_turn_probe_snapshot", {}) or {})
    assert snapshot["source"] == "FastPixelProbe"
    assert snapshot["is_our_turn"] is False
    assert snapshot["error"] == "probe_failed"


def test_runtime_loop_triggers_hitl_when_turn_without_hero_cards():
    requested = []
    button = types.SimpleNamespace(class_name="fold_button")
    other_button = types.SimpleNamespace(class_name="call_button")

    class HitlStub:
        is_waiting_for_human = False

        async def request_intervention_async(self, *args, **kwargs):
            requested.append(kwargs.get("issue_type"))

        def record_anomaly_silently(self, *args, **kwargs):
            pass

    async def _process_frame(_frame):
        controller.is_running = False
        return types.SimpleNamespace(action_buttons=[button, other_button], hero_cards=[])

    controller, _events = make_controller(
        camera=FakeCamera([FRAME, None]),
        is_running=True,
        hitl=HitlStub(),
        pixel_probe=types.SimpleNamespace(is_our_turn=lambda frame: True),
        action_controller=types.SimpleNamespace(hwnd=None),
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(
            metadata={}, spot_id="s", street="PREFLOP", pot=1.5, board=(),
            hero_cards=(), players=(), legal_actions=("FOLD",),
            action_buttons=[button, other_button], state_confidence=0.9,
            to_tracker_payload=lambda: {}, to_dict=lambda: {},
        ),
        tracker=types.SimpleNamespace(update_from_vision=None, current_hand_actions=[]),
        _build_resolved_runtime_state=lambda observed: observed,
        _clear_live_decision_summary=lambda canonical_state: None,
        _process_frame=_process_frame,
    )
    controller.tracker.hero_cards = []  # pas de secours tracker -> HITL demandé
    controller.camera.controller = controller
    asyncio.run(RuntimeLoop(controller).run())
    assert "yolo_failure" in requested


def test_runtime_loop_silent_anomaly_when_tracker_has_cards():
    silent = []
    button = types.SimpleNamespace(class_name="fold_button")
    other_button = types.SimpleNamespace(class_name="call_button")

    class HitlStub:
        is_waiting_for_human = False

        async def request_intervention_async(self, *args, **kwargs):
            raise AssertionError("ne doit pas être appelé")

        def record_anomaly_silently(self, *args, **kwargs):
            silent.append(args)

    async def _process_frame(_frame):
        controller.is_running = False
        return types.SimpleNamespace(action_buttons=[button, other_button], hero_cards=[])

    controller, _events = make_controller(
        camera=FakeCamera([FRAME, None]),
        is_running=True,
        hitl=HitlStub(),
        pixel_probe=types.SimpleNamespace(is_our_turn=lambda frame: True),
        action_controller=types.SimpleNamespace(hwnd=None),
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(
            metadata={}, spot_id="s", street="PREFLOP", pot=1.5, board=(),
            hero_cards=(), players=(), legal_actions=("FOLD",),
            action_buttons=[button, other_button], state_confidence=0.9,
            to_tracker_payload=lambda: {}, to_dict=lambda: {},
        ),
        tracker=types.SimpleNamespace(update_from_vision=None, current_hand_actions=[]),
        _build_resolved_runtime_state=lambda observed: observed,
        _clear_live_decision_summary=lambda canonical_state: None,
        _process_frame=_process_frame,
    )
    controller.tracker.hero_cards = ["Ah", "Kd"]  # le tracker sauve les cartes
    controller.camera.controller = controller
    asyncio.run(RuntimeLoop(controller).run())
    assert silent


def test_runtime_loop_time_bank_button_clicks_and_continues():
    clicked = []
    time_bank = types.SimpleNamespace(class_name="time_bank_button", center=(100, 50))

    async def fake_click(x, y):
        clicked.append((x, y))
        return True

    async def _process_frame(_frame):
        return types.SimpleNamespace(action_buttons=[time_bank], hero_cards=[])

    controller, _events = make_controller(
        camera=FakeCamera([FRAME, FRAME, None]),
        is_running=True,
        action_controller=types.SimpleNamespace(hwnd=None, click_at=fake_click),
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(
            metadata={}, spot_id="s", street="IDLE", pot=0.0, board=(),
            hero_cards=(), players=(), legal_actions=(), action_buttons=[],
            state_confidence=0.9, to_tracker_payload=lambda: {}, to_dict=lambda: {},
        ),
        tracker=types.SimpleNamespace(update_from_vision=None, current_hand_actions=[]),
        _build_resolved_runtime_state=lambda observed: observed,
        _clear_live_decision_summary=lambda canonical_state: None,
        _process_frame=_process_frame,
    )
    controller.camera.controller = controller
    asyncio.run(RuntimeLoop(controller).run())
    # un clic par frame affichant le time bank (2 frames fournies)
    assert clicked == [(100, 50), (100, 50)]


def test_runtime_loop_survives_exception_in_process_frame():
    incidents = []
    processed = {"count": 0}

    async def broken_process_frame(_frame):
        processed["count"] += 1
        if processed["count"] == 1:
            raise RuntimeError("vision exploded")
        controller.is_running = False
        return types.SimpleNamespace(action_buttons=[], hero_cards=[])

    controller, events = make_controller(
        camera=FakeCamera([FRAME, FRAME, None]),
        is_running=True,
        _process_frame=broken_process_frame,
        action_controller=types.SimpleNamespace(hwnd=None),
        _convert_state_for_tracker=lambda state, frame: types.SimpleNamespace(
            metadata={}, spot_id="s", street="IDLE", pot=0.0, board=(),
            hero_cards=(), players=(), legal_actions=(), action_buttons=[],
            state_confidence=0.9, to_tracker_payload=lambda: {}, to_dict=lambda: {},
        ),
        tracker=types.SimpleNamespace(update_from_vision=None, current_hand_actions=[]),
        _build_resolved_runtime_state=lambda observed: observed,
        _clear_live_decision_summary=lambda canonical_state: None,
    )
    controller.camera.controller = controller
    asyncio.run(RuntimeLoop(controller).run())

    incident_events = [e for e in events if e[0] == "incident"]
    assert incident_events  # l'erreur de la première frame a bien été encaissée
