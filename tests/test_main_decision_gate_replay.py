import asyncio
import json
import sys
import time
import types
from collections import deque
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if "aiohttp_cors" not in sys.modules:
    class _StubResourceOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


    class _StubCors:
        def add(self, route):
            return route


    def _stub_setup(app, defaults=None):
        return _StubCors()


    sys.modules["aiohttp_cors"] = types.SimpleNamespace(
        setup=_stub_setup,
        ResourceOptions=_StubResourceOptions,
    )


if "src.vision.capture" not in sys.modules:
    class _StubScreenCapture:
        def __init__(self, *args, **kwargs):
            pass


    sys.modules["src.vision.capture"] = types.SimpleNamespace(ScreenCapture=_StubScreenCapture)


if "src.vision.detector" not in sys.modules:
    class _StubTableState:
        def __init__(self, **kwargs):
            self.board_cards = kwargs.get("board_cards", [])
            self.hero_cards = kwargs.get("hero_cards", [])
            self.dealer_button = kwargs.get("dealer_button")
            self.pots = kwargs.get("pots", [])
            self.stacks = kwargs.get("stacks", [])
            self.player_names = kwargs.get("player_names", [])
            self.action_buttons = kwargs.get("action_buttons", [])
            self.metadata = kwargs.get("metadata", {})


    class _StubDetectionResult:
        def __init__(self, bbox=(0, 0, 0, 0), confidence=0.0, class_name=""):
            self.bbox = bbox
            self.confidence = confidence
            self.class_name = class_name

        @property
        def center(self):
            x1, y1, x2, y2 = self.bbox
            return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


    class _StubPokerDetector:
        def __init__(self, *args, **kwargs):
            pass


    def _stub_decode_card_token(token):
        return token

    def _stub_dedupe_nearby_detections(detections, *args, **kwargs):
        return list(detections)

    def _stub_detection_sort_key(det):
        return (0, 0)


    sys.modules["src.vision.detector"] = types.SimpleNamespace(
        PokerDetector=_StubPokerDetector,
        TableState=_StubTableState,
        DetectionResult=_StubDetectionResult,
        decode_card_token=_stub_decode_card_token,
        dedupe_nearby_detections=_stub_dedupe_nearby_detections,
        detection_sort_key=_stub_detection_sort_key,
    )


if "src.vision.ocr" not in sys.modules:
    class _StubPokerOCR:
        def __init__(self, *args, **kwargs):
            pass


    sys.modules["src.vision.ocr"] = types.SimpleNamespace(PokerOCR=_StubPokerOCR)


from src.bot.runtime_types import CanonicalPlayer, CanonicalTableState
from src.bot.sanity_checker import GateResult, SanityChecker
from src.runtime.poker_state_validator import PokerStateValidator
from src.runtime.readiness import build_runtime_readiness
from src.runtime.go_live_gate import evaluate_go_live_gate
from src.main import SuperBotController


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class FixtureHistoryStore:
    def __init__(self):
        self.records = []

    def append(self, stream: str, entry: dict) -> None:
        self.records.append({"stream": stream, **entry})

    def summarize(self) -> dict:
        return {"enabled": True, "available": True}

    def read_recent(self, stream: str, limit: int = 10) -> list:
        items = [record for record in self.records if record.get("stream") == stream]
        return list(reversed(items[-limit:]))


class FixtureDecisionMaker:
    def __init__(self, decision: dict):
        self.decision = decision
        self.calls = []

    async def get_best_action(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.decision)


class FixtureActionController:
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def execute_action(self, action_intent, dynamic_coords, jit_check=None, bet_validation_callback=None):
        self.calls.append(
            {
                "action": action_intent.action,
                "bet_size": action_intent.bet_size,
                "dynamic_coords": dict(dynamic_coords),
            }
        )
        if callable(self.result):
            return self.result(action_intent, dynamic_coords)
        if self.result is not None:
            return dict(self.result)
        return {"ok": True, "action": action_intent.action}


class FixtureVillain:
    def __init__(self, name: str, has_button: bool):
        self.name = name
        self.has_button = has_button


class FixtureFailureDataset:
    def __init__(self):
        self.records = []

    def record_incident(self, payload):
        self.records.append(dict(payload))
        return None


class FixtureState:
    pass


def _build_canonical_state(payload: dict) -> CanonicalTableState:
    players = tuple(CanonicalPlayer(**player) for player in payload["players"])
    return CanonicalTableState(
        spot_id=payload["spot_id"],
        street=payload["street"],
        pot=payload["pot"],
        board=tuple(payload["board"]),
        hero_cards=tuple(payload["hero_cards"]),
        players=players,
        legal_actions=tuple(payload["legal_actions"]),
        action_buttons=tuple(payload["action_buttons"]),
        state_confidence=payload["state_confidence"],
        metadata=payload["metadata"],
    )


class _ReusableFrameState:
    def __init__(self, metadata=None, action_buttons=None):
        self.board_cards = []
        self.hero_cards = []
        self.dealer_button = None
        self.pots = []
        self.stacks = []
        self.player_names = []
        self.action_buttons = list(action_buttons or [])
        self.metadata = dict(metadata or {})

    def copy(self, deep=False):
        return _ReusableFrameState(metadata=self.metadata, action_buttons=self.action_buttons)


def test_main_decision_gate_trace_replay_fixture_matches_expected_output(monkeypatch):
    fixture = _load_fixture("main_gate_decision_trace_replay.json")
    controller = object.__new__(SuperBotController)
    controller.runtime_sanity = SanityChecker()
    controller.runtime_history_store = FixtureHistoryStore()
    controller.decision_maker = FixtureDecisionMaker(fixture["decision"])
    controller.action_controller = FixtureActionController()
    controller.tracker = types.SimpleNamespace(
        current_hand_actions=list(fixture["tracker_snapshot"]["action_history"])
    )
    controller.last_tracker_snapshot = dict(fixture["tracker_snapshot"])
    controller.last_decision_summary = {}
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller._last_runtime_street = "IDLE"
    controller._last_hero_seat_id = fixture["tracker_snapshot"]["hero_seat_id"]
    controller.fallback_coords = {}
    controller._get_dynamic_coordinates = lambda state: {
        key: tuple(value) for key, value in fixture["dynamic_coords"].items()
    }

    tick = {"value": 0}

    def fake_utc_now():
        tick["value"] += 1
        return f"2026-04-11T12:00:{tick['value']:02d}Z"

    controller._utc_now = fake_utc_now
    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)
    controller._operator_action_mode = lambda: "ready"

    canonical_state = _build_canonical_state(fixture["canonical_state"])
    state = FixtureState()
    villain = FixtureVillain(name="VillainBTN", has_button=True)

    result = asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=state,
            primary_villain=villain,
            effective_stack=88.0,
        )
    )

    expected = fixture["expected"]
    trace = controller.decision_trace_history[0]

    assert result["decision"]["action"] == expected["executed_action"]
    assert controller.last_decision_summary["gate_reason"] == expected["gate_reason"]
    assert controller.last_decision_summary["gate_allowed"] is expected["gate_allowed"]
    assert trace["chosen_action"] == expected["trace_chosen_action"]
    assert trace["source"] == expected["trace_source"]
    assert trace["incidents"] == expected["trace_incidents"]
    assert trace["gate_result"]["reason"] == expected["trace_gate_reason"]
    assert [event["message"] for event in controller.runtime_event_history] == list(reversed(expected["runtime_event_messages"]))
    assert [entry["id"] for entry in controller.incident_history] == expected["incident_ids"]
    assert controller.action_controller.calls == [
        {
            "action": expected["executed_action"],
            "bet_size": fixture["decision"]["bet_size"],
            "dynamic_coords": {key: tuple(value) for key, value in fixture["dynamic_coords"].items()},
        }
    ]
    assert [record["stream"] for record in controller.runtime_history_store.records] == ["decisions", "events", "events"]


def test_process_frame_reuses_cached_state_when_visual_regions_are_unchanged():
    controller = object.__new__(SuperBotController)
    controller._last_visual_state = _ReusableFrameState(metadata={"table_detected": True})
    controller._last_visual_state_at = 10_000.0
    controller._visual_state_refresh_interval_s = 10**9
    controller._last_visual_previews = {"table": np.zeros((8, 8), dtype=np.uint8)}
    controller._detect_relevant_visual_change = lambda frame: (False, {"table": np.zeros((8, 8), dtype=np.uint8)}, ())
    controller.detector = types.SimpleNamespace(analyze_frame=lambda frame: (_ for _ in ()).throw(AssertionError("detector should not run")))

    state = asyncio.run(controller._process_frame(np.zeros((32, 32, 3), dtype=np.uint8)))

    assert isinstance(state, _ReusableFrameState)
    assert state.metadata["reused_visual_state"] is True


def test_process_frame_reuses_cached_state_when_only_actions_region_changes():
    controller = SuperBotController.__new__(SuperBotController)
    controller._last_visual_state_at = time.monotonic()
    controller._visual_state_refresh_interval_s = 10.0
    controller._last_visual_previews = {"actions": np.zeros((10, 10), dtype=np.uint8)}
    cached_state = types.SimpleNamespace(
        metadata={"runtime_geometry": {"regions": {}}},
        action_buttons=[types.SimpleNamespace(class_name="action_button_generic", bbox=(0, 0, 10, 10), confidence=1.0, center=(5, 5))],
        pots=[],
    )
    controller._last_visual_state = cached_state
    controller._copy_table_state = lambda state: types.SimpleNamespace(
        metadata=dict(getattr(state, "metadata", {}) or {}),
        action_buttons=list(getattr(state, "action_buttons", []) or []),
        pots=list(getattr(state, "pots", []) or []),
    )
    controller._detect_relevant_visual_change = lambda frame: (True, {"actions": np.ones((10, 10), dtype=np.uint8)}, ("actions",))
    controller._label_generic_action_buttons = lambda state, frame: state
    controller._try_update_cached_fast_pot = lambda frame, state: state
    controller._set_loop_stage = lambda *args, **kwargs: None
    controller.detector = types.SimpleNamespace(analyze_frame=lambda frame: None)

    from src.runtime.frame_pipeline import FramePipeline

    state = asyncio.run(FramePipeline(controller)._process_frame(np.zeros((20, 20, 3), dtype=np.uint8)))

    assert state.metadata["reused_visual_state"] is True
    assert state.metadata["fast_action_refresh"] is True
    assert state.metadata["visual_changed_regions"] == ["actions"]
    assert state.metadata["visual_changed"] is True


