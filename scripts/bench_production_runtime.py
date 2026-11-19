"""Benchmark headless du runtime de production (Phase 1.7).

Contrairement au benchmark Slumbot, qui mesure la politique de recherche
``hero_heuristic``, ce script appelle ``DecisionMaker.get_best_action`` : gate,
preflop store, solveur Rust, cache et fallbacks compris. Il répond à la question
« combien coûte et que décide le produit ? » sur un corpus fixe de spots.

Usage :
    python scripts/bench_production_runtime.py
    python scripts/bench_production_runtime.py --bet-sizes 50% --raise-sizes 2.5x --repeat 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.decision_maker import DecisionMaker  # noqa: E402

DEFAULT_OUTPUT = ROOT / "research" / "results" / "runtime_benchmark.json"
DEFAULT_MULTIWAY_OUTPUT = ROOT / "research" / "results" / "runtime_multiway_benchmark.json"

MULTIWAY_SPOTS: list[dict[str, Any]] = [
    {
        "spot_id": "multiway_3way_flop",
        "num_players": 3,
        "active_positions": ["UTG", "BTN", "BB"],
        "hero_player_index": 1,
        "hero_position": "BTN",
        "villain_ranges": ["AA,KK,QQ", "AKs,AQo+,TT+"],
        "street": "flop",
        "hero_hand": "AhKd",
        "board": ["Jc", "7s", "2d"],
        "pot": 6.0,
        "effective_stack": 97.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
    },
    {
        "spot_id": "multiway_4way_flop",
        "num_players": 4,
        "active_positions": ["UTG", "CO", "BTN", "BB"],
        "hero_player_index": 2,
        "hero_position": "BTN",
        "villain_ranges": ["AA,KK,QQ", "AKs,AQo+,TT+", "JJ+,AKs"],
        "street": "flop",
        "hero_hand": "QsQd",
        "board": ["9h", "8c", "3c"],
        "pot": 20.0,
        "effective_stack": 85.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
    },
    {
        "spot_id": "multiway_5way_turn",
        "num_players": 5,
        "active_positions": ["UTG", "MP", "CO", "BTN", "BB"],
        "hero_player_index": 3,
        "hero_position": "BTN",
        "villain_ranges": ["AA,KK,QQ", "AKs,AQo+,TT+", "JJ+,AKs", "AQ+,KQ"],
        "street": "turn",
        "hero_hand": "Ts9s",
        "board": ["Ks", "7h", "2c", "4d"],
        "pot": 14.0,
        "effective_stack": 78.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
    },
    {
        "spot_id": "multiway_6way_river",
        "num_players": 6,
        "active_positions": ["UTG", "MP", "HJ", "CO", "BTN", "BB"],
        "hero_player_index": 4,
        "hero_position": "BTN",
        "villain_ranges": [
            "AA,KK,QQ",
            "AKs,AQo+,TT+",
            "JJ+,AKs",
            "AQ+,KQ",
            "99+,AJs+,KQo",
        ],
        "street": "river",
        "hero_hand": "5c5d",
        "board": ["Ah", "Kd", "9c", "2s", "7h"],
        "pot": 30.0,
        "effective_stack": 60.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
    },
]

SPOTS: list[dict[str, Any]] = [
    {
        "spot_id": "preflop_btn_aa",
        "street": "preflop",
        "hero_hand": "AsAd",
        "board": [],
        "pot": 1.5,
        "effective_stack": 100.0,
        "legal_actions": ["fold", "call", "raise"],
        "hero_position": "btn",
    },
    {
        "spot_id": "preflop_bb_kqo_face_open",
        "street": "preflop",
        "hero_hand": "KhQd",
        "board": [],
        "pot": 4.0,
        "effective_stack": 98.0,
        "legal_actions": ["fold", "call", "raise"],
        "hero_position": "bb",
        "action_history": [
            {"player": "villain", "action": "raise", "amount": 2.5},
        ],
    },
    {
        "spot_id": "flop_srp_akhk",
        "street": "flop",
        "hero_hand": "AhKh",
        "board": ["Jc", "7s", "2d"],
        "pot": 6.0,
        "effective_stack": 97.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
        "hero_position": "ip",
    },
    {
        "spot_id": "flop_3bp_qq",
        "street": "flop",
        "hero_hand": "QsQd",
        "board": ["9h", "8c", "3c"],
        "pot": 20.0,
        "effective_stack": 85.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
        "hero_position": "oop",
    },
    {
        "spot_id": "turn_ts9s",
        "street": "turn",
        "hero_hand": "Ts9s",
        "board": ["Ks", "7h", "2c", "4d"],
        "pot": 14.0,
        "effective_stack": 78.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
        "hero_position": "ip",
    },
    {
        "spot_id": "river_55",
        "street": "river",
        "hero_hand": "5c5d",
        "board": ["Ah", "Kd", "9c", "2s", "7h"],
        "pot": 30.0,
        "effective_stack": 60.0,
        "legal_actions": ["check", "bet_50", "bet_75", "allin"],
        "hero_position": "ip",
    },
]


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(ratio * len(ordered)))
    return ordered[index]


def _memory_rss_mb() -> float:
    try:
        import psutil
    except ImportError:
        return 0.0
    return round(psutil.Process().memory_info().rss / (1024.0 * 1024.0), 1)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cold = [row["elapsed_ms"] for row in rows if row["pass"] == "cold"]
    warm = [row["elapsed_ms"] for row in rows if row["pass"] == "warm"]
    return {
        "runs": len(rows),
        "cold_ms_p50": round(statistics.median(cold), 1) if cold else 0.0,
        "cold_ms_p95": round(_percentile(cold, 0.95), 1),
        "warm_ms_p50": round(statistics.median(warm), 1) if warm else 0.0,
        "warm_ms_p95": round(_percentile(warm, 0.95), 1),
        "fallbacks": sum(1 for row in rows if row.get("fallback_used")),
        "cache_hits": sum(1 for row in rows if row.get("cache_hit")),
        "exploitability_max": round(max((row.get("exploitability") or 0.0) for row in rows), 4),
    }


def _summarize_multiway(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_players: dict[str, Any] = {}
    for num_players in sorted({int(row["num_players"]) for row in rows}):
        group = [row for row in rows if int(row["num_players"]) == num_players]
        cold = [row["elapsed_ms"] for row in group if row["pass"] == "cold"]
        warm = [row["elapsed_ms"] for row in group if row["pass"] == "warm"]
        by_players[str(num_players)] = {
            "runs": len(group),
            "cold_ms_p50": round(statistics.median(cold), 1) if cold else 0.0,
            "cold_ms_p95": round(_percentile(cold, 0.95), 1),
            "warm_ms_p50": round(statistics.median(warm), 1) if warm else 0.0,
            "warm_ms_p95": round(_percentile(warm, 0.95), 1),
            "memory_rss_mb": round(max((row.get("memory_rss_mb") or 0.0) for row in group), 1),
            "multiway_backends": sorted(
                {
                    str(row.get("backend"))
                    for row in group
                    if row.get("backend") in {"multiway_mccfr", "multiway"}
                }
            ),
            "fallbacks": sum(1 for row in group if row.get("fallback_used")),
            "sampled": sum(1 for row in group if row.get("sampled") is True),
        }
    return {
        "runs": len(rows),
        "by_num_players": by_players,
        "fallbacks": sum(1 for row in rows if row.get("fallback_used")),
        "multiway_backends": sorted(
            {
                str(row.get("backend"))
                for row in rows
                if row.get("backend") in {"multiway_mccfr", "multiway"}
            }
        ),
        "max_memory_rss_mb": round(max((row.get("memory_rss_mb") or 0.0) for row in rows), 1),
    }


async def _run_spot(
    maker: DecisionMaker,
    spot: dict[str, Any],
    *,
    pass_name: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = await maker.get_best_action(
        spot["hero_hand"],
        list(spot["board"]),
        float(spot["pot"]),
        float(spot["effective_stack"]),
        "villain",
        list(spot["legal_actions"]),
        spot_id=spot["spot_id"],
        hero_position=spot["hero_position"],
        state_confidence=0.9,
        action_history=spot.get("action_history"),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "spot_id": spot["spot_id"],
        "street": spot["street"],
        "pass": pass_name,
        "action": result.get("action"),
        "bet_size": result.get("bet_size"),
        "source": result.get("source"),
        "fallback_used": bool(result.get("fallback_used")),
        "fallback_reason": result.get("fallback_reason"),
        "cache_hit": bool(result.get("cache_hit")),
        "exploitability": result.get("exploitability"),
        "backend": result.get("backend"),
        "elapsed_ms": round(elapsed_ms, 1),
        "reported_ms": result.get("elapsed_ms"),
    }


async def _run_multiway_spot(
    maker: DecisionMaker,
    spot: dict[str, Any],
    *,
    pass_name: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = await maker.get_best_action(
        spot["hero_hand"],
        list(spot["board"]),
        float(spot["pot"]),
        float(spot["effective_stack"]),
        "villain",
        list(spot["legal_actions"]),
        spot_id=spot["spot_id"],
        hero_position=spot["hero_position"],
        state_confidence=0.9,
        num_players=int(spot["num_players"]),
        villain_ranges=list(spot["villain_ranges"]),
        hero_player_index=int(spot["hero_player_index"]),
        active_positions=list(spot["active_positions"]),
        primary_villain_index=0,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    multiway = metadata.get("multiway") if isinstance(metadata.get("multiway"), dict) else {}
    return {
        "spot_id": spot["spot_id"],
        "street": spot["street"],
        "num_players": int(spot["num_players"]),
        "pass": pass_name,
        "action": result.get("action"),
        "source": result.get("source"),
        "fallback_used": bool(result.get("fallback_used")),
        "fallback_reason": result.get("fallback_reason"),
        "cache_hit": bool(result.get("cache_hit")),
        "backend": result.get("backend"),
        "converged": multiway.get("converged"),
        "sampled": bool(multiway.get("sampled", False)),
        "warnings": list(multiway.get("warnings") or []),
        "elapsed_ms": round(elapsed_ms, 1),
        "reported_ms": result.get("elapsed_ms"),
        "memory_rss_mb": _memory_rss_mb(),
    }


async def run(*, bet_sizes: str | None, raise_sizes: str | None, repeat: int) -> dict[str, Any]:
    maker = DecisionMaker(
        None,
        create_rl_agent=False,
        autoload_rl_model=False,
        heads_up=True,
    )
    if bet_sizes:
        maker.solver_bet_sizes = bet_sizes
    if raise_sizes:
        maker.solver_raise_sizes = raise_sizes

    rows: list[dict[str, Any]] = []
    for _ in range(max(1, repeat)):
        for spot in SPOTS:
            rows.append(await _run_spot(maker, spot, pass_name="cold"))
            rows.append(await _run_spot(maker, spot, pass_name="warm"))

    return {
        "kind": "runtime_benchmark",
        "bet_sizes": maker.solver_bet_sizes,
        "raise_sizes": maker.solver_raise_sizes,
        "heads_up": True,
        "spots": SPOTS,
        "results": rows,
        "summary": _summarize(rows),
    }


async def run_multiway(
    *, bet_sizes: str | None, raise_sizes: str | None, repeat: int
) -> dict[str, Any]:
    maker = DecisionMaker(
        None,
        create_rl_agent=False,
        autoload_rl_model=False,
        heads_up=True,
    )
    if bet_sizes:
        maker.solver_bet_sizes = bet_sizes
    if raise_sizes:
        maker.solver_raise_sizes = raise_sizes

    rows: list[dict[str, Any]] = []
    for _ in range(max(1, repeat)):
        for spot in MULTIWAY_SPOTS:
            rows.append(await _run_multiway_spot(maker, spot, pass_name="cold"))
            rows.append(await _run_multiway_spot(maker, spot, pass_name="warm"))

    return {
        "kind": "runtime_multiway_benchmark",
        "bet_sizes": maker.solver_bet_sizes,
        "raise_sizes": maker.solver_raise_sizes,
        "multiway_max_players": maker.multiway_max_players,
        "spots": MULTIWAY_SPOTS,
        "results": rows,
        "summary": _summarize_multiway(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bet-sizes", type=str, default=None)
    parser.add_argument("--raise-sizes", type=str, default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--mode", choices=("heads-up", "multiway"), default="heads-up")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or (DEFAULT_MULTIWAY_OUTPUT if args.mode == "multiway" else DEFAULT_OUTPUT)

    logging.getLogger("src.bot.decision_maker").setLevel(logging.WARNING)
    runner = run if args.mode == "heads-up" else run_multiway
    payload = asyncio.run(
        runner(bet_sizes=args.bet_sizes, raise_sizes=args.raise_sizes, repeat=args.repeat)
    )

    for row in payload["results"]:
        n = f" n={row['num_players']}" if "num_players" in row else ""
        print(
            f"{row['spot_id']:<28} {row['pass']:<5}{n:<5} {row['action']:<6} "
            f"{row['source']:<12} {row['elapsed_ms']:>8.1f} ms "
            f"cache={row['cache_hit']}"
        )
    print(json.dumps(payload["summary"], indent=2))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"saved={output}")


if __name__ == "__main__":
    main()
