import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import DecisionMaker
from src.solver.provider import SolverProvider


def run(coro):
    return asyncio.run(coro)


class FakeDB:
    def __init__(self, profile=None):
        self.profile = profile
        self.is_available = True
        self.calls = []

    async def get_player_profile(self, villain_name):
        self.calls.append(villain_name)
        return self.profile


class FakeSolver:
    backend_name = "fake_solver"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def solve_spot_v2(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.response)


class FakeRLAgent:
    def __init__(self, action_dim=5, action_idx=0):
        self.action_dim = action_dim
        self.action_idx = action_idx
        self.calls = []

    def select_action(self, state_vector, valid_mask, exploit_mode=False):
        self.calls.append(
            {
                "state_vector": state_vector,
                "valid_mask": valid_mask.copy(),
                "exploit_mode": exploit_mode,
            }
        )
        return self.action_idx


class FakeRLLoaderAgent(FakeRLAgent):
    def __init__(self):
        super().__init__()
        self.load_calls = 0

    def load_model(self):
        self.load_calls += 1


class RaisingRLAgent:
    def __init__(self, *args, **kwargs):
        raise AssertionError("RL agent should not be instantiated")


class FakeHTTPResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_normalize_runtime_actions_collapses_variants_and_deduplicates():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    normalized = decision_maker._normalize_runtime_actions(
        [" fold ", "call", "check", "bet_50", "BET_75", "raise_pot", None, "BET"]
    )

    assert normalized == ["FOLD", "CALL", "CHECK", "BET", "RAISE"]


def test_normalize_solver_action_maps_bet_variant_to_runtime_bet():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    normalized = decision_maker._normalize_solver_action("BET_75", ["FOLD", "CALL", "BET"])

    assert normalized == "BET"


def test_normalize_solver_action_swaps_check_and_call_when_only_one_is_legal():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    assert decision_maker._normalize_solver_action("CHECK", ["FOLD", "CALL"]) == "CALL"
    assert decision_maker._normalize_solver_action("CALL", ["FOLD", "CHECK"]) == "CHECK"


def test_normalize_solver_action_falls_back_to_fold_then_first_legal_action():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    assert decision_maker._normalize_solver_action("ALL_IN", ["FOLD", "BET"]) == "FOLD"
    assert decision_maker._normalize_solver_action("ALL_IN", ["BET", "RAISE"]) == "BET"


def test_fallback_action_prefers_fold_and_preserves_backend_metadata():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    fallback = decision_maker._fallback_action(["call", "fold", "bet_75"])

    assert fallback["action"] == "FOLD"
    assert fallback["source"] == "FALLBACK"
    assert fallback["fallback_used"] is True
    assert fallback["fallback_reason"] == "solver_unavailable"
    assert fallback["backend"] == "fallback"


def test_fallback_action_uses_first_normalized_action_when_fold_is_unavailable():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    fallback = decision_maker._fallback_action(["bet_75", "raise_half"])

    assert fallback["action"] == "BET"


def test_select_exploit_action_applies_pressure_bias_when_deviation_cap_allows_it():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    action, source = decision_maker._select_exploit_action(
        legal_actions=["FOLD", "CALL", "BET"],
        gto_action="CALL",
        rl_action_name=None,
        structured_profile={
            "deviation_cap": 0.12,
            "pressure_bias": 0.18,
            "fold_bias": 0.0,
            "call_bias": 0.0,
        },
    )

    assert action == "BET"
    assert source == "EXPLOIT_PROFILE"


def test_select_exploit_action_applies_fold_bias_toward_passive_action():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    action, source = decision_maker._select_exploit_action(
        legal_actions=["FOLD", "CHECK", "BET"],
        gto_action="BET",
        rl_action_name=None,
        structured_profile={
            "deviation_cap": 0.12,
            "pressure_bias": 0.0,
            "fold_bias": 0.16,
            "call_bias": 0.0,
        },
    )

    assert action == "CHECK"
    assert source == "EXPLOIT_PROFILE"


def test_select_exploit_action_applies_call_bias_only_against_gto_fold():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    action, source = decision_maker._select_exploit_action(
        legal_actions=["FOLD", "CALL"],
        gto_action="FOLD",
        rl_action_name=None,
        structured_profile={
            "deviation_cap": 0.12,
            "pressure_bias": 0.0,
            "fold_bias": 0.0,
            "call_bias": 0.15,
        },
    )

    assert action == "CALL"
    assert source == "EXPLOIT_PROFILE"