def test_wait_for_action_settle_finishes_as_soon_as_buttons_disappear(monkeypatch):
    controller = object.__new__(SuperBotController)
    controller._post_action_settle_timeout_s = 0.3
    controller._post_action_settle_poll_interval_s = 0.01
    controller._refresh_capture_region = lambda *args, **kwargs: None
    controller.camera = types.SimpleNamespace(get_latest_frame=lambda: np.zeros((24, 24, 3), dtype=np.uint8))
    controller._label_generic_action_buttons = lambda state, frame: state
    calls = {"value": 0}

    def analyze_frame(_frame):
        calls["value"] += 1
        if calls["value"] == 1:
            return _ReusableFrameState(action_buttons=[types.SimpleNamespace(class_name="call_button")])
        return _ReusableFrameState(action_buttons=[])

    controller.detector = types.SimpleNamespace(analyze_frame=analyze_frame)

    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)

    result = asyncio.run(controller._wait_for_action_settle())

    assert result["settled"] is True
    assert result["buttons"] == []
    assert calls["value"] >= 2


def test_resolve_live_decision_context_falls_back_for_actionable_preflop():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(
        get_primary_villain=lambda: None,
        get_effective_stack=lambda: 0.0,
        players={},
    )

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:preflop",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("Jh", "9s"),
        players=(
            CanonicalPlayer(
                seat_id="seat_hero",
                seat_index=0,
                stack=42.0,
                name="Hero",
                is_active=True,
                has_folded=False,
                is_hero=True,
                has_button=False,
                confidence=1.0,
                metadata={},
            ),
        ),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.83,
        metadata={},
    )

    primary_villain, effective_stack = controller._resolve_live_decision_context(canonical_state)

    assert primary_villain is not None
    assert primary_villain.name == "live_villain"
    assert effective_stack == 42.0


def test_duplicate_live_action_guard_suppresses_same_spot_temporarily():
    controller = object.__new__(SuperBotController)
    controller._live_action_repeat_cooldown_s = 3.5
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:preflop",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("Jh", "9s"),
        players=(),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.83,
        metadata={},
    )

    controller._remember_live_execution(canonical_state, "BET", "click_failed")
    assert controller._should_suppress_duplicate_live_action(canonical_state, "BET") is True

    controller._last_live_execution_at -= 4.0
    assert controller._should_suppress_duplicate_live_action(canonical_state, "BET") is False


def test_recent_live_execution_guard_blocks_second_action_in_same_context():
    controller = object.__new__(SuperBotController)
    controller._post_action_context_guard_s = 2.25
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:preflop",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("7d", "4h"),
        players=(),
        legal_actions=("FOLD",),
        action_buttons=("fold_button",),
        state_confidence=0.83,
        metadata={},
    )
    identical_material_state = CanonicalTableState(
        spot_id=canonical_state.spot_id,
        street=canonical_state.street,
        pot=canonical_state.pot,
        board=canonical_state.board,
        hero_cards=canonical_state.hero_cards,
        players=canonical_state.players,
        legal_actions=canonical_state.legal_actions,
        action_buttons=canonical_state.action_buttons,
        state_confidence=canonical_state.state_confidence,
        metadata=canonical_state.metadata,
    )

    controller._remember_live_execution(canonical_state, "FOLD", "executed")

    assert controller._should_suppress_recent_live_execution(identical_material_state) is True

    controller._last_live_execution_at -= 3.0
    assert controller._should_suppress_recent_live_execution(identical_material_state) is False


def test_recent_live_execution_guard_does_not_block_new_material_preflop_spot():
    controller = object.__new__(SuperBotController)
    controller._post_action_context_guard_s = 2.25
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:preflop-a",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("7d", "4h"),
        players=(),
        legal_actions=("FOLD",),
        action_buttons=("fold_button",),
        state_confidence=0.83,
        metadata={},
    )
    next_preflop_spot = CanonicalTableState(
        spot_id="live:PREFLOP:preflop-b",
        street="PREFLOP",
        pot=8.0,
        board=(),
        hero_cards=canonical_state.hero_cards,
        players=canonical_state.players,
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=canonical_state.state_confidence,
        metadata={},
    )

    controller._remember_live_execution(canonical_state, "FOLD", "executed")

    assert controller._should_suppress_recent_live_execution(next_preflop_spot) is False


def test_unsettled_timeout_locks_same_material_spot_until_it_changes():
    controller = object.__new__(SuperBotController)
    controller._post_action_context_guard_s = 2.25
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:timeout-lock",
        street="PREFLOP",
        pot=8.0,
        board=(),
        hero_cards=("5s", "2s"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.83,
        metadata={},
    )
    changed_state = CanonicalTableState(
        spot_id="live:PREFLOP:timeout-lock-next",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=canonical_state.hero_cards,
        players=canonical_state.players,
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=canonical_state.state_confidence,
        metadata={},
    )

    controller._remember_live_execution(canonical_state, "FOLD", "executed", settle_status="timeout")

    assert controller._should_suppress_recent_live_execution(canonical_state) is True
    assert controller._should_suppress_recent_live_execution(changed_state) is False


def test_recent_live_execution_guard_ignores_button_order_noise_on_same_spot():
    controller = object.__new__(SuperBotController)
    controller._post_action_context_guard_s = 2.25
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:stable-order",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("Th", "5s"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.83,
        metadata={"spot_signature": ["PREFLOP", ["Th", "5s"], [], 3.0, ["FOLD", "CALL", "BET"], ["fold_button", "call_button", "bet_button"]]},
    )
    reordered_buttons_state = CanonicalTableState(
        spot_id=canonical_state.spot_id,
        street=canonical_state.street,
        pot=canonical_state.pot,
        board=canonical_state.board,
        hero_cards=canonical_state.hero_cards,
        players=canonical_state.players,
        legal_actions=canonical_state.legal_actions,
        action_buttons=("call_button", "bet_button", "fold_button"),
        state_confidence=canonical_state.state_confidence,
        metadata={"spot_signature": ["PREFLOP", ["Th", "5s"], [], 3.0, ["FOLD", "CALL", "BET"], ["call_button", "bet_button", "fold_button"]]},
    )

    controller._remember_live_execution(canonical_state, "FOLD", "executed", settle_status="timeout")

    assert controller._should_suppress_recent_live_execution(reordered_buttons_state) is True


def test_run_decision_gate_flow_skips_decision_maker_for_locked_same_spot():
    controller = object.__new__(SuperBotController)
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""
    controller._last_locked_decision_signature = ()
    controller._last_locked_decision_action = ""
    controller._last_locked_decision_reason = ""
    controller._last_locked_decision_at = 0.0
    controller._last_locked_decision_log_signature = ()
    controller._last_locked_decision_log_at = 0.0
    controller._last_decision_signature = ()
    controller._last_decision_payload = None
    controller._last_decision_cached_at = 0.0
    controller._decision_cache_ttl_s = 0.35
    controller._locked_spot_log_interval_s = 1.0
    controller.last_decision_summary = {
        "confidence": 0.78,
        "fallback_used": False,
        "fallback_reason": None,
        "profile": {},
        "solver": {},
        "confidence_details": {},
        "history": {"fallback": [], "warnings": [], "incidents": []},
    }
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller._get_dynamic_coordinates = lambda state: {"FOLD": (100, 100)}
    controller._derive_live_hero_position = lambda villain: "BB"
    controller._utc_now = lambda: "2026-04-14T12:00:00Z"
    controller._push_runtime_event = lambda *args, **kwargs: None
    controller._record_decision_trace = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("trace should not be recorded for locked skip"))
    controller._format_log_cards = lambda cards: " ".join(cards) if cards else "-"
    controller._format_log_list = lambda values: ", ".join(values) if values else "-"
    controller._operator_action_mode = lambda: "assisted"
    controller._evaluate_assisted_execution = lambda canonical_state, decision, gate_result: {
        "enabled": True,
        "learning_live": True,
        "auto_execute": True,
        "requires_operator_action": False,
        "status": "auto_execute",
        "reason": "ready",
        "signals": {},
        "thresholds": {},
    }
    controller._build_gate_tracker_snapshot = lambda canonical_state: {
        "street": canonical_state.street,
        "pot": canonical_state.pot,
        "hero_cards": list(canonical_state.hero_cards),
        "legal_actions": list(canonical_state.legal_actions),
    }
    controller.runtime_sanity = SanityChecker()
    controller.runtime_sanity.evaluate_action_gate = lambda **kwargs: GateResult(allowed=True, status="ready", reasons=[])
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller.decision_maker = FixtureDecisionMaker(
        {
            "action": "FOLD",
            "source": "GTO_PREFLOP_FAST",
            "confidence": 0.78,
            "fallback_used": False,
            "warnings": [],
            "incidents": [],
            "elapsed_ms": 12.0,
            "backend": "fast_path",
            "metadata": {"profile": {}, "solver": {}, "confidence": {}},
        }
    )

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:locked-same-spot",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("9s", "7d"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.83,
        metadata={"spot_signature": ["PREFLOP", ["9s", "7d"], [], 3.0, ["FOLD", "CALL", "BET"], ["fold_button", "call_button", "bet_button"]]},
    )
    controller._remember_locked_decision(canonical_state, "FOLD", "same_spot_unconfirmed")

    result = asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain("seat_0", False),
            effective_stack=100.0,
            gate_tracker_snapshot=None,
            frame_age_ms=500.0,
        )
    )

    assert controller.decision_maker.calls == []
    assert result["decision"]["source"] == "LOCKED_SPOT_SKIP"
    assert result["decision"]["action"] == "FOLD"
    assert controller.last_decision_summary["execution"]["status"] == "decision_locked"
    assert controller.last_decision_summary["execution"]["reason"] == "same_spot_unconfirmed"


