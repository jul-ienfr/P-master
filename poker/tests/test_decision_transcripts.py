"""Transcript-style decision tests for readable fallback/gate validation."""

from __future__ import annotations

import pathlib
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from poker.decisionmaker.decision_service import CanonicalDecisionService
from poker.decisionmaker.v2_contracts import SpotSnapshot


def build_spot_from_transcript(transcript: str) -> SpotSnapshot:
    fields: dict[str, str] = {}
    for raw_line in transcript.strip().splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    return SpotSnapshot(
        spot_id=fields.get("spot", "transcript"),
        source="replay",
        game_stage=fields.get("street", "Flop"),
        hero_cards=tuple(item.strip() for item in fields.get("hero", "").split() if item.strip()),
        board=tuple(item.strip() for item in fields.get("board", "").split() if item.strip()),
        hero_position=fields.get("hero_position", "BTN"),
        legal_actions=tuple(item.strip() for item in fields.get("legal_actions", "").split(",") if item.strip()),
        action_history=tuple(item.strip() for item in fields.get("history", "").split(",") if item.strip()),
        pot=float(fields.get("pot", "0")),
        stack=float(fields.get("stack", "0")),
        state_confidence=float(fields.get("confidence", "0")),
    )


class TestDecisionTranscripts(unittest.TestCase):
    def test_low_confidence_transcript_blocks_live_action(self):
        transcript = """
        spot: hand-1002
        street: Flop
        hero: As Kd
        board: Qh 7s 2c
        hero_position: BTN
        legal_actions: check,bet,fold
        history: preflop:raise,flop:check
        pot: 12.5
        stack: 87.5
        confidence: 0.41
        """
        service = CanonicalDecisionService()
        spot = build_spot_from_transcript(transcript)
        gate = service.evaluate_gate(spot)

        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, "low_state_confidence")


if __name__ == "__main__":
    unittest.main()