def test_select_exploit_action_keeps_gto_when_deviation_cap_is_too_low():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)

    action, source = decision_maker._select_exploit_action(
        legal_actions=["FOLD", "CALL", "BET"],
        gto_action="CALL",
        rl_action_name="BET",
        structured_profile={
            "deviation_cap": 0.05,
            "pressure_bias": 0.18,
            "fold_bias": 0.16,
            "call_bias": 0.15,
            "rl_ready": True,
            "reliability": 1.0,
            "exploit_confidence": 1.0,
        },
    )

    assert action == "CALL"
    assert source == "GTO_RUST"


def test_get_best_action_uses_injected_solver_backend_and_returns_backend_name():
    solver = FakeSolver(
        {
            "chosen_action": "BET_75",
            "hero_ev": 1.2,
            "exploitability": 0.03,
            "decision_confidence": 0.84,
            "actions": [{"action": "BET_75", "freq": 1.0}],
            "elapsed_ms": 7,
        }
    )
    decision_maker = DecisionMaker(FakeDB(), solver_backend=solver, rl_agent=None)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            action_history=[{"player": "Hero", "action": "BET", "amount": 5.0}],
        )
    )

    assert decision["action"] == "BET"
    assert decision["bet_size"] == 7.5
    assert decision["fallback_used"] is False
    assert decision["backend"] == "fake_solver"
    assert solver.calls[0]["action_history"] == ["Hero:BET:5.0"]
    assert solver.calls[0]["legal_actions"] == ["FOLD", "CALL", "BET"]


def test_get_best_action_uses_http_solver_provider_when_native_backend_fails():
    solver = FakeSolver(response=None)

    def fake_post(url, json, timeout):
        return FakeHTTPResponse(
            {
                "chosen_action": "CHECK",
                "backend": "gto_server",
                "decision_confidence": 0.81,
                "elapsed_ms": 9,
                "metadata": {"transport": "local_http"},
            }
        )

    provider = SolverProvider(native_backend=solver, request_post=fake_post)
    decision_maker = DecisionMaker(FakeDB(), solver_backend=solver, solver_provider=provider, rl_agent=None)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["CHECK", "BET"],
        )
    )

    assert decision["action"] == "CHECK"
    assert decision["backend"] == "gto_server"
    assert decision["fallback_used"] is False
    assert decision["metadata"]["solver"]["backend"] == "gto_server"


def test_get_best_action_uses_provider_fallback_reason_when_native_and_http_fail():
    class RaisingNativeSolver:
        backend_name = "raising_native"

        def solve_spot_v2(self, **kwargs):
            raise RuntimeError("native_solver_down")

    def fake_post(url, json, timeout):
        raise RuntimeError("http_down")

    provider = SolverProvider(native_backend=RaisingNativeSolver(), request_post=fake_post)
    decision_maker = DecisionMaker(FakeDB(), solver_provider=provider, rl_agent=None)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CHECK"],
        )
    )

    assert decision["action"] == "FOLD"
    assert decision["backend"] == "fallback"
    assert decision["fallback_used"] is True
    assert decision["fallback_reason"] == "native_solver_down"