def test_run_decision_gate_flow_reuses_cached_decision_for_same_spot():
    controller = object.__new__(SuperBotController)
    controller.last_tracker_snapshot = {}
    controller._last_live_execution_signature = ()
    controller._last_live_execution_context_signature = ()
    controller._last_live_execution_action = ""
    controller._last_live_execution_at = 0.0
    controller._last_live_execution_status = ""
    controller._last_live_execution_settle_status = ""
    controller._last_locked_decision_signature = ()
    controller._last_locked_decision_action = ""
    controller._last_locked_decision_reason = ""
    controller._last_locked_decision_at = 0.0
    controller._last_locked_decision_log_signature = ()
    controller._last_locked_decision_log_at = 0.0
    controller._last_decision_signature = ()
    controller._last_decision_payload = None
    controller._last_decision_cached_at = 0.0
    controller._decision_cache_ttl_s = 10.0
    controller._locked_spot_log_interval_s = 1.0
    controller.last_decision_summary = {
        "history": {"fallback": [], "warnings": [], "incidents": []},
    }
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller._get_dynamic_coordinates = lambda state: {"FOLD": (100, 100)}
    controller._derive_live_hero_position = lambda villain: "BB"
    controller._utc_now = lambda: "2026-04-14T12:00:00Z"
    controller._push_runtime_event = lambda *args, **kwargs: None
    controller._record_decision_trace = lambda *args, **kwargs: None
    controller._format_log_cards = lambda cards: " ".join(cards) if cards else "-"
    controller._format_log_list = lambda values: ", ".join(values) if values else "-"
    controller._operator_action_mode = lambda: "manual_override"
    controller._evaluate_assisted_execution = lambda canonical_state, decision, gate_result: {
        "enabled": True,
        "learning_live": True,
        "auto_execute": False,
        "requires_operator_action": True,
        "status": "manual_required",
        "reason": "manual_review_required",
        "signals": {},
        "thresholds": {},
    }
    controller._build_gate_tracker_snapshot = lambda canonical_state: {
        "street": canonical_state.street,
        "pot": canonical_state.pot,
        "hero_cards": list(canonical_state.hero_cards),
        "legal_actions": list(canonical_state.legal_actions),
    }
    controller.runtime_sanity = SanityChecker()
    controller.runtime_sanity.evaluate_action_gate = lambda **kwargs: GateResult(allowed=True, status="ready", reasons=[])
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller.decision_maker = FixtureDecisionMaker(
        {
            "action": "FOLD",
            "source": "GTO_PREFLOP_FAST",
            "confidence": 0.78,
            "fallback_used": False,
            "warnings": [],
            "incidents": [],
            "elapsed_ms": 12.0,
            "backend": "fast_path",
            "metadata": {"profile": {}, "solver": {}, "confidence": {}},
        }
    )

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:cached-spot",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("9s", "7d"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.83,
        metadata={"spot_signature": ["PREFLOP", ["9s", "7d"], [], 3.0, ["FOLD", "CALL", "BET"], ["fold_button", "call_button", "bet_button"]]},
    )

    asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain("seat_0", False),
            effective_stack=100.0,
            gate_tracker_snapshot=None,
            frame_age_ms=500.0,
        )
    )
    asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain("seat_0", False),
            effective_stack=100.0,
            gate_tracker_snapshot=None,
            frame_age_ms=500.0,
        )
    )

    assert len(controller.decision_maker.calls) == 1


def test_jit_action_validator_can_ignore_action_region_changes():
    controller = object.__new__(SuperBotController)
    controller.camera = types.SimpleNamespace(get_latest_frame=lambda: np.zeros((24, 24, 3), dtype=np.uint8))
    
    # Simuler un changement important
    base_preview = np.zeros((18, 24), dtype=np.uint8)
    mutated_preview = np.ones((18, 24), dtype=np.uint8) * 100
    
    controller._last_visual_previews = {"actions": base_preview}
    controller._capture_live_visual_previews = lambda frame: {"actions": mutated_preview}

    assert asyncio.run(controller._jit_action_validator()) is False
    assert asyncio.run(controller._jit_action_validator(ignore_action_region=True)) is True


def test_main_decision_gate_trace_gate_blocked_replay_fixture_matches_expected_output(monkeypatch):
    fixture = _load_fixture("main_gate_decision_trace_gate_blocked_replay.json")
    controller = object.__new__(SuperBotController)
    controller.runtime_sanity = SanityChecker()
    controller.runtime_history_store = FixtureHistoryStore()
    controller.decision_maker = FixtureDecisionMaker(fixture["decision"])
    controller.action_controller = FixtureActionController()
    controller.tracker = types.SimpleNamespace(
        current_hand_actions=list(fixture["tracker_snapshot"]["action_history"])
    )
    controller.last_tracker_snapshot = dict(fixture["tracker_snapshot"])
    controller.last_decision_summary = {}
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller._last_runtime_street = "IDLE"
    controller._last_hero_seat_id = fixture["tracker_snapshot"]["hero_seat_id"]
    controller.fallback_coords = {}
    controller._get_dynamic_coordinates = lambda state: {
        key: tuple(value) for key, value in fixture["dynamic_coords"].items()
    }

    tick = {"value": 0}

    def fake_utc_now():
        tick["value"] += 1
        return f"2026-04-11T12:10:{tick['value']:02d}Z"

    controller._utc_now = fake_utc_now

    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)

    canonical_state = _build_canonical_state(fixture["canonical_state"])

    result = asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain(name="VillainBTN", has_button=True),
            effective_stack=88.0,
        )
    )

    expected = fixture["expected"]
    trace = controller.decision_trace_history[0]

    assert result["decision"]["action"] == expected["executed_action"]
    assert result["gate_result"].allowed is expected["gate_allowed"]
    assert controller.last_decision_summary["gate_reason"] == expected["gate_reason"]
    assert controller.last_decision_summary["gate_allowed"] is expected["gate_allowed"]
    assert controller.last_decision_summary["history"]["incidents"] == expected["trace_incidents"]
    assert trace["chosen_action"] == expected["trace_chosen_action"]
    assert trace["source"] == expected["trace_source"]
    assert trace["incidents"] == expected["trace_incidents"]
    assert trace["gate_result"]["reason"] == expected["trace_gate_reason"]
    assert trace["gate_result"]["allowed"] is expected["gate_allowed"]
    assert [event["message"] for event in controller.runtime_event_history] == list(reversed(expected["runtime_event_messages"]))
    assert [entry["id"] for entry in controller.incident_history] == expected["incident_ids"]
    assert controller.action_controller.calls == []
    assert [record["stream"] for record in controller.runtime_history_store.records] == ["decisions", "events", "incidents", "events"]


def test_main_decision_summary_keeps_compact_enriched_metadata(monkeypatch):
    controller = object.__new__(SuperBotController)
    controller.runtime_sanity = SanityChecker()
    controller.runtime_history_store = FixtureHistoryStore()
    controller.decision_maker = FixtureDecisionMaker(
        {
            "action": "BET",
            "bet_size": 12.0,
            "source": "RL_VALIDATED",
            "confidence": 0.88,
            "fallback_used": False,
            "warnings": [],
            "incidents": [],
            "backend": "solver_stub",
            "elapsed_ms": 11,
            "profile": {"observed_hands": 55},
            "metadata": {
                "profile": {"style": "Balanced", "observed_hands": 55},
                "solver": {
                    "has_alternatives": True,
                    "action_count": 2,
                    "alternatives": [
                        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62},
                        {"action": "BET", "raw_action": "BET_75", "freq": 0.38},
                    ],
                },
                "confidence": {"value": 0.88, "source": "solver"},
                "rl_ab": {"eligible": True, "applied": True},
            },
            "ab_decision": {"eligible": True, "applied": True},
        }
    )
    controller.action_controller = FixtureActionController()
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller.last_tracker_snapshot = {
        "street": "PREFLOP",
        "board": [],
        "pot": 3.0,
        "hero_cards": ["Ah", "Kd"],
        "action_history": [],
        "in_hand": True,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "hero_seat_id": "seat_2",
        "state_confidence": 0.95,
    }
    controller.last_decision_summary = {}
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller._last_runtime_street = "IDLE"
    controller._last_hero_seat_id = "seat_2"
    controller.fallback_coords = {}
    controller._get_dynamic_coordinates = lambda state: {
        "FOLD": (100, 200),
        "CALL": (220, 200),
        "BET_BOX": (340, 200),
        "BET_BTN": (460, 200),
    }
    controller._utc_now = lambda: "2026-04-11T12:02:00Z"

    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:preflop",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("Ah", "Kd"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.95,
        metadata={"hero_seat_id": "seat_2"},
    )

    asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain(name="Villain", has_button=False),
            effective_stack=100.0,
        )
    )

    assert controller.last_decision_summary["profile"] == {"style": "Balanced", "observed_hands": 55}
    assert controller.last_decision_summary["solver"] == {
        "has_alternatives": True,
        "action_count": 2,
        "alternatives": [
            {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62},
            {"action": "BET", "raw_action": "BET_75", "freq": 0.38},
        ],
    }
    assert controller.last_decision_summary["confidence_details"] == {"value": 0.88, "source": "solver"}
    assert controller.last_decision_summary["ab_decision"] == {"eligible": True, "applied": True}


