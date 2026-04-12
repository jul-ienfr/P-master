"""Benchmark harness for the native equity pipeline versus legacy Python Monte Carlo.

Run this module from the repository root after either:
1. installing the `postflop_solver_py` extension, or
2. starting the local `gto_server` on http://127.0.0.1:8765.
"""

from __future__ import annotations

import json
import pathlib
import statistics
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import requests

from poker.decisionmaker.montecarlo_python import MonteCarlo
from poker.decisionmaker.native_equity import (
    GTO_SERVER_URL,
    call_native_api,
    call_native_binding,
    percent_to_range_string,
)


@dataclass(frozen=True)
class OpponentPool:
    name: str
    percent: float


@dataclass(frozen=True)
class BenchmarkScenario:
    name: str
    hero_hand: tuple[str, str]
    board: tuple[str, ...]
    pool: OpponentPool
    players: int
    max_samples: int


POOLS = {
    "nit": OpponentPool("nit", 0.12),
    "tag": OpponentPool("tag", 0.22),
    "lag": OpponentPool("lag", 0.35),
    "calling_station": OpponentPool("calling_station", 0.55),
    "random": OpponentPool("random", 1.0),
    "baseline": OpponentPool("baseline", 0.25),
}


SCENARIOS = [
    BenchmarkScenario(
        name="preflop_aks_tag",
        hero_hand=("As", "Ks"),
        board=(),
        pool=POOLS["tag"],
        players=2,
        max_samples=3000,
    ),
    BenchmarkScenario(
        name="flop_overpair_nit",
        hero_hand=("Ah", "Ad"),
        board=("2c", "7d", "9h"),
        pool=POOLS["nit"],
        players=2,
        max_samples=5000,
    ),
    BenchmarkScenario(
        name="turn_combo_draw_lag",
        hero_hand=("Kh", "Qh"),
        board=("Jh", "Th", "2c", "4d"),
        pool=POOLS["lag"],
        players=2,
        max_samples=4000,
    ),
    BenchmarkScenario(
        name="river_multiway_random",
        hero_hand=("As", "Ah"),
        board=("Ad", "7h", "2c", "9s", "3d"),
        pool=POOLS["random"],
        players=4,
        max_samples=3000,
    ),
]


SERVER_EXECUTABLE_CANDIDATES = (
    pathlib.Path("gto_server/target/release/gto_server.exe"),
    pathlib.Path("gto_server/target/debug/gto_server.exe"),
)


def benchmark_native_equity(
    scenario: BenchmarkScenario,
    runs: int,
    seed: int,
) -> dict[str, Any]:
    villain_ranges = [
        percent_to_range_string(scenario.pool.percent) for _ in range(max(1, scenario.players - 1))
    ]
    payload = {
        "hero_hand": list(scenario.hero_hand),
        "villain_ranges": villain_ranges,
        "board": list(scenario.board),
        "dead_cards": [],
        "mode": "auto",
        "max_samples": scenario.max_samples,
        "seed": seed,
        "use_cache": False,
    }

    timings = []
    equities = []
    for _ in range(runs):
        start = time.perf_counter()
        response = call_native_api("evaluate_equity", "/equity", payload)
        timings.append(time.perf_counter() - start)
        equities.append(float(response["equity"]))

    return summarize_engine("native", timings, equities)


def benchmark_python_montecarlo(
    scenario: BenchmarkScenario,
    runs: int,
    seed: int,
) -> dict[str, Any]:
    opponent_range = scenario.pool.percent
    player_cards = [[card.upper() for card in scenario.hero_hand]]
    board = [card.upper() for card in scenario.board]

    timings = []
    equities = []
    for offset in range(runs):
        np.random.seed(seed + offset)
        simulation = MonteCarlo()
        start = time.perf_counter()
        simulation.run_montecarlo(
            logger=type("Logger", (), {"info": lambda *args, **kwargs: None})(),
            original_player_card_list=player_cards,
            original_table_card_list=board,
            player_amount=scenario.players,
            ui=None,
            max_runs=scenario.max_samples,
            timeout=time.time() + 30,
            ghost_cards="",
            opponent_range=opponent_range,
        )
        timings.append(time.perf_counter() - start)
        equities.append(float(simulation.equity))

    return summarize_engine("python_montecarlo", timings, equities)


def summarize_engine(name: str, timings: list[float], equities: list[float]) -> dict[str, Any]:
    return {
        "engine": name,
        "runs": len(timings),
        "avg_ms": round(statistics.mean(timings) * 1000, 2),
        "median_ms": round(statistics.median(timings) * 1000, 2),
        "min_ms": round(min(timings) * 1000, 2),
        "max_ms": round(max(timings) * 1000, 2),
        "avg_equity": round(statistics.mean(equities), 4),
        "equity_stdev": round(statistics.pstdev(equities), 4),
    }


def run_suite(runs: int = 5, seed: int = 42) -> list[dict[str, Any]]:
    server_process = ensure_native_backend()
    try:
        report = []
        for scenario in SCENARIOS:
            native = benchmark_native_equity(scenario, runs=runs, seed=seed)
            python = benchmark_python_montecarlo(scenario, runs=runs, seed=seed)
            speedup = round(python["avg_ms"] / native["avg_ms"], 2) if native["avg_ms"] else None
            report.append(
                {
                    "scenario": scenario.name,
                    "pool": scenario.pool.name,
                    "players": scenario.players,
                    "native": native,
                    "python_montecarlo": python,
                    "speedup_native_vs_python": speedup,
                    "equity_delta": round(native["avg_equity"] - python["avg_equity"], 4),
                }
            )
        return report
    finally:
        if server_process is not None:
            server_process.terminate()
            server_process.wait(timeout=5)


def ensure_native_backend():
    binding_probe = call_native_binding(
        "evaluate_equity",
        {
            "hero_hand": ["As", "Ah"],
            "villain_ranges": ["KcKd"],
            "board": ["2c", "7d", "9h", "Js", "Qd"],
            "mode": "exact",
            "use_cache": False,
        },
    )
    if binding_probe is not None:
        return None

    if http_backend_ready():
        return None

    for executable in SERVER_EXECUTABLE_CANDIDATES:
        if executable.exists():
            process = subprocess.Popen(
                [str(executable)],
                cwd=pathlib.Path("."),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if wait_for_http_backend(timeout_sec=10):
                return process
            process.terminate()
            process.wait(timeout=5)

    raise RuntimeError(
        "No native backend available. Build gto_server or install postflop_solver_py before benchmarking."
    )


def http_backend_ready():
    payload = {
        "hero_hand": ["Ah", "Ad"],
        "villain_ranges": ["KcKd"],
        "board": ["2c", "7d", "9h", "Js", "Qd"],
        "mode": "exact",
        "use_cache": False,
    }
    try:
        response = requests.post(f"{GTO_SERVER_URL}/equity", json=payload, timeout=1)
    except requests.RequestException:
        return False
    return response.ok


def wait_for_http_backend(timeout_sec: int):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if http_backend_ready():
            return True
        time.sleep(0.25)
    return False


if __name__ == "__main__":
    print(json.dumps(run_suite(), indent=2))
