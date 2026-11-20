"""Limites de mise par site (spec 005, constat F-06).

Le runtime appliquait une correction locale en dur (« si la mise est inférieure
à 1 BB, forcer 3 BB ») sans modèle de limite par plateforme. Ce module porte la
règle : une mise proposée est bornée par les limites du site, arrondie selon ses
conventions, et le verdict est explicite.

Fonctions pures, sans état et sans dépendance au reste du runtime : elles sont
testables hors ligne et ne jugent jamais la stratégie — seulement la légalité
formelle de la taille demandée.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ActionLimits:
    """Limites formelles de mise d'un site (unités : bb)."""

    min_bet_bb: float = 1.0
    min_raise_increment_bb: float = 1.0
    allow_decimals: bool = False
    all_in_supported: bool = True

    def __post_init__(self) -> None:
        if not isfinite(self.min_bet_bb) or self.min_bet_bb < 0:
            raise ValueError("min_bet_bb doit être un nombre fini positif")
        if not isfinite(self.min_raise_increment_bb) or self.min_raise_increment_bb < 0:
            raise ValueError("min_raise_increment_bb doit être un nombre fini positif")


@dataclass(frozen=True)
class BetAmountVerdict:
    """Résultat de la validation d'une taille de mise."""

    accepted: bool
    value: float | None = None
    reason: str = ""
    adjusted: bool = False


def _round_to_convention(amount_bb: float, allow_decimals: bool) -> float:
    """Arrondit selon la convention du site (entier, ou 2 décimales)."""
    if allow_decimals:
        return round(amount_bb, 2)
    return float(round(amount_bb))


def validate_bet_amount(
    amount_bb: float | None,
    limits: ActionLimits,
    *,
    is_all_in: bool = False,
) -> BetAmountVerdict:
    """Valide une taille de mise (en bb) contre les limites du site.

    - entrée non finie ou négative → refus ``invalid_amount`` ;
    - tapis demandé et supporté → accepté tel quel (cas particulier du minimum) ;
    - mise sous ``min_bet_bb`` après arrondi → refus ``below_min_bet`` ;
    - arrondi modifiant la valeur → acceptée, marquée ``adjusted`` ;
    - sinon → acceptée sans modification.
    """
    if amount_bb is None or not isfinite(amount_bb) or amount_bb < 0:
        return BetAmountVerdict(accepted=False, reason="invalid_amount")

    if is_all_in:
        if not limits.all_in_supported:
            return BetAmountVerdict(accepted=False, reason="all_in_unsupported")
        return BetAmountVerdict(accepted=True, value=float(amount_bb))

    rounded = _round_to_convention(float(amount_bb), limits.allow_decimals)
    if rounded < limits.min_bet_bb:
        return BetAmountVerdict(
            accepted=False,
            value=rounded,
            reason="below_min_bet",
        )
    if rounded != float(amount_bb):
        return BetAmountVerdict(accepted=True, value=rounded, adjusted=True)
    return BetAmountVerdict(accepted=True, value=rounded)
