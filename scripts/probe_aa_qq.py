# -*- coding: utf-8 -*-
"""Sonde provisoire : asymétrie de convergence AA vs QQ (spot river_jam)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import postflop_solver_py

BOARD = ["2c", "7d", "Js", "4h", "9s"]


def run(hero_range, villain_range, hero_hand, tag):
    raw = postflop_solver_py.solve_spot_v2(
        hero_range=hero_range,
        villain_ranges=[villain_range],
        board=BOARD,
        starting_pot=10.0,
        effective_stack=20.0,
        legal_actions=["FOLD", "CALL", "ALL_IN"],
        spot_id=tag,
        hero_position="oop",
        action_history=[],
        num_players=2,
        use_cache=False,
        time_budget_ms=None,
        epsilon_target=0.001,
        hero_hand=hero_hand,
        sample_mixed=False,
        random_seed=None,
        rake=0.0,
        rake_cap=0.0,
    )
    data = raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)
    return {
        "tag": tag,
        "hero_range": hero_range,
        "villain_range": villain_range,
        "hero_hand": hero_hand,
        "converged": data.get("converged"),
        "exploitability": data.get("exploitability"),
        "fallback_reason": data.get("fallback_reason"),
        "chosen_action": data.get("chosen_action"),
    }


results = [
    run("AsAd", "QQ", "AsAd", "A-exact-vs-pair"),
    run("AA", "QQ", "AsAd", "B-pair-vs-pair"),
    run("AsAd", "QhQs", "AsAd", "C-exact-vs-exact"),
    run("QhQs", "AA", "QhQs", "D-working-sanity"),
    run("AdAh", "QQ", "AdAh", "E-AA-other-suits"),
]
Path("evidence/probe_results.json").write_text(
    json.dumps(results, indent=1), encoding="utf-8"
)
print(json.dumps(results, indent=1))
