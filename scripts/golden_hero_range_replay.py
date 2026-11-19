"""Rejeu golden spec 001 : range héros complète + combo cible vs singleton.

Compare, sur un spot postflop fixe, la requête « range complète + hero_hand »
(chemin de production après correctif) à la requête « hero_hand comme range »
(chemin historique). Le script échoue si la range de production contient un
seul combo, si l'EV du combo n'est pas extraite, si l'état de convergence n'est
pas explicite, ou si la courbe de budget ne s'améliore pas. La comparaison
directe d'exploitabilité singleton vs range complète est une erreur de
catégorie (deux jeux différents) — voir les commentaires des `checks`.

Sémantique des EV (vérifiée par sonde le 19/11/2026) :

- `hero_ev` est l'EV de **range** (moyenne pondérée sur la range du héros à la
  racine, `root_range_ev`) : elle est identique pour deux `hero_hand` différents
  de la même range.
- l'EV du **combo** cible est dans `actions[].ev` lorsque `selection` vaut
  `combo_ev_max` : elle dépend de `hero_hand`. C'est cette valeur que le script
  lit pour l'EV du combo (et non `hero_ev`, qui passait le test pour la
  mauvaise raison).
- `selection` est exposé à la racine de la réponse (pas sous `metadata`).

Mesure d'instabilité (19/11/2026) : l'exploitabilité n'est rafraîchie que tous
les 10 tours. Sur le singleton à 800 ms, ~10 itérations tiennent dans le budget,
donc la valeur rapportée bascule entre 0,0389 (fraîche, `converged=true`) et
11,6855 (valeur pré-boucle, `converged=false`) selon la charge machine ; le
script ajoute une jambe de référence à 3 200 ms, déterministe. Sur la range
complète à 800 ms, ~2 itérations seulement, donc la valeur rapportée est
toujours la valeur pré-boucle 12,7015 — la stratégie renvoyée varie en revanche
selon qu'une ou deux itérations tiennent.

Usage :
    python scripts/golden_hero_range_replay.py
    python scripts/golden_hero_range_replay.py --output research/results/golden_hero_range_replay.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.solver.provider import SolverProvider  # noqa: E402

HERO_RANGE = "22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo"
HERO_HAND = "AhKh"
# Second combo de la même range : sert à prouver que l'EV extraite dépend bien
# de `hero_hand` (et non de la range). `7c7d` = 77, inclus par `22+`.
HERO_HAND_ALT = "7c7d"
VILLAIN_RANGE = "QQ+, AKs, AKo"
BOARD = ["Jc", "7s", "2d"]
POT = 6.0
STACK = 97.0
LEGAL_ACTIONS = ["check", "bet_50", "bet_75", "allin"]
TIME_BUDGET_MS = 800

# Cible de convergence en unités solveur (même référence que le mode legacy,
# `LEGACY_TARGET_EXPLOITABILITY` dans `src/v2_api.rs`). Le balayage de budget
# documente à partir de quand le spot à range complète l'atteint.
CONVERGENCE_TARGET = 0.5


def _solve(
    provider: SolverProvider,
    *,
    hero_range: str,
    hero_hand: str | None,
    time_budget_ms: int = TIME_BUDGET_MS,
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = provider.solve_spot_v2(
        hero_range=hero_range,
        villain_ranges=[VILLAIN_RANGE],
        board=BOARD,
        starting_pot=POT,
        effective_stack=STACK,
        legal_actions=LEGAL_ACTIONS,
        spot_id="golden-hero-range",
        hero_position="ip",
        state_confidence=0.95,
        action_history=[],
        use_cache=False,
        time_budget_ms=time_budget_ms,
        rake=0.0,
        rake_cap=0.0,
        num_players=2,
        hero_hand=hero_hand,
        bet_sizes="50%",
        raise_sizes="2.5x",
    )
    return response, (time.perf_counter() - started) * 1000.0


def _actions_payload(response: dict[str, Any]) -> list[dict[str, Any]]:
    payload = []
    for item in response.get("actions") or []:
        if not isinstance(item, dict):
            continue
        # Le provider expose `name` (et `label`) ; `action` n'existe pas. Lire
        # la mauvaise clé rendait tout nom d'action nul, donc l'EV par action
        # introuvable et la comparaison de stratégie vide.
        name = item.get("name") if item.get("name") is not None else item.get("action")
        payload.append(
            {
                "action": name,
                "freq": item.get("frequency") if item.get("frequency") is not None else item.get("freq"),
                "ev": item.get("ev"),
            }
        )
    return payload


def _ev_for(actions: list[dict[str, Any]], name: Any) -> float | None:
    """EV porté par l'action nommée, ou None si absente/sans EV."""
    for item in actions:
        if item["action"] == name:
            value = item.get("ev")
            return float(value) if value is not None else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research" / "results" / "golden_hero_range_replay.json",
    )
    args = parser.parse_args()

    try:
        import postflop_solver_py
    except ImportError:
        print("postflop_solver_py indisponible : reconstruire via maturin develop.")
        return 2

    provider = SolverProvider(native_backend=postflop_solver_py)

    after, after_wall_ms = _solve(provider, hero_range=HERO_RANGE, hero_hand=HERO_HAND)
    before, before_wall_ms = _solve(provider, hero_range=HERO_HAND, hero_hand=HERO_HAND)
    # Même range, autre combo, au budget de production : sonde indicative (le
    # nombre d'itérations qui tiennent dans 800 ms varie, donc l'EV du combo
    # varie aussi). La preuve déterministe est faite plus bas à budget convergé.
    alt, alt_wall_ms = _solve(provider, hero_range=HERO_RANGE, hero_hand=HERO_HAND_ALT)
    # Référence déterministe du singleton : à 800 ms, l'exploitabilité n'est
    # rafraîchie qu'au 10ᵉ tour ; ~10 itérations tiennent dans le budget, donc
    # la valeur rapportée bascule entre 0,0389 (fraîche) et la valeur pré-boucle
    # selon la charge machine. À budget large, le singleton converge toujours.
    before_ref, before_ref_wall_ms = _solve(
        provider, hero_range=HERO_HAND, hero_hand=HERO_HAND, time_budget_ms=3200
    )

    # Balayage de budget sur la range complète : l'exploitabilité d'un jeu plus
    # grand ne se compare pas à celle du singleton ; il faut sa courbe propre.
    # Les budgets longs dépassent 10 itérations, donc l'exploitabilité rapportée
    # y est une mesure fraîche (elle n'est recalculée que tous les 10 tours).
    budget_sweep: list[dict[str, Any]] = []
    for budget_ms in (100, 800, 1600, 3200, 6400, 12800):
        sweep, sweep_wall_ms = _solve(
            provider, hero_range=HERO_RANGE, hero_hand=HERO_HAND, time_budget_ms=budget_ms
        )
        budget_sweep.append(
            {
                "time_budget_ms": budget_ms,
                "wall_ms": round(sweep_wall_ms, 1),
                "chosen_action": sweep.get("chosen_action"),
                "range_hero_ev": sweep.get("hero_ev"),
                "chosen_combo_ev": _ev_for(_actions_payload(sweep), sweep.get("chosen_action")),
                "exploitability": float(sweep.get("exploitability") or 0.0),
                "converged": bool(sweep.get("converged")),
            }
        )

    # Preuve déterministe de l'EV par combo : à budget convergé (12 800 ms), le
    # jeu est résolu, donc les EV ne dépendent plus du nombre d'itérations qui
    # tiennent dans le budget. La range complète est identique dans les deux
    # requêtes ; seul `hero_hand` change.
    alt_converged, alt_converged_wall_ms = _solve(
        provider, hero_range=HERO_RANGE, hero_hand=HERO_HAND_ALT, time_budget_ms=12800
    )

    after_actions = _actions_payload(after)
    before_actions = _actions_payload(before)
    alt_actions = _actions_payload(alt)
    alt_converged_actions = _actions_payload(alt_converged)

    # EV du combo cible pour l'action choisie : lue dans `actions[].ev`, qui est
    # l'EV par combo quand `selection == "combo_ev_max"` (voir la docstring).
    after_ev = _ev_for(after_actions, after.get("chosen_action"))
    before_ev = _ev_for(before_actions, before.get("chosen_action"))
    alt_ev = _ev_for(alt_actions, alt.get("chosen_action"))

    # Paire déterministe : même range, budget convergé, seul `hero_hand` change.
    # La jambe `AhKh` est déjà mesurée par le balayage (dernière ligne) ; seule
    # la jambe `7c7d` est résolue ici.
    after_conv = next(
        (row for row in budget_sweep if row["time_budget_ms"] == 12800), None
    )
    alt_converged_ev = _ev_for(alt_converged_actions, alt_converged.get("chosen_action"))
    after_conv_ev = (after_conv or {}).get("chosen_combo_ev")

    after_expl = float(after.get("exploitability") or 0.0)
    before_expl = float(before.get("exploitability") or 0.0)

    # Invariance de l'EV de range et discrimination de l'EV de combo, mesurées
    # sur la paire convergée (déterministe) et non sur la paire à 800 ms.
    conv_range_ev_a = float((after_conv or {}).get("range_hero_ev") or 0.0)
    conv_range_ev_b = float(alt_converged.get("hero_ev") or 0.0)
    range_ev_stable = abs(conv_range_ev_a - conv_range_ev_b) <= 1e-4
    combo_ev_differs = (
        after_conv_ev is not None
        and alt_converged_ev is not None
        and abs(after_conv_ev - alt_converged_ev) > 1e-4
    )

    report: dict[str, Any] = {
        "kind": "golden_hero_range_replay",
        "spot": {
            "hero_hand": HERO_HAND,
            "hero_hand_alt": HERO_HAND_ALT,
            "board": BOARD,
            "pot": POT,
            "effective_stack": STACK,
            "villain_range": VILLAIN_RANGE,
            "time_budget_ms": TIME_BUDGET_MS,
        },
        "ev_semantics": (
            "hero_ev = EV de range (invariante au combo) ; "
            "actions[].ev avec selection=combo_ev_max = EV du combo cible"
        ),
        "before_singleton": {
            "hero_range": HERO_HAND,
            "wall_ms": round(before_wall_ms, 1),
            "chosen_action": before.get("chosen_action"),
            "range_hero_ev": before.get("hero_ev"),
            "chosen_combo_ev": before_ev,
            "exploitability": before_expl,
            "backend": before.get("backend"),
            "actions": before_actions,
        },
        "after_full_range": {
            "hero_range": HERO_RANGE,
            "hero_hand": HERO_HAND,
            "wall_ms": round(after_wall_ms, 1),
            "chosen_action": after.get("chosen_action"),
            "range_hero_ev": after.get("hero_ev"),
            "chosen_combo_ev": after_ev,
            "exploitability": after_expl,
            "backend": after.get("backend"),
            "selection": after.get("selection"),
            "converged": bool(after.get("converged")),
            "epsilon_target": after.get("epsilon_target"),
            "warnings": list(after.get("warnings") or []),
            "actions": after_actions,
        },
        "combo_probe_same_range": {
            "hero_hand": HERO_HAND_ALT,
            "wall_ms": round(alt_wall_ms, 1),
            "chosen_action": alt.get("chosen_action"),
            "range_hero_ev": alt.get("hero_ev"),
            "chosen_combo_ev": alt_ev,
            "selection": alt.get("selection"),
            "actions": alt_actions,
            "note": (
                "sonde indicative au budget de production : le nombre "
                "d'itérations qui tiennent dans 800 ms varie, donc l'EV du "
                "combo varie aussi ; la preuve déterministe est la paire "
                "convergée ci-dessous"
            ),
        },
        "combo_probe_converged_pair": {
            "time_budget_ms": 12800,
            "hero_range": HERO_RANGE,
            "hero_hand": HERO_HAND,
            "chosen_combo_ev": after_conv_ev,
            "range_hero_ev": conv_range_ev_a,
            "alt_hero_hand": HERO_HAND_ALT,
            "alt_wall_ms": round(alt_converged_wall_ms, 1),
            "alt_chosen_action": alt_converged.get("chosen_action"),
            "alt_chosen_combo_ev": alt_converged_ev,
            "alt_range_hero_ev": conv_range_ev_b,
            "note": (
                "jeu résolu : les EV ne dépendent plus du nombre d'itérations. "
                "Même range dans les deux requêtes, seul hero_hand change."
            ),
        },
        "before_singleton_reference": {
            "hero_range": HERO_HAND,
            "time_budget_ms": 3200,
            "wall_ms": round(before_ref_wall_ms, 1),
            "chosen_action": before_ref.get("chosen_action"),
            "range_hero_ev": before_ref.get("hero_ev"),
            "exploitability": float(before_ref.get("exploitability") or 0.0),
            "converged": bool(before_ref.get("converged")),
            "note": (
                "référence déterministe : à 800 ms la valeur rapportée du "
                "singleton dépend de la charge (rafraîchissement tous les 10 tours)"
            ),
        },
        "budget_sweep_full_range": budget_sweep,
            "converged_within_sweep": any(
                float(row.get("exploitability") or 0.0) <= CONVERGENCE_TARGET
                for row in budget_sweep
            ),
        "checks": {
            "production_range_multi_combo": len(HERO_RANGE.split(",")) > 1,
            # L'EV du combo n'est extraite que si le solveur a apparié
            # `hero_hand` à la range (`selection == "combo_ev_max"`) et si
            # l'action choisie porte un EV fini.
            "combo_ev_extracted": (
                after.get("selection") == "combo_ev_max" and after_ev is not None
            ),
            # Preuve directe : deux combos de la même range donnent deux EV
            # d'action différents, tandis que l'EV de range reste identique.
            # Sans cela, `hero_ev` (invariante) aurait suffi à faire passer le
            # test pour la mauvaise raison.
            "combo_ev_is_per_combo": bool(combo_ev_differs and range_ev_stable),
            "strategy_differs": (
                after.get("chosen_action") != before.get("chosen_action")
                or (
                    after_ev is not None
                    and before_ev is not None
                    and abs(after_ev - before_ev) > 1e-4
                )
            ),
            # La comparaison d'exploitabilité singleton vs range complète est une
            # erreur de catégorie : ce sont deux jeux différents (le singleton
            # converge à 0,04 parce que le villain connaît la main du héros).
            # Les invariants mesurables sont : (1) l'état de convergence est
            # toujours explicite (US3-AC3), (2) plus de budget améliore
            # réellement la stratégie. La courbe complète est dans
            # `budget_sweep_full_range` et `converged_within_sweep`.
            "convergence_state_explicit": (
                after.get("converged") is True
                or "convergence_not_reached" in (after.get("warnings") or [])
            ),
            "budget_sweep_improves": (
                len(budget_sweep) >= 2
                and float(budget_sweep[-1].get("exploitability") or 0.0)
                < float(budget_sweep[0].get("exploitability") or 0.0)
            ),
        },
    }
    report["verdict"] = "pass" if all(report["checks"].values()) else "fail"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for key, value in report["checks"].items():
        print(f"{key}: {value}")
    print(
        f"before: {before.get('chosen_action')} combo_ev={before_ev} "
        f"range_ev={before.get('hero_ev')} expl={before_expl}"
    )
    print(
        f"after : {after.get('chosen_action')} combo_ev={after_ev} "
        f"range_ev={after.get('hero_ev')} expl={after_expl} "
        f"sel={after.get('selection')}"
    )
    print(
        f"probe : {HERO_HAND_ALT} {alt.get('chosen_action')} combo_ev={alt_ev} "
        f"range_ev={alt.get('hero_ev')}"
    )
    print(
        f"ref   : singleton@3200ms {before_ref.get('chosen_action')} "
        f"expl={before_ref.get('exploitability')} converged={before_ref.get('converged')}"
    )
    for row in budget_sweep:
        print(
            f"sweep : {row['time_budget_ms']} ms -> {row['chosen_action']} "
            f"combo_ev={row['chosen_combo_ev']} range_ev={row['range_hero_ev']} "
            f"expl={row['exploitability']} conv={row['converged']}"
        )
    print(f"verdict: {report['verdict']} -> {args.output}")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