def test_main_decision_trace_persists_runtime_ab_metadata(monkeypatch):
    controller = object.__new__(SuperBotController)
    controller.runtime_sanity = SanityChecker()
    controller.runtime_history_store = FixtureHistoryStore()
    controller.decision_maker = FixtureDecisionMaker(
        {
            "action": "BET",
            "bet_size": 12.0,
            "source": "RL_VALIDATED",
            "confidence": 0.88,
            "fallback_used": False,
            "warnings": [],
            "incidents": [],
            "backend": "solver_stub",
            "elapsed_ms": 11,
            "ev": 0.27,
            "profile": {"observed_hands": 55},
            "metadata": {
                "profile": {"style": "Balanced", "observed_hands": 55},
                "solver": {
                    "has_alternatives": True,
                    "action_count": 2,
                    "elapsed_ms": 11,
                    "exploitability": 0.042,
                    "gto_action": "FOLD",
                    "final_action": "BET",
                    "solver_id": "solver_stub_main",
                    "preset_id": "turn_probe_oop",
                    "ev_by_action": {"FOLD": -0.15, "BET": 0.27},
                    "freq_by_action": {"FOLD": 0.62, "BET": 0.38},
                    "action_metadata": {
                        "FOLD": {"raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
                        "BET": {"raw_action": "BET_75", "freq": 0.38, "ev": 0.27},
                    },
                    "warnings": ["subtree_reused"],
                    "warning_details": [
                        {"code": "subtree_reused", "detail": "cache line reused"},
                    ],
                    "backend_details": {"name": "solver_stub", "node_count": 123},
                    "cache_details": {"hit": False, "tier": "memory"},
                    "action_buckets": ["FOLD", "BET_75"],
                    "alternatives": [
                        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
                        {"action": "BET", "raw_action": "BET_75", "freq": 0.38, "ev": 0.27},
                    ],
                },
                "confidence": {"value": 0.88, "source": "solver"},
                "rl_ab": {
                    "compared": True,
                    "eligible": True,
                    "applied": True,
                    "rl_differs_from_gto": True,
                    "would_override": True,
                    "comparison": {
                        "action_changed": True,
                        "freq_delta": -0.24,
                        "ev_delta": 0.13,
                    },
                },
            },
            "ab_decision": {
                "compared": True,
                "eligible": True,
                "applied": True,
                "rl_differs_from_gto": True,
                "would_override": True,
                "comparison": {
                    "action_changed": True,
                    "freq_delta": -0.24,
                    "ev_delta": 0.13,
                },
            },
        }
    )
    controller.action_controller = FixtureActionController()
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller.last_tracker_snapshot = {
        "street": "TURN",
        "board": ["As", "Kd", "7h", "2c"],
        "pot": 14.0,
        "hero_cards": ["Ah", "Kd"],
        "action_history": [],
        "in_hand": True,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "hero_seat_id": "seat_2",
        "state_confidence": 0.95,
    }
    controller.last_decision_summary = {}
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller._last_runtime_street = "IDLE"
    controller._last_hero_seat_id = "seat_2"
    controller.fallback_coords = {}
    controller.metric_snapshot_history = deque(maxlen=24)
    controller._get_dynamic_coordinates = lambda state: {
        "FOLD": (100, 200),
        "CALL": (220, 200),
        "BET_BOX": (340, 200),
        "BET_BTN": (460, 200),
    }
    controller._utc_now = lambda: "2026-04-11T12:03:00Z"

    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)

    canonical_state = CanonicalTableState(
        spot_id="live:TURN:001",
        street="TURN",
        pot=14.0,
        board=("As", "Kd", "7h", "2c"),
        hero_cards=("Ah", "Kd"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.95,
        metadata={"hero_seat_id": "seat_2"},
    )

    asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain(name="Villain", has_button=False),
            effective_stack=100.0,
        )
    )

    trace = controller.decision_trace_history[0]

    assert trace["ev"] == 0.27
    assert trace["ab_decision"]["comparison"]["ev_delta"] == 0.13
    assert trace["gto_action"] == "FOLD"
    assert trace["final_action"] == "BET"
    assert trace["ev_by_action"] == {"FOLD": -0.15, "BET": 0.27}
    assert trace["freq_by_action"] == {"FOLD": 0.62, "BET": 0.38}
    assert trace["action_metadata"] == {
        "FOLD": {"raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
        "BET": {"raw_action": "BET_75", "freq": 0.38, "ev": 0.27},
    }
    assert trace["solver_warnings"] == ["subtree_reused"]
    assert trace["solver_warning_details"] == [{"code": "subtree_reused", "detail": "cache line reused"}]
    assert trace["backend_details"] == {"name": "solver_stub", "node_count": 123}
    assert trace["cache_details"] == {"hit": False, "tier": "memory"}
    assert trace["node_count"] == 123
    assert trace["exploitability"] == 0.042
    assert trace["solver_elapsed_ms"] == 11.0
    assert trace["solver_id"] == "solver_stub_main"
    assert trace["preset_id"] == "turn_probe_oop"
    assert trace["action_buckets"] == ["FOLD", "BET_75"]
    assert trace["metadata"]["solver"]["alternatives"] == [
        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
        {"action": "BET", "raw_action": "BET_75", "freq": 0.38, "ev": 0.27},
    ]
    assert "alternatives_complete" not in trace["metadata"]["solver"]
    assert controller.runtime_history_store.records[0]["metadata"]["solver"]["alternatives"][1]["action"] == "BET"
    assert controller.runtime_history_store.records[0]["ev_by_action"] == {"FOLD": -0.15, "BET": 0.27}
    assert controller.runtime_history_store.records[0]["solver_warnings"] == ["subtree_reused"]
    assert controller.runtime_history_store.records[0]["solver_warning_details"] == [{"code": "subtree_reused", "detail": "cache line reused"}]
    assert controller.runtime_history_store.records[0]["ab_decision"]["comparison"]["action_changed"] is True


def test_main_runtime_status_includes_compact_rl_ab_summary():
    controller = object.__new__(SuperBotController)
    controller.runtime_history_store = FixtureHistoryStore()
    controller.is_running = False
    controller.last_tracker_snapshot = {
        "street": "TURN",
        "board": ["As", "Kd", "7h", "2c"],
        "pot": 14.0,
        "hero_cards": ["Ah", "Kd"],
        "action_history": [],
        "in_hand": True,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "hero_seat_id": "seat_2",
        "state_confidence": 0.95,
    }
    controller.last_canonical_spot_snapshot = {"spot_id": "live:TURN:001", "street": "TURN"}
    controller.last_gate_result = GateResult(allowed=True, status="ready", reasons=[])
    controller.last_decision_summary = {"action": "BET", "source": "RL_VALIDATED"}
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(
        [
            {
                "timestamp": "2026-04-11T12:05:00Z",
                "street": "TURN",
                "source": "validated_rl",
                "chosen_action": "BET",
                "ab_decision": {
                    "compared": True,
                    "eligible": True,
                    "applied": True,
                    "gto_action": "CALL",
                    "rl_action": "BET",
                    "final_action": "BET",
                    "rl_differs_from_gto": True,
                    "would_override": True,
                    "comparison": {
                        "action_changed": True,
                        "rl_off": {"action": "CALL", "ev": 0.1},
                        "rl_on": {"action": "BET", "ev": 0.2},
                        "freq_delta": -0.2,
                        "ev_delta": 0.1,
                    },
                },
            },
            {
                "timestamp": "2026-04-11T12:04:00Z",
                "street": "FLOP",
                "source": "validated_rl",
                "chosen_action": "CHECK",
                "ab_decision": {
                    "compared": True,
                    "eligible": False,
                    "applied": False,
                    "gto_action": "CHECK",
                    "rl_action": "CHECK",
                    "final_action": "CHECK",
                    "rl_differs_from_gto": False,
                    "would_override": False,
                    "comparison": {
                        "action_changed": False,
                        "rl_off": {"action": "CHECK", "ev": -0.05},
                        "rl_on": {"action": "CHECK", "ev": -0.05},
                        "freq_delta": 0.0,
                        "ev_delta": -0.05,
                    },
                },
            },
        ],
        maxlen=16,
    )
    controller.incident_history = deque(maxlen=16)
    controller.metric_snapshot_history = deque(maxlen=24)
    controller._build_local_metrics = lambda history: {
        "decision_count": len(history["decisions"]),
        "blocked_count": 0,
        "fallback_count": 0,
        "block_rate": 0.0,
        "fallback_rate": 0.0,
        "rolling_latency_ms": 0.0,
        "decision_rate": float(len(history["decisions"])),
        "window_size": len(history["decisions"]),
    }
    controller._build_persisted_metrics_snapshot = lambda local_metrics, history, persistence: {
        "timestamp": "2026-04-11T12:05:00Z",
        **local_metrics,
    }

    controller.runtime_history_store.records = [
        {
            "stream": "decisions",
            "timestamp": "2026-04-11T12:03:00Z",
            "street": "RIVER",
            "source": "validated_rl",
            "chosen_action": "BET",
            "ab_decision": {
                "compared": True,
                "eligible": True,
                "applied": False,
                "gto_action": "CALL",
                "rl_action": "BET",
                "final_action": "BET",
                "rl_differs_from_gto": True,
                "would_override": True,
                "comparison": {
                    "action_changed": True,
                    "rl_off": {"action": "CALL", "ev": 0.0},
                    "rl_on": {"action": "BET", "ev": 0.2},
                    "freq_delta": 0.3,
                    "ev_delta": 0.2,
                },
            },
        }
    ]

    status = controller._get_runtime_status()
    rl_ab = status["history_summary"]["rl_ab"]
    policy_compare = status["history_summary"]["policy_compare"]

    assert rl_ab["runtime"] == {
        "sample_count": 2,
        "compared_count": 2,
        "eligible_count": 1,
        "applied_count": 1,
        "diff_count": 1,
        "action_change_count": 1,
        "avg_delta_ev": 0.025,
        "avg_delta_freq": -0.1,
        "impacted_streets": ["TURN"],
        "street_counts": {"TURN": 1},
    }
    assert rl_ab["persisted"] == {
        "sample_count": 1,
        "compared_count": 1,
        "eligible_count": 1,
        "applied_count": 0,
        "diff_count": 1,
        "action_change_count": 1,
        "avg_delta_ev": 0.2,
        "avg_delta_freq": 0.3,
        "impacted_streets": ["RIVER"],
        "street_counts": {"RIVER": 1},
    }
    assert rl_ab["combined"] == {
        "sample_count": 3,
        "compared_count": 3,
        "eligible_count": 2,
        "applied_count": 1,
        "diff_count": 2,
        "action_change_count": 2,
        "avg_delta_ev": 0.0833,
        "avg_delta_freq": 0.0333,
        "impacted_streets": ["RIVER", "TURN"],
        "street_counts": {"RIVER": 1, "TURN": 1},
    }
    assert policy_compare["runtime"]["sample_count"] == 2
    assert policy_compare["runtime"]["comparable_count"] == 2
    assert policy_compare["runtime"]["agreement_count"] == 1
    assert policy_compare["runtime"]["disagreement_count"] == 1
    assert policy_compare["runtime"]["changed_action_count"] == 1
    assert policy_compare["runtime"]["ev_coverage_count"] == 12
    assert policy_compare["runtime"]["ev_coverage_rate"] == 1.0
    assert policy_compare["runtime"]["policies"] == ["gto_solver", "rl_off", "rl_on", "validated_rl"]
    assert policy_compare["runtime"]["policy_counts"] == {"gto_solver": 2, "rl_off": 2, "rl_on": 2, "validated_rl": 2}
    assert policy_compare["runtime"]["street_counts"] == {"FLOP": 1, "TURN": 1}
    assert policy_compare["runtime"]["source_counts"] == {"validated_rl": 2}
    assert any(
        comparison["baseline_policy"] == "rl_off"
        and comparison["challenger_policy"] == "rl_on"
        and comparison["challenger_ev_delta"] == 0.1
        for comparison in policy_compare["runtime"]["comparisons"]
    )
    runtime_rl_pair = next(
        comparison
        for comparison in policy_compare["runtime"]["comparisons"]
        if comparison["baseline_policy"] == "rl_off"
        and comparison["challenger_policy"] == "rl_on"
    )
    assert sorted(runtime_rl_pair["sample_ids"]) == ["2026-04-11T12:04:00Z", "2026-04-11T12:05:00Z"]
    assert runtime_rl_pair["top_spots"][0]["action_pair"] == "CALL->BET"
    assert runtime_rl_pair["divergence_examples"][0]["street"] == "TURN"
    assert any(
        comparison["baseline_policy"] == "rl_off"
        and comparison["challenger_policy"] == "rl_on"
        and comparison["challenger_ev_delta"] == 0.2
        for comparison in policy_compare["persisted"]["comparisons"]
    )
    assert policy_compare["combined"]["sample_count"] == 3
    assert policy_compare["combined"]["street_counts"] == {"FLOP": 1, "RIVER": 1, "TURN": 1}
    assert sorted(policy_compare["runtime"]["highlights"]["most_compared_pair"]["sample_ids"]) == [
        "2026-04-11T12:04:00Z",
        "2026-04-11T12:05:00Z",
    ]
    assert policy_compare["runtime"]["highlights"]["most_divergent_pair"]["divergence_examples"][0]["sample_id"] == "2026-04-11T12:05:00Z"
    assert policy_compare["combined"]["highlights"]["top_spots"][0]["sample_count"] == 1


def test_main_runtime_status_dedupes_combined_rl_ab_summary_for_same_spot_and_timestamp():
    controller = object.__new__(SuperBotController)
    controller.runtime_history_store = FixtureHistoryStore()
    controller.is_running = False
    controller.last_tracker_snapshot = {
        "street": "TURN",
        "board": ["As", "Kd", "7h", "2c"],
        "pot": 14.0,
        "hero_cards": ["Ah", "Kd"],
        "action_history": [],
        "in_hand": True,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "hero_seat_id": "seat_2",
        "state_confidence": 0.95,
    }
    controller.last_canonical_spot_snapshot = {"spot_id": "live:TURN:001", "street": "TURN"}
    controller.last_gate_result = GateResult(allowed=True, status="ready", reasons=[])
    controller.last_decision_summary = {"action": "BET", "source": "RL_VALIDATED"}
    duplicate_decision = {
        "timestamp": "2026-04-11T12:05:00Z",
        "spot_id": "live:TURN:001",
        "street": "TURN",
        "chosen_action": "BET",
        "source": "RL_VALIDATED",
        "ab_decision": {
            "compared": True,
            "eligible": True,
            "applied": True,
            "gto_action": "CALL",
            "rl_action": "BET",
            "final_action": "BET",
            "rl_differs_from_gto": True,
            "would_override": True,
            "comparison": {
                "action_changed": True,
                "rl_off": {"action": "CALL", "ev": 0.0},
                "rl_on": {"action": "BET", "ev": 0.1},
                "freq_delta": -0.2,
                "ev_delta": 0.1,
            },
        },
    }
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque([duplicate_decision], maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller.metric_snapshot_history = deque(maxlen=24)
    controller._build_local_metrics = lambda history: {
        "decision_count": len(history["decisions"]),
        "blocked_count": 0,
        "fallback_count": 0,
        "block_rate": 0.0,
        "fallback_rate": 0.0,
        "rolling_latency_ms": 0.0,
        "decision_rate": float(len(history["decisions"])),
        "window_size": len(history["decisions"]),
    }
    controller._build_persisted_metrics_snapshot = lambda local_metrics, history, persistence: {
        "timestamp": "2026-04-11T12:05:00Z",
        **local_metrics,
    }

    controller.runtime_history_store.records = [
        {
            "stream": "decisions",
            **duplicate_decision,
        }
    ]

    status = controller._get_runtime_status()
    rl_ab = status["history_summary"]["rl_ab"]
    policy_compare = status["history_summary"]["policy_compare"]

    assert rl_ab["runtime"] == {
        "sample_count": 1,
        "compared_count": 1,
        "eligible_count": 1,
        "applied_count": 1,
        "diff_count": 1,
        "action_change_count": 1,
        "avg_delta_ev": 0.1,
        "avg_delta_freq": -0.2,
        "impacted_streets": ["TURN"],
        "street_counts": {"TURN": 1},
    }
    assert rl_ab["persisted"] == rl_ab["runtime"]
    assert rl_ab["combined"] == rl_ab["runtime"]
    assert policy_compare["persisted"] == policy_compare["runtime"]
    assert policy_compare["combined"] == policy_compare["runtime"]


def test_main_decision_gate_trace_normalizes_structured_incidents(monkeypatch):
    controller = object.__new__(SuperBotController)
    controller.runtime_sanity = SanityChecker()
    controller.runtime_history_store = FixtureHistoryStore()
    controller.decision_maker = FixtureDecisionMaker(
        {
            "action": "BET",
            "bet_size": 12.0,
            "source": "FALLBACK",
            "confidence": 0.2,
            "fallback_used": True,
            "fallback_reason": "solver_timeout",
            "warnings": ["fallback_used"],
            "incidents": [
                {"id": "solver_fallback", "severity": "warning"},
                {"id": "solver_fallback", "severity": "warning"},
            ],
            "backend": "fallback",
            "elapsed_ms": 0,
            "profile": {"observed_hands": 0},
        }
    )
    controller.action_controller = FixtureActionController()
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller.last_tracker_snapshot = {
        "street": "PREFLOP",
        "board": [],
        "pot": 3.0,
        "hero_cards": ["Ah", "Kd"],
        "action_history": [],
        "in_hand": True,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "hero_seat_id": "seat_2",
        "state_confidence": 0.95,
    }
    controller.last_decision_summary = {}
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller._last_runtime_street = "IDLE"
    controller._last_hero_seat_id = "seat_2"
    controller.fallback_coords = {}
    controller._get_dynamic_coordinates = lambda state: {
        "FOLD": (100, 200),
        "CALL": (220, 200),
        "BET_BOX": (340, 200),
        "BET_BTN": (460, 200),
    }
    controller._utc_now = lambda: "2026-04-11T12:01:00Z"
    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:preflop",
        street="PREFLOP",
        pot=3.0,
        board=(),
        hero_cards=("Ah", "Kd"),
        players=(),
        legal_actions=("FOLD", "CALL", "BET"),
        action_buttons=("fold_button", "call_button", "bet_button"),
        state_confidence=0.95,
        metadata={"hero_seat_id": "seat_2"},
    )

    asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain(name="Villain", has_button=False),
            effective_stack=100.0,
        )
    )

    assert controller.last_decision_summary["incidents"] == ["solver_fallback"]
    assert controller.last_decision_summary["history"]["incidents"] == ["solver_fallback"]
    assert controller.decision_trace_history[0]["incidents"] == ["solver_fallback"]
    assert [entry["id"] for entry in controller.incident_history] == ["solver_fallback"]


