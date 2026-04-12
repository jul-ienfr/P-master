import asyncio
import json
import sys
import types
from collections import deque
from pathlib import Path


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
        pass


    class _StubDetectionResult:
        def __init__(self, bbox=(0, 0, 0, 0), confidence=0.0, class_name=""):
            self.bbox = bbox
            self.confidence = confidence
            self.class_name = class_name


    class _StubPokerDetector:
        def __init__(self, *args, **kwargs):
            pass


    def _stub_decode_card_token(token):
        return token


    sys.modules["src.vision.detector"] = types.SimpleNamespace(
        PokerDetector=_StubPokerDetector,
        TableState=_StubTableState,
        DetectionResult=_StubDetectionResult,
        decode_card_token=_stub_decode_card_token,
    )


if "src.vision.ocr" not in sys.modules:
    class _StubPokerOCR:
        def __init__(self, *args, **kwargs):
            pass


    sys.modules["src.vision.ocr"] = types.SimpleNamespace(PokerOCR=_StubPokerOCR)


from src.bot.runtime_types import CanonicalPlayer, CanonicalTableState
from src.bot.sanity_checker import GateResult, SanityChecker
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
    def __init__(self):
        self.calls = []

    async def execute_action(self, action_intent, dynamic_coords):
        self.calls.append(
            {
                "action": action_intent.action,
                "bet_size": action_intent.bet_size,
                "dynamic_coords": dict(dynamic_coords),
            }
        )


class FixtureVillain:
    def __init__(self, name: str, has_button: bool):
        self.name = name
        self.has_button = has_button


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
