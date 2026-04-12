"""Tests for the canonical decision service."""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker.decision_service import CanonicalDecisionService
from poker.decisionmaker.tree_presets import build_prewarm_requests
from poker.decisionmaker.v2_contracts import (
    CachePolicy,
    SolveResponseV2,
    SpotSnapshot,
    build_mock_spot_snapshot,
)


class TestDecisionService(unittest.TestCase):
    def test_gate_blocks_duplicate_cards(self):
        service = CanonicalDecisionService()
        spot = SpotSnapshot(
            spot_id="dup",
            source="ocr",
            game_stage="Flop",
            hero_cards=("As", "Kd"),
            board=("As", "7s", "2c"),
            hero_position="BTN",
            legal_actions=("check", "bet"),
            state_confidence=0.98,
        )

        gate = service.evaluate_gate(spot)
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, "duplicate_cards")

    def test_build_solve_request_carries_v2_fields(self):
        service = CanonicalDecisionService()
        spot = build_mock_spot_snapshot()

        request = service.build_solve_request(
            spot,
            "AsKd",
            ("QQ+,AK",),
            hero_position="ip",
            tree_preset_id="srp_hu_100bb",
            rake=0.0,
            num_players=2,
            time_budget_ms=1200,
            cache_policy=CachePolicy.PERSISTENT,
        )

        self.assertEqual(request.spot_id, "mock-spot-001")
        self.assertEqual(request.cache_policy, CachePolicy.PERSISTENT)
        self.assertEqual(request.legal_actions[0].name, "check")
        self.assertGreater(request.state_confidence, 0.9)

    def test_persistent_cache_round_trips_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CanonicalDecisionService(cache_dir=tmpdir)
            request = service.build_solve_request(
                build_mock_spot_snapshot(),
                "AsKd",
                ("QQ+,AK",),
                hero_position="ip",
                tree_preset_id="srp_hu_100bb",
                rake=0.0,
                num_players=2,
                time_budget_ms=1200,
            )
            response = SolveResponseV2(
                chosen_action="bet_50",
                backend="native",
                normalized_ranges=("AsKd", "QQ+,AK"),
                decision_confidence=0.92,
                cache_hit=False,
                elapsed_ms=15,
                preset_id="srp_hu_100bb",
            )
            service.cache.put(request, response)
            cached = service.cache.get(request)

            self.assertIsNotNone(cached)
            self.assertTrue(cached.cache_hit)
            self.assertEqual(cached.cache_tier.value, "disk")
            self.assertEqual(cached.chosen_action, "bet_50")

    def test_gate_blocks_temporal_hero_card_change(self):
        service = CanonicalDecisionService()
        first_spot = build_mock_spot_snapshot()
        second_spot = SpotSnapshot.from_dict(
            {
                **first_spot.to_dict(),
                "hero_cards": ("Ac", "Kh"),
            }
        )

        first_gate = service.evaluate_gate(first_spot)
        second_gate = service.evaluate_gate(second_spot)

        self.assertTrue(first_gate.allowed)
        self.assertFalse(second_gate.allowed)
        self.assertEqual(second_gate.reason, "hero_cards_changed_recently")

    def test_prewarm_requests_cover_catalog(self):
        requests = build_prewarm_requests(["srp_hu_100bb", "turn_probe_hu"])
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.cache_policy.value == "persistent" for request in requests))

    def test_solve_request_prefers_native_and_skips_http_when_native_returns_result(self):
        service = CanonicalDecisionService()
        request = service.build_solve_request(
            build_mock_spot_snapshot(),
            "AsKd",
            ("QQ+,AK",),
            hero_position="ip",
            tree_preset_id="srp_hu_100bb",
            rake=0.0,
            num_players=2,
            time_budget_ms=1200,
            cache_policy=CachePolicy.MEMORY,
        )
        calls: list[str] = []

        def native_solver(_request):
            calls.append("native")
            return {
                "chosen_action": "bet_50",
                "backend": "native",
                "decision_confidence": 0.91,
                "cache_hit": True,
                "elapsed_ms": 12,
            }

        def http_solver(_request):
            calls.append("http")
            return {"chosen_action": "check", "backend": "http"}

        response = service.solve_request(request, native_solver, http_solver)

        self.assertEqual(calls, ["native"])
        self.assertEqual(response.chosen_action, "bet_50")
        self.assertEqual(response.backend, "native")
        self.assertTrue(response.cache_hit)
        self.assertEqual(response.cache_tier.value, "memory")
        self.assertEqual(response.fallback_reason, "")

    def test_solve_request_uses_http_then_explicit_fallback_when_needed(self):
        service = CanonicalDecisionService()
        request = service.build_solve_request(
            build_mock_spot_snapshot(),
            "AsKd",
            ("QQ+,AK",),
            hero_position="ip",
            tree_preset_id="srp_hu_100bb",
            rake=0.0,
            num_players=2,
            time_budget_ms=1200,
            cache_policy=CachePolicy.MEMORY,
        )

        with self.subTest("http_success"):
            calls: list[str] = []

            def native_solver(_request):
                calls.append("native")
                return None

            def http_solver(_request):
                calls.append("http")
                return {
                    "chosen_action": "check",
                    "backend": "http",
                    "decision_confidence": 0.83,
                    "elapsed_ms": 21,
                    "metadata": {"transport": "local_http"},
                }

            response = service.solve_request(request, native_solver, http_solver)

            self.assertEqual(calls, ["native", "http"])
            self.assertEqual(response.backend, "http")
            self.assertEqual(response.chosen_action, "check")
            self.assertEqual(response.decision_confidence, 0.83)
            self.assertEqual(response.metadata["transport"], "local_http")
            self.assertEqual(response.fallback_reason, "")

        with self.subTest("fallback"):
            calls = []

            def native_solver_none(_request):
                calls.append("native")
                return None

            def http_solver_none(_request):
                calls.append("http")
                return None

            response = service.solve_request(request, native_solver_none, http_solver_none)

            self.assertEqual(calls, ["native", "http"])
            self.assertEqual(response.backend, "fallback")
            self.assertEqual(response.chosen_action, "")
            self.assertEqual(response.fallback_reason, "no_backend_result")
            self.assertEqual(response.warnings, ("fallback_used",))
            self.assertEqual(response.decision_confidence, 0.0)

    def test_gate_allows_stable_board_progression_with_consistent_actions(self):
        service = CanonicalDecisionService()
        flop = SpotSnapshot(
            spot_id="stable-seq",
            source="ocr",
            game_stage="Flop",
            hero_cards=("As", "Kd"),
            board=("7h", "8d", "Qc"),
            hero_position="BTN",
            pot=6.0,
            stack=94.0,
            legal_actions=("check", "bet"),
            state_confidence=0.91,
        )
        turn = SpotSnapshot(
            spot_id="stable-seq",
            source="ocr",
            game_stage="Turn",
            hero_cards=("As", "Kd"),
            board=("7h", "8d", "Qc", "2s"),
            hero_position="BTN",
            pot=10.5,
            stack=91.0,
            legal_actions=("check", "bet"),
            state_confidence=0.9,
        )

        first_gate = service.evaluate_gate(flop)
        second_gate = service.evaluate_gate(turn)

        self.assertTrue(first_gate.allowed)
        self.assertTrue(second_gate.allowed)
        self.assertEqual(second_gate.reason, "ready")
        self.assertEqual(second_gate.metadata["previous_board_len"], 3)
        self.assertEqual(second_gate.metadata["current_board_len"], 4)
        self.assertEqual(second_gate.metadata["temporal_warning_count"], 0)
        self.assertFalse(second_gate.metadata["blocked"])

    def test_gate_blocks_unstable_recent_frames_when_temporal_warning_and_low_confidence_overlap(self):
        service = CanonicalDecisionService()
        baseline = SpotSnapshot(
            spot_id="unstable-seq",
            source="ocr",
            game_stage="Flop",
            hero_cards=("As", "Kd"),
            board=("7h", "8d", "Qc"),
            hero_position="BTN",
            pot=6.0,
            stack=94.0,
            legal_actions=("check", "bet"),
            state_confidence=0.88,
        )
        noisy = SpotSnapshot(
            spot_id="unstable-seq",
            source="ocr",
            game_stage="Flop",
            hero_cards=("As", "Kd"),
            board=("7h", "8d", "Qc"),
            hero_position="BTN",
            pot=20.0,
            stack=94.0,
            legal_actions=("check", "bet"),
            state_confidence=0.63,
        )

        first_gate = service.evaluate_gate(baseline)
        second_gate = service.evaluate_gate(noisy)

        self.assertTrue(first_gate.allowed)
        self.assertFalse(second_gate.allowed)
        self.assertEqual(second_gate.reason, "unstable_recent_frames")
        self.assertIn("unstable_pot_recently", second_gate.warnings)
        self.assertIn("unstable_recent_frames", second_gate.warnings)
        self.assertEqual(second_gate.metadata["temporal_warning_count"], 1)
        self.assertTrue(second_gate.metadata["blocked"])
        self.assertEqual(second_gate.metadata["decision_stage"], "Flop")

    def test_gate_blocks_disjoint_legal_actions_with_explicit_temporal_reason(self):
        service = CanonicalDecisionService()
        previous = SpotSnapshot(
            spot_id="legal-shift",
            source="ocr",
            game_stage="Turn",
            hero_cards=("As", "Kd"),
            board=("7h", "8d", "Qc", "2s"),
            hero_position="BTN",
            pot=10.0,
            stack=88.0,
            legal_actions=("check", "bet"),
            state_confidence=0.92,
        )
        current = SpotSnapshot(
            spot_id="legal-shift",
            source="ocr",
            game_stage="Turn",
            hero_cards=("As", "Kd"),
            board=("7h", "8d", "Qc", "2s"),
            hero_position="BTN",
            pot=10.5,
            stack=86.0,
            legal_actions=("fold", "call"),
            state_confidence=0.95,
        )

        service.evaluate_gate(previous)
        gate = service.evaluate_gate(current)

        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, "legal_actions_changed_recently")
        self.assertIn("legal_actions_changed_recently", gate.warnings)
        self.assertEqual(gate.metadata["temporal_reason"], "legal_actions_changed_recently")
        self.assertEqual(gate.metadata["previous_legal_actions"], "check,bet")
        self.assertEqual(gate.metadata["current_legal_actions"], "fold,call")


if __name__ == "__main__":
    unittest.main()
