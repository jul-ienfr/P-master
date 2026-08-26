"""Générateur hors-ligne des solutions préflop (Phase 1 — mode pré-calculé).

Résout les spots canoniques (RFI / vs raise / vs 3bet × position × profondeur)
par équité Monte-Carlo et stocke les stratégies compressées sous ``models/preflop/``.

Usage :
    python scripts/gen_preflop_solutions.py
    python scripts/gen_preflop_solutions.py --positions BTN SB --depths 20 100 --samples 48
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.preflop_solutions import (  # noqa: E402
    CONTEXTS,
    DEFAULT_SOLUTIONS_PATH,
    DEPTH_BUCKETS,
    PREFLOP_POSITIONS,
    PreflopSolutionStore,
    build_spot_solution,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", nargs="*", default=list(PREFLOP_POSITIONS))
    parser.add_argument("--contexts", nargs="*", default=list(CONTEXTS))
    parser.add_argument("--depths", nargs="*", type=int, default=list(DEPTH_BUCKETS))
    parser.add_argument("--samples", type=int, default=24, help="MC samples par combo")
    parser.add_argument(
        "--out", type=str, default=str(ROOT / DEFAULT_SOLUTIONS_PATH),
        help="Répertoire de sortie des .npz",
    )
    parser.add_argument("--seed", type=int, default=20260826)
    args = parser.parse_args()

    store = PreflopSolutionStore(args.out)
    started = time.perf_counter()
    written = 0

    for context in args.contexts:
        if context not in CONTEXTS:
            print(f"contexte inconnu ignoré: {context}")
            continue
        for position in args.positions:
            if position not in PREFLOP_POSITIONS:
                print(f"position inconnue ignorée: {position}")
                continue
            for depth in args.depths:
                table = build_spot_solution(
                    context=context,
                    position=position,
                    depth_bb=depth,
                    samples_per_combo=args.samples,
                    seed=args.seed + hash((context, position, depth)) % 1000,
                )
                target = store.save_table(context, position, depth, table)
                sample_combo = next(iter(table))
                print(
                    f"[{target.name}] combos={len(table)} "
                    f"ex({sample_combo})={table[sample_combo]}"
                )
                written += 1

    elapsed = time.perf_counter() - started
    print(f"solutions écrites: {written} en {elapsed:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
