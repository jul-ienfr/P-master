"""Tests for offline research helpers."""

from __future__ import annotations

from dataclasses import replace
import pathlib
import json
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from research.automation import build_automation_payload
from poker.decisionmaker.v2_contracts import build_mock_replay_record
from research.calibration import benchmark_range_model_versions, fit_calibration_profile
from research.challengers import challenger_payload, challenger_registry, load_challenger
from research.opponent_datasets import build_opponent_dataset
from research.postflop_vendor import build_postflop_bundle, summarize_postflop_bundle
from research.policy_compare import build_policy_compare_summary, load_policy_compare_corpus
from research.rl_lab import build_rl_lab_payload, run_policy_round_robin
from research.self_play import (
    BestAlternativePolicy,
    ReplayDecisionPolicy,
    estimate_local_best_response,
    run_head_to_head,
)
from research.validation import build_validation_lab_payload, run_oracle_conformance_suite


class TestResearchLab(unittest.TestCase):
    def test_policy_compare_summary_supports_corpus_and_decision_fixture_inputs(self):
        fixtures_dir = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures"
        records = load_policy_compare_corpus(
            [
                fixtures_dir / "policy_compare_sample_corpus.json",
                fixtures_dir / "decision_replay_validated_rl.json",
            ]
        )

        summary = build_policy_compare_summary(
            records,
            baseline_policy="gto_solver",
            challenger_policy="rl_validated",
        )

        self.assertEqual(summary["kind"], "policy_compare_summary")
        self.assertIn("gto_solver", summary["available_policies"])
        self.assertIn("rl_validated", summary["available_policies"])
        matchup = summary["pairwise"][0]
        self.assertEqual(matchup["baseline_policy"], "gto_solver")
        self.assertEqual(matchup["challenger_policy"], "rl_validated")
        self.assertEqual(matchup["comparable_records"], 4)
        self.assertEqual(matchup["agreements"], 0)
        self.assertGreaterEqual(matchup["disagreements"], 1)
        self.assertGreaterEqual(len(matchup["differing_samples"]), 1)

    def test_policy_compare_summary_supports_runtime_replay_bundle_inputs(self):
        runtime_bundle_path = pathlib.Path(self._testMethodName + ".json")
        try:
            runtime_bundle_path.write_text(
                json.dumps(
                    {
                        "format": "runtime_history_v1",
                        "bundle": {
                            "kind": "runtime_replay_bundle",
                            "runtime": {
                                "canonical_spot": {
                                    "spot_id": "live:PREFLOP:001",
                                    "street": "PREFLOP",
                                    "pot": 5.5,
                                    "board": [],
                                    "hero_cards": ["Ah", "Kd"],
                                    "players": [
                                        {
                                            "seat_id": "hero",
                                            "stack": 100.0,
                                            "is_hero": True,
                                        }
                                    ],
                                    "legal_actions": ["FOLD", "CALL", "BET"],
                                    "metadata": {"hero_seat_id": "btn"},
                                    "state_confidence": 0.91,
                                }
                            },
                            "records": [
                                {
                                    "stream": "decisions",
                                    "timestamp": "2026-04-11T12:00:01Z",
                                    "spot_id": "live:PREFLOP:001",
                                    "street": "PREFLOP",
                                    "hero_cards": ["Ah", "Kd"],
                                    "board": [],
                                    "pot": 5.5,
                                    "legal_actions": ["FOLD", "CALL", "BET"],
                                    "action_history": ["open_2.5x"],
                                    "chosen_action": "CALL",
                                    "source": "validated_rl",
                                },
                                {
                                    "stream": "decisions",
                                    "timestamp": "2026-04-11T12:00:02Z",
                                    "spot_id": "live:PREFLOP:002",
                                    "street": "PREFLOP",
                                    "hero_cards": ["Qs", "Qc"],
                                    "board": [],
                                    "pot": 6.0,
                                    "legal_actions": ["FOLD", "CALL", "BET"],
                                    "action_history": ["open_2.5x"],
                                    "chosen_action": "BET",
                                    "source": "gto_solver",
                                },
                            ],
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            records = load_policy_compare_corpus([runtime_bundle_path])

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].policy_actions, {"validated_rl": "CALL"})
            self.assertEqual(records[0].spot.hero_position, "btn")
            self.assertEqual(records[0].spot.legal_actions, ("FOLD", "CALL", "BET"))

            summary = build_policy_compare_summary(records)

            self.assertIn("validated_rl", summary["available_policies"])
            self.assertIn("gto_solver", summary["available_policies"])
        finally:
            runtime_bundle_path.unlink(missing_ok=True)

    def test_policy_compare_summary_supports_multi_session_runtime_corpus_batches(self):
        runtime_batch_path = pathlib.Path(self._testMethodName + ".json")
        try:
            runtime_batch_path.write_text(
                json.dumps(
                    {
                        "kind": "policy_compare_corpus_batch",
                        "sessions": [
                            {
                                "session_id": "backup_legacy",
                                "records": [
                                    {
                                        "replay_id": "live:PREFLOP:001",
                                        "spot": {
                                            "spot_id": "live:PREFLOP:001",
                                            "source": "runtime_replay_bundle",
                                            "game_stage": "preflop",
                                            "hero_cards": ["Ah", "Kd"],
                                            "board": [],
                                            "hero_position": "btn",
                                            "pot": 5.5,
                                            "stack": 100.0,
                                            "legal_actions": ["FOLD", "CALL", "BET"],
                                        },
                                        "policy_actions": {"gto_solver": "FOLD"},
                                        "metadata": {"session_id": "backup_legacy"},
                                    }
                                ],
                            },
                            {
                                "session_id": "current",
                                "records": [
                                    {
                                        "replay_id": "live:PREFLOP:002",
                                        "spot": {
                                            "spot_id": "live:PREFLOP:002",
                                            "source": "runtime_replay_bundle",
                                            "game_stage": "preflop",
                                            "hero_cards": ["Qs", "Qc"],
                                            "board": [],
                                            "hero_position": "btn",
                                            "pot": 6.0,
                                            "stack": 100.0,
                                            "legal_actions": ["FOLD", "CALL", "BET"],
                                        },
                                        "policy_actions": {"validated_rl": "BET"},
                                        "metadata": {"session_id": "current"},
                                    }
                                ],
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            records = load_policy_compare_corpus([runtime_batch_path])

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].metadata["session_id"], "backup_legacy")
            self.assertEqual(records[1].metadata["session_id"], "current")

            summary = build_policy_compare_summary(records)

            self.assertIn("validated_rl", summary["available_policies"])
            self.assertIn("gto_solver", summary["available_policies"])
        finally:
            runtime_batch_path.unlink(missing_ok=True)

    def test_calibration_profile_has_diagnostics(self):
        profile = fit_calibration_profile([build_mock_replay_record()])
        self.assertEqual(profile["version"], "calibrated_v3")
        self.assertIn("diagnostics", profile)
        self.assertTrue(profile["multipliers"])
        self.assertIn("diagnostics_by_profile", profile)
        self.assertTrue(all(":" in key and key.count(":") == 1 for key in profile["multipliers"]))

    def test_calibration_profile_softens_low_confidence_low_sample_signals(self):
        baseline = build_mock_replay_record()
        records = [
            replace(
                baseline,
                result_metadata={"result_bb": 2.2},
                decision=replace(baseline.decision, action="bet", confidence=0.3),
            ),
            replace(
                baseline,
                replay_id="mock-replay-002",
                result_metadata={"result_bb": 1.8},
                decision=replace(baseline.decision, action="bet", confidence=0.4),
            ),
        ]
        profile = fit_calibration_profile(records)

        self.assertIn("flop:bet", profile["multipliers"])
        self.assertGreater(profile["multipliers"]["flop:bet"], 1.0)
        self.assertLess(profile["multipliers"]["flop:bet"], 1.1)

    def test_head_to_head_and_lbr_return_metrics(self):
        records = [build_mock_replay_record()]
        duel = run_head_to_head(
            records,
            baseline=ReplayDecisionPolicy(name="baseline"),
            challenger=BestAlternativePolicy(name="best_alt"),
        )
        self.assertIn("challenger_beats_baseline", duel)
        self.assertIn("ev_delta", duel)
        self.assertIn("avg_ev_delta", duel)

        lbr = estimate_local_best_response(
            records,
            policy=ReplayDecisionPolicy(name="baseline"),
        )
        self.assertIn("average_gap", lbr)

    def test_opponent_dataset_and_version_benchmark_are_populated(self):
        records = [build_mock_replay_record()]
        dataset = build_opponent_dataset(records)
        self.assertEqual(len(dataset), 1)
        self.assertEqual(dataset[0]["spot_id"], "mock-spot-001")

        benchmarks = benchmark_range_model_versions(records)
        self.assertEqual(benchmarks[-1]["model_version"], "calibrated_v3")
        self.assertEqual([item["model_version"] for item in benchmarks], ["heuristic_v1", "board_aware_v2", "calibrated_v3"])
        self.assertTrue(all("records" in item and "positive_rate" in item and "promotion_reason" in item for item in benchmarks))

    def test_challenger_registry_lists_expected_entries(self):
        registry = challenger_registry()
        ids = {entry["id"] for entry in registry}
        self.assertIn("rlcard", ids)
        self.assertIn("pokerkit", ids)

    def test_challenger_payload_and_loader_return_runtime_metadata(self):
        payload = challenger_payload()
        self.assertTrue(payload)
        self.assertIn("sample_payload", payload[0])

        rlcard = load_challenger("rlcard")
        self.assertIn("factory_hint", rlcard)
        self.assertIn("capabilities", rlcard)

    def test_postflop_bundle_and_validation_payload_are_structured(self):
        bundle = build_postflop_bundle("desktop-postflop")
        self.assertEqual(bundle["target"], "desktop-postflop")
        self.assertTrue(bundle["presets"])

        summary = summarize_postflop_bundle()
        self.assertIn("files", summary)
        self.assertGreaterEqual(summary["preset_count"], 1)
        self.assertTrue(any(item["exists"] for item in summary["files"]))

        validation = build_validation_lab_payload([build_mock_replay_record()])
        self.assertIn("oracle_conformance", validation)
        self.assertIn("replay_validation", validation)

        oracle_suite = run_oracle_conformance_suite()
        self.assertEqual(oracle_suite["kind"], "oracle_conformance")
        self.assertIn("summary", oracle_suite)

    def test_rl_lab_and_automation_payloads_are_structured(self):
        records = [build_mock_replay_record()]
        tournament = run_policy_round_robin(records)
        self.assertEqual(tournament["kind"], "round_robin")
        self.assertTrue(tournament["standings"])

        rl_lab = build_rl_lab_payload(records)
        self.assertEqual(rl_lab["kind"], "rl_lab")
        self.assertIn("tournament", rl_lab)
        self.assertIn("challenger_smoke", rl_lab)

        automation = build_automation_payload()
        self.assertEqual(automation["kind"], "automation")
        self.assertIn("artifacts", automation)
        self.assertGreaterEqual(len(automation["artifacts"]), 3)


if __name__ == "__main__":
    unittest.main()
