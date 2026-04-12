"""Tests for the PokerMaster V2 Python bridge contracts."""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker.v2_contracts import (
    ActionEstimate,
    CachePolicy,
    CacheTier,
    DecisionSnapshot,
    DecisionGateResult,
    LlmAssistResponse,
    LlmAssistTask,
    LlmAssistTaskType,
    LlmConfig,
    LlmProviderMode,
    OcrConfidenceReport,
    RangeModelVersion,
    ReplayRecord,
    SolveRequestV2,
    SolveResponseV2,
    SpotSnapshot,
    BenchmarkResult,
    build_mock_benchmark_result,
    build_default_llm_config,
    build_mock_decision_snapshot,
    build_mock_gate_result,
    build_mock_solve_response_payload,
    build_mock_llm_task,
    build_mock_replay_record,
    build_mock_spot_snapshot,
    build_runtime_snapshot,
)


class TestV2Contracts(unittest.TestCase):
    def test_llm_config_defaults_are_disabled(self):
        config = build_default_llm_config()
        self.assertFalse(config.enabled)
        self.assertEqual(config.provider_mode, LlmProviderMode.DISABLED)
        self.assertEqual(config.privacy_mode, "strict_local")
        self.assertFalse(config.roles_enabled["analysis"])
        self.assertFalse(config.context_scopes_enabled["spot"])

    def test_spot_snapshot_roundtrip(self):
        spot = SpotSnapshot(
            spot_id="spot-1",
            source="live",
            game_stage="Turn",
            hero_cards=("As", "Kd"),
            board=("Qh", "7s", "2c", "9d"),
            hero_position="BTN",
            positions={"hero": "BTN", "villain": "BB"},
            pot=17.5,
            stack=82.5,
            legal_actions=("check", "bet", "fold"),
            action_history=("preflop:raise", "flop:check"),
            hero_range="AsKd",
            villain_ranges=("22+,A2s+",),
            state_confidence=0.96,
            ocr_confidence=OcrConfidenceReport(overall=0.96, hero_cards=1.0, board=0.9),
            range_model_version=RangeModelVersion.CALIBRATED_V3,
            ocr_metadata={"confidence": 0.97},
            metadata={"table": "alpha"},
        )
        restored = SpotSnapshot.from_dict(spot.to_dict())
        self.assertEqual(restored.spot_id, "spot-1")
        self.assertEqual(restored.hero_cards, ("As", "Kd"))
        self.assertEqual(restored.board, ("Qh", "7s", "2c", "9d"))
        self.assertEqual(restored.legal_actions, ("check", "bet", "fold"))
        self.assertEqual(restored.metadata["table"], "alpha")
        self.assertEqual(SpotSnapshot.from_json(spot.to_json()).hero_position, "BTN")

    def test_decision_snapshot_roundtrip(self):
        decision = DecisionSnapshot(
            action="bet",
            alternatives=(
                ActionEstimate(name="check", size=0.0, frequency=0.4, ev=0.08),
                ActionEstimate(name="bet", size=0.5, frequency=0.6, ev=0.22),
            ),
            ev_by_action={"check": 0.08, "bet": 0.22},
            exploitability=0.05,
            source="native",
            warnings=("low_confidence",),
            latency_ms=14,
            confidence=0.88,
            gate_result=DecisionGateResult(allowed=False, confidence=0.42, reason="low_state_confidence"),
            metadata={"backend": "rust"},
        )
        restored = DecisionSnapshot.from_dict(json.loads(decision.to_json()))
        self.assertEqual(restored.action, "bet")
        self.assertEqual(restored.alternatives[1].name, "bet")
        self.assertEqual(restored.ev_by_action["check"], 0.08)
        self.assertEqual(restored.warnings, ("low_confidence",))
        self.assertEqual(restored.gate_result.reason, "low_state_confidence")

    def test_solve_request_and_response_roundtrip(self):
        request = SolveRequestV2(
            spot_id="spot-2",
            hero_range="AsKd",
            villain_ranges=("22+,A2s+",),
            board=("Qh", "7s", "2c"),
            starting_pot=12.5,
            effective_stack=87.5,
            hero_position="BTN",
            action_history=("preflop:raise",),
            tree_preset_id="srp_hu_100bb",
            rake=0.05,
            num_players=2,
            cache_policy=CachePolicy.PERSISTENT,
            hero_confidence=1.0,
            state_confidence=0.93,
            range_model_version=RangeModelVersion.CALIBRATED_V3,
            use_cache=True,
            time_budget_ms=1500,
            metadata={"surface": "solver_studio"},
        )
        response = SolveResponseV2(
            chosen_action="bet",
            actions=(ActionEstimate(name="bet", size=0.5, frequency=0.6, ev=0.22),),
            hero_ev=0.22,
            exploitability=0.05,
            backend="native",
            cache_tier=CacheTier.MEMORY,
            normalized_ranges=("AsKd", "22+,A2s+"),
            decision_confidence=0.91,
            fallback_reason="",
            cache_hit=True,
            elapsed_ms=42,
            preset_id="srp_hu_100bb",
            warnings=("mock",),
            metadata={"backend": "native"},
        )
        self.assertEqual(SolveRequestV2.from_dict(request.to_dict()).spot_id, "spot-2")
        self.assertEqual(SolveRequestV2.from_dict(request.to_dict()).tree_preset_id, "srp_hu_100bb")
        restored = SolveResponseV2.from_dict(response.to_dict())
        self.assertEqual(restored.chosen_action, "bet")
        self.assertEqual(restored.cache_tier, CacheTier.MEMORY)
        self.assertEqual(restored.normalized_ranges[0], "AsKd")

    def test_solve_response_accepts_legacy_and_camelcase_keys(self):
        response = SolveResponseV2.from_dict(
            {
                "recommended_action": "bet_50",
                "actions": [{"name": "bet_50", "size": 0.5, "frequency": 0.7, "ev": 0.33}],
                "heroEv": 0.33,
                "cacheTier": "disk",
                "decisionConfidence": 0.83,
                "cacheHit": True,
                "elapsedMs": 28,
                "presetId": "srp_hu_100bb",
            }
        )
        self.assertEqual(response.chosen_action, "bet_50")
        self.assertTrue(response.cache_hit)
        self.assertEqual(response.elapsed_ms, 28)
        self.assertEqual(response.cache_tier, CacheTier.DISK)

    def test_llm_task_and_response_roundtrip(self):
        task = build_mock_llm_task()
        response = LlmAssistResponse(
            summary="The solver prefers betting for value and protection.",
            recommendations=("Keep the line compact.", "Review turn probe ranges."),
            warnings=("consultative_only",),
            confidence=0.81,
            used_context=("solver_studio", "spot_explain"),
            latency_ms=120,
            provider_metadata={"provider": "openai-compatible"},
            raw_text="mock response",
            metadata={"model": "test"},
        )
        restored_task = LlmAssistTask.from_dict(task.to_dict())
        restored_response = LlmAssistResponse.from_dict(response.to_dict())
        self.assertEqual(restored_task.task_type, LlmAssistTaskType.SPOT_EXPLAIN)
        self.assertEqual(restored_task.spot.hero_cards, ("As", "Kd"))
        self.assertEqual(restored_response.recommendations[0], "Keep the line compact.")
        self.assertEqual(restored_response.used_context[0], "solver_studio")
        self.assertEqual(restored_response.provider_metadata["provider"], "openai-compatible")

    def test_runtime_snapshot_is_llm_optional(self):
        snapshot = build_runtime_snapshot()
        self.assertEqual(snapshot["api_version"], "v2")
        self.assertFalse(snapshot["llm"]["enabled"])
        self.assertEqual(snapshot["samples"]["llm_config"]["provider_mode"], "disabled")
        self.assertIn("spot_snapshot", snapshot["samples"])

    def test_llm_config_accepts_surface_arrays(self):
        config = LlmConfig.from_dict(
            {
                "enabled": True,
                "providerMode": "openai_compatible_local",
                "rolesEnabled": ["analysis", "operator_assistance"],
                "contextScopesEnabled": ["spot", "decision"],
            }
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.provider_mode, LlmProviderMode.OPENAI_COMPATIBLE_LOCAL)
        self.assertTrue(config.roles_enabled["analysis"])
        self.assertTrue(config.context_scopes_enabled["spot"])

    def test_mock_solve_payload_is_structured(self):
        payload = build_mock_solve_response_payload(
            {
                "spot_id": "spot-3",
                "hero_range": "AsKd",
                "villain_ranges": ["QQ+,AK"],
                "board": ["Qh", "7s", "2c"],
                "starting_pot": 12.5,
                "effective_stack": 87.5,
                "hero_position": "ip",
                "tree_preset_id": "srp_hu_100bb",
                "num_players": 2,
                "use_cache": True,
            }
        )
        self.assertEqual(payload["chosen_action"], "bet_50")
        self.assertEqual(payload["recommended_action"], "bet_50")
        self.assertTrue(payload["cache_hit"])
        self.assertEqual(payload["cache_tier"], "memory")
        self.assertIn("actions", payload)

    def test_replay_and_benchmark_helpers_roundtrip(self):
        replay = build_mock_replay_record()
        benchmark = build_mock_benchmark_result()
        self.assertEqual(ReplayRecord.from_dict(replay.to_dict()).replay_id, "mock-replay-001")
        self.assertTrue(BenchmarkResult.from_dict(benchmark.to_dict()).passed)

    def test_runtime_snapshot_exposes_new_samples(self):
        snapshot = build_runtime_snapshot()
        self.assertIn("decision_gate", snapshot["samples"])
        self.assertIn("benchmark_result", snapshot["samples"])
        self.assertEqual(snapshot["samples"]["decision_gate"]["reason"], "ready")


if __name__ == "__main__":
    unittest.main()