def test_get_best_action_enriches_metadata_with_solver_profile_and_confidence_details():
    solver = FakeSolver(
        {
            "chosen_action": "BET_75",
            "hero_ev": 1.2,
            "exploitability": 0.03,
            "decision_confidence": 0.84,
            "actions": [
                {"action": "CHECK", "freq": 0.15, "ev": 0.4},
                {"action": "BET_75", "freq": 0.85, "ev": 1.2},
            ],
            "elapsed_ms": 7,
            "backend": "solver_stub",
            "cache_hit": True,
            "node_count": 321,
        }
    )
    profile = {
        "player_type": "RegAggressive",
        "derived_profile": {
            "style": "RegAggressive",
            "observed_hands": 88,
            "hands_played": 88,
            "vpip_rate": 0.28,
            "pfr_rate": 0.21,
            "aggression_frequency": 0.52,
            "reliability": 0.81,
            "rl_ready": True,
        },
    }
    decision_maker = DecisionMaker(FakeDB(profile), solver_backend=solver, rl_agent=FakeRLAgent(action_idx=2))

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CHECK", "BET"],
            state_confidence=0.9,
        )
    )

    assert decision["metadata"]["solver"]["chosen_action_raw"] == "BET_75"
    assert decision["metadata"]["solver"]["has_alternatives"] is True
    assert decision["metadata"]["solver"]["action_count"] == 2
    assert decision["metadata"]["solver"]["node_count"] == 321
    assert decision["metadata"]["solver"]["backend"] == "solver_stub"
    assert decision["metadata"]["solver"]["gto_action"] == "BET"
    assert decision["metadata"]["solver"]["final_action"] == "BET"
    assert decision["metadata"]["solver"]["alternatives"] == [
        {"action": "CHECK", "raw_action": "CHECK", "freq": 0.15, "ev": 0.4},
        {"action": "BET", "raw_action": "BET_75", "freq": 0.85, "ev": 1.2},
    ]
    assert decision["metadata"]["solver"]["alternatives_complete"] == decision["metadata"]["solver"]["alternatives"]
    assert decision["metadata"]["solver"]["ev_by_action"] == {"CHECK": 0.4, "BET": 1.2}
    assert decision["metadata"]["solver"]["freq_by_action"] == {"CHECK": 0.15, "BET": 0.85}
    assert decision["metadata"]["solver"]["action_metadata"] == {
        "CHECK": {"raw_action": "CHECK", "ev": 0.4, "freq": 0.15},
        "BET": {"raw_action": "BET_75", "ev": 1.2, "freq": 0.85},
    }
    assert decision["metadata"]["solver"]["backend_details"] == {
        "name": "solver_stub",
        "node_count": 321,
    }
    assert decision["metadata"]["solver"]["cache_details"] == {"hit": True}
    assert decision["metadata"]["profile"]["style"] == "RegAggressive"
    assert decision["metadata"]["profile"]["observed_hands"] == 88
    assert decision["metadata"]["profile"]["pressure_bias"] == -0.04
    assert decision["metadata"]["profile"]["call_bias"] == -0.04
    assert decision["metadata"]["profile"]["fold_bias"] == 0.04
    assert decision["metadata"]["profile"]["deviation_cap"] == 0.181
    assert decision["metadata"]["confidence"] == {
        "value": 0.84,
        "source": "solver",
        "state_confidence": 0.9,
        "profile_reliability": 0.81,
        "vs_profile_exploit_gap": 0.184,
    }
    assert decision["metadata"]["exploit"] == {
        "decision_source": "GTO_RUST",
        "source_slug": "gto_solver",
        "applied": False,
        "gto_action": "BET",
        "final_action": "BET",
        "exploit_confidence": 0.656,
        "deviation_cap": 0.181,
        "pressure_bias": -0.04,
        "call_bias": -0.04,
        "fold_bias": 0.04,
    }
    assert decision["metadata"]["rl_ab"]["comparison"] == {
        "rl_off": {
            "branch": "rl_off",
            "action": "BET",
            "freq": 0.85,
            "ev": 1.2,
            "present_in_solver": True,
        },
        "rl_on": {
            "branch": "rl_on",
            "action": "BET",
            "freq": 0.85,
            "ev": 1.2,
            "present_in_solver": True,
        },
        "action_changed": False,
        "freq_delta": 0.0,
        "ev_delta": 0.0,
    }


def test_get_best_action_without_solver_uses_fallback_even_if_rl_stub_exists():
    rl_agent = FakeRLAgent(action_idx=2)
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=rl_agent)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=5.5,
            effective_stack=96.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.88,
        )
    )

    assert decision["action"] == "FOLD"
    assert decision["fallback_used"] is True
    assert decision["fallback_reason"] == "rust_solver_unavailable"
    assert decision["backend"] == "fallback"
    assert decision["metadata"]["solver"]["backend"] == "fallback"
    assert decision["metadata"]["solver"]["gto_action"] == "FOLD"
    assert decision["metadata"]["solver"]["final_action"] == "FOLD"
    assert decision["metadata"]["solver"]["alternatives_complete"] == []
    assert len(rl_agent.calls) == 1
    assert rl_agent.calls[0]["valid_mask"].tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]


def test_get_best_action_uses_preflop_fast_path_without_solver_or_db_fetch():
    solver = FakeSolver(
        {
            "chosen_action": "FOLD",
            "hero_ev": -1.0,
            "exploitability": 1.0,
            "decision_confidence": 0.1,
            "actions": [{"action": "FOLD", "freq": 1.0}],
            "elapsed_ms": 99,
        }
    )
    db = FakeDB(profile={"player_type": "Nit"})
    decision_maker = DecisionMaker(db, solver_backend=solver, rl_agent=None)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AsKh",
            board=[],
            pot=3.0,
            effective_stack=100.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            hero_position="BTN",
            action_history=[],
        )
    )

    assert decision["action"] == "BET"
    assert decision["source"] == "GTO_PREFLOP_FAST"
    assert decision["backend"] == "preflop_fast_path"
    assert decision["elapsed_ms"] == 0
    assert decision["fallback_used"] is False
    assert solver.calls == []
    assert db.calls == []


