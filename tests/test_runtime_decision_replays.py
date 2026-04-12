import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import DecisionMaker
from src.bot.live_reconstruction import (
    derive_legal_actions,
    derive_street,
    infer_hero_seat_id,
    normalize_board_for_street,
    ordered_stacks_by_table_geometry,
)
from src.bot.runtime_types import CanonicalPlayer, CanonicalTableState


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class FixtureDB:
    def __init__(self, profile=None):
        self.profile = profile
        self.is_available = True

    async def get_player_profile(self, villain_name):
        return self.profile


class FixtureSolver:
    backend_name = "fixture_solver"

    def __init__(self, response):
        self.response = response

    def solve_spot_v2(self, **kwargs):
        return dict(self.response)


class FixtureRLAgent:
    def __init__(self, action_dim=5, action_idx=0):
        self.action_dim = action_dim
        self.action_idx = action_idx

    def select_action(self, state_vector, valid_mask, exploit_mode=False):
        return self.action_idx


def test_runtime_replay_fixture_matches_expected_tracker_payload():
    fixture = _load_fixture("runtime_replay_turn_anchor.json")

    ordered_stacks = ordered_stacks_by_table_geometry(
        [tuple(bbox) for bbox in fixture["stack_bboxes"]],
        frame_shape=tuple(fixture["frame_shape"]),
        pot_bbox=tuple(fixture["pot_bbox"]),
    )
    hero_seat_id = infer_hero_seat_id(
        ordered_stacks,
        [tuple(bbox) for bbox in fixture["hero_card_bboxes"]],
        frame_shape=tuple(fixture["frame_shape"]),
    )
    street = derive_street(fixture["board"], fixture["hero_cards"])
    board = normalize_board_for_street(fixture["board"], street)
    legal_actions, action_buttons = derive_legal_actions(fixture["action_button_names"])

    players = []
    for seat_index, (seat_id, _) in enumerate(ordered_stacks):
        player_data = fixture["players_by_seat_index"][seat_index]
        players.append(
            CanonicalPlayer(
                seat_id=seat_id,
                seat_index=seat_index,
                stack=player_data["stack"],
                name=player_data["name"],
                is_active=player_data["is_active"],
                has_folded=player_data["has_folded"],
                is_hero=seat_id == hero_seat_id,
                has_button=player_data["has_button"],
                confidence=player_data["confidence"],
            )
        )

    table_state = CanonicalTableState(
        spot_id=fixture["spot_id"],
        street=street,
        pot=fixture["pot"],
        board=board,
        hero_cards=tuple(fixture["hero_cards"]),
        players=tuple(players),
        legal_actions=legal_actions,
        action_buttons=action_buttons,
        state_confidence=fixture["state_confidence"],
        metadata={**fixture["metadata"], "hero_seat_id": hero_seat_id},
    )

    assert hero_seat_id == "seat_2"
    payload = table_state.to_tracker_payload()
    for player in payload["players"]:
        player.pop("metadata", None)
    assert payload == fixture["expected_payload"]


def test_decision_replay_validated_rl_fixture_matches_expected_output():
    fixture = _load_fixture("decision_replay_validated_rl.json")
    decision_maker = DecisionMaker(
        FixtureDB(fixture["profile"]),
        solver_backend=FixtureSolver(fixture["solver_response"]),
        rl_agent=FixtureRLAgent(action_idx=fixture["rl_action_idx"]),
        enable_validated_rl=fixture["enable_validated_rl"],
    )

    decision = asyncio.run(decision_maker.get_best_action(**fixture["request"]))

    comparable = {key: value for key, value in decision.items() if key not in {"metadata", "ab_decision"}}
    assert comparable == fixture["expected"]
    assert decision["metadata"]["rl_ab"]["applied"] is True
    assert decision["metadata"]["rl_ab"]["gto_action"] == "FOLD"
    assert decision["metadata"]["rl_ab"]["final_action"] == "BET"
    assert decision["ab_decision"] == decision["metadata"]["rl_ab"]


def test_decision_replay_fallback_fixture_matches_expected_output():
    fixture = _load_fixture("decision_replay_fallback_low_confidence.json")
    decision_maker = DecisionMaker(
        FixtureDB(fixture["profile"]),
        solver_backend=None,
        create_rl_agent=False,
        enable_validated_rl=fixture["enable_validated_rl"],
    )

    decision = asyncio.run(decision_maker.get_best_action(**fixture["request"]))

    comparable = {key: value for key, value in decision.items() if key not in {"metadata", "ab_decision"}}
    assert comparable == fixture["expected"]
    assert decision["metadata"]["profile"]["style"] == "Unknown"
    assert decision["metadata"]["solver"]["chosen_action_raw"] is None
    assert decision["metadata"]["confidence"]["source"] == "derived"
    assert decision["ab_decision"] is None


def test_smoke_mode_bypasses_rl_creation_entirely(monkeypatch):
    fixture = _load_fixture("decision_replay_fallback_low_confidence.json")

    class RaisingFixtureRLAgent:
        def __init__(self, *args, **kwargs):
            raise AssertionError("RL agent should not be instantiated in smoke mode")

    monkeypatch.setattr("src.bot.decision_maker.RL_AVAILABLE", True)
    monkeypatch.setattr("src.bot.decision_maker.RLAdapterAgent", RaisingFixtureRLAgent)

    decision_maker = DecisionMaker(
        FixtureDB(fixture["profile"]),
        solver_backend=None,
        create_rl_agent=False,
        enable_validated_rl=fixture["enable_validated_rl"],
    )

    decision = asyncio.run(decision_maker.get_best_action(**fixture["request"]))

    assert decision["action"] == fixture["expected"]["action"]
    assert decision["fallback_used"] is True
    assert decision_maker.rl_agent is None