def test_resolve_live_decision_context_falls_back_to_canonical_players_when_tracker_is_empty():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(
        players={},
        get_primary_villain=lambda: None,
        get_effective_stack=lambda: 0.0,
    )

    canonical_state = CanonicalTableState(
        spot_id="live:FLOP:8d-8h-7d",
        street="FLOP",
        pot=300.0,
        board=("8d", "8h", "7d"),
        hero_cards=("3h", "Kh"),
        players=(
            CanonicalPlayer(seat_id="seat_0", seat_index=0, stack=7800.0, name="Hero", is_hero=True),
            CanonicalPlayer(seat_id="seat_1", seat_index=1, stack=5124.0, name="SBM1970", has_button=True),
            CanonicalPlayer(seat_id="seat_2", seat_index=2, stack=20000.0, name="xavisousa86"),
        ),
        legal_actions=("FOLD", "CHECK"),
        action_buttons=("fold_button", "check_button"),
        state_confidence=0.96,
        metadata={},
    )

    primary_villain, effective_stack = controller._resolve_live_decision_context(canonical_state)

    assert primary_villain is not None
    assert primary_villain.name == "SBM1970"
    assert primary_villain.has_button is True
    assert effective_stack == 7800.0


def test_assisted_execution_allows_auto_click_when_runtime_confidence_is_high():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {"assisted_mode_enabled": True}

    canonical_state = CanonicalTableState(
        spot_id="live:FLOP:auto",
        street="FLOP",
        pot=120.0,
        board=("Ah", "7d", "2c"),
        hero_cards=("As", "Kd"),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.91,
        metadata={},
    )
    decision = {
        "action": "CHECK",
        "source": "GTO_RUST",
        "confidence": 0.88,
        "fallback_used": False,
        "metadata": {
            "confidence": {
                "state_confidence": 0.91,
                "profile_reliability": 0.04,
            },
            "profile": {
                "observed_hands": 4,
                "reliability": 0.04,
                "exploit_confidence": 0.0,
            },
        },
    }
    gate_result = GateResult(allowed=True, status="ready", reasons=[], confidence=0.96)

    assisted = controller._evaluate_assisted_execution(canonical_state, decision, gate_result)

    assert assisted["enabled"] is True
    assert assisted["auto_execute"] is True
    assert assisted["reason"] == "ready"


def test_assisted_execution_requires_manual_click_when_exploit_profile_data_is_thin():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {"assisted_mode_enabled": True}

    canonical_state = CanonicalTableState(
        spot_id="live:TURN:manual",
        street="TURN",
        pot=240.0,
        board=("Ah", "7d", "2c", "Ts"),
        hero_cards=("As", "Kd"),
        legal_actions=("FOLD", "CALL", "RAISE"),
        action_buttons=("fold_button", "call_button", "raise_button"),
        state_confidence=0.93,
        metadata={},
    )
    decision = {
        "action": "CALL",
        "source": "EXPLOIT_PROFILE",
        "confidence": 0.86,
        "fallback_used": False,
        "metadata": {
            "confidence": {
                "state_confidence": 0.93,
                "profile_reliability": 0.03,
            },
            "profile": {
                "observed_hands": 5,
                "reliability": 0.03,
                "exploit_confidence": 0.22,
            },
        },
    }
    gate_result = GateResult(allowed=True, status="ready", reasons=[], confidence=0.96)

    assisted = controller._evaluate_assisted_execution(canonical_state, decision, gate_result)

    assert assisted["enabled"] is True
    assert assisted["auto_execute"] is False
    assert assisted["requires_operator_action"] is True
    assert assisted["reason"] == "insufficient_profile_data"


