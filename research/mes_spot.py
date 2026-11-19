"""Mesure MES native d'un preset de l'arbre (Phase 1.6).

Le solveur Rust évalue un spot unique et renvoie l'EV de l'action de politique,
l'EV de la meilleure réponse et l'exploitabilité du spot. Les ranges des presets
se chevauchent ; elles sont rendues disjointes avant l'appel et les combos
retirés sont conservés dans le résultat (``removed_overlap``).

Usage :
    python -m research.mes_spot --preset srp_hu_100bb --max-iterations 20
    python -m research.mes_spot --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poker.decisionmaker.tree_presets import (  # noqa: E402
    TreePresetDefinition,
    list_tree_presets,
)
from research import best_response  # noqa: E402

OOP_POSITIONS = {
    "oop",
    "out_of_position",
    "out-of-position",
    "sb",
    "small_blind",
    "small blind",
    "utg",
    "under_the_gun",
    "under the gun",
    "ep",
    "early_position",
    "early position",
}


def spot_from_preset(preset: TreePresetDefinition) -> dict[str, Any]:
    """Construit le spot du solveur depuis un preset, héro inclus."""
    hero_is_oop = preset.hero_position.strip().lower() in OOP_POSITIONS
    if hero_is_oop:
        oop_range, ip_range = preset.hero_range, preset.villain_ranges[0]
    else:
        oop_range, ip_range = preset.villain_ranges[0], preset.hero_range
    return {
        "spot_id": f"preset:{preset.preset_id}",
        "oop_range": oop_range,
        "ip_range": ip_range,
        "board": list(preset.board),
        "starting_pot": preset.starting_pot,
        "effective_stack": preset.effective_stack,
        "hero_is_oop": hero_is_oop,
        "policy_action": "check" if "check" in preset.legal_actions else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", type=str, default=None)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    presets = list_tree_presets()
    if args.list:
        for preset in presets:
            print(f"{preset.preset_id}\t{preset.title}\t{preset.hero_position}")
        return

    if best_response.postflop_solver_py is None:
        raise SystemExit(
            "postflop_solver_py indisponible : recompiler le binding Rust "
            "(maturin develop --release) avant de lancer ce script"
        )

    if args.preset:
        preset = next((item for item in presets if item.preset_id == args.preset), None)
        if preset is None:
            available = ", ".join(item.preset_id for item in presets)
            raise SystemExit(f"preset inconnu : {args.preset} (disponibles : {available})")
    else:
        preset = presets[0]

    spot = spot_from_preset(preset)
    result = best_response.measure_spot_best_response(
        spot,
        max_iterations=args.max_iterations,
    )
    payload = {
        "kind": "mes_spot",
        "preset_id": preset.preset_id,
        "title": preset.title,
        "policy_action": spot["policy_action"],
        "spot": spot,
        "result": result,
    }

    print(json.dumps(payload, indent=2, sort_keys=True))
    output = args.output or (
        ROOT / "research" / "results" / f"mes_{preset.preset_id}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"saved={output}")


if __name__ == "__main__":
    main()
