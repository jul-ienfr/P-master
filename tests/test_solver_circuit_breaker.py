"""Tests Phase 2.6 — circuit breaker solver exponentiel et métriqué."""

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.decision_maker import _SOLVER_BREAKER_THRESHOLD, DecisionMaker


class FakeDB:
    is_available = False

    async def get_player_profile(self, villain_name):
        return None


class FakeSolver:
    backend_name = "fake_solver"

    def solve_spot_v2(self, **kwargs):  # jamais atteint si wait_for patché
        return {"chosen_action": "FOLD", "actions": [{"action": "FOLD", "freq": 1.0}]}


def _make_decision_maker():
    return DecisionMaker(FakeDB(), solver_backend=FakeSolver(), rl_agent=None)


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


def test_breaker_inactive_by_default():
    dm = _make_decision_maker()
    state = dm.solver_circuit_breaker_state()
    assert state == {
        "active": False,
        "consecutive_timeouts": 0,
        "cooldown_remaining_s": 0.0,
        "threshold": _SOLVER_BREAKER_THRESHOLD,
    }


def test_timeout_below_threshold_does_not_trip_breaker():
    dm = _make_decision_maker()
    for _ in range(_SOLVER_BREAKER_THRESHOLD - 1):
        dm._register_solver_timeout()
    state = dm.solver_circuit_breaker_state()
    assert state["active"] is False
    assert state["consecutive_timeouts"] == _SOLVER_BREAKER_THRESHOLD - 1
    assert dm._solver_cooldown_until == 0.0


def test_breaker_backoff_is_exponential_and_capped(monkeypatch):
    dm = _make_decision_maker()
    clock = {"t": 1000.0}
    monkeypatch.setattr("src.bot.decision_maker.time.monotonic", lambda: clock["t"])

    for _ in range(_SOLVER_BREAKER_THRESHOLD - 1):
        dm._register_solver_timeout()
        assert dm._solver_cooldown_until == 0.0

    expected = [60.0, 120.0, 240.0, 300.0, 300.0]
    for cooldown in expected:
        clock["t"] += 1.0
        dm._register_solver_timeout()
        remaining = dm._solver_cooldown_until - clock["t"]
        assert remaining == pytest.approx(cooldown), (
            f"cooldown attendu {cooldown}s, obtenu {remaining}s"
        )


def test_success_resets_consecutive_timeouts(monkeypatch):
    import src.bot.decision_maker as dm_module

    dm = _make_decision_maker()
    clock = {"t": 1000.0}
    monkeypatch.setattr("src.bot.decision_maker.time.monotonic", lambda: clock["t"])

    dm._register_solver_timeout()
    dm._register_solver_timeout()

    real_wait_for = dm_module.asyncio.wait_for
    calls = {"n": 0}

    async def flaky_wait_for(coro, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError()
        return await real_wait_for(coro, timeout=timeout)

    monkeypatch.setattr(dm_module.asyncio, "wait_for", flaky_wait_for)

    first = asyncio.run(dm.get_best_action(**_request()))
    assert first["fallback_reason"] == "solver_timeout"
    assert first["metadata"]["solver"]["circuit_breaker"]["consecutive_timeouts"] == 3

    # On repasse le cooldown (60s) avant l'appel suivant.
    clock["t"] += 61.0

    second = asyncio.run(dm.get_best_action(**_request()))
    assert second["fallback_used"] is False
    breaker = second["metadata"]["solver"]["circuit_breaker"]
    assert breaker["consecutive_timeouts"] == 0
    assert breaker["active"] is False


def test_active_breaker_short_circuits_solver_call(monkeypatch):
    dm = _make_decision_maker()

    def boom(*args, **kwargs):
        raise AssertionError("solver ne doit pas être appelé pendant le cooldown")

    monkeypatch.setattr("src.bot.decision_maker.time.monotonic", lambda: 500.0)
    dm._consecutive_solver_timeouts = 5
    dm._solver_cooldown_until = 1000.0

    fallback = asyncio.run(dm.get_best_action(**_request()))
    assert fallback["action"] == "FOLD"
    assert fallback["source"] == "FALLBACK"
    assert fallback["metadata"]["solver"]["circuit_breaker"]["active"] is True
