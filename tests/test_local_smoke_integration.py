import asyncio
import json
import sys
import types
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


from src.api.server import BotAPI
from src.bot.decision_maker import DecisionMaker
from src.bot.table_tracker import TableTracker
from src.data.database import DatabaseManager
from src.runtime.history_store import RuntimeHistoryStore
from src.runtime.timesfm_service import RuntimeTimesFMService


def run(coro):
    return asyncio.run(coro)


class StubHITL:
    def __init__(self):
        self.annotations_count = 3
        self.target_dataset_size = 10
        self.is_waiting_for_human = True
        self.current_issue = {
            "type": "vision",
            "reason": "low_confidence",
            "image_base64": "ZmFrZQ==",
            "width": 320,
            "height": 200,
        }
        self.resolved_boxes = None

    def check_convergence(self):
        return False

    def resolve_human_intervention(self, boxes):
        self.resolved_boxes = list(boxes)
        self.is_waiting_for_human = False


class FakeJSONRequest:
    def __init__(self, payload):
        self.payload = payload
        self.query = {}

    async def json(self):
        return self.payload


class FakeQueryRequest:
    def __init__(self, query=None, payload=None):
        self.query = query or {}
        self.payload = payload

    async def json(self):
        return self.payload


def test_memory_tracker_and_decisionmaker_smoke_flow():
    async def scenario():
        db = DatabaseManager(mode="memory")
        await db.connect()

        tracker = TableTracker(db)
        opening_state = {
            "street": "PREFLOP",
            "hero_cards": ["Ah", "Kd"],
            "pot": 1.5,
            "state_confidence": 0.93,
            "players": [
                {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
                {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 100.0},
            ],
        }
        action_state = {
            "street": "PREFLOP",
            "hero_cards": ["Ah", "Kd"],
            "pot": 5.5,
            "state_confidence": 0.93,
            "players": [
                {"seat_id": "hero", "seat_index": 0, "name": "Hero", "stack": 100.0, "is_hero": True},
                {"seat_id": "villain", "seat_index": 1, "name": "Villain", "stack": 96.0},
            ],
        }

        next_hand_signal = {
            "street": "PREFLOP",
            "hero_cards": ["Qs", "Qc"],
            "pot": 1.0,
            "state_confidence": 0.95,
            "players": [],
        }
        
        force_idle_signal = {
            "street": "PREFLOP",
            "hero_cards": [], # Pas de hero_cards = plus en main
            "pot": 0.0,
            "state_confidence": 0.95,
            "players": [],
        }


        await tracker.update_from_vision(opening_state)
        await tracker.update_from_vision(action_state)
        tracker.current_board = ["2c", "7d", "Jh"]
        tracker._temporal_board_buffer = ["2c", "7d", "Jh"]
        await tracker.update_from_vision(next_hand_signal)
        await asyncio.sleep(0)

        profile = await db.get_player_profile("Villain")
        decision_maker = DecisionMaker(db, create_rl_agent=False, autoload_rl_model=False)
        decision = await decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=5.5,
            effective_stack=96.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.88,
        )

        assert tracker.state == "PREFLOP"
        tracker.state = "IDLE"
        tracker.reset_for_new_hand()
        
        assert tracker.state == "IDLE"
        assert len(db.hands_history_memory) == 1

        assert profile is not None
        assert profile["player_type"] == "LooseAggressive"
        assert profile["derived_profile"]["observed_hands"] == 1
        assert profile["derived_profile"]["last_action"] == "RAISE/BET"
        assert profile["derived_profile"]["vpip_rate"] == 1.0
        assert profile["derived_profile"]["pfr_rate"] == 1.0

        assert decision["action"] == "BET"
        assert decision["fallback_used"] is False
        assert decision["fallback_reason"] is None

    run(scenario())


def test_botapi_status_and_resolution_smoke():
    async def scenario():
        hitl = StubHITL()
        api = BotAPI(
            hitl,
            runtime_status_provider=lambda: {
                "tracker": {"street": "PREFLOP", "pot": 5.5},
                "gate": {"allowed": True, "status": "allowed", "reasons": []},
                "decision": {"action": "CALL", "source": "unit-test"},
                "health": {"solver": {"status": "healthy", "reasons": []}},
                "active_solver_backend": "gto_server",
                "degraded_reasons": [],
                "last_success_at": "2026-04-14T10:00:00Z",
            },
        )

        status_response = await api.handle_get_status(object())
        status_payload = json.loads(status_response.text)

        bad_resolve = await api.handle_resolve(FakeJSONRequest({"boxes": []}))
        bad_payload = json.loads(bad_resolve.text)

        good_boxes = [{"x": 10, "y": 20, "w": 30, "h": 40}]
        good_resolve = await api.handle_resolve(FakeJSONRequest({"boxes": good_boxes}))
        good_payload = json.loads(good_resolve.text)

        assert status_response.status == 200
        assert status_payload["status"] == "waiting_for_human"
        assert status_payload["ready_for_training"] is False
        assert status_payload["tracker"]["street"] == "PREFLOP"
        assert status_payload["decision"]["action"] == "CALL"
        assert status_payload["health"]["solver"]["status"] == "healthy"
        assert status_payload["active_solver_backend"] == "gto_server"
        assert status_payload["degraded_reasons"] == []
        assert status_payload["last_success_at"] == "2026-04-14T10:00:00Z"
        assert status_payload["issue"]["reason"] == "low_confidence"

        assert bad_resolve.status == 400
        assert bad_payload["error"] == "Aucune boîte fournie."

        assert good_resolve.status == 200
        assert good_payload["success"] is True
        assert hitl.resolved_boxes == good_boxes
        assert hitl.is_waiting_for_human is False

    run(scenario())


