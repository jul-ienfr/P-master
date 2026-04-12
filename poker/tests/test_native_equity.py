"""Tests for the native equity Python adapter."""

import pathlib
import sys
import types
import unittest
from unittest.mock import patch

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker import native_equity


class TestNativeEquityHelpers(unittest.TestCase):
    def test_normalize_range_percent_accepts_fraction_and_percent(self):
        self.assertEqual(native_equity.normalize_range_percent(0.2), 0.2)
        self.assertEqual(native_equity.normalize_range_percent(20), 0.2)
        self.assertEqual(native_equity.normalize_range_percent(100), 1.0)

    def test_percent_to_range_string_is_stable_for_percent_and_fraction(self):
        self.assertEqual(
            native_equity.percent_to_range_string(20),
            native_equity.percent_to_range_string(0.2),
        )

    def test_normalize_winner_types_accepts_list_payload(self):
        counter = native_equity.normalize_winner_types(
            [
                {"name": "Pair", "frequency": 0.4},
                {"name": "Two Pair", "frequency": 0.1},
            ]
        )
        self.assertEqual(counter["Pair"], 0.4)
        self.assertEqual(counter["Two Pair"], 0.1)

    def test_normalize_range_token_orders_ranks_descending(self):
        self.assertEqual(native_equity.normalize_range_token("TQs"), "QTs")
        self.assertEqual(native_equity.normalize_range_token("kdas"), "AsKd")

    def test_call_native_binding_accepts_dict_result(self):
        fake_module = types.SimpleNamespace(
            evaluate_equity=lambda **kwargs: {"equity": 0.75, "mode_used": "monte_carlo"}
        )

        with patch.object(
            native_equity,
            "NATIVE_GTO_MODULE_CANDIDATES",
            ("fake_native_module",),
        ):
            with patch("poker.decisionmaker.native_equity.importlib.import_module", return_value=fake_module):
                result = native_equity.call_native_binding("evaluate_equity", {"hero_hand": ["As", "Ah"]})

        self.assertEqual(result["equity"], 0.75)
        self.assertEqual(result["mode_used"], "monte_carlo")


if __name__ == "__main__":
    unittest.main()
