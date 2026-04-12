"""Tests for the local REST API V2 helpers and routes."""

from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.restapi_local import (
    app,
    build_config_lab_payload,
    build_health_payload,
    build_mock_config_payload,
    build_research_lab_payload,
    build_solver_inspection_payload,
    build_runtime_snapshot,
    build_version_payload,
    get_bot_cockpit_payload,
    get_config_lab_payload,
    get_research_payload,
    get_solver_cache_index,
    get_solver_preset_catalog,
    post_solve_legacy,
    post_llm_assist,
    post_v2_solve,
    get_replay_analytics_payload,
    refresh_bot_cockpit_payload,
    refresh_config_lab_payload,
    refresh_research_payload,
    refresh_replay_analytics_payload,
)


class TestRestApiLocalV2(unittest.TestCase):
    def test_health_payload_is_ready_without_llm(self):
        payload = build_health_payload()
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["llm_enabled"])
        self.assertEqual(payload["api_version"], "v2")

    def test_version_payload_contains_runtime_info(self):
        payload = build_version_payload()
        self.assertEqual(payload["service"], "poker-restapi-local")
        self.assertEqual(payload["api_version"], "v2")
        self.assertTrue(payload["python_version"])

    def test_mock_config_payload_disables_llm_by_default(self):
        payload = build_mock_config_payload()
        self.assertFalse(payload["llm_config"]["enabled"])
        self.assertEqual(payload["llm_config"]["provider_mode"], "disabled")
        self.assertIn("spot_snapshot", payload)
        self.assertIn("decision_snapshot", payload)
        self.assertIn("replay_analytics", payload)
        self.assertIn("config_lab", payload)

    def test_config_lab_payload_enriches_research_and_inspection(self):
        payload = build_config_lab_payload()
        self.assertIn("solver_inspection", payload)
        self.assertIn("research", payload)
        self.assertTrue(payload["solver"]["availablePresetIds"])

    def test_runtime_snapshot_contains_samples(self):
        payload = build_runtime_snapshot()
        self.assertEqual(payload["service"], "poker-restapi-local")
        self.assertIn("samples", payload)
        self.assertFalse(payload["llm"]["enabled"])
        self.assertIn("replay_analytics", payload["samples"])
        self.assertIn("config_lab", payload["samples"])

    def test_routes_are_registered(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/health", paths)
        self.assertIn("/version", paths)
        self.assertIn("/mock-config", paths)
        self.assertIn("/v2/llm/assist", paths)
        self.assertIn("/v2/solve", paths)
        self.assertIn("/solve", paths)
        self.assertIn("/runtime-snapshot", paths)
        self.assertIn("/solver-studio/preset-catalog", paths)
        self.assertIn("/solver-studio/cache-index", paths)
        self.assertIn("/bot-cockpit/payload", paths)
        self.assertIn("/bot-cockpit/refresh", paths)
        self.assertIn("/replay-analytics/payload", paths)
        self.assertIn("/replay-analytics/refresh", paths)
        self.assertIn("/config-lab/payload", paths)
        self.assertIn("/config-lab/refresh", paths)
        self.assertIn("/research/payload", paths)
        self.assertIn("/research/refresh", paths)
        self.assertIn("/get_computer_name", paths)
        self.assertIn("/take_screenshot", paths)

    def test_replay_analytics_endpoint_contract(self):
        payload = asyncio.run(get_replay_analytics_payload())
        self.assertEqual(payload["kind"], "replay_analytics")
        self.assertIn("summary", payload)
        self.assertIn("highlights", payload)
        self.assertIn("filters", payload)

        refreshed = asyncio.run(refresh_replay_analytics_payload())
        self.assertEqual(refreshed["status"], "ok")
        self.assertEqual(refreshed["payload"]["kind"], "replay_analytics")

    def test_config_lab_endpoint_contract(self):
        payload = asyncio.run(get_config_lab_payload())
        self.assertEqual(payload["kind"], "config_lab")
        self.assertIn("llm", payload)
        self.assertIn("solver", payload)
        self.assertIn("benchmarks", payload)
        self.assertIn("privacy", payload)
        self.assertIn("solver_inspection", payload)
        self.assertIn("research", payload)

        refreshed = asyncio.run(refresh_config_lab_payload())
        self.assertEqual(refreshed["status"], "ok")
        self.assertEqual(refreshed["payload"]["kind"], "config_lab")

    def test_solver_inspection_endpoint_contract(self):
        payload = build_solver_inspection_payload()
        self.assertEqual(payload["kind"], "solver_inspection")
        self.assertIn("preset_catalog", payload)
        self.assertIn("cache_entries", payload)

        route_payload = asyncio.run(get_solver_preset_catalog())
        self.assertEqual(route_payload["kind"], "solver_inspection")

        cache_payload = asyncio.run(get_solver_cache_index())
        self.assertEqual(cache_payload["kind"], "solver_inspection")

    def test_research_lab_endpoint_contract(self):
        payload = build_research_lab_payload()
        self.assertEqual(payload["kind"], "research_lab")
        self.assertIn("calibration", payload)
        self.assertIn("challengers", payload)
        self.assertIn("head_to_head", payload)
        self.assertIn("local_best_response", payload)
        self.assertIn("opponent_dataset", payload)
        self.assertIn("postflop_bridge", payload)
        self.assertIn("validation", payload)
        self.assertIn("rl_lab", payload)
        self.assertIn("automation", payload)

        route_payload = asyncio.run(get_research_payload())
        self.assertEqual(route_payload["kind"], "research_lab")

        refreshed = asyncio.run(refresh_research_payload())
        self.assertEqual(refreshed["status"], "ok")
        self.assertEqual(refreshed["payload"]["kind"], "research_lab")

    def test_bot_cockpit_endpoint_contract(self):
        payload = asyncio.run(get_bot_cockpit_payload())
        self.assertEqual(payload["state"], "live")
        self.assertIn("spot", payload)
        self.assertIn("decision", payload)
        self.assertIn("ocr", payload)
        self.assertIn("operator", payload)

        refreshed = asyncio.run(refresh_bot_cockpit_payload())
        self.assertEqual(refreshed["status"], "ok")
        self.assertEqual(refreshed["payload"]["state"], "live")

    def test_llm_assist_endpoint_contract(self):
        payload = asyncio.run(
            post_llm_assist({"task": "spot_explain", "context_summary": "Explain this spot"})
        )
        self.assertIn("summary", payload)
        self.assertIn("recommendations", payload)
        self.assertEqual(payload["provider_metadata"]["source"], "local_rest_mock")

    def test_v2_solve_endpoint_contract(self):
        payload = asyncio.run(
            post_v2_solve(
                {
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
        )
        self.assertEqual(payload["chosen_action"], "bet_50")
        self.assertEqual(payload["recommended_action"], "bet_50")
        self.assertIn("actions", payload)
        self.assertTrue(payload["cache_hit"])

    def test_legacy_solve_endpoint_contract(self):
        payload = asyncio.run(
            post_solve_legacy(
                {
                    "oop_range": "AsKd",
                    "ip_range": "QQ+,AK",
                    "board": ["Qh", "7s", "2c"],
                    "starting_pot": 12.5,
                    "effective_stack": 87.5,
                    "hero_is_oop": False,
                }
            )
        )
        self.assertIn(payload["chosen_action"], {"check", "bet_50", "bet_75", "call"})
        self.assertIn("actions", payload)


if __name__ == "__main__":
    unittest.main()