def test_botapi_runtime_history_export_import_smoke(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        history_store.append("events", {"timestamp": "2026-04-11T12:00:00Z", "message": "boot"})
        history_store.append("decisions", {"timestamp": "2026-04-11T12:00:01Z", "chosen_action": "CALL"})

        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {
                "canonical_spot": {
                    "spot_id": "live:PREFLOP:preflop",
                    "street": "PREFLOP",
                    "pot": 1.5,
                    "board": [],
                    "hero_cards": ["Ah", "Kd"],
                    "players": [
                        {
                            "seat_id": "hero",
                            "seat_index": 0,
                            "name": "Hero",
                            "stack": 100.0,
                            "active": True,
                            "folded": False,
                            "is_hero": True,
                            "has_button": False,
                            "confidence": 0.95,
                        }
                    ],
                    "legal_actions": ["FOLD", "CALL", "BET"],
                    "action_buttons": ["fold_button", "call_button", "bet_button"],
                    "state_confidence": 0.91,
                    "metadata": {"hero_seat_id": "hero"},
                },
                "history_summary": {
                    "persistence": history_store.summarize(),
                },
            },
            runtime_history_store=history_store,
        )

        export_response = await api.handle_runtime_history_export(FakeQueryRequest({"stream": "events"}))
        export_payload = json.loads(export_response.text)

        assert export_response.status == 200
        assert export_payload["format"] == "runtime_history_v1"
        assert export_payload["stream"] == "events"
        assert len(export_payload["records"]) == 1
        assert export_payload["records"][0]["message"] == "boot"
        assert export_payload["bundle"]["kind"] == "runtime_replay_bundle"
        assert export_payload["bundle"]["version"] == "v1"
        assert export_payload["bundle"]["stream"] == "events"
        assert export_payload["bundle"]["summary"]["record_count"] == 1
        assert export_payload["bundle"]["summary"]["counts"] == {
            "events": 1,
            "decisions": 0,
            "incidents": 0,
            "metrics": 0,
        }
        assert export_payload["bundle"]["records"] == export_payload["records"]
        assert export_payload["bundle"]["runtime"]["tracker"] == {}
        assert export_payload["bundle"]["runtime"]["canonical_spot"]["spot_id"] == "live:PREFLOP:preflop"
        assert export_payload["bundle"]["runtime"]["canonical_spot"]["metadata"]["hero_seat_id"] == "hero"
        assert export_payload["bundle"]["metadata"]["persistence"]["enabled"] is True

        imported_store = RuntimeHistoryStore(file_path=str(tmp_path / "imported_runtime_history.jsonl"))
        import_api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {
                "history_summary": {
                    "persistence": imported_store.summarize(),
                },
            },
            runtime_history_store=imported_store,
        )

        import_response = await import_api.handle_runtime_history_import(
            FakeQueryRequest(query={"replace": "true"}, payload=export_payload)
        )
        import_payload = json.loads(import_response.text)

        assert import_response.status == 200
        assert import_payload["success"] is True
        assert import_payload["import"]["imported_count"] == 1
        assert imported_store.read_recent("events", limit=5)[0]["message"] == "boot"

        bare_import_response = await import_api.handle_runtime_history_import(
            FakeQueryRequest(query={}, payload=export_payload["records"])
        )
        bare_import_payload = json.loads(bare_import_response.text)

        assert bare_import_response.status == 200
        assert bare_import_payload["success"] is True
        assert bare_import_payload["import"]["imported_count"] == 1

    run(scenario())