def test_assisted_execution_allows_passive_fallback_when_state_is_strong_and_action_is_legal():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {"assisted_mode_enabled": True}

    canonical_state = CanonicalTableState(
        spot_id="live:PREFLOP:fallback-check",
        street="PREFLOP",
        pot=42.0,
        board=(),
        hero_cards=("As", "Ad"),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.833,
        metadata={},
    )
    decision = {
        "action": "CHECK",
        "source": "GTO_RUST",
        "confidence": 0.458,
        "fallback_used": True,
        "metadata": {
            "confidence": {
                "state_confidence": 0.833,
                "profile_reliability": 0.0,
            },
            "profile": {
                "observed_hands": 0,
                "reliability": 0.0,
                "exploit_confidence": 0.0,
            },
        },
    }
    gate_result = GateResult(allowed=True, status="ready", reasons=[], confidence=0.96)

    assisted = controller._evaluate_assisted_execution(canonical_state, decision, gate_result)

    assert assisted["enabled"] is True
    assert assisted["auto_execute"] is True
    assert assisted["requires_operator_action"] is False
    assert assisted["reason"] == "fallback_passive_ready"


def test_assisted_execution_requires_manual_when_runtime_readiness_is_conservative():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {"assisted_mode_enabled": True}

    canonical_state = CanonicalTableState(
        spot_id="live:FLOP:conservative",
        street="FLOP",
        pot=0.0,
        board=("Ah", "7d", "2c"),
        hero_cards=("As", "Kd"),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.83,
        metadata={"runtime_readiness": {"state": "conservative", "score": 0.58}},
    )
    decision = {
        "action": "CHECK",
        "source": "GTO_RUST",
        "confidence": 0.9,
        "fallback_used": False,
        "metadata": {"confidence": {"state_confidence": 0.83}, "profile": {"observed_hands": 0}},
    }
    gate_result = GateResult(allowed=True, status="ready", reasons=[], confidence=0.96)

    assisted = controller._evaluate_assisted_execution(canonical_state, decision, gate_result)

    assert assisted["auto_execute"] is False
    assert assisted["reason"] == "runtime_conservative"


def test_assisted_execution_blocks_when_runtime_readiness_is_blocked_local():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {"assisted_mode_enabled": True}

    canonical_state = CanonicalTableState(
        spot_id="live:FLOP:blocked",
        street="FLOP",
        pot=0.0,
        board=("Ah", "7d", "2c"),
        hero_cards=("As", "Kd"),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.83,
        metadata={"runtime_readiness": {"state": "blocked_local", "score": 0.22}},
    )
    decision = {
        "action": "CHECK",
        "source": "GTO_RUST",
        "confidence": 0.9,
        "fallback_used": False,
        "metadata": {"confidence": {"state_confidence": 0.83}, "profile": {"observed_hands": 0}},
    }
    gate_result = GateResult(allowed=True, status="ready", reasons=[], confidence=0.96)

    assisted = controller._evaluate_assisted_execution(canonical_state, decision, gate_result)

    assert assisted["auto_execute"] is False
    assert assisted["reason"] == "runtime_blocked"


def test_run_decision_gate_flow_reports_click_failure_instead_of_fake_executed(monkeypatch):
    controller = object.__new__(SuperBotController)
    controller.runtime_sanity = SanityChecker()
    controller.runtime_history_store = FixtureHistoryStore()
    controller.decision_maker = FixtureDecisionMaker(
        {
            "action": "CHECK",
            "bet_size": None,
            "source": "GTO_RUST",
            "confidence": 0.91,
            "fallback_used": False,
            "warnings": [],
            "incidents": [],
            "backend": "solver_stub",
            "elapsed_ms": 7,
            "metadata": {
                "profile": {"observed_hands": 0},
                "confidence": {"state_confidence": 0.95},
                "solver": {},
            },
        }
    )
    controller.action_controller = FixtureActionController(result={"ok": False, "reason": "call_click_failed"})
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller.last_tracker_snapshot = {
        "street": "FLOP",
        "board": ["Ah", "7d", "2c"],
        "pot": 120.0,
        "hero_cards": ["As", "Kd"],
        "action_history": [],
        "in_hand": True,
        "legal_actions": ["CHECK", "BET"],
        "hero_seat_id": "seat_2",
        "state_confidence": 0.95,
    }
    controller.last_decision_summary = {}
    controller.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
    controller.runtime_event_history = deque(maxlen=24)
    controller.decision_trace_history = deque(maxlen=16)
    controller.incident_history = deque(maxlen=16)
    controller._last_runtime_street = "IDLE"
    controller._last_hero_seat_id = "seat_2"
    controller.operator_controls = {"assisted_mode_enabled": True}
    controller.fallback_coords = {}
    controller._get_dynamic_coordinates = lambda state: {
        "CALL": (220, 200),
        "BET_BOX": (340, 200),
        "BET_BTN": (460, 200),
    }
    controller._utc_now = lambda: "2026-04-13T16:00:00Z"

    async def _fast_sleep(_delay):
        await _ORIGINAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr("src.main.asyncio.sleep", _fast_sleep)

    canonical_state = CanonicalTableState(
        spot_id="live:FLOP:click-failed",
        street="FLOP",
        pot=120.0,
        board=("Ah", "7d", "2c"),
        hero_cards=("As", "Kd"),
        players=(),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.95,
        metadata={},
    )

    asyncio.run(
        controller._run_decision_gate_flow(
            canonical_state=canonical_state,
            state=FixtureState(),
            primary_villain=FixtureVillain(name="Villain", has_button=False),
            effective_stack=100.0,
        )
    )

    assert controller.last_decision_summary["execution"]["status"] == "click_failed"
    assert controller.last_decision_summary["execution"]["reason"] == "call_click_failed"
    assert controller.runtime_event_history[0]["message"] == "click_failed"


def test_update_operator_controls_switches_to_assisted_mode_and_disables_observation_modes():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {
        "profile_name": "live-runtime",
        "surface": "bot_cockpit",
        "capture_source": "ocr",
        "auto_refresh_enabled": True,
        "assisted_mode_enabled": False,
        "observation_mode_enabled": True,
        "shadow_mode_enabled": True,
        "manual_override_enabled": True,
        "paused": False,
        "updated_at": "2026-04-13T10:00:00Z",
    }
    controller.is_running = True
    controller.runtime_event_history = deque(maxlen=24)
    controller.runtime_history_store = FixtureHistoryStore()
    controller._utc_now = lambda: "2026-04-13T10:01:00Z"

    snapshot = controller.update_operator_controls({"assistedModeEnabled": True})

    assert snapshot["status"] == "assisted"
    assert snapshot["assisted_mode_enabled"] is True
    assert snapshot["observation_mode_enabled"] is False
    assert snapshot["shadow_mode_enabled"] is False
    assert snapshot["manual_override_enabled"] is False


def test_derive_runtime_street_resets_to_idle_when_only_resume_hand_is_visible():
    controller = object.__new__(SuperBotController)
    controller._recent_runtime_streets = deque(["PREFLOP"], maxlen=3)

    street = controller._derive_runtime_street((), (), ("resume_hand",))

    assert street == "IDLE"
    assert list(controller._recent_runtime_streets) == []


def test_stabilize_runtime_hero_cards_drops_cached_cards_on_resume_hand_screen():
    controller = object.__new__(SuperBotController)
    controller._last_good_runtime_hero_cards = ("Jh", "Ts")
    controller._last_good_runtime_hero_cards_at = 999999.0
    controller._runtime_hero_cards_ttl_s = 10.0

    state = types.SimpleNamespace(
        action_buttons=[types.SimpleNamespace(class_name="resume_hand")],
        pots=[],
    )

    result = controller._stabilize_runtime_hero_cards((), (), state)

    assert result == ()
    assert controller._last_good_runtime_hero_cards == ()
    assert controller._last_good_runtime_hero_cards_at == 0.0


def test_stabilize_runtime_hero_cards_drops_cached_cards_on_button_only_idle_noise():
    controller = object.__new__(SuperBotController)
    controller._last_good_runtime_hero_cards = ("Jh", "Ts")
    controller._last_good_runtime_hero_cards_at = 999999.0
    controller._runtime_hero_cards_ttl_s = 10.0

    state = types.SimpleNamespace(
        action_buttons=[types.SimpleNamespace(class_name="check_button")],
        pots=[],
    )

    result = controller._stabilize_runtime_hero_cards((), (), state)

    assert result == ()
    assert controller._last_good_runtime_hero_cards == ()


def test_stabilize_runtime_hero_cards_reuses_previous_pair_on_suspicious_single_rank_flip_same_suit():
    controller = object.__new__(SuperBotController)
    controller._runtime_hero_cards_ttl_s = 10.0
    controller._runtime_hero_cards_rank_flip_ttl_s = 1.0
    controller._last_good_runtime_hero_cards = ("Kc", "8h")
    controller._last_good_runtime_hero_cards_at = time.monotonic()
    controller._format_log_cards = lambda cards: " ".join(cards) if cards else "-"

    state = types.SimpleNamespace(pots=[types.SimpleNamespace(confidence=3.0)])

    result = controller._stabilize_runtime_hero_cards(("Kc", "5h"), (), state)

    assert result == ("Kc", "8h")
    assert controller._last_good_runtime_hero_cards == ("Kc", "8h")


def test_build_tracker_snapshot_prefers_idle_fallback_when_live_state_is_empty():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(
        players={},
        state="PREFLOP",
        current_board=[],
        pot_total=0.0,
        hero_cards=[],
        legal_actions=[],
        current_hand_actions=[],
        state_confidence=0.9,
    )

    snapshot = controller._build_tracker_snapshot(
        {
            "street": "IDLE",
            "board": [],
            "pot": 0.0,
            "hero_cards": [],
            "legal_actions": [],
            "state_confidence": 0.5,
            "metadata": {"hero_seat_id": ""},
        }
    )

    assert snapshot["street"] == "IDLE"
    assert snapshot["hero_cards"] == []
    assert snapshot["legal_actions"] == []
    assert snapshot["in_hand"] is False


def test_convert_state_for_tracker_ignores_actionable_buttons_without_live_context():
    controller = object.__new__(SuperBotController)
    controller._label_generic_action_buttons = lambda state, frame: state
    controller._stabilize_runtime_hero_cards = lambda hero_cards, board, state: hero_cards
    controller._build_players = lambda state, frame: []
    controller._derive_legal_actions = lambda state: (
        ("CHECK", "BET"),
        ("check_button", "bet_button", "resume_hand"),
    )
    controller._derive_runtime_street = lambda board, hero_cards, action_buttons: "IDLE"
    controller._normalize_board_for_street = lambda board, street: board
    controller._smooth_legal_actions = lambda legal_actions, action_buttons, board, hero_cards: (
        legal_actions,
        action_buttons,
    )
    controller._smooth_runtime_state_confidence = lambda confidence, street, board, hero_cards: confidence
    controller.last_canonical_spot_snapshot = None

    state = types.SimpleNamespace(
        board_cards=[],
        hero_cards=[],
        pots=[],
        metadata={"table_detected": True},
        action_buttons=[],
        dealer_button=None,
    )

    canonical = controller._convert_state_for_tracker(state, frame=None)

    assert canonical.street == "IDLE"
    assert canonical.legal_actions == ()
    assert canonical.action_buttons == ("resume_hand",)


