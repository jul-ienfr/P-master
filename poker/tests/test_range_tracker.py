"""Tests for the staged range tracker."""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker.range_tracker import (
    PostflopAction,
    PreflopAction,
    RangeTrackerManager,
    VillainRange,
)


class TestRangeTracker(unittest.TestCase):
    def test_villain_range_applies_board_aware_weights(self):
        villain = VillainRange(position_utg=2)
        villain.update_preflop(PreflopAction.OPEN_RAISE)
        before = villain.get_range_string()
        villain.update_postflop(PostflopAction.RAISE, ["Qh", "7h", "2c"], "Flop")
        after = villain.get_range_string()

        self.assertNotEqual(before, after)
        self.assertIn(":", after)

    def test_tracker_builds_calibration_rows(self):
        tracker = RangeTrackerManager()
        table = SimpleNamespace(
            GameID="game-1",
            position_utg_plus=3,
            total_players=6,
            gameStage="Flop",
            cardsOnTable=["Qh", "7s", "2c"],
            totalPotValue=10.0,
            minCall=2.0,
            minBet=5.0,
            other_player_has_initiative=True,
            first_raiser_utg=1,
            first_caller_utg=2,
            second_raiser_utg=0,
            other_players=[
                {"status": 1, "utg_position": 1},
                {"status": 0, "utg_position": 2},
            ],
        )

        tracker.update_from_table(table)
        rows = tracker.build_calibration_rows(table)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["street"], "Flop")
        self.assertIn("model_version", rows[0])

    def test_tracker_applies_calibration_profile(self):
        villain = VillainRange(
            position_utg=2,
            calibration_profile={"flop:raise": 0.85, "flop:raise:pair": 1.1},
        )
        villain.update_preflop(PreflopAction.OPEN_RAISE)
        before_weights = dict(villain.weighted_tokens)
        villain.update_postflop(PostflopAction.RAISE, ["Qh", "7h", "2c"], "Flop")

        self.assertNotEqual(before_weights, villain.weighted_tokens)
        self.assertTrue(any(weight != 1.0 for weight in villain.weighted_tokens.values()))

    def test_tracker_manager_propagates_calibration_profile_to_existing_and_new_trackers(self):
        tracker = RangeTrackerManager()
        tracker.set_calibration_profile({"turn:call": 0.9})
        table = SimpleNamespace(
            GameID="game-2",
            position_utg_plus=3,
            total_players=6,
            gameStage="Turn",
            cardsOnTable=["Qh", "7s", "2c", "9d"],
            totalPotValue=10.0,
            minCall=2.0,
            minBet=5.0,
            other_player_has_initiative=False,
            first_raiser_utg=1,
            first_caller_utg=2,
            second_raiser_utg=0,
            other_players=[
                {"status": 1, "utg_position": 1},
            ],
        )

        tracker.update_from_table(table)
        self.assertEqual(tracker.trackers[0].calibration_profile, {"turn:call": 0.9})

        tracker.set_calibration_profile({"river:bet": 1.1})
        self.assertEqual(tracker.trackers[0].calibration_profile, {"river:bet": 1.1})

        table.other_players.append({"status": 1, "utg_position": 2})
        tracker.update_from_table(table)
        self.assertEqual(tracker.trackers[1].calibration_profile, {"river:bet": 1.1})

    def test_tracker_manager_board_change_updates_fingerprint_even_when_other_signals_match(self):
        tracker = RangeTrackerManager()
        table = SimpleNamespace(
            GameID="game-3",
            position_utg_plus=3,
            total_players=6,
            gameStage="Turn",
            cardsOnTable=["Qh", "7s", "2c", "9d"],
            totalPotValue=10.0,
            minCall=2.0,
            minBet=5.0,
            other_player_has_initiative=False,
            first_raiser_utg=1,
            first_caller_utg=2,
            second_raiser_utg=0,
            other_players=[
                {"status": 1, "utg_position": 1},
            ],
        )

        tracker.update_from_table(table)
        first_fingerprint = tracker.trackers[0].last_update_fingerprint
        table.cardsOnTable = ["Qh", "7s", "2c", "Td"]
        tracker.update_from_table(table)
        second_fingerprint = tracker.trackers[0].last_update_fingerprint

        self.assertNotEqual(first_fingerprint, second_fingerprint)


if __name__ == "__main__":
    unittest.main()