def test_botapi_runtime_history_can_export_policy_compare_corpus(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        history_store.append(
            "decisions",
            {
                "timestamp": "2026-04-11T12:00:01Z",
                "spot_id": "live:PREFLOP:001",
                "street": "PREFLOP",
                "board": [],
                "hero_cards": ["Ah", "Kd"],
                "pot": 5.5,
                "legal_actions": ["FOLD", "CALL", "BET"],
                "action_history": ["open_2.5x"],
                "chosen_action": "CALL",
                "source": "validated_rl",
                "ev": 0.12,
                "confidence": 0.91,
                "latency_ms": 12,
                "metadata": {
                    "solver": {
                        "backend": "solver_stub",
                        "gto_action": "CALL",
                        "final_action": "CALL",
                        "ev_by_action": {"FOLD": -0.35, "CALL": 0.12},
                        "freq_by_action": {"FOLD": 0.2, "CALL": 0.8},
                        "action_metadata": {
                            "FOLD": {"raw_action": "FOLD", "freq": 0.2, "ev": -0.35},
                            "CALL": {"raw_action": "CALL", "freq": 0.8, "ev": 0.12},
                        },
                        "backend_details": {"name": "solver_stub", "version": "2026.04"},
                        "cache_details": {"hit": True, "tier": "memory"},
                        "warnings": ["subtree_reused"],
                        "alternatives": [
                            {"action": "FOLD", "raw_action": "FOLD", "freq": 0.2, "ev": -0.35},
                            {"action": "CALL", "raw_action": "CALL", "freq": 0.8, "ev": 0.12},
                        ]
                    }
                },
            },
        )

        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {
                "canonical_spot": {
                    "spot_id": "live:PREFLOP:001",
                    "street": "PREFLOP",
                    "pot": 5.5,
                    "board": [],
                    "hero_cards": ["Ah", "Kd"],
                    "players": [
                        {
                            "seat_id": "hero",
                            "seat_index": 0,
                            "name": "Hero",
                            "stack": 100.0,
                            "active": True,
                            "folded": False,
                            "is_hero": True,
                        }
                    ],
                    "legal_actions": ["FOLD", "CALL", "BET"],
                    "state_confidence": 0.91,
                    "metadata": {"hero_seat_id": "btn"},
                },
                "history_summary": {
                    "persistence": history_store.summarize(),
                },
            },
            runtime_history_store=history_store,
        )

        export_response = await api.handle_runtime_history_export(
            FakeQueryRequest({"stream": "decisions", "format": "policy_compare"})
        )
        export_payload = json.loads(export_response.text)

        assert export_response.status == 200
        assert export_payload["kind"] == "policy_compare_corpus"
        assert len(export_payload["records"]) == 1
        assert export_payload["records"][0]["replay_id"] == "live:PREFLOP:001"
        assert export_payload["records"][0]["policy_actions"] == {"validated_rl": "CALL"}
        assert export_payload["records"][0]["ev_by_action"] == {"FOLD": -0.35, "CALL": 0.12}
        assert export_payload["records"][0]["freq_by_action"] == {"FOLD": 0.2, "CALL": 0.8}
        assert export_payload["records"][0]["action_metadata"] == {
            "FOLD": {"raw_action": "FOLD", "freq": 0.2, "ev": -0.35},
            "CALL": {"raw_action": "CALL", "freq": 0.8, "ev": 0.12},
        }
        assert export_payload["records"][0]["backend_details"] == {"name": "solver_stub", "version": "2026.04"}
        assert export_payload["records"][0]["cache_details"] == {"hit": True, "tier": "memory"}
        assert export_payload["records"][0]["warnings"] == ["subtree_reused"]
        assert export_payload["records"][0]["gto_action"] == "CALL"
        assert export_payload["records"][0]["final_action"] == "CALL"
        assert export_payload["records"][0]["spot"]["legal_actions"] == ["FOLD", "CALL", "BET"]
        assert export_payload["records"][0]["spot"]["hero_position"] == "btn"

    run(scenario())


def test_database_observation_summary_and_export():
    async def scenario():
        db = DatabaseManager(mode="memory")
        await db.connect()

        await db.record_observed_hand("VillainA", "PREFLOP")
        await db.update_player_action("VillainA", {"action": "CALL", "street": "PREFLOP"})
        await db.record_observed_hand("VillainB", "FLOP")
        await db.update_player_action("VillainB", {"action": "RAISE/BET", "street": "FLOP"})
        await db.insert_hand_history(
            "Table_1",
            ["Ah", "Kd", "2c"],
            [{"player": "VillainB", "action": "RAISE/BET", "street": "FLOP"}],
        )

        summary = db.summarize_observation(limit=5)
        exported = db.export_observation_dataset(player_limit=10, hand_limit=10)

        assert summary["player_count"] == 2
        assert summary["observed_hands"] == 2
        assert summary["hands_recorded"] == 1
        assert summary["top_profiles"][0]["player_name"] == "VillainB"
        assert exported["format"] == "runtime_observation_v1"
        assert exported["summary"]["hands_recorded"] == 1
        assert exported["players"][0]["derived_profile"]["style"] == "LooseAggressive"
        assert exported["hands"][0]["board"] == "AhKd2c"

    run(scenario())


