"""Tests Phase 3.6 — cache solve en mémoire (LRU + TTL)."""
import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import DecisionMaker


class FakeDB:
    is_available = False

    async def get_player_profile(self, villain_name):
        return None


class CountingSolver:
    backend_name = "counting_solver"

    def __init__(self):
        self.calls = 0

    def solve_spot_v2(self, **kwargs):
        self.calls += 1
        return {
            "chosen_action": "BET_75",
            "hero_ev": 1.0,
            "exploitability": 0.02,
            "decision_confidence": 0.9,
            "actions": [{"action": "BET_75", "freq": 1.0}],
            "elapsed_ms": 5,
            "backend": "counting_solver",
        }


def _make_dm_and_solver():
    solver = CountingSolver()
    dm = DecisionMaker(FakeDB(), solver_backend=solver, rl_agent=None)
    return dm, solver


def _request(**overrides):
    payload = {
        "hero_hand": "AhKd",
        "board": ["2c", "7d", "Jh"],
        "pot": 10.0,
        "effective_stack": 80.0,
        "villain_name": "Villain",
        "legal_actions": ["FOLD", "CALL", "BET"],
    }
    payload.update(overrides)
    return payload


def test_repeated_identical_spot_hits_cache_once():
    dm, solver = _make_dm_and_solver()

    first = asyncio.run(dm.get_best_action(**_request()))
    second = asyncio.run(dm.get_best_action(**_request()))

    assert solver.calls == 1
    assert first["backend"] == "counting_solver"
    assert second["cache_hit"] is True
    assert second["metadata"]["solver"]["cache_hit"] is True
    # La décision elle-même est identique.
    assert second["action"] == first["action"]


def test_different_board_misses_cache():
    dm, solver = _make_dm_and_solver()

    asyncio.run(dm.get_best_action(**_request()))
    asyncio.run(dm.get_best_action(**_request(board=["2c", "7d", "8s"])))

    assert solver.calls == 2


def test_ttl_expiry_forces_new_solve(monkeypatch):
    dm, solver = _make_dm_and_solver()
    clock = {"t": 1000.0}
    monkeypatch.setattr("src.bot.decision_maker.time.monotonic", lambda: clock["t"])

    asyncio.run(dm.get_best_action(**_request()))
    clock["t"] += dm._solve_cache_ttl_s + 1.0
    asyncio.run(dm.get_best_action(**_request()))

    assert solver.calls == 2


def test_fallback_responses_are_not_cached():
    class FailingSolver:
        backend_name = "failing_solver"

        def __init__(self):
            self.calls = 0

        def solve_spot_v2(self, **kwargs):
            self.calls += 1
            raise RuntimeError("boom")

    solver = FailingSolver()
    dm = DecisionMaker(FakeDB(), solver_backend=solver, rl_agent=None)

    first = asyncio.run(dm.get_best_action(**_request()))
    second = asyncio.run(dm.get_best_action(**_request()))

    assert solver.calls == 2
    assert first["fallback_used"] is True
    assert second["fallback_used"] is True


def test_lru_eviction_respects_max_entries():
    dm, _ = _make_dm_and_solver()
    dm._solve_cache_max_entries = 4

    for i in range(6):
        key = f"key_{i}"
        dm._solve_cache_put(key, {"chosen_action": "FOLD"})

    assert len(dm._solve_cache) == 4
    # Les plus anciens sont évincés.
    assert "key_0" not in dm._solve_cache
    assert "key_5" in dm._solve_cache
