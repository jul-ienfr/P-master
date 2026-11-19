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

_RANKS = "23456789TJQKA"


def _expand_token(token: str) -> set[str]:
    """Étend une notation 169 (``22+``, ``A2s+``, ``88-JJ``, ``A5s-A2s``)."""
    token = token.strip()
    if not token:
        return set()
    if "-" in token:
        left, right = token.split("-", 1)
        if len(left) == 2 and left[0] == left[1] and right[0] == right[1]:
            start = min(_RANKS.index(left[0]), _RANKS.index(right[0]))
            end = max(_RANKS.index(left[0]), _RANKS.index(right[0]))
            return {f"{_RANKS[index]}{_RANKS[index]}" for index in range(start, end + 1)}
        if (
            len(left) == 3
            and len(right) == 3
            and left[0] == right[0]
            and left[2] == right[2]
        ):
            start = min(_RANKS.index(left[1]), _RANKS.index(right[1]))
            end = max(_RANKS.index(left[1]), _RANKS.index(right[1]))
            return {
                f"{left[0]}{_RANKS[index]}{left[2]}" for index in range(start, end + 1)
            }
        return {left, right}
    if token.endswith("+"):
        base = token[:-1]
        if len(base) == 2 and base[0] == base[1]:
            start = _RANKS.index(base[0])
            return {f"{_RANKS[index]}{_RANKS[index]}" for index in range(start, len(_RANKS))}
        if len(base) == 3 and base[2] in "so":
            start = _RANKS.index(base[1])
            end = _RANKS.index(base[0]) - 1
            return {
                f"{base[0]}{_RANKS[index]}{base[2]}" for index in range(start, end + 1)
            }
    return {token}


def expand_range(range_string: str) -> set[str]:
    """Développe une range textuelle en ensemble de combos 169."""
    combos: set[str] = set()
    for token in str(range_string).split(","):
        combos |= _expand_token(token)
    return combos


def ranges_overlap(first: str, second: str) -> set[str]:
    """Combos présents dans les deux ranges (le solveur les refuse)."""
    return expand_range(first) & expand_range(second)


def make_ranges_disjoint(first: str, second: str) -> tuple[str, str]:
    """Retire de ``second`` les combos déjà couverts par ``first``."""
    first_set = expand_range(first)
    second_set = expand_range(second) - first_set
    return ",".join(sorted(first_set)), ",".join(sorted(second_set))


def make_spot_ranges_disjoint(
    oop_range: str,
    ip_range: str,
) -> tuple[str, str]:
    """Rend deux ranges disjointes en préservant la plus petite.

    Les presets décrivent souvent la range héro comme un sous-ensemble de la
    range adverse. Soustraire systématiquement l'OOP de l'IP viderait alors
    l'IP ; on retire donc l'intersection de la range la plus large.
    """
    oop_set = expand_range(oop_range)
    ip_set = expand_range(ip_range)
    if not oop_set or not ip_set:
        raise ValueError("une des ranges est vide")
    if oop_set == ip_set:
        raise ValueError("ranges identiques : impossible de les rendre disjointes")
    if len(ip_set) <= len(oop_set):
        ip_range, oop_range = make_ranges_disjoint(ip_range, oop_range)
    else:
        oop_range, ip_range = make_ranges_disjoint(oop_range, ip_range)
    return oop_range, ip_range


def bet_sizes_from_legal_actions(legal_actions: Sequence[str] | None) -> str | None:
    """Convertit ``bet_25``/``bet_75`` en ``25%,75%`` pour le solveur.

    Les actions nommées ``jam`` ne sont pas incluses : le solveur ajoute
    lui-même l'all-in à partir de la taille de pot et du tapis.
    """
    sizes: list[str] = []
    for action in legal_actions or ():
        token = str(action).strip().lower()
        if token.startswith("bet_"):
            size = token.removeprefix("bet_")
            if size and size not in sizes:
                sizes.append(size)
    return ",".join(f"{size}%" for size in sizes) or None


def _action_field(action: Any, field: str) -> Any:
    if isinstance(action, dict):
        return action.get(field)
    return getattr(action, field, None)


