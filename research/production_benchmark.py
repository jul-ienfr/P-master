"""Harnais de benchmark du **chemin de production** (constat F-03).

Les chiffres publiés par ``monte_carlo_sim`` mesurent ``hero_heuristic``, pas le
produit : le runtime décide par ``DecisionMaker.get_best_action`` (gate, store
préflop, solveur Rust, cache, replis). Ce harnais mesure **une politique
fournie** — donc le chemin de production quand on lui passe le runtime — sur un
pool synthétique, et enregistre honnêtement *quelle* politique a été mesurée.

Deux garanties d'honnêteté :

- le rapport porte ``hero_policy_is_production`` ; un artefact d'heuristique ne
  satisfait jamais le protocole du gate ;
- sans main évaluable, le rapport est ``unmeasured`` avec des taux ``None``,
  jamais un chiffre inventé.

La variable de contrôle par défaut est l'équité préflop centrée (``équité − 0,5``
dont la moyenne est exactement ``0`` par symétrie) : c'est le contrôle AIVAT
concret du harnais.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Any

from research.monte_carlo_sim import (
    ARCHETYPES,
    BIG_BLIND,
    ActionFn,
    apply_action,
    build_view,
    make_archetype_policy,
    monte_carlo_equity,
    new_state,
)
from research.sample_size import WinrateVerdict, classify_winrate, required_hands
from research.variance_reduction import VarianceReducedEstimate, control_variate_estimate

ControlFn = Callable[[str, Random], float]
Opponent = str

ARTIFACT_KIND = "production_winrate_benchmark"


def preflop_equity_control(hole_cards: str, rng: Random) -> float:
    """Contrôle AIVAT : ``équité préflop − 0,5``, de moyenne exactement nulle.

    La moyenne est nulle **par construction** : l'équité d'une main tirée
    uniformément contre une main tirée uniformément est symétrique autour de
    0,5 (les deux mains sont interchangeables). C'est ce qui rend le contrôle
    utilisable sans échantillon de calibration distinct.
    """
    return monte_carlo_equity(hole_cards, "", samples=80, rng=rng) - 0.5


def _default_control_fn(hole_cards: str, rng: Random) -> float:
    return preflop_equity_control(hole_cards, rng)


@dataclass
class ProductionBenchmarkReport:
    """Rapport d'un benchmark de production (ou d'une politique étiquetée)."""

    hero_policy: str
    hero_policy_is_production: bool
    opponents: list[str]
    hands: int
    required_hands: int
    status: str
    winrate_bb100: float | None
    ci95_low_bb100: float | None
    ci95_high_bb100: float | None
    std_per_hand_bb: float | None
    variance_reduction: float | None
    reduced_winrate_bb100: float | None
    reduced_ci95_bb100: float | None
    verdict: dict[str, Any]
    generated_at: str
    seed: int
    target_half_width_bb100: float
    elapsed_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ARTIFACT_KIND,
            "generated_at": self.generated_at,
            "hero_policy": self.hero_policy,
            "hero_policy_is_production": self.hero_policy_is_production,
            "opponents": list(self.opponents),
            "hands": self.hands,
            "required_hands": self.required_hands,
            "status": self.status,
            "winrate_bb100": self.winrate_bb100,
            "ci95_low_bb100": self.ci95_low_bb100,
            "ci95_high_bb100": self.ci95_high_bb100,
            "std_per_hand_bb": self.std_per_hand_bb,
            "variance_reduction": self.variance_reduction,
            "reduced_winrate_bb100": self.reduced_winrate_bb100,
            "reduced_ci95_bb100": self.reduced_ci95_bb100,
            "verdict": dict(self.verdict),
            "seed": self.seed,
            "target_half_width_bb100": self.target_half_width_bb100,
            "elapsed_s": self.elapsed_s,
            "notes": list(self.notes),
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / n)


def _play_hand(
    hero_action_fn: ActionFn,
    villain_action_fn: ActionFn,
    rng: Random,
    *,
    hero_index: int = 0,
) -> tuple[float, str]:
    """Joue une main HU ; retourne (résultat héro en bb, cartes du héro)."""
    state, holes = new_state(rng)

    while state.status:
        actor = state.actor_index
        if actor is None:
            break
        action_fn = hero_action_fn if actor == hero_index else villain_action_fn
        try:
            action, amount = action_fn(build_view(state, holes[actor]))
        except Exception:
            action, amount = "check_call", None
        try:
            apply_action(state, action, amount)
        except Exception:
            if state.can_check_or_call():
                state.check_or_call()
            elif state.can_fold():
                state.fold()

    payoffs = state.payoffs or (0.0, 0.0)
    return float(payoffs[hero_index]) / BIG_BLIND, holes[hero_index]


def run_production_benchmark(
    hero_action_fn: ActionFn,
    *,
    policy_label: str,
    is_production: bool,
    opponents: Sequence[Opponent] = ("nit", "tag", "lag", "station", "whale"),
    hands: int = 1_000,
    seed: int = 20261120,
    target_half_width_bb100: float = 10.0,
    control_fn: ControlFn | None = None,
    mean_control: float = 0.0,
    z: float = 1.96,
) -> ProductionBenchmarkReport:
    """Mesure ``hero_action_fn`` contre un pool synthétique, avec IC et verdict.

    ``is_production`` doit valoir ``True`` seulement si ``hero_action_fn`` est le
    chemin de décision réellement déployé. L'indicateur est enregistré tel quel :
    il n'est jamais déduit du nom de la politique.
    """
    selected = [name for name in opponents if name in ARCHETYPES]
    if not selected:
        selected = list(ARCHETYPES)

    control_fn = control_fn or _default_control_fn
    rng = Random(seed)
    started = datetime.now(UTC)

    payoffs: list[float] = []
    controls: list[float] = []
    for index, name in enumerate(selected):
        villain_action_fn = make_archetype_policy(ARCHETYPES[name], seed + index)
        for _ in range(max(0, hands)):
            payoff, hole_cards = _play_hand(hero_action_fn, villain_action_fn, rng)
            payoffs.append(payoff)
            controls.append(control_fn(hole_cards, rng))

    elapsed_s = (datetime.now(UTC) - started).total_seconds()
    evaluated = len(payoffs)

    notes: list[str] = []
    if not is_production:
        notes.append(
            "politique non-production : cet artefact ne mesure pas le chemin de "
            "décision déployé et ne peut pas fonder un go-live"
        )

    if evaluated == 0:
        return ProductionBenchmarkReport(
            hero_policy=policy_label,
            hero_policy_is_production=bool(is_production),
            opponents=list(selected),
            hands=0,
            required_hands=0,
            status="unmeasured",
            winrate_bb100=None,
            ci95_low_bb100=None,
            ci95_high_bb100=None,
            std_per_hand_bb=None,
            variance_reduction=None,
            reduced_winrate_bb100=None,
            reduced_ci95_bb100=None,
            verdict=classify_winrate(
                None,
                None,
                0,
                0,
                is_production_policy=bool(is_production),
            ).to_dict(),
            generated_at=_utc_now(),
            seed=seed,
            target_half_width_bb100=target_half_width_bb100,
            elapsed_s=elapsed_s,
            notes=notes + ["aucune main évaluable : aucun taux n'est publié"],
        )

    estimate: VarianceReducedEstimate = control_variate_estimate(
        payoffs,
        controls,
        mean_control=mean_control,
        beta="optimal",
        z=z,
    )
    if not estimate.unbiased_inputs:
        notes.append(
            "moyenne du contrôle estimée sur l'échantillon mesuré : l'estimateur "
            "n'est pas garanti sans biais"
        )

    sigma_bb100 = estimate.raw_std_bb * 100.0
    required = required_hands(sigma_bb100, target_half_width_bb100, z=z)

    ci95 = (
        estimate.raw_bb100 - estimate.raw_ci95_bb100,
        estimate.raw_bb100 + estimate.raw_ci95_bb100,
    )
    verdict: WinrateVerdict = classify_winrate(
        estimate.raw_bb100,
        ci95,
        evaluated,
        required,
        is_production_policy=bool(is_production),
    )

    return ProductionBenchmarkReport(
        hero_policy=policy_label,
        hero_policy_is_production=bool(is_production),
        opponents=list(selected),
        hands=evaluated,
        required_hands=required,
        status=verdict.verdict,
        winrate_bb100=round(estimate.raw_bb100, 3),
        ci95_low_bb100=round(ci95[0], 3),
        ci95_high_bb100=round(ci95[1], 3),
        std_per_hand_bb=round(estimate.raw_std_bb, 4),
        variance_reduction=round(estimate.variance_reduction, 4),
        reduced_winrate_bb100=round(estimate.reduced_bb100, 3),
        reduced_ci95_bb100=round(estimate.reduced_ci95_bb100, 3),
        verdict=verdict.to_dict(),
        generated_at=_utc_now(),
        seed=seed,
        target_half_width_bb100=target_half_width_bb100,
        elapsed_s=elapsed_s,
        notes=notes,
    )


def write_report(report: ProductionBenchmarkReport, path: str | Path) -> Path:
    """Écrit l'artefact JSON daté (versionnable)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target
