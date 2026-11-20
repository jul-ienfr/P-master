"""Point d'entrée opérateur : campagne de winrate du chemin de production (F-03).

Mesure une politique sur le pool synthétique et écrit l'artefact daté consommé
par le gate go-live. Par défaut la politique mesurée est ``heuristic`` — la
politique de recherche — explicitement étiquetée **non-production** : elle sert
à valider le harnais, jamais à fonder un go-live. ``--policy production`` mesure
``DecisionMaker.get_best_action`` (gate, store préflop, solveur Rust, cache,
replis), c'est-à-dire le produit.

Usage :
    python scripts/production_winrate_benchmark.py --policy heuristic --hands 200
    python scripts/production_winrate_benchmark.py --policy production --hands 5000 \
        --target-half-width 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.monte_carlo_sim import (  # noqa: E402
    ActionFn,
    View,
    make_heuristic_hero_policy,
)
from research.production_benchmark import (  # noqa: E402
    run_production_benchmark,
    write_report,
)

DEFAULT_OUTPUT = ROOT / "research" / "results" / "production_winrate.json"

# Table (legal_actions → action runtime) utilisée pour traduire la décision du
# produit en action du simulateur.
_LEGAL_ACTIONS = ["fold", "check", "call", "raise"]


def build_heuristic_policy() -> ActionFn:
    """Politique de recherche (``hero_heuristic``) : **non-production**."""
    return make_heuristic_hero_policy()


def build_production_policy(*, bet_sizes: str | None = None) -> ActionFn:
    """Politique de production : ``DecisionMaker.get_best_action``.

    Le runtime est asynchrone ; le simulateur est synchrone. La boucle
    d'événements est pilotée à chaque décision. Le coût du solveur (~800 ms par
    flop à froid) rend une campagne longue coûteuse : c'est la raison pour
    laquelle l'artefact est produit par l'opérateur, pas dans un tour de
    développement.
    """
    from src.bot.decision_maker import DecisionMaker

    maker = DecisionMaker(
        None,
        create_rl_agent=False,
        autoload_rl_model=False,
        heads_up=True,
    )
    if bet_sizes:
        maker.solver_bet_sizes = bet_sizes

    def act(view: View) -> tuple[str, float | None]:
        result = asyncio.run(
            maker.get_best_action(
                view.hole_cards,
                list(_board_cards(view.board_cards)),
                float(view.pot_amount),
                float(view.effective_stack),
                "villain",
                list(_LEGAL_ACTIONS),
                hero_position="btn" if view.is_button else "bb",
            )
        )
        return _map_runtime_action(result, view)

    return act


def _board_cards(board: str) -> list[str]:
    return [board[index : index + 2] for index in range(0, len(board), 2)]


def _map_runtime_action(result: dict, view: View) -> tuple[str, float | None]:
    """Traduit une décision du runtime en action du simulateur."""
    action = str(result.get("action") or "").lower()
    if action in {"fold", "check", "call"}:
        return ("check_call" if action in {"check", "call"} else "fold"), None

    bet_size = result.get("bet_size")
    if action in {"raise", "bet", "allin"} or bet_size is not None:
        if action == "allin":
            return "raise_to", float(view.max_raise_to)
        if bet_size is not None:
            try:
                ratio = float(bet_size)
            except (TypeError, ValueError):
                ratio = 0.66
            if ratio <= 1.0:
                target = view.pot_amount * ratio + view.to_call
            else:
                target = ratio + view.to_call
            return "raise_to", float(target)
        return "raise_to", float(view.pot_amount * 0.66 + view.to_call)
    return "check_call", None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        choices=("heuristic", "production"),
        default="heuristic",
        help="politique mesurée (heuristic = recherche, non-production)",
    )
    parser.add_argument("--hands", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20261120)
    parser.add_argument(
        "--target-half-width",
        type=float,
        default=10.0,
        help="demi-largeur d'IC95 visée en bb/100 (détermine les mains requises)",
    )
    parser.add_argument("--bet-sizes", type=str, default=None)
    parser.add_argument("--opponents", type=str, nargs="*", default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    is_production = args.policy == "production"
    if is_production:
        hero_action_fn = build_production_policy(bet_sizes=args.bet_sizes)
        policy_label = "DecisionMaker.get_best_action"
    else:
        hero_action_fn = build_heuristic_policy()
        policy_label = "hero_heuristic"

    report = run_production_benchmark(
        hero_action_fn,
        policy_label=policy_label,
        is_production=is_production,
        opponents=tuple(args.opponents)
        if args.opponents
        else ("nit", "tag", "lag", "station", "whale"),
        hands=args.hands,
        seed=args.seed,
        target_half_width_bb100=args.target_half_width,
    )

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    write_report(report, output_path)

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    if report.status == "unmeasured":
        print("\naucune main évaluable : rien n'a été mesuré, aucun taux n'est publié.")
    elif not is_production:
        print(
            "\npolitique NON-PRODUCTION : cet artefact ne mesure pas le chemin de "
            "décision déployé et ne peut pas fonder un go-live."
        )
    elif not report.verdict.get("protocol_complete"):
        print(
            f"\nprotocole incomplet ({report.verdict.get('verdict')}) : "
            f"{report.hands} mains évaluées pour {report.required_hands} requises "
            f"à la demi-largeur visée de {args.target_half_width} bb/100."
        )
    print(f"\nsaved={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