def _action_amount(name: str) -> float | None:
    _, _, suffix = str(name).partition("_")
    try:
        return float(suffix)
    except ValueError:
        return None


def map_policy_action_to_solver(
    policy_action: str | None,
    actions: Sequence[Any],
    *,
    starting_pot: float,
    effective_stack: float,
    size_tolerance: float = 0.05,
) -> dict[str, Any]:
    """Associe une action de politique à une action du solveur.

    Les noms de politique sont exprimés en pourcentage de pot (``bet_50``)
    alors que le solveur nomme ses actions par montant (``bet_9``). Le
    rapprochement est donc fait sur le montant cible, avec une tolérance
    explicite pour ne pas confondre deux tailles différentes.
    """
    names = [str(_action_field(action, "name") or "") for action in actions]
    result: dict[str, Any] = {
        "policy_action": policy_action,
        "solver_action": None,
        "mapping": "unsupported",
        "target_amount": None,
        "solver_amount": None,
    }
    if not policy_action:
        result["reason"] = "missing_policy_action"
        return result

    normalized = str(policy_action).strip().lower()
    result["policy_action"] = normalized
    if normalized in names:
        result.update(
            solver_action=normalized,
            mapping="exact",
            solver_amount=_action_amount(normalized),
        )
        return result

    if normalized in {"check", "call", "fold"}:
        result["reason"] = f"solver_action_absent:{normalized}"
        return result

    if normalized in {"jam", "all_in", "allin", "shove"}:
        allins = [name for name in names if name.startswith("allin_")]
        if not allins:
            result["reason"] = "no_allin_action"
            return result
        solver_action = max(allins, key=lambda name: _action_amount(name) or 0.0)
        result.update(
            solver_action=solver_action,
            mapping="allin",
            solver_amount=_action_amount(solver_action),
        )
        return result

    if not normalized.startswith("bet_"):
        result["reason"] = f"unsupported_action:{normalized}"
        return result

    percent = _action_amount(normalized)
    if percent is None or starting_pot <= 0:
        result["reason"] = "unparsable_bet_size"
        return result

    target = starting_pot * percent / 100.0
    result["target_amount"] = round(target, 4)
    if effective_stack > 0 and target >= effective_stack * 0.95:
        allins = [name for name in names if name.startswith("allin_")]
        if allins:
            solver_action = max(allins, key=lambda name: _action_amount(name) or 0.0)
            result.update(
                solver_action=solver_action,
                mapping="allin_for_oversize",
                solver_amount=_action_amount(solver_action),
            )
            return result

    bets = [
        (name, _action_amount(name))
        for name in names
        if name.startswith("bet_")
    ]
    candidates = [(name, amount) for name, amount in bets if amount is not None]
    if not candidates:
        result["reason"] = "no_bet_action"
        return result

    solver_action, solver_amount = min(
        candidates, key=lambda item: abs(item[1] - target)
    )
    tolerance = max(0.5, abs(target) * size_tolerance)
    if abs(solver_amount - target) > tolerance:
        result["reason"] = f"no_size_match:{target:g}"
        result["solver_amount"] = solver_amount
        return result

    result.update(
        solver_action=solver_action,
        mapping="nearest_size",
        solver_amount=solver_amount,
    )
    return result


def best_response_gap_for_action(
    actions: Sequence[Any],
    policy_action: str | None,
    *,
    starting_pot: float,
    effective_stack: float,
    size_tolerance: float = 0.05,
) -> dict[str, Any]:
    """Calcule l'écart EV entre l'action mappée et la meilleure action du solveur."""
    mapping = map_policy_action_to_solver(
        policy_action,
        actions,
        starting_pot=starting_pot,
        effective_stack=effective_stack,
        size_tolerance=size_tolerance,
    )
    evs: dict[str, float] = {}
    for action in actions:
        name = _action_field(action, "name")
        ev = _action_field(action, "ev")
        if name is not None and ev is not None:
            evs[str(name)] = float(ev)

    mes_ev = max(evs.values()) if evs else None
    mapping["mes_ev"] = round(mes_ev, 4) if mes_ev is not None else None
    solver_action = mapping.get("solver_action")
    if solver_action is None or solver_action not in evs:
        mapping["policy_ev"] = None
        mapping["best_response_gap"] = None
        return mapping

    policy_ev = evs[solver_action]
    mapping["policy_ev"] = round(policy_ev, 4)
    mapping["best_response_gap"] = (
        round(max(0.0, mes_ev - policy_ev), 4) if mes_ev is not None else None
    )
    return mapping


