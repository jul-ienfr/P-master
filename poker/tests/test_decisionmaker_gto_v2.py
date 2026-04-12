"""Focused tests for the V2 bridge inside decisionmaker_gto."""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker.decisionmaker_gto import DecisionGTO, DecisionTypes


class TestDecisionMakerGtoV2(unittest.TestCase):
    def test_builds_v2_snapshots_from_solver_payload(self):
        decision = DecisionGTO.__new__(DecisionGTO)
        decision.t = SimpleNamespace(gameStage="Flop")
        decision.h = None
        decision.p = None
        decision.l = None
        decision.decision = DecisionTypes.bet3
        decision.solve_response_v2 = None
        decision.decision_snapshot_v2 = None
        decision._last_solver_source = "native"

        response = decision._build_solve_response_v2(
            "bet_50",
            {
                "actions": [
                    {"name": "check", "size": 0.0, "frequency": 0.4, "ev": 0.08},
                    {"name": "bet_50", "size": 0.5, "frequency": 0.6, "ev": 0.22},
                ],
                "hero_ev": 0.22,
                "exploitability": 0.05,
                "backend": "native",
                "cache_tier": "memory",
                "decision_confidence": 0.93,
                "cache_hit": True,
                "elapsed_ms": 18,
            },
        )
        decision.solve_response_v2 = response
        decision._record_decision_snapshot("native")

        self.assertEqual(response.chosen_action, "bet_50")
        self.assertEqual(len(response.actions), 2)
        self.assertTrue(response.cache_hit)
        self.assertEqual(response.backend, "native")
        self.assertIsNotNone(decision.decision_snapshot_v2)
        self.assertEqual(decision.decision_snapshot_v2.source, "native")
        self.assertEqual(decision.decision_snapshot_v2.ev_by_action["bet_50"], 0.22)
        self.assertEqual(decision.decision_snapshot_v2.metadata["solver_source"], "native")

    def test_builds_canonical_solve_request_with_action_history(self):
        decision = DecisionGTO.__new__(DecisionGTO)
        decision.spot_snapshot_v2 = SimpleNamespace(
            action_history=("preflop:raise", "flop:check")
        )

        request = decision._build_postflop_solve_request_v2(
            hero_range="AsKd",
            villain_range="QQ+,AK",
            board=["Qh", "7s", "2c"],
            pot_bb=12.5,
            eff_stack_bb=87.5,
            hero_is_oop=False,
            game_stage="Flop",
        )

        self.assertEqual(request.action_history, ("preflop:raise", "flop:check"))
        self.assertEqual(request.hero_position, "ip")
        self.assertEqual(request.tree_preset_id, "srp_hu_100bb")
        self.assertEqual(request.cache_policy.value, "persistent")

        legacy_payload = decision._build_legacy_solver_payload(request)
        self.assertEqual(legacy_payload["ip_range"], "AsKd")
        self.assertEqual(legacy_payload["oop_range"], "QQ+,AK")
        self.assertEqual(legacy_payload["action_history"], ["preflop:raise", "flop:check"])

    def test_extracts_action_from_chosen_action_payload(self):
        decision = DecisionGTO.__new__(DecisionGTO)
        self.assertEqual(
            decision._extract_solver_action({"chosen_action": "bet_50"}),
            "bet_50",
        )

    def test_set_no_action_builds_gate_snapshot(self):
        decision = DecisionGTO.__new__(DecisionGTO)
        decision.solve_request_v2 = SimpleNamespace(tree_preset_id="srp_hu_100bb")
        decision.decision_gate_v2 = None
        decision.solve_response_v2 = None
        decision.decision_snapshot_v2 = None
        decision._last_solver_source = "gate"

        decision._set_no_action("duplicate_cards", warnings=("duplicate_cards",))

        self.assertEqual(decision.decision, "NoAction")
        self.assertEqual(decision.solve_response_v2.fallback_reason, "duplicate_cards")
        self.assertEqual(decision.decision_snapshot_v2.warnings, ("duplicate_cards",))

    def test_build_solve_response_v2_preserves_metadata_parity_for_native_and_http_payloads(self):
        decision = DecisionGTO.__new__(DecisionGTO)
        decision.solve_request_v2 = SimpleNamespace(tree_preset_id="srp_hu_100bb")
        decision._last_solver_source = "native"

        base_payload = {
            "chosen_action": "bet_50",
            "actions": [
                {"name": "bet_50", "size": 0.5, "frequency": 0.7, "ev": 0.3},
            ],
            "hero_ev": 0.3,
            "exploitability": 0.04,
            "cache_tier": "memory",
            "decision_confidence": 0.88,
            "cache_hit": True,
            "elapsed_ms": 17,
            "metadata": {"trace_id": "abc123"},
        }

        native_response = decision._build_solve_response_v2(
            "bet_50",
            {**base_payload, "backend": "native"},
        )
        http_response = decision._build_solve_response_v2(
            "bet_50",
            {**base_payload, "backend": "http"},
        )

        for response in (native_response, http_response):
            self.assertEqual(response.chosen_action, "bet_50")
            self.assertEqual(response.hero_ev, 0.3)
            self.assertEqual(response.exploitability, 0.04)
            self.assertTrue(response.cache_hit)
            self.assertEqual(response.elapsed_ms, 17)
            self.assertEqual(response.decision_confidence, 0.88)
            self.assertEqual(response.metadata["trace_id"], "abc123")
            self.assertEqual(response.metadata["bridge"], "decisionmaker_gto")

        self.assertEqual(native_response.backend, "native")
        self.assertEqual(http_response.backend, "http")

    def test_record_decision_snapshot_uses_cache_and_legacy_bridge_metadata(self):
        decision = DecisionGTO.__new__(DecisionGTO)
        decision.t = SimpleNamespace(gameStage="Turn")
        decision.decision = DecisionTypes.check
        decision.solve_request_v2 = SimpleNamespace(tree_preset_id="srp_hu_100bb")

        decision._last_solver_source = "native"
        decision.solve_response_v2 = decision._build_solve_response_v2(
            "check",
            {
                "recommended_action": "check",
                "hero_ev": 0.2,
                "cache_tier": "disk",
                "elapsed_ms": 11,
            },
        )
        decision._record_decision_snapshot("legacy")

        self.assertEqual(decision.solve_response_v2.backend, "legacy_bridge")
        self.assertEqual(decision.solve_response_v2.metadata["solver_transport"], "native")
        self.assertEqual(decision.decision_snapshot_v2.source, "cache")
        self.assertEqual(decision.decision_snapshot_v2.metadata["solver_source"], "cache")
        self.assertEqual(decision.decision_snapshot_v2.metadata["solver_transport"], "native")

        decision._last_solver_source = "http"
        decision.solve_response_v2 = decision._build_solve_response_v2(
            "",
            {
                "backend": "fallback",
                "fallback_reason": "no_backend_result",
                "warnings": ["fallback_used"],
            },
        )
        decision._record_decision_snapshot("http")

        self.assertEqual(decision.decision_snapshot_v2.source, "fallback")
        self.assertEqual(decision.decision_snapshot_v2.metadata["backend"], "fallback")
        self.assertEqual(decision.decision_snapshot_v2.metadata["fallback_reason"], "no_backend_result")
        self.assertEqual(decision.decision_snapshot_v2.metadata["solver_transport"], "http")
        self.assertEqual(decision.decision_snapshot_v2.warnings, ("fallback_used",))


if __name__ == "__main__":
    unittest.main()