def test_build_tracker_snapshot_prefers_recent_observed_pot_over_slower_tracker_pot():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(
        players={},
        state="FLOP",
        current_board=["Qh", "9c", "2c"],
        pot_total=3402.0,
        hero_cards=[],
        legal_actions=[],
        current_hand_actions=[],
        state_confidence=0.8,
    )

    snapshot = controller._build_tracker_snapshot(
        {
            "street": "FLOP",
            "board": ["Qh", "9c", "2c"],
            "pot": 3602.0,
            "hero_cards": [],
            "legal_actions": [],
            "state_confidence": 0.7,
            "metadata": {
                "hero_seat_id": "",
                "vision": {},
                "ocr": {},
                "observed_pot": {
                    "value": 3602.0,
                    "observed_at_monotonic": time.monotonic(),
                    "source_region": "preset_geometry",
                    "ocr_focus": "top_label",
                },
            },
        }
    )

    assert snapshot["pot"] == 3602.0
    assert snapshot["vision_metadata"]["prefer_observed_pot"] is True


def test_build_tracker_snapshot_prefers_recent_fast_lane_pot_over_other_sources():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(
        players={},
        state="FLOP",
        current_board=["Qh", "9c", "2c"],
        pot_total=3402.0,
        hero_cards=[],
        legal_actions=[],
        current_hand_actions=[],
        state_confidence=0.8,
    )

    snapshot = controller._build_tracker_snapshot(
        {
            "street": "FLOP",
            "board": ["Qh", "9c", "2c"],
            "pot": 3602.0,
            "hero_cards": [],
            "legal_actions": [],
            "state_confidence": 0.7,
            "metadata": {
                "hero_seat_id": "",
                "vision": {},
                "ocr": {},
                "observed_pot_fast": {
                    "value": 3802.0,
                    "observed_at_monotonic": time.monotonic(),
                    "source_region": "fast_lane_geometry",
                    "ocr_focus": "top_label",
                },
                "observed_pot": {
                    "value": 3602.0,
                    "observed_at_monotonic": time.monotonic(),
                    "source_region": "preset_geometry",
                    "ocr_focus": "top_label",
                },
            },
        }
    )

    assert snapshot["pot"] == 3802.0
    assert snapshot["vision_metadata"]["prefer_observed_pot_fast"] is True


def test_build_tracker_snapshot_does_not_force_idle_when_raw_board_is_visible():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(
        players={},
        state="IDLE",
        current_board=[],
        pot_total=8739.0,
        hero_cards=[],
        legal_actions=[],
        current_hand_actions=[],
        state_confidence=0.33,
    )

    snapshot = controller._build_tracker_snapshot(
        {
            "street": "IDLE",
            "board": [],
            "pot": 8739.0,
            "hero_cards": [],
            "legal_actions": [],
            "state_confidence": 0.33,
            "metadata": {
                "hero_seat_id": "",
                "vision": {"raw_board_count": 3},
                "ocr": {},
                "observed_pot_fast": {
                    "value": 8739.0,
                    "observed_at_monotonic": time.monotonic(),
                    "source_region": "fast_lane_geometry",
                    "ocr_focus": "top_label",
                },
            },
        }
    )

    assert snapshot["pot"] == 8739.0
    assert snapshot["vision_metadata"]["raw_board_count"] == 3


def test_convert_state_for_tracker_ignores_fast_fold_preselect_buttons():
    controller = object.__new__(SuperBotController)
    controller._label_generic_action_buttons = lambda state, frame: state
    controller._stabilize_runtime_hero_cards = lambda hero_cards, board, state: hero_cards
    controller._build_players = lambda state, frame: []
    controller._derive_legal_actions = lambda state: (
        ("FOLD", "CALL"),
        ("fast_fold_button", "call_button"),
    )
    controller._derive_runtime_street = SuperBotController._derive_runtime_street.__get__(controller, SuperBotController)
    controller._normalize_board_for_street = lambda board, street: board
    controller._smooth_legal_actions = lambda legal_actions, action_buttons, board, hero_cards: (
        legal_actions,
        action_buttons,
    )
    controller._smooth_runtime_state_confidence = lambda confidence, street, board, hero_cards: confidence
    controller._recent_runtime_streets = deque(maxlen=6)
    controller.last_canonical_spot_snapshot = None

    state = types.SimpleNamespace(
        board_cards=[],
        hero_cards=[types.SimpleNamespace(class_name="4h"), types.SimpleNamespace(class_name="2d")],
        pots=[],
        metadata={"table_detected": True},
        action_buttons=[],
        dealer_button=None,
    )

    canonical = controller._convert_state_for_tracker(state, frame=None)

    assert canonical.street == "PREFLOP"
    assert canonical.hero_cards == ("4h", "2d")
    assert canonical.legal_actions == ()
    assert canonical.action_buttons == ("fast_fold_button",)


def test_build_gate_tracker_snapshot_uses_canonical_live_state():
    controller = object.__new__(SuperBotController)
    controller.last_tracker_snapshot = {"hero_seat_id": "seat_hero"}

    canonical_state = _build_canonical_state(
        {
            "spot_id": "live:PREFLOP:preflop",
            "street": "PREFLOP",
            "pot": 300.0,
            "board": [],
            "hero_cards": ["Ah", "Kd"],
            "players": [],
            "legal_actions": ["FOLD", "CALL", "RAISE"],
            "action_buttons": ["fold_button", "call_button", "raise_button"],
            "state_confidence": 0.91,
            "metadata": {"ocr": {"mode": "priority"}},
        }
    )

    snapshot = controller._build_gate_tracker_snapshot(canonical_state)

    assert snapshot["street"] == "PREFLOP"
    assert snapshot["hero_cards"] == ["Ah", "Kd"]
    assert snapshot["legal_actions"] == ["FOLD", "CALL", "RAISE"]
    assert snapshot["in_hand"] is True
    assert snapshot["hero_seat_id"] == "seat_hero"


def test_handle_stale_live_frame_marks_execution_as_stale():
    controller = object.__new__(SuperBotController)
    controller._max_live_frame_age_s = 1.25
    controller.tracker = types.SimpleNamespace(current_hand_actions=[])
    controller._build_operator_snapshot = lambda: {"assisted_mode_enabled": True}
    controller._utc_now = lambda: "2026-04-13T19:15:00Z"
    controller._push_incident = lambda *args, **kwargs: None
    controller._push_runtime_event = lambda *args, **kwargs: None
    controller._format_log_cards = lambda cards: " ".join(cards) if cards else "-"
    controller._format_log_list = lambda values: ", ".join(values) if values else "-"
    controller._recent_runtime_action_button_signatures = deque(maxlen=5)
    controller.action_controller = types.SimpleNamespace(hwnd=123, _get_foreground_window=lambda: 123)
    controller._clear_live_decision_summary = SuperBotController._clear_live_decision_summary.__get__(controller, SuperBotController)
    controller._evaluate_fallback_execution_readiness = SuperBotController._evaluate_fallback_execution_readiness.__get__(controller, SuperBotController)

    canonical_state = _build_canonical_state(
        {
            "spot_id": "live:PREFLOP:preflop",
            "street": "PREFLOP",
            "pot": 300.0,
            "board": [],
            "hero_cards": ["Ah", "Kd"],
            "players": [],
            "legal_actions": ["FOLD", "CALL", "RAISE"],
            "action_buttons": ["fold_button", "call_button", "raise_button"],
            "state_confidence": 0.91,
            "metadata": {},
        }
    )

    controller._handle_stale_live_frame(canonical_state, 2.0)

    assert controller.last_gate_result.reason == "STALE_FRAME"
    assert controller.last_decision_summary["execution"]["status"] == "stale_frame"
    assert controller.last_decision_summary["gate_reason"] == "STALE_FRAME"
    assert controller.last_decision_summary["fallback_execution_readiness"]["status"] == "blocked"
    assert "stale_frame" in controller.last_decision_summary["fallback_execution_readiness"]["reasons"]


def test_fallback_execution_readiness_requires_stable_buttons_across_frames():
    controller = object.__new__(SuperBotController)
    controller._recent_runtime_action_button_signatures = deque(maxlen=5)
    controller.action_controller = types.SimpleNamespace(hwnd=777, _get_foreground_window=lambda: 777)
    controller._evaluate_fallback_execution_readiness = SuperBotController._evaluate_fallback_execution_readiness.__get__(controller, SuperBotController)

    canonical_state = _build_canonical_state(
        {
            "spot_id": "live:PREFLOP:test",
            "street": "PREFLOP",
            "pot": 100.0,
            "board": [],
            "hero_cards": ["Ah", "Kd"],
            "players": [],
            "legal_actions": ["CHECK", "FOLD"],
            "action_buttons": ["fold_button", "check_button"],
            "state_confidence": 0.95,
            "metadata": {"vision": {"visual_changed_regions": []}},
        }
    )

    first = controller._evaluate_fallback_execution_readiness(canonical_state, frame_age_ms=120.0)
    second = controller._evaluate_fallback_execution_readiness(canonical_state, frame_age_ms=120.0)
    third = controller._evaluate_fallback_execution_readiness(canonical_state, frame_age_ms=120.0)

    assert first["status"] == "blocked"
    assert "buttons_not_stable" in first["reasons"]
    assert second["status"] == "blocked"
    assert third["status"] == "ready"
    assert third["recommended_action"] == "CHECK"


def test_classify_slot_button_label_skips_ocr_for_standard_three_button_layout():
    controller = object.__new__(SuperBotController)

    def fail_if_called(_crop):
        raise AssertionError("button OCR should not run for standard fold/call/raise layouts")

    controller._read_action_button_text = fail_if_called

    assert controller._classify_slot_button_label(
        image_crop=None,
        slot_key="CALL",
        visible_slot_keys={"FOLD", "CALL", "BET_BTN"},
        fallback_label="action_button_generic",
    ) == "call_button"

    assert controller._classify_slot_button_label(
        image_crop=None,
        slot_key="BET_BTN",
        visible_slot_keys={"FOLD", "CALL", "BET_BTN"},
        fallback_label="action_button_generic",
    ) == "raise_button"