def test_get_best_action_uses_dynamic_villain_position_from_history():
    solver = FakeSolver(
        {
            "chosen_action": "CHECK",
            "hero_ev": 0.4,
            "exploitability": 0.02,
            "decision_confidence": 0.9,
            "actions": [{"action": "CHECK", "freq": 1.0}],
            "elapsed_ms": 5,
        }
    )
    decision_maker = DecisionMaker(FakeDB(), solver_backend=solver, rl_agent=None)

    run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["CHECK", "BET"],
            hero_position="BTN",
            action_history=[{"player": "Villain", "action": "OPEN", "position": "CO"}],
        )
    )

    assert solver.calls
    assert solver.calls[0]["villain_ranges"] == [decision_maker.preflop_manager.get_villain_range("CO")]


def test_get_best_action_keeps_optional_solver_backend_cache_and_warning_details_when_present():
    solver = FakeSolver(
        {
            "chosen_action": "CALL",
            "hero_ev": 0.33,
            "decision_confidence": 0.77,
            "actions": [
                {"action": "FOLD", "freq": 0.2, "ev": -0.1},
                {"action": "CALL", "freq": 0.8, "ev": 0.33},
            ],
            "elapsed_ms": 5,
            "backend": "solver_stub",
            "backend_version": "2026.04",
            "solve_mode": "cached_lookup",
            "cache_hit": True,
            "cache_key": "turn:spot:123",
            "cache_tier": "memory",
            "warnings": ["subtree_reused", "rounded_strategy"],
        }
    )
    decision_maker = DecisionMaker(FakeDB(), solver_backend=solver, rl_agent=None)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
        )
    )

    assert decision["metadata"]["solver"]["warnings"] == ["subtree_reused", "rounded_strategy"]
    assert decision["metadata"]["solver"]["backend_details"] == {
        "name": "solver_stub",
        "version": "2026.04",
        "solve_mode": "cached_lookup",
    }
    assert decision["metadata"]["solver"]["cache_details"] == {
        "hit": True,
        "key": "turn:spot:123",
        "tier": "memory",
    }


def test_get_best_action_preserves_existing_native_solver_compact_fields_when_present():
    solver = FakeSolver(
        {
            "chosen_action": "BET_75",
            "hero_ev": 0.61,
            "exploitability": 0.018,
            "decision_confidence": 0.93,
            "actions": [
                {"action": "CHECK", "freq": 0.31, "ev": 0.12},
                {"action": "BET_75", "freq": 0.69, "ev": 0.61},
            ],
            "elapsed_ms": 14,
            "backend": "native_rust",
            "node_count": 2048,
            "solver_id": "postflop-main",
            "preset_id": "turn_cbet_ip",
            "action_buckets": ["CHECK", "BET_75"],
            "warning_details": [
                {"code": "subtree_reused", "detail": "turn subtree cache hit"},
                "rounded_strategy",
            ],
        }
    )
    decision_maker = DecisionMaker(FakeDB(), solver_backend=solver, rl_agent=None)

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=["2c", "7d", "Jh"],
            pot=10.0,
            effective_stack=80.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CHECK", "BET"],
        )
    )

    assert decision["exploitability"] == 0.018
    assert decision["elapsed_ms"] == 14
    assert decision["metadata"]["solver"]["exploitability"] == 0.018
    assert decision["metadata"]["solver"]["elapsed_ms"] == 14
    assert decision["metadata"]["solver"]["node_count"] == 2048
    assert decision["metadata"]["solver"]["solver_id"] == "postflop-main"
    assert decision["metadata"]["solver"]["preset_id"] == "turn_cbet_ip"
    assert decision["metadata"]["solver"]["action_buckets"] == ["CHECK", "BET_75"]
    assert decision["metadata"]["solver"]["warning_details"] == [
        {"code": "subtree_reused", "detail": "turn subtree cache hit"},
        "rounded_strategy",
    ]


