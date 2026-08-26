"""Best-response réel sur un corpus de spots via le MES du solveur natif (Phase 5.17).

Remplace le pseudo-LBR circulaire basé sur les alternatives auto-déclarées : chaque spot
est résolu par le moteur DCFR et l'écart entre l'action de la politique évaluée et la
meilleure action disponible (MES-style) est mesuré côté Rust.

Usage :
    python -m research.best_response --corpus path/to/corpus.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import postflop_solver_py
except ImportError:  # pragma: no cover - binding optionnel hors build Rust
    postflop_solver_py = None


def _gap_from_native(spot: dict[str, Any], *, max_iterations: int) -> dict[str, Any]:
    response = postflop_solver_py.measure_best_response_gap(
        oop_range=str(spot["oop_range"]),
        ip_range=str(spot["ip_range"]),
        board=[str(card) for card in spot.get("board", [])],
        starting_pot=float(spot.get("starting_pot", 0.0)),
        effective_stack=float(spot.get("effective_stack", 0.0)),
        hero_is_oop=bool(spot.get("hero_is_oop", True)),
        max_iterations=int(max_iterations),
        policy_action=spot.get("policy_action"),
    )
    return {
        "policy_action": response.get("policy_action"),
        "policy_ev": round(float(response.get("policy_ev", 0.0)), 4),
        "mes_ev": round(float(response.get("mes_ev", 0.0)), 4),
        "best_response_gap": round(float(response.get("best_response_gap", 0.0)), 4),
        "exploitability": round(float(response.get("exploitability", 0.0)), 4),
        "backend": "native_mes",
    }


def _gap_from_alternatives(
    spot: dict[str, Any],
    alternatives: Sequence[dict[str, Any]] | tuple[Any, ...],
) -> dict[str, Any]:
    """Repli : estimation locale depuis les alternatives du replay (pseudo-LBR)."""
    evs: dict[str, float] = {}
    for item in alternatives:
        name = getattr(item, "name", None) or (
            item.get("name") if isinstance(item, dict) else None
        )
        ev = getattr(item, "ev", None)
        if ev is None and isinstance(item, dict):
            ev = item.get("ev")
        if name is not None and ev is not None:
            evs[str(name)] = float(ev)

    chosen = str(spot.get("policy_action") or "")
    if not evs:
        return {
            "policy_action": chosen or None,
            "policy_ev": 0.0,
            "mes_ev": 0.0,
            "best_response_gap": 0.0,
            "backend": "alternatives_fallback",
        }

    policy_ev = evs.get(chosen, min(evs.values()))
    mes_ev = max(evs.values())
    return {
        "policy_action": chosen or None,
        "policy_ev": round(policy_ev, 4),
        "mes_ev": round(mes_ev, 4),
        "best_response_gap": round(max(0.0, mes_ev - policy_ev), 4),
        "backend": "alternatives_fallback",
    }


def measure_corpus_best_response(
    spots: Sequence[dict[str, Any]],
    *,
    max_iterations: int = 200,
    gap_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mesure le gap de best-response pour chaque spot puis agrège.

    Chaque spot est un dictionnaire avec ``oop_range``, ``ip_range``, ``board``,
    ``starting_pot``, ``effective_stack``, ``hero_is_oop`` et ``policy_action``.
    Les ranges doivent être disjointes (contrainte du moteur de solve).
    """
    if gap_fn is None:
        if postflop_solver_py is None:
            raise RuntimeError(
                "postflop_solver_py indisponible : fournissez gap_fn ou recompilez le binding"
            )
        gap_fn = lambda spot: _gap_from_native(spot, max_iterations=max_iterations)  # noqa: E731

    results = [dict(gap_fn(spot)) | {"spot_id": spot.get("spot_id")} for spot in spots]
    gaps = [float(result["best_response_gap"]) for result in results]

    return {
        "spots": len(results),
        "mean_best_response_gap": round(sum(gaps) / len(gaps), 4) if gaps else 0.0,
        "max_best_response_gap": round(max(gaps), 4) if gaps else 0.0,
        "backend": results[0]["backend"] if results else "none",
        "results": results,
    }


def spots_from_replay_records(records: Sequence[Any]) -> list[dict[str, Any]]:
    """Convertit des ReplayRecords en spots exploitables par le solveur natif.

    Le héro est supposé OOP avec la première range du snapshot ; à adapter si la
    provenance des positions est disponible dans le corpus.
    """
    spots: list[dict[str, Any]] = []
    for record in records:
        spot = getattr(record, "spot", None)
        decision = getattr(record, "decision", None)
        if spot is None or decision is None:
            continue
        ranges = list(getattr(spot, "ranges", []) or [])
        if len(ranges) < 2:
            continue
        spots.append(
            {
                "spot_id": getattr(record, "replay_id", None) or getattr(spot, "spot_id", None),
                "oop_range": ranges[0],
                "ip_range": ranges[1],
                "board": list(getattr(spot, "board", []) or []),
                "starting_pot": float(getattr(spot, "pot", 0.0) or 0.0),
                "effective_stack": float(getattr(spot, "effective_stack", 0.0) or 0.0),
                "hero_is_oop": True,
                "policy_action": getattr(decision, "action", None),
            }
        )
    return spots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=str, required=True,
                        help="JSON listant les spots (oop_range/ip_range/board/...)")
    parser.add_argument("--max-iterations", type=int, default=200)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    spots = payload.get("spots", payload) if isinstance(payload, dict) else payload

    summary = measure_corpus_best_response(spots, max_iterations=args.max_iterations)

    output = json.dumps(summary, indent=2)
    print(output)
    output_path = args.output or str(ROOT / "research" / "results" / "best_response.json")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(output + "\n", encoding="utf-8")
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