def test_classify_slot_button_label_skips_ocr_for_standard_check_bet_layout():
    controller = object.__new__(SuperBotController)

    def fail_if_called(_crop):
        raise AssertionError("button OCR should not run for standard check/bet layouts")

    controller._read_action_button_text = fail_if_called

    assert controller._classify_slot_button_label(
        image_crop=None,
        slot_key="CALL",
        visible_slot_keys={"CALL", "BET_BTN"},
        fallback_label="action_button_generic",
    ) == "check_button"

    assert controller._classify_slot_button_label(
        image_crop=None,
        slot_key="BET_BTN",
        visible_slot_keys={"CALL", "BET_BTN"},
        fallback_label="action_button_generic",
    ) == "bet_button"


def test_runtime_readiness_becomes_actionable_for_coherent_runtime_state():
    canonical_state = _build_canonical_state(
        {
            "spot_id": "live:FLOP:ready",
            "street": "FLOP",
            "pot": 120.0,
            "board": ["Ah", "7d", "2c"],
            "hero_cards": ["As", "Kd"],
            "players": [],
            "legal_actions": ["CHECK", "BET"],
            "action_buttons": ["check_button", "bet_button"],
            "state_confidence": 0.9,
            "metadata": {
                "vision": {
                    "frame_quality": {"quality_score": 0.92, "rejected": False},
                    "crop_quality": {"pot": {"quality_score": 0.88, "rejected": False}},
                },
                "fallback_execution_readiness": {"status": "ready", "reasons": []},
            },
        }
    )

    validation = PokerStateValidator().validate(canonical_state)
    readiness = build_runtime_readiness(canonical_state, validation)

    assert validation.state == "fully_valid"
    assert readiness.state == "actionable"
    assert readiness.actionable is True


def test_runtime_readiness_blocks_invalid_postflop_state_without_pot():
    canonical_state = _build_canonical_state(
        {
            "spot_id": "live:FLOP:invalid",
            "street": "FLOP",
            "pot": 0.0,
            "board": ["Ah", "7d", "2c"],
            "hero_cards": ["As", "Kd"],
            "players": [],
            "legal_actions": ["CHECK", "BET"],
            "action_buttons": ["check_button", "bet_button"],
            "state_confidence": 0.8,
            "metadata": {
                "vision": {
                    "frame_quality": {"quality_score": 0.92, "rejected": False},
                    "crop_quality": {},
                },
                "fallback_execution_readiness": {"status": "blocked", "reasons": ["missing_pot"]},
            },
        }
    )

    validation = PokerStateValidator().validate(canonical_state)
    readiness = build_runtime_readiness(canonical_state, validation)

    assert validation.state in {"soft_invalid", "hard_invalid"}
    assert readiness.actionable is False
    assert "missing_postflop_pot" in readiness.reasons


def test_build_resolved_runtime_state_records_near_miss_when_validation_is_not_fully_valid():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(pending_street_promotion="")
    controller.poker_state_validator = PokerStateValidator()
    controller.runtime_failure_dataset = FixtureFailureDataset()
    controller.last_decision_summary = {}
    controller.last_tracker_snapshot = {}
    controller.last_resolved_runtime_state = None
    controller._utc_now = lambda: "2026-04-11T12:10:00Z"
    controller._get_runtime_session_id = lambda: "runtime-test"
    controller._record_runtime_failure = SuperBotController._record_runtime_failure.__get__(controller, SuperBotController)
    controller._build_tracker_snapshot = lambda payload: {
        "street": "FLOP",
        "board": ["Ah", "7d", "2c"],
        "hero_cards": ["As", "Kd"],
        "legal_actions": ["CHECK", "BET"],
        "pot": 0.0,
        "state_confidence": 0.8,
        "spot_id": payload.get("spot_id", "live:FLOP:test"),
    }

    canonical_state = CanonicalTableState(
        spot_id="live:FLOP:test",
        street="FLOP",
        pot=0.0,
        board=("Ah", "7d", "2c"),
        hero_cards=("As", "Kd"),
        players=(),
        legal_actions=("CHECK", "BET"),
        action_buttons=("check_button", "bet_button"),
        state_confidence=0.8,
        metadata={
            "hero_participation": "in_hand",
            "vision": {
                "frame_quality": {"quality_score": 0.9, "rejected": False},
                "crop_quality": {},
            },
            "fallback_execution_readiness": {"status": "blocked", "reasons": ["missing_pot"]},
        },
    )

    resolved = SuperBotController._build_resolved_runtime_state(controller, canonical_state)

    assert resolved.metadata["poker_state_validation"]["state"] in {"soft_invalid", "hard_invalid"}
    assert resolved.metadata["runtime_readiness"]["state"] in {"conservative", "blocked_local"}
    assert controller.runtime_failure_dataset.records
    assert controller.runtime_failure_dataset.records[0]["category"] == "near_miss"
    assert controller.runtime_failure_dataset.records[0]["incident_id"] == "runtime_readiness_not_fully_valid"


def test_build_resolved_runtime_state_skips_near_miss_for_idle_observation_states():
    controller = object.__new__(SuperBotController)
    controller.tracker = types.SimpleNamespace(pending_street_promotion="")
    controller.poker_state_validator = PokerStateValidator()
    controller.runtime_failure_dataset = FixtureFailureDataset()
    controller.last_decision_summary = {}
    controller.last_tracker_snapshot = {}
    controller.last_resolved_runtime_state = None
    controller._utc_now = lambda: "2026-04-11T12:12:00Z"
    controller._get_runtime_session_id = lambda: "runtime-test"
    controller._record_runtime_failure = SuperBotController._record_runtime_failure.__get__(controller, SuperBotController)
    controller._build_tracker_snapshot = lambda payload: {
        "street": "IDLE",
        "board": [],
        "hero_cards": [],
        "legal_actions": [],
        "pot": 0.0,
        "state_confidence": 0.56,
        "spot_id": payload.get("spot_id", "live:IDLE:idle"),
    }

    canonical_state = CanonicalTableState(
        spot_id="live:IDLE:idle",
        street="IDLE",
        pot=0.0,
        board=(),
        hero_cards=(),
        players=(),
        legal_actions=(),
        action_buttons=(),
        state_confidence=0.56,
        metadata={
            "hero_participation": "idle",
            "vision": {
                "frame_quality": {"quality_score": 0.78, "rejected": False},
                "crop_quality": {},
            },
            "fallback_execution_readiness": {"status": "idle", "reasons": ["idle"]},
        },
    )

    resolved = SuperBotController._build_resolved_runtime_state(controller, canonical_state)

    assert resolved.metadata["poker_state_validation"]["state"] == "degraded_valid"
    assert resolved.metadata["runtime_readiness"]["state"] == "conservative"
    assert controller.runtime_failure_dataset.records == []


def test_go_live_gate_blocks_when_runtime_metrics_are_too_weak():
    result = evaluate_go_live_gate(
        {
            "decision_count": 3,
            "block_rate": 0.9,
            "fallback_rate": 0.8,
            "rolling_latency_ms": 3000.0,
        },
        {"runtime": {"incident_count": 12}},
    )

    assert result.passed is False
    assert "insufficient_decision_count" in result.reasons
    assert "block_rate_too_high" in result.reasons


def test_go_live_gate_passes_when_metrics_are_within_thresholds():
    result = evaluate_go_live_gate(
        {
            "decision_count": 30,
            "block_rate": 0.1,
            "fallback_rate": 0.1,
            "rolling_latency_ms": 120.0,
        },
        {"runtime": {"incident_count": 1}},
        readiness={"state": "actionable", "score": 0.9},
        validation={"state": "fully_valid"},
    )

    assert result.passed is True
    assert result.status == "ready"


def test_go_live_gate_blocks_when_readiness_and_validation_are_not_safe():
    result = evaluate_go_live_gate(
        {
            "decision_count": 30,
            "block_rate": 0.1,
            "fallback_rate": 0.1,
            "rolling_latency_ms": 120.0,
        },
        {"runtime": {"incident_count": 1}},
        readiness={"state": "conservative", "score": 0.4},
        validation={"state": "soft_invalid"},
    )

    assert result.passed is False
    assert "readiness_score_too_low" in result.reasons
    assert "readiness_state_not_actionable" in result.reasons
    assert "validation_state_invalid" in result.reasons
    assert result.checks["readiness_score"]["ok"] is False
    assert result.checks["invalid_validation_rate"]["ok"] is False


def test_go_live_gate_honors_custom_thresholds():
    result = evaluate_go_live_gate(
        {
            "decision_count": 10,
            "block_rate": 0.1,
            "fallback_rate": 0.1,
            "rolling_latency_ms": 120.0,
        },
        {"runtime": {"incident_count": 1}},
        readiness={"state": "actionable", "score": 0.9},
        validation={"state": "fully_valid"},
        thresholds={"min_decision_count": 5},
    )

    assert result.passed is True
    assert result.checks["decision_count"]["threshold"] == 5


def test_operator_snapshot_exposes_go_live_blocked_when_gate_fails():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {
        "paused": False,
        "assisted_mode_enabled": False,
        "observation_mode_enabled": False,
        "shadow_mode_enabled": False,
        "manual_override_enabled": False,
        "auto_refresh_enabled": True,
    }
    controller.is_running = True
    controller.last_go_live_gate = {"passed": False, "status": "blocked", "reasons": ["insufficient_decision_count"]}
    controller._utc_now = lambda: "2026-04-11T12:20:00Z"

    snapshot = controller._build_operator_snapshot()

    assert snapshot["status"] == "go_live_blocked"
    assert snapshot["go_live_gate"]["passed"] is False


def test_operator_snapshot_keeps_assisted_mode_even_when_go_live_gate_is_blocked():
    controller = object.__new__(SuperBotController)
    controller.operator_controls = {
        "paused": False,
        "assisted_mode_enabled": True,
        "observation_mode_enabled": False,
        "shadow_mode_enabled": False,
        "manual_override_enabled": False,
        "auto_refresh_enabled": True,
    }
    controller.is_running = True
    controller.last_go_live_gate = {"passed": False, "status": "blocked", "reasons": ["insufficient_decision_count"]}
    controller._utc_now = lambda: "2026-04-11T12:20:00Z"

    snapshot = controller._build_operator_snapshot()

    assert snapshot["status"] == "assisted"