try:
    import postflop_solver_py
except ImportError:  # pragma: no cover - binding optionnel hors build Rust
    postflop_solver_py = None


def _map_single_bet_action(
    actions: Sequence[Any], policy_action: str | None
) -> dict[str, Any]:
    """Associe ``bet_50`` à l'unique action de mise d'un arbre mono-taille.

    Utilisé quand l'arbre a été construit depuis la taille de la politique :
    le rapprochement par montant échoue à cause des arrondis de jetons, mais
    il n'y a qu'une mise possible, donc l'action de politique est celle-là.
    """
    normalized = str(policy_action or "").strip().lower()
    result: dict[str, Any] = {
        "policy_action": normalized or None,
        "solver_action": None,
        "mapping": "single_tree_size",
    }
    if not normalized.startswith("bet_"):
        result["mapping"] = "unsupported"
        return result

    evs = {
        str(_action_field(action, "name")): float(_action_field(action, "ev"))
        for action in actions
        if _action_field(action, "name") is not None
        and _action_field(action, "ev") is not None
    }
    bets = [name for name in evs if name.startswith("bet_")]
    if len(bets) != 1:
        result["mapping"] = "ambiguous_single_bet"
        return result

    solver_action = bets[0]
    policy_ev = evs[solver_action]
    mes_ev = max(evs.values())
    result.update(
        solver_action=solver_action,
        solver_amount=_action_amount(solver_action),
        policy_ev=round(policy_ev, 4),
        mes_ev=round(mes_ev, 4),
        best_response_gap=round(max(0.0, mes_ev - policy_ev), 4),
    )
    return result


def _gap_from_native(spot: dict[str, Any], *, max_iterations: int) -> dict[str, Any]:
    overlap = ranges_overlap(str(spot["oop_range"]), str(spot["ip_range"]))
    if overlap:
        preview = ", ".join(sorted(overlap)[:10])
        raise ValueError(
            f"ranges non disjointes ({len(overlap)} combos communs : {preview}) ; "
            "appeler make_ranges_disjoint() avant le solveur"
        )

    starting_pot = float(spot.get("starting_pot", 0.0))
    effective_stack = float(spot.get("effective_stack", 0.0))
    response = postflop_solver_py.measure_best_response_gap(
        oop_range=str(spot["oop_range"]),
        ip_range=str(spot["ip_range"]),
        board=[str(card) for card in spot.get("board", [])],
        starting_pot=starting_pot,
        effective_stack=effective_stack,
        hero_is_oop=bool(spot.get("hero_is_oop", True)),
        max_iterations=int(max_iterations),
        policy_action=None,
        bet_sizes=spot.get("bet_sizes") or None,
    )
    actions = list(response.get("actions", []) or [])
    policy_action = spot.get("policy_action")
    mapped = best_response_gap_for_action(
        actions,
        policy_action,
        starting_pot=starting_pot,
        effective_stack=effective_stack,
    )

    if mapped.get("solver_action") is None and spot.get("map_single_bet"):
        mapped = _map_single_bet_action(actions, policy_action)

    policy_ev = mapped.get("policy_ev")
    mes_ev = mapped.get("mes_ev")
    gap = mapped.get("best_response_gap")
    if policy_action in (None, "") or (policy_ev is None and mes_ev is None):
        policy_ev = round(float(response.get("policy_ev", 0.0)), 4)
        mes_ev = round(float(response.get("mes_ev", 0.0)), 4)
        gap = round(float(response.get("best_response_gap", 0.0)), 4)

    return {
        "policy_action": mapped.get("policy_action") or policy_action,
        "solver_action": mapped.get("solver_action"),
        "policy_ev": policy_ev,
        "mes_ev": mes_ev,
        "best_response_gap": gap,
        "exploitability": round(float(response.get("exploitability", 0.0)), 4),
        "actions": actions,
        "backend": "native_mes",
    }