def test_init_does_not_autoload_rl_model_when_disabled():
    rl_agent = FakeRLLoaderAgent()

    decision_maker = DecisionMaker(
        FakeDB(),
        solver_backend=None,
        rl_agent=rl_agent,
        autoload_rl_model=False,
    )

    assert decision_maker.rl_agent is rl_agent
    assert rl_agent.load_calls == 0


def test_init_skips_default_rl_agent_creation_when_disabled(monkeypatch):
    monkeypatch.setattr("src.bot.decision_maker.RL_AVAILABLE", True)
    monkeypatch.setattr("src.bot.decision_maker.RLAdapterAgent", RaisingRLAgent)

    decision_maker = DecisionMaker(
        FakeDB(),
        solver_backend=None,
        create_rl_agent=False,
    )

    assert decision_maker.rl_agent is None


def test_injected_rl_agent_is_kept_even_when_default_creation_is_disabled():
    rl_agent = FakeRLAgent(action_idx=2)

    decision_maker = DecisionMaker(
        FakeDB(),
        solver_backend=None,
        rl_agent=rl_agent,
        create_rl_agent=False,
    )

    assert decision_maker.rl_agent is rl_agent


def test_validated_rl_override_can_be_enabled_with_stub_agent():
    profile = {
        "player_type": "Balanced",
        "derived_profile": {
            "style": "Balanced",
            "observed_hands": 120,
            "hands_played": 120,
            "vpip_rate": 0.35,
            "pfr_rate": 0.15,
            "aggression_frequency": 0.65,
            "reliability": 0.95,
            "rl_ready": True,
        },
    }
    solver = FakeSolver(
        {
            "chosen_action": "FOLD",
            "decision_confidence": 0.91,
            "backend": "solver_stub",
        }
    )
    rl_agent = FakeRLAgent(action_idx=2)
    decision_maker = DecisionMaker(
        FakeDB(profile),
        solver_backend=solver,
        rl_agent=rl_agent,
        enable_validated_rl=True,
    )

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=6.0,
            effective_stack=50.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.92,
        )
    )

    assert decision["action"] == "BET"
    assert decision["source"] == "RL_VALIDATED"
    assert decision["fallback_used"] is False
    assert decision["profile"]["rl_ready"] is True
    assert decision["metadata"]["exploit"]["source_slug"] == "validated_rl"
    assert decision["metadata"]["exploit"]["applied"] is True


def test_rl_ab_metadata_keeps_final_action_aligned_to_gto_when_rl_differs_but_is_ineligible():
    profile = {
        "player_type": "Balanced",
        "derived_profile": {
            "style": "Balanced",
            "observed_hands": 20,
            "hands_played": 20,
            "vpip_rate": 0.35,
            "pfr_rate": 0.15,
            "aggression_frequency": 0.65,
            "reliability": 0.4,
            "rl_ready": True,
        },
    }
    solver = FakeSolver(
        {
            "chosen_action": "FOLD",
            "decision_confidence": 0.77,
            "backend": "solver_stub",
            "actions": [{"action": "FOLD", "freq": 0.7}, {"action": "BET_75", "freq": 0.3}],
        }
    )
    decision_maker = DecisionMaker(
        FakeDB(profile),
        solver_backend=solver,
        rl_agent=FakeRLAgent(action_idx=2),
        enable_validated_rl=True,
    )

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=6.0,
            effective_stack=50.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.92,
        )
    )

    assert decision["action"] == "FOLD"
    assert decision["source"] == "GTO_RUST"
    assert decision["metadata"]["rl_ab"]["rl_action"] == "BET"
    assert decision["metadata"]["rl_ab"]["rl_differs_from_gto"] is True
    assert decision["metadata"]["rl_ab"]["eligible"] is False
    assert decision["metadata"]["rl_ab"]["would_override"] is False
    assert decision["metadata"]["rl_ab"]["final_action"] == "FOLD"
    assert decision["ab_decision"] == decision["metadata"]["rl_ab"]


def test_get_best_action_enriches_solver_alternatives_with_missing_ab_branch_actions():
    profile = {
        "player_type": "Balanced",
        "derived_profile": {
            "style": "Balanced",
            "observed_hands": 120,
            "hands_played": 120,
            "vpip_rate": 0.35,
            "pfr_rate": 0.15,
            "aggression_frequency": 0.65,
            "reliability": 0.95,
            "rl_ready": True,
        },
    }
    solver = FakeSolver(
        {
            "chosen_action": "FOLD",
            "decision_confidence": 0.91,
            "backend": "solver_stub",
            "hero_ev": -0.15,
            "actions": [{"action": "FOLD", "freq": 0.62, "ev": -0.15}],
        }
    )
    decision_maker = DecisionMaker(
        FakeDB(profile),
        solver_backend=solver,
        rl_agent=FakeRLAgent(action_idx=2),
        enable_validated_rl=True,
    )

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=6.0,
            effective_stack=50.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.92,
        )
    )

    assert decision["action"] == "BET"
    assert decision["metadata"]["solver"]["alternatives"] == [
        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
        {"action": "BET", "raw_action": "BET", "source": "final_action"},
    ]
    assert decision["metadata"]["solver"]["action_count"] == 2


