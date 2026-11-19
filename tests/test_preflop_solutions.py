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
    enumerate_combos,
    resolve_live_decision,
)
from src.bot.preflop_support import CARD_RANK_ORDER  # noqa: E402


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


def test_monte_carlo_equity_samples_the_runout():
    from random import Random

    from src.bot.preflop_solutions import monte_carlo_equity_vs_range

    weak = monte_carlo_equity_vs_range(
        "7h2d", (), samples=4000, rng=Random(1)
    )
    strong = monte_carlo_equity_vs_range(
        "AhAd", (), samples=4000, rng=Random(1)
    )
    assert 0.25 < weak < 0.45, weak
    assert 0.78 < strong < 0.92, strong
    assert weak < 0.5 < strong


def test_enumerate_combos_is_canonical_descending():
    combos = enumerate_combos()
    assert len(combos) == 169
    assert len(set(combos)) == 169
    assert "AKs" in combos and "KAs" not in combos
    assert "32o" in combos and "23o" not in combos
    for combo in combos:
        assert len(combo) in (2, 3)
        assert CARD_RANK_ORDER[combo[0]] >= CARD_RANK_ORDER[combo[1]]
        if len(combo) == 3:
            assert combo[2] in {"s", "o"}


def test_build_spot_solution_is_position_aware():
    btn = build_spot_solution(
        context="rfi", position="BTN", depth_bb=100, samples_per_combo=0
    )
    utg = build_spot_solution(
        context="rfi", position="UTG", depth_bb=100, samples_per_combo=0
    )
    assert btn["K9s"]["raise"] == 1.0
    assert utg["K9s"]["fold"] == 1.0
    assert btn["72o"]["fold"] == 1.0


def test_build_spot_solution_vs_raise_has_a_real_call_band():
    bb = build_spot_solution(
        context="vs_raise", position="BB", depth_bb=100, samples_per_combo=0
    )
    assert bb["AA"]["raise"] == 1.0
    assert bb["ATo"]["call"] == 1.0
    assert bb["72o"]["fold"] == 1.0
    assert any(entry["call"] == 1.0 for entry in bb.values())

    # Les positions 6-max hors BB jouent 3-bet or fold : pas de call.
    sb = build_spot_solution(
        context="vs_raise", position="SB", depth_bb=100, samples_per_combo=0
    )
    assert all(entry["call"] == 0.0 for entry in sb.values())


def test_hu_tables_use_heads_up_ranges():
    hu_rfi = build_spot_solution(
        context="hu_rfi", position="SB", depth_bb=100, samples_per_combo=0, heads_up=True
    )
    assert hu_rfi["K2s"]["raise"] == 1.0
    assert hu_rfi["72o"]["fold"] == 1.0

    hu_defense = build_spot_solution(
        context="hu_vs_raise",
        position="SB",
        depth_bb=100,
        samples_per_combo=0,
        heads_up=True,
    )
    assert hu_defense["AA"]["raise"] == 1.0
    assert hu_defense["K5s"]["call"] == 1.0
    assert hu_defense["72o"]["fold"] == 1.0


def test_store_loads_hu_context_keys(tmp_path):
    store = PreflopSolutionStore(tmp_path)
    store.save_table("hu_rfi", "SB", 100, _tiny_table())

    reloaded = PreflopSolutionStore(tmp_path)
    strategy = reloaded.get_strategy("hu_rfi", "SB", 100)
    assert strategy is not None
    assert strategy["AA"]["raise"] == 1.0


def test_heads_up_precomputed_uses_hu_sb_table(tmp_path):
    store = PreflopSolutionStore(tmp_path)
    store.save_table("hu_rfi", "SB", 100, _tiny_table())

    decision_maker = DecisionMaker(
        FakeDB(), solver_backend=None, rl_agent=None, heads_up=True
    )
    decision_maker.configure_preflop(mode="precomputed", solutions_path=str(tmp_path))
    action, details = decision_maker._run_preflop_dual_mode(
        hero_hand="AsAc",
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="btn",
        action_history=[],
        effective_stack=100.0,
        pot=1.5,
        facing_raise=False,
        aggressive_action="RAISE",
    )
    assert details["backend"] == "preflop_precomputed"
    assert details["preflop_solution"]["spot_key"] == "hu_rfi_SB_100"
    assert action in {"RAISE", "BET", "ALL_IN"}


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


def _charts_hu_maker() -> DecisionMaker:
    maker = DecisionMaker(FakeDB(), solver_backend=None, rl_agent=None, heads_up=True)
    maker.configure_preflop(mode="charts")
    return maker


def test_facing_raise_ignores_blind_completion():
    assert (
        DecisionMaker._is_facing_preflop_raise(
            ["FOLD", "CALL", "RAISE"], action_history=[]
        )
        is False
    )
    history = [{"player": "villain", "action": "raise", "street": "PREFLOP"}]
    assert (
        DecisionMaker._is_facing_preflop_raise(
            ["FOLD", "CALL", "RAISE"], action_history=history
        )
        is True
    )
    # Sans historique fourni, l'heuristique historique reste le repli.
    assert (
        DecisionMaker._is_facing_preflop_raise(
            ["FOLD", "CALL", "RAISE"], action_history=None
        )
        is True
    )


def test_heads_up_button_opens_instead_of_folding():
    maker = _charts_hu_maker()
    action, details = maker._run_preflop_fast_path(
        hero_hand="KhTd",
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="btn",
        action_history=[],
        effective_stack=200.0,
        pot=1.5,
    )
    assert details["backend"] == "preflop_fast_path"
    assert action == "RAISE"
    assert details["backend_details"]["hero_position"] == "BTN"


def test_heads_up_big_blind_defends_but_folds_junk():
    maker = _charts_hu_maker()
    facing_raise = [{"player": "villain", "action": "raise", "street": "PREFLOP"}]
    action, _ = maker._run_preflop_fast_path(
        hero_hand="AhTd",
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="bb",
        action_history=facing_raise,
        effective_stack=200.0,
        pot=3.0,
    )
    assert action == "CALL"

    junk, _ = maker._run_preflop_fast_path(
        hero_hand="7c2d",
        legal_actions=["FOLD", "CALL", "RAISE"],
        hero_position="bb",
        action_history=facing_raise,
        effective_stack=200.0,
        pot=3.0,
    )
    assert junk == "FOLD"