def measure_spot_best_response(
    spot: dict[str, Any],
    *,
    max_iterations: int = 200,
    make_disjoint: bool = True,
) -> dict[str, Any]:
    """Mesure un spot unique et journalise la normalisation des ranges.

    Le solveur exige des ranges disjointes. Quand ``make_disjoint`` est vrai,
    les combos communs sont retirés de la range IP et listés dans
    ``removed_overlap`` pour que l'altération reste auditable.
    """
    prepared = dict(spot)
    overlap = ranges_overlap(str(prepared["oop_range"]), str(prepared["ip_range"]))
    if overlap and make_disjoint:
        prepared["oop_range"], prepared["ip_range"] = make_spot_ranges_disjoint(
            str(prepared["oop_range"]), str(prepared["ip_range"])
        )
    result = dict(_gap_from_native(prepared, max_iterations=max_iterations))
    result["removed_overlap"] = sorted(overlap) if make_disjoint else []
    if overlap and make_disjoint:
        result["normalized_oop_range"] = prepared["oop_range"]
        result["normalized_ip_range"] = prepared["ip_range"]
    return result


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

    results = []
    for spot in spots:
        try:
            result = dict(gap_fn(spot))
        except Exception as exc:
            result = {
                "best_response_gap": None,
                "backend": "native_mes_skipped",
                "error": str(exc),
            }
        result["spot_id"] = spot.get("spot_id")
        results.append(result)
    evaluated = [
        result
        for result in results
        if result.get("best_response_gap") is not None
        and result.get("backend") != "native_mes_skipped"
    ]
    gaps = [float(result["best_response_gap"]) for result in evaluated]

    return {
        "spots": len(results),
        "evaluated_spots": len(evaluated),
        "unmapped_spots": len(results) - len(evaluated),
        "mean_best_response_gap": round(sum(gaps) / len(gaps), 4) if gaps else 0.0,
        "max_best_response_gap": round(max(gaps), 4) if gaps else 0.0,
        "backend": evaluated[0]["backend"] if evaluated else "none",
        "results": results,
    }


def spots_from_replay_records(records: Sequence[Any]) -> list[dict[str, Any]]:
    """Convertit des ReplayRecords en spots exploitables par le solveur natif.

    Les snapshots récents exposent ``hero_range`` et ``villain_ranges`` ; les
    anciens fixtures utilisaient ``ranges``. Les deux formes sont acceptées.
    Le héro est OOP si sa position l'indique, sinon il est traité comme IP.
    """
    spots: list[dict[str, Any]] = []
    for record in records:
        spot = getattr(record, "spot", None)
        decision = getattr(record, "decision", None)
        if spot is None or decision is None:
            continue

        ranges = list(getattr(spot, "ranges", []) or [])
        hero_range = str(getattr(spot, "hero_range", "") or "")
        villain_ranges = [str(item) for item in (getattr(spot, "villain_ranges", []) or [])]
        if len(ranges) >= 2:
            hero_is_oop = bool(getattr(spot, "hero_is_oop", True))
            oop_range, ip_range = (
                (ranges[0], ranges[1]) if hero_is_oop else (ranges[1], ranges[0])
            )
        elif hero_range and villain_ranges:
            position = str(getattr(spot, "hero_position", "") or "").strip().lower()
            hero_is_oop = position in {
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
            oop_range, ip_range = (
                (hero_range, villain_ranges[0])
                if hero_is_oop
                else (villain_ranges[0], hero_range)
            )
        else:
            continue

        spots.append(
            {
                "spot_id": getattr(record, "replay_id", None) or getattr(spot, "spot_id", None),
                "oop_range": oop_range,
                "ip_range": ip_range,
                "board": list(getattr(spot, "board", []) or []),
                "starting_pot": float(
                    getattr(spot, "pot", 0.0) or getattr(spot, "starting_pot", 0.0) or 0.0
                ),
                "effective_stack": float(
                    getattr(spot, "stack", 0.0)
                    or getattr(spot, "effective_stack", 0.0)
                    or 0.0
                ),
                "hero_is_oop": hero_is_oop,
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
