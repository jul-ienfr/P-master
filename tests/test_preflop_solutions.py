"""Tests Phase 1 — préflop dual-mode : store, loader, config runtime, décision."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import DecisionMaker  # noqa: E402
from src.bot.preflop_solutions import (  # noqa: E402
    PreflopSolutionStore,
    build_spot_solution,
    resolve_live_decision,
)


class FakeDB:
    is_available = False


def _tiny_table() -> dict:
    return {
        "AA": {"raise": 1.0, "call": 0.0, "fold": 0.0, "ev": 5.0},
        "72o": {"raise": 0.0, "call": 0.0, "fold": 1.0, "ev": -0.5},
    }


def test_store_save_and_lookup_roundtrip_under_10ms(tmp_path):
    store = PreflopSolutionStore(tmp_path)
    target = store.save_table("rfi", "BTN", 100, _tiny_table())
    assert target.exists()

    reloaded = PreflopSolutionStore(tmp_path)
    strategy = reloaded.get_strategy("rfi", "BTN", 100)
    assert strategy is not None
    assert "AA" in strategy

    # Lookup mémoire <10ms après chargement
    started = time.perf_counter()
    for _ in range(100):
        reloaded.get_strategy("rfi", "BTN", 100)
    assert (time.perf_counter() - started) / 100 < 0.010


def test_store_decide_maps_actions(tmp_path):
    store = PreflopSolutionStore(tmp_path)
    store._tables[store.spot_key("rfi", "BTN", 100)] = _tiny_table()
    store._loaded = True

    chosen, amount, metadata = store.decide(
        "AA",
        context="rfi",
        position="BTN",
        depth_bb=100,
        facing_raise=False,
        aggressive_action="RAISE",
        can_check=False,
    )
    assert metadata["available"] is True
    assert metadata["backend"] == "preflop_precomputed"
    assert chosen in {"BET", "RAISE"}

    missing, _, meta_missing = store.decide(
        "QQ",
        context="rfi",
        position="BTN",
        depth_bb=100,
        facing_raise=False,
        aggressive_action="RAISE",
        can_check=False,
    )
    assert missing is None
    assert meta_missing["available"] is False


def test_build_spot_solution_shape():
    table = build_spot_solution(
        context="vs_raise", position="SB", depth_bb=50, samples_per_combo=4, seed=3
    )
    assert len(table) == 169
    entry = table["AA"]
    for key in ("raise", "call", "fold", "ev"):
        assert key in entry
    assert abs(entry["raise"] + entry["call"] + entry["fold"] - 1.0) < 1e-6


def test_resolve_live_decision_respects_budget():
    result = resolve_live_decision(
        "AsKs",
        context="rfi",
        depth_bb=100,
        pot=1.5,
        to_call=0.0,
        effective_stack=100.0,
        time_budget_ms=800,
        seed=5,
    )
    assert result["chosen_action"] in {"RAISE", "CALL", "CHECK", "FOLD"}
    assert result["budget_respected"] is True


def test_decision_maker_preflop_falls_back_to_charts_without_solutions():
    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)
    decision_maker.configure_preflop(mode="precomputed", solutions_path=str(ROOT / "models" / "_inexistant"))
    action, details = decision_maker._run_preflop_dual_mode(
        hero_hand="AsKs",
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="BTN",
        action_history=[],
        effective_stack=100.0,
        pot=1.5,
        facing_raise=False,
        aggressive_action="RAISE",
    )
    assert details["backend"] == "preflop_fast_path"
    assert action in {"RAISE", "CALL", "CHECK", "FOLD"}


def test_decision_maker_preflop_precomputed_backend_when_table_exists(tmp_path):
    store = PreflopSolutionStore(tmp_path)
    store.save_table("rfi", "BTN", 100, _tiny_table())

    decision_maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None)
    decision_maker.configure_preflop(mode="precomputed", solutions_path=str(tmp_path))
    action, details = decision_maker._run_preflop_dual_mode(
        hero_hand="AsAc",  # combo AA
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="BTN",
        action_history=[],
        effective_stack=100.0,
        pot=1.5,
        facing_raise=False,
        aggressive_action="RAISE",
    )
    assert details["backend"] == "preflop_precomputed"
    assert details["solve_mode"] == "preflop_precomputed"
    assert action in {"RAISE", "BET", "ALL_IN"}