def test_botapi_operator_observation_mode_and_export():
    async def scenario():
        operator_state = {
            "profile_name": "live-runtime",
            "surface": "bot_cockpit",
            "capture_source": "ocr",
            "auto_refresh_enabled": True,
            "observation_mode_enabled": False,
            "shadow_mode_enabled": False,
            "manual_override_enabled": False,
            "paused": False,
            "status": "ready",
        }
        observation_snapshot = {
            "mode_enabled": False,
            "collecting": False,
            "backend": "memory",
            "persistence": {
                "mode": "json_file",
                "enabled": True,
                "path": "log/observation_store.json",
                "last_persisted_at": "2026-04-13T00:39:58Z",
                "error": None,
            },
            "player_count": 1,
            "observed_hands": 4,
            "hands_recorded": 2,
            "last_seen": "2026-04-13T00:40:00Z",
            "top_profiles": [
                {
                    "player_name": "VillainA",
                    "player_type": "LooseAggressive",
                    "observed_hands": 4,
                    "vpip_rate": 0.5,
                    "pfr_rate": 0.25,
                    "aggression_frequency": 0.5,
                    "reliability": 0.1,
                    "last_seen": "2026-04-13T00:40:00Z",
                }
            ],
        }

        def runtime_status_provider():
            return {
                "is_running": True,
                "tracker": {"street": "PREFLOP", "pot": 5.5},
                "gate": {"allowed": True, "status": "allowed", "reasons": []},
                "decision": {"action": "CALL", "source": "unit-test"},
                "metrics": {},
                "history": {"events": [], "decisions": [], "incidents": [], "metrics": []},
                "history_summary": {"persistence": {"enabled": False}},
                "operator": dict(operator_state),
                "observation": dict(observation_snapshot),
            }

        def runtime_operator_handler(patch: dict):
            if "observation_mode_enabled" in patch:
                observation_enabled = bool(patch["observation_mode_enabled"])
                operator_state["observation_mode_enabled"] = observation_enabled
                observation_snapshot["mode_enabled"] = observation_enabled
                observation_snapshot["collecting"] = observation_enabled
                if observation_enabled:
                    operator_state["shadow_mode_enabled"] = False
                    operator_state["manual_override_enabled"] = False
                    operator_state["status"] = "observation"
                else:
                    operator_state["status"] = "ready"
            if "paused" in patch:
                operator_state["paused"] = bool(patch["paused"])
                operator_state["status"] = "paused" if operator_state["paused"] else (
                    "observation" if operator_state["observation_mode_enabled"] else "ready"
                )
            return dict(operator_state)

        def observation_exporter(*, player_limit: int = 50, hand_limit: int = 100):
            return {
                "format": "runtime_observation_v1",
                "summary": dict(observation_snapshot),
                "players": observation_snapshot["top_profiles"][:player_limit],
                "hands": [{"hand_id": 1}, {"hand_id": 2}][:hand_limit],
            }

        api = BotAPI(
            StubHITL(),
            runtime_status_provider=runtime_status_provider,
            runtime_operator_handler=runtime_operator_handler,
            runtime_observation_provider=lambda: dict(observation_snapshot),
            runtime_observation_exporter=observation_exporter,
        )

        control_response = await api.handle_operator_control(
            FakeJSONRequest({"observation_mode_enabled": True})
        )
        control_payload = json.loads(control_response.text)

        summary_response = await api.handle_runtime_observation(FakeQueryRequest({"limit": "3"}))
        summary_payload = json.loads(summary_response.text)

        export_response = await api.handle_runtime_observation_export(
            FakeQueryRequest({"players": "1", "hands": "1"})
        )
        export_payload = json.loads(export_response.text)

        assert control_response.status == 200
        assert control_payload["operator"]["observation_mode_enabled"] is True
        assert control_payload["operator"]["status"] == "observation"
        assert control_payload["observation"]["collecting"] is True
        assert summary_response.status == 200
        assert summary_payload["mode_enabled"] is True
        assert summary_payload["persistence"]["mode"] == "json_file"
        assert summary_payload["player_count"] == 1
        assert export_response.status == 200
        assert export_payload["format"] == "runtime_observation_v1"
        assert len(export_payload["players"]) == 1
        assert len(export_payload["hands"]) == 1

    run(scenario())


