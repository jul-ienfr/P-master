import asyncio
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import DecisionMaker


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


@pytest.mark.parametrize(
    ("enable_validated_rl", "expected_key"),
    [(False, "rl_off"), (True, "rl_on")],
    ids=["rl-off", "rl-on"],
)
def test_runtime_decision_fixture_compares_rl_on_off_on_same_inputs(enable_validated_rl, expected_key):
    fixture = _load_fixture("decision_ab_runtime_validated_rl.json")
    decision_maker = DecisionMaker(
        FixtureDB(fixture["profile"]),
        solver_backend=FixtureSolver(fixture["solver_response"]),
        rl_agent=FixtureRLAgent(action_idx=fixture["rl_action_idx"]),
        enable_validated_rl=enable_validated_rl,
    )

    decision = asyncio.run(decision_maker.get_best_action(**fixture["request"]))
    expected = fixture["expected"][expected_key]

    assert decision["action"] == expected["action"]
    assert decision["source"] == expected["source"]
    assert decision["bet_size"] == expected["bet_size"]
    assert decision["backend"] == expected["backend"]
    assert decision["fallback_used"] is expected["fallback_used"]
    assert decision["confidence"] == expected["confidence"]
    assert decision["metadata"]["rl_ab"]["gto_action"] == fixture["expected"]["rl_off"]["action"]
    assert decision["metadata"]["rl_ab"]["final_action"] == expected["action"]
    assert decision["metadata"]["rl_ab"]["applied"] is enable_validated_rl
    assert decision["ab_decision"] == decision["metadata"]["rl_ab"]
    expected_eligibility_reasons = ["validated_rl_ready"] if enable_validated_rl else ["validated_rl_disabled"]
    assert decision["metadata"]["rl_ab"]["eligibility_reasons"] == expected_eligibility_reasons
    assert decision["metadata"]["profile"]["style"] == fixture["profile"]["derived_profile"]["style"]
    assert decision["metadata"]["solver"]["has_alternatives"] is True
    assert decision["metadata"]["solver"]["alternatives"] == [
        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62},
        {"action": "BET", "raw_action": "BET_75", "freq": 0.38},
    ]
    assert decision["metadata"]["confidence"]["source"] == "solver"


def test_runtime_decision_fixture_ab_difference_is_explicit():
    fixture = _load_fixture("decision_ab_runtime_validated_rl.json")

    rl_off = asyncio.run(
        DecisionMaker(
            FixtureDB(fixture["profile"]),
            solver_backend=FixtureSolver(fixture["solver_response"]),
            rl_agent=FixtureRLAgent(action_idx=fixture["rl_action_idx"]),
            enable_validated_rl=False,
        ).get_best_action(**fixture["request"])
    )
    rl_on = asyncio.run(
        DecisionMaker(
            FixtureDB(fixture["profile"]),
            solver_backend=FixtureSolver(fixture["solver_response"]),
            rl_agent=FixtureRLAgent(action_idx=fixture["rl_action_idx"]),
            enable_validated_rl=True,
        ).get_best_action(**fixture["request"])
    )

    assert rl_off["action"] == "FOLD"
    assert rl_off["source"] == "GTO_RUST"
    assert rl_on["action"] == "BET"
    assert rl_on["source"] == "RL_VALIDATED"
    assert rl_off["backend"] == rl_on["backend"] == fixture["solver_response"]["backend"]
    assert rl_off["details"] == rl_on["details"] == fixture["solver_response"]["actions"]
    assert rl_off["confidence"] == rl_on["confidence"] == fixture["solver_response"]["decision_confidence"]
    assert rl_off["metadata"]["rl_ab"]["applied"] is False
    assert rl_off["metadata"]["rl_ab"]["would_override"] is False
    assert rl_off["metadata"]["rl_ab"]["rl_differs_from_gto"] is True
    assert rl_off["metadata"]["rl_ab"]["comparison"] == {
        "rl_off": {
            "branch": "rl_off",
            "action": "FOLD",
            "freq": 0.62,
            "ev": None,
            "present_in_solver": True,
        },
        "rl_on": {
            "branch": "rl_on",
            "action": "FOLD",
            "freq": 0.62,
            "ev": None,
            "present_in_solver": True,
        },
        "action_changed": False,
        "freq_delta": 0.0,
        "ev_delta": None,
    }
    assert rl_on["metadata"]["rl_ab"]["applied"] is True
    assert rl_on["metadata"]["rl_ab"]["rl_action"] == "BET"
    assert rl_on["metadata"]["rl_ab"]["profile_snapshot"]["rl_ready"] is True
    assert rl_on["metadata"]["rl_ab"]["comparison"] == {
        "rl_off": {
            "branch": "rl_off",
            "action": "FOLD",
            "freq": 0.62,
            "ev": None,
            "present_in_solver": True,
        },
        "rl_on": {
            "branch": "rl_on",
            "action": "BET",
            "freq": 0.38,
            "ev": None,
            "present_in_solver": True,
        },
        "action_changed": True,
        "freq_delta": -0.24,
        "ev_delta": None,
    }