def test_rl_ab_metadata_exposes_eligibility_reasons_and_profile_snapshot():
    profile = {
        "player_type": "Balanced",
        "derived_profile": {
            "style": "Balanced",
            "observed_hands": 20,
            "hands_played": 20,
            "vpip_rate": 0.35,
            "pfr_rate": 0.15,
            "aggression_frequency": 0.65,
            "reliability": 0.4,
            "rl_ready": False,
        },
    }
    solver = FakeSolver(
        {
            "chosen_action": "FOLD",
            "decision_confidence": 0.77,
            "backend": "solver_stub",
            "actions": [{"action": "FOLD", "freq": 0.7}, {"action": "BET_75", "freq": 0.3}],
        }
    )
    decision_maker = DecisionMaker(
        FakeDB(profile),
        solver_backend=solver,
        rl_agent=FakeRLAgent(action_idx=2),
        enable_validated_rl=True,
    )

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=6.0,
            effective_stack=50.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.92,
        )
    )

    assert decision["metadata"]["rl_ab"]["eligible"] is False
    assert decision["metadata"]["rl_ab"]["eligibility_reasons"] == [
        "profile_not_rl_ready",
        "profile_reliability_too_low",
        "exploit_confidence_too_low",
    ]
    assert decision["metadata"]["rl_ab"]["profile_snapshot"] == {
        "style": "Balanced",
        "observed_hands": 20,
        "reliability": 0.4,
        "exploit_confidence": 0.428,
        "deviation_cap": 0.136,
        "rl_ready": False,
    }
    assert decision["metadata"]["rl_ab"]["comparison"] == {
        "rl_off": {
            "branch": "rl_off",
            "action": "FOLD",
            "freq": 0.7,
            "ev": None,
            "present_in_solver": True,
        },
        "rl_on": {
            "branch": "rl_on",
            "action": "FOLD",
            "freq": 0.7,
            "ev": None,
            "present_in_solver": True,
        },
        "action_changed": False,
        "freq_delta": 0.0,
        "ev_delta": None,
    }


def test_validated_rl_ab_comparison_exposes_solver_freq_and_ev_deltas_without_resolve():
    profile = {
        "player_type": "Balanced",
        "derived_profile": {
            "style": "Balanced",
            "observed_hands": 120,
            "hands_played": 120,
            "vpip_rate": 0.35,
            "pfr_rate": 0.15,
            "aggression_frequency": 0.65,
            "reliability": 0.95,
            "rl_ready": True,
        },
    }
    solver = FakeSolver(
        {
            "chosen_action": "FOLD",
            "decision_confidence": 0.91,
            "backend": "solver_stub",
            "actions": [
                {"action": "FOLD", "freq": 0.62, "ev": -0.15},
                {"action": "BET_75", "freq": 0.38, "ev": 0.41},
            ],
        }
    )
    decision_maker = DecisionMaker(
        FakeDB(profile),
        solver_backend=solver,
        rl_agent=FakeRLAgent(action_idx=2),
        enable_validated_rl=True,
    )

    decision = run(
        decision_maker.get_best_action(
            hero_hand="AhKd",
            board=[],
            pot=6.0,
            effective_stack=50.0,
            villain_name="Villain",
            legal_actions=["FOLD", "CALL", "BET"],
            state_confidence=0.92,
        )
    )

    assert len(solver.calls) == 1
    assert decision["metadata"]["rl_ab"]["comparison"] == {
        "rl_off": {
            "branch": "rl_off",
            "action": "FOLD",
            "freq": 0.62,
            "ev": -0.15,
            "present_in_solver": True,
        },
        "rl_on": {
            "branch": "rl_on",
            "action": "BET",
            "freq": 0.38,
            "ev": 0.41,
            "present_in_solver": True,
        },
        "action_changed": True,
        "freq_delta": -0.24,
        "ev_delta": 0.56,
    }