def test_botapi_runtime_history_metrics_supports_runtime_persisted_and_combined_sources(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        history_store.append(
            "metrics",
            {
                "timestamp": "2026-04-11T12:00:00Z",
                "decision_count": 3,
                "window_size": 8,
                "storage": {"path": str(tmp_path / "runtime_history.jsonl")},
            },
        )

        runtime_metrics = {
            "timestamp": "2026-04-11T12:00:30Z",
            "decision_count": 4,
            "window_size": 9,
            "storage": {"path": str(tmp_path / "runtime_history.jsonl")},
        }

        def runtime_status_provider():
            persisted_metrics = history_store.read_recent("metrics", limit=10)
            persistence = history_store.summarize()
            return {
                "history": {
                    "events": [],
                    "decisions": [],
                    "incidents": [],
                    "metrics": [runtime_metrics],
                    "persisted": {
                        "events": [],
                        "decisions": [],
                        "incidents": [],
                        "metrics": persisted_metrics,
                    },
                },
                "history_summary": {
                    "event_count": 0,
                    "decision_count": 0,
                    "incident_count": 0,
                    "metrics_count": len(persisted_metrics) + 1,
                    "latest_event_at": None,
                    "latest_decision_at": None,
                    "latest_incident_at": None,
                    "latest_metrics_at": runtime_metrics["timestamp"],
                    "persistence": persistence,
                },
            }

        api = BotAPI(
            StubHITL(),
            runtime_status_provider=runtime_status_provider,
            runtime_history_store=history_store,
        )

        runtime_response = await api.handle_runtime_history(
            FakeQueryRequest({"kind": "metrics", "source": "runtime", "limit": "5"})
        )
        persisted_response = await api.handle_runtime_history(
            FakeQueryRequest({"kind": "metrics", "source": "persisted", "limit": "5"})
        )
        combined_response = await api.handle_runtime_history(
            FakeQueryRequest({"kind": "metrics", "source": "combined", "limit": "5"})
        )

        runtime_payload = json.loads(runtime_response.text)
        persisted_payload = json.loads(persisted_response.text)
        combined_payload = json.loads(combined_response.text)

        assert runtime_response.status == 200
        assert runtime_payload["kind"] == "metrics"
        assert runtime_payload["source"] == "runtime"
        assert [entry["timestamp"] for entry in runtime_payload["entries"]] == ["2026-04-11T12:00:30Z"]
        assert runtime_payload["summary"]["metrics_count"] == 1
        assert runtime_payload["summary"]["latest_metrics_at"] == "2026-04-11T12:00:30Z"

        assert persisted_response.status == 200
        assert persisted_payload["kind"] == "metrics"
        assert persisted_payload["source"] == "persisted"
        assert [entry["timestamp"] for entry in persisted_payload["entries"]] == ["2026-04-11T12:00:00Z"]
        assert persisted_payload["summary"]["metrics_count"] == 1
        assert persisted_payload["summary"]["latest_metrics_at"] == "2026-04-11T12:00:00Z"

        assert combined_response.status == 200
        assert combined_payload["kind"] == "metrics"
        assert combined_payload["source"] == "combined"
        assert [entry["timestamp"] for entry in combined_payload["entries"]] == [
            "2026-04-11T12:00:30Z",
            "2026-04-11T12:00:00Z",
        ]
        assert combined_payload["summary"]["metrics_count"] == 2
        assert combined_payload["summary"]["latest_metrics_at"] == "2026-04-11T12:00:30Z"
        assert combined_payload["summary"]["sources"]["runtime"]["metrics_count"] == 1
        assert combined_payload["summary"]["sources"]["persisted"]["metrics_count"] == 1

    run(scenario())


def test_botapi_runtime_history_exposes_compact_rl_ab_summary_by_source(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        history_store.append(
            "decisions",
            {
                "timestamp": "2026-04-11T12:00:00Z",
                "street": "RIVER",
                "chosen_action": "BET",
                "source": "validated_rl",
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
            },
        )

        runtime_decisions = [
            {
                "timestamp": "2026-04-11T12:00:30Z",
                "street": "TURN",
                "chosen_action": "CALL",
                "source": "validated_rl",
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
                "timestamp": "2026-04-11T12:00:20Z",
                "street": "FLOP",
                "chosen_action": "CHECK",
                "source": "validated_rl",
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
        ]

        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {
                "history": {
                    "events": [],
                    "decisions": runtime_decisions,
                    "incidents": [],
                    "metrics": [],
                    "persisted": {
                        "events": [],
                        "decisions": history_store.read_recent("decisions", limit=10),
                        "incidents": [],
                        "metrics": [],
                    },
                },
                "history_summary": {
                    "event_count": 0,
                    "decision_count": len(runtime_decisions),
                    "incident_count": 0,
                    "metrics_count": 0,
                    "latest_event_at": None,
                    "latest_decision_at": runtime_decisions[0]["timestamp"],
                    "latest_incident_at": None,
                    "latest_metrics_at": None,
                    "rl_ab": {
                        "runtime": {
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
                        },
                        "persisted": {
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
                        },
                        "combined": {
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
                        },
                    },
                    "persistence": history_store.summarize(),
                },
            },
            runtime_history_store=history_store,
        )

        runtime_response = await api.handle_runtime_history(
            FakeQueryRequest({"kind": "decisions", "source": "runtime", "limit": "5"})
        )
        persisted_response = await api.handle_runtime_history(
            FakeQueryRequest({"kind": "decisions", "source": "persisted", "limit": "5"})
        )
        combined_response = await api.handle_runtime_snapshot(FakeQueryRequest())

        runtime_payload = json.loads(runtime_response.text)
        persisted_payload = json.loads(persisted_response.text)
        snapshot_payload = json.loads(combined_response.text)

        assert runtime_payload["summary"]["rl_ab"] == {
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
        assert runtime_payload["summary"]["policy_compare"]["sample_count"] == 2
        assert runtime_payload["summary"]["policy_compare"]["comparable_count"] == 2
        assert runtime_payload["summary"]["policy_compare"]["agreement_count"] == 1
        assert runtime_payload["summary"]["policy_compare"]["changed_action_count"] == 1
        assert runtime_payload["summary"]["policy_compare"]["ev_coverage_count"] == 12
        assert runtime_payload["summary"]["policy_compare"]["ev_coverage_rate"] == 1.0
        assert runtime_payload["summary"]["policy_compare"]["policies"] == ["gto_solver", "rl_off", "rl_on", "validated_rl"]
        assert runtime_payload["summary"]["policy_compare"]["source_counts"] == {"validated_rl": 2}
        assert any(
            comparison["baseline_policy"] == "rl_off"
            and comparison["challenger_policy"] == "rl_on"
            and comparison["challenger_ev_delta"] == 0.1
            for comparison in runtime_payload["summary"]["policy_compare"]["comparisons"]
        )
        runtime_rl_pair = next(
            comparison
            for comparison in runtime_payload["summary"]["policy_compare"]["comparisons"]
            if comparison["baseline_policy"] == "rl_off"
            and comparison["challenger_policy"] == "rl_on"
        )
        assert runtime_rl_pair["sample_ids"] == ["2026-04-11T12:00:30Z", "2026-04-11T12:00:20Z"]
        assert runtime_rl_pair["divergence_examples"][0]["action_pair"] == "CALL->BET"
        assert runtime_payload["summary"]["policy_compare"]["highlights"]["top_spots"][0]["sample_count"] == 1
        assert persisted_payload["summary"]["rl_ab"] == {
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
        assert any(
            comparison["baseline_policy"] == "rl_off"
            and comparison["challenger_policy"] == "rl_on"
            and comparison["challenger_ev_delta"] == 0.2
            for comparison in persisted_payload["summary"]["policy_compare"]["comparisons"]
        )
        assert snapshot_payload["decision"]["metadata"]["rl_ab"] == {
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
        assert snapshot_payload["decision"]["metadata"]["policy_compare"]["sample_count"] == 3
        assert any(
            comparison["baseline_policy"] == "rl_off"
            and comparison["challenger_policy"] == "rl_on"
            for comparison in snapshot_payload["decision"]["metadata"]["policy_compare"]["comparisons"]
        )
        assert snapshot_payload["decision"]["metadata"]["policy_compare"]["highlights"]["most_divergent_pair"]["divergence_examples"][0]["street"] == "RIVER"

    run(scenario())


def test_botapi_timesfm_forecast_route_returns_404_when_disabled(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {},
            runtime_history_store=history_store,
        )

        response = await api.handle_runtime_timesfm_forecast(FakeQueryRequest())
        payload = json.loads(response.text)

        assert response.status == 404
        assert "disabled" in payload["message"].lower()

    run(scenario())


def test_botapi_timesfm_forecast_route_returns_forecast_payload(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        service = RuntimeTimesFMService(
            enabled=True,
            history_path=str(tmp_path / "runtime_history.jsonl"),
            default_horizon=6,
            default_max_context=128,
            series_loader=lambda path: {"fallback_rate": object()},
            forecaster=lambda series_map, horizon, max_context: {
                "fallback_rate": type(
                    "ForecastResult",
                    (),
                    {
                        "metric_name": "fallback_rate",
                        "horizon": horizon,
                        "context_values": [0.1, 0.2],
                        "target_values": [0.3, 0.4],
                        "point_forecast": [0.31, 0.39],
                        "quantile_forecast": [[0.31], [0.39]],
                        "last_value_baseline": [0.2, 0.2],
                        "moving_average_baseline": [0.15, 0.15],
                    },
                )()
            },
        )
        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {},
            runtime_history_store=history_store,
            runtime_timesfm_provider=service.forecast_runtime_metrics,
        )

        response = await api.handle_runtime_timesfm_forecast(
            FakeQueryRequest({"metric": "fallback_rate", "horizon": "2", "max-context": "64"})
        )
        payload = json.loads(response.text)

        assert response.status == 200
        assert payload["enabled"] is True
        assert payload["metric"] == "fallback_rate"
        assert payload["metric_count"] == 1
        assert payload["attempted_metric_count"] == 1
        assert payload["error_count"] == 0
        assert payload["success_rate"] == 1.0
        assert payload["errors"] == {}
        assert payload["timesfm_win_count"] == 1
        assert payload["timesfm_win_rate"] == 1.0
        assert payload["best_by_metric"] == {"fallback_rate": "timesfm"}
        assert payload["horizon"] == 2
        assert payload["max_context"] == 64
        assert payload["results"]["fallback_rate"]["point_forecast"] == [0.31, 0.39]
        assert payload["results"]["fallback_rate"]["best_forecaster"] == "timesfm"
        assert payload["results"]["fallback_rate"]["quantile_range_coverage"] == 0.0
        assert round(payload["results"]["fallback_rate"]["mae"]["timesfm"], 6) == 0.01
        assert round(payload["results"]["fallback_rate"]["baseline_comparison"]["last_value"]["relative_improvement"], 6) == round(14 / 15, 6)

    run(scenario())


def test_botapi_timesfm_forecast_route_accepts_explicit_all_metric(tmp_path):
    async def scenario():
        service = RuntimeTimesFMService(
            enabled=True,
            history_path=str(tmp_path / "runtime_history.jsonl"),
            series_loader=lambda path: {"fallback_rate": object(), "block_rate": object()},
            forecaster=lambda series_map, horizon, max_context: {
                metric_name: type(
                    "ForecastResult",
                    (),
                    {
                        "metric_name": metric_name,
                        "horizon": horizon,
                        "context_values": [0.1, 0.2],
                        "target_values": [0.3, 0.4],
                        "point_forecast": [0.31, 0.39],
                        "quantile_forecast": [[0.25, 0.35], [0.35, 0.45]],
                        "last_value_baseline": [0.2, 0.2],
                        "moving_average_baseline": [0.15, 0.15],
                    },
                )()
                for metric_name in series_map
            },
        )
        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {},
            runtime_timesfm_provider=service.forecast_runtime_metrics,
        )

        response = await api.handle_runtime_timesfm_forecast(
            FakeQueryRequest({"metric": "all", "horizon": "2"})
        )
        payload = json.loads(response.text)

        assert response.status == 200
        assert payload["metric"] == "all"
        assert payload["metric_count"] == 2
        assert payload["attempted_metric_count"] == 2
        assert payload["error_count"] == 0
        assert payload["success_rate"] == 1.0
        assert payload["errors"] == {}
        assert sorted(payload["results"]) == ["block_rate", "fallback_rate"]
        assert payload["best_by_metric"] == {"fallback_rate": "timesfm", "block_rate": "timesfm"}

    run(scenario())


def test_botapi_timesfm_forecast_route_keeps_successful_metrics_when_one_fails(tmp_path):
    async def scenario():
        def forecaster(series_map, horizon, max_context):
            metric_name = next(iter(series_map))
            if metric_name == "block_rate":
                raise ValueError("Series 'block_rate' must contain at least 3 points for a holdout split.")
            return {
                metric_name: type(
                    "ForecastResult",
                    (),
                    {
                        "metric_name": metric_name,
                        "horizon": horizon,
                        "context_values": [0.1, 0.2],
                        "target_values": [0.3, 0.4],
                        "point_forecast": [0.31, 0.39],
                        "quantile_forecast": [[0.25, 0.35], [0.35, 0.45]],
                        "last_value_baseline": [0.2, 0.2],
                        "moving_average_baseline": [0.15, 0.15],
                    },
                )()
            }

        service = RuntimeTimesFMService(
            enabled=True,
            history_path=str(tmp_path / "runtime_history.jsonl"),
            series_loader=lambda path: {"fallback_rate": object(), "block_rate": object()},
            forecaster=forecaster,
        )
        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {},
            runtime_timesfm_provider=service.forecast_runtime_metrics,
        )

        response = await api.handle_runtime_timesfm_forecast(
            FakeQueryRequest({"metric": "all", "horizon": "2"})
        )
        payload = json.loads(response.text)

        assert response.status == 200
        assert payload["metric"] == "all"
        assert payload["metric_count"] == 1
        assert payload["attempted_metric_count"] == 2
        assert payload["error_count"] == 1
        assert payload["success_rate"] == 0.5
        assert sorted(payload["results"]) == ["fallback_rate"]
        assert "at least 3 points" in payload["errors"]["block_rate"]
        assert payload["timesfm_win_count"] == 1
        assert payload["timesfm_win_rate"] == 1.0
        assert payload["best_by_metric"] == {"fallback_rate": "timesfm"}

    run(scenario())


def test_botapi_timesfm_forecast_route_returns_structured_payload_when_all_metrics_fail(tmp_path):
    async def scenario():
        service = RuntimeTimesFMService(
            enabled=True,
            history_path=str(tmp_path / "runtime_history.jsonl"),
            series_loader=lambda path: {"fallback_rate": object(), "block_rate": object()},
            forecaster=lambda series_map, horizon, max_context: (_ for _ in ()).throw(ValueError("not enough data")),
        )
        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {},
            runtime_timesfm_provider=service.forecast_runtime_metrics,
        )

        response = await api.handle_runtime_timesfm_forecast(
            FakeQueryRequest({"metric": "all", "horizon": "2"})
        )
        payload = json.loads(response.text)

        assert response.status == 200
        assert payload["metric"] == "all"
        assert payload["metric_count"] == 0
        assert payload["attempted_metric_count"] == 2
        assert payload["error_count"] == 2
        assert payload["success_rate"] == 0.0
        assert payload["results"] == {}
        assert sorted(payload["errors"]) == ["block_rate", "fallback_rate"]

    run(scenario())


def test_botapi_runtime_snapshot_exposes_deduped_combined_rl_ab_summary(tmp_path):
    async def scenario():
        history_store = RuntimeHistoryStore(file_path=str(tmp_path / "runtime_history.jsonl"))
        duplicate_decision = {
            "timestamp": "2026-04-11T12:00:30Z",
            "spot_id": "live:TURN:001",
            "street": "TURN",
            "chosen_action": "CALL",
            "source": "validated_rl",
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
        history_store.append("decisions", duplicate_decision)

        summary_payload = {
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

        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {
                "is_running": True,
                "session_id": "runtime-session-001",
                "canonical_spot": {
                    "spot_id": "live:TURN:001",
                    "street": "TURN",
                    "pot": 14.0,
                    "board": ["As", "Kd", "7h", "2c"],
                    "hero_cards": ["Ah", "Kd"],
                    "players": [],
                    "legal_actions": ["FOLD", "CALL", "BET"],
                    "action_buttons": ["fold_button", "call_button", "bet_button"],
                    "state_confidence": 0.95,
                    "metadata": {"hero_participation": "in_hand"},
                },
                "tracker": {
                    "street": "TURN",
                    "board": ["As", "Kd", "7h", "2c"],
                    "pot": 14.0,
                    "hero_cards": ["Ah", "Kd"],
                    "hero_seat_id": "seat_2",
                    "legal_actions": ["FOLD", "CALL", "BET"],
                    "action_history": [],
                    "state_confidence": 0.95,
                    "in_hand": True,
                },
                "gate": {"allowed": True, "status": "ready", "reason": "ready", "confidence": 1.0},
                "readiness": {"state": "actionable", "score": 0.91, "actionable": True},
                "go_live_gate": {"status": "blocked", "verdict": "no_go", "passed": False},
                "decision": {
                    "action": "CALL",
                    "source": "validated_rl",
                    "warnings": [],
                    "incidents": [],
                },
                "history": {
                    "events": [],
                    "decisions": [dict(duplicate_decision)],
                    "incidents": [],
                    "metrics": [],
                    "persisted": {
                        "events": [],
                        "decisions": history_store.read_recent("decisions", limit=10),
                        "incidents": [],
                        "metrics": [],
                    },
                },
                "history_summary": {
                    "event_count": 0,
                    "decision_count": 1,
                    "incident_count": 0,
                    "metrics_count": 0,
                    "latest_event_at": None,
                    "latest_decision_at": duplicate_decision["timestamp"],
                    "latest_incident_at": None,
                    "latest_metrics_at": None,
                    "rl_ab": {
                        "runtime": dict(summary_payload),
                        "persisted": dict(summary_payload),
                        "combined": dict(summary_payload),
                    },
                    "persistence": history_store.summarize(),
                },
                "metrics": {},
            },
            runtime_history_store=history_store,
        )

        snapshot_response = await api.handle_runtime_snapshot(FakeQueryRequest())
        history_response = await api.handle_runtime_history(
            FakeQueryRequest({"kind": "decisions", "source": "combined", "limit": "5"})
        )

        snapshot_payload = json.loads(snapshot_response.text)
        history_payload = json.loads(history_response.text)

        assert snapshot_response.status == 200
        assert history_response.status == 200
        assert snapshot_payload["runtime"]["session_id"] == "runtime-session-001"
        assert snapshot_payload["runtime"]["canonical_spot"]["spot_id"] == "live:TURN:001"
        assert snapshot_payload["runtime"]["readiness"]["state"] == "actionable"
        assert snapshot_payload["runtime"]["go_live_gate"]["verdict"] == "no_go"
        assert snapshot_payload["canonical_spot"]["spot_id"] == "live:TURN:001"
        assert snapshot_payload["readiness"]["state"] == "actionable"
        assert snapshot_payload["go_live_gate"]["verdict"] == "no_go"
        assert snapshot_payload["decision"]["metadata"]["rl_ab"] == summary_payload
        assert history_payload["summary"]["rl_ab"] == summary_payload
        assert snapshot_payload["decision"]["metadata"]["policy_compare"]["sample_count"] == 1
        assert history_payload["summary"]["policy_compare"]["sample_count"] == 1
        assert history_payload["entries"] == [duplicate_decision]

    run(scenario())
