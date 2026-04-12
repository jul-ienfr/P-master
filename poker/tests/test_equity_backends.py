"""Tests for equity backend selection helpers."""

from __future__ import annotations

import pathlib
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker.equity_backends import (
    build_equity_plan,
    normalize_equity_response,
    select_equity_backend,
)


class TestEquityBackends(unittest.TestCase):
    def test_turn_single_range_prefers_exact(self):
        backend, mode = select_equity_backend(["Qh", "7s", "2c", "9d"], ["QQ+,AK"])
        self.assertEqual(backend.value, "rust_exact")
        self.assertEqual(mode, "exact")

    def test_normalize_equity_response_sets_backend_fields(self):
        normalized = normalize_equity_response({"equity": 0.5, "cache_hit": True}, backend=select_equity_backend([], [])[0])
        self.assertIn("backend", normalized)
        self.assertEqual(normalized["cache_tier"], "memory")

    def test_auto_plan_uses_monte_carlo_for_wide_flop(self):
        plan = build_equity_plan(["Qh", "7s", "2c"], ["22+,A2s+,K9s+,Q9s+,J9s+,T9s"], time_budget_ms=300)
        self.assertEqual(plan.backend.value, "rust_monte_carlo")
        self.assertEqual(plan.mode, "monte_carlo")


if __name__ == "__main__":
    unittest.main()
