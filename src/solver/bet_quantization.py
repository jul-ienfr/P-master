"""Quantification des mises adverses (Phase 0.6.5 / 0.7).

Le bot résout sur un menu discret de tailles de mise (fractions du pot). Une
mise adverse réelle ne colle que rarement exactement à un nœud du menu. La
règle « zéro approximation » :

- si la taille observée tombe à ±``tolerance`` (fraction de pot) d'un nœud du
  menu, on la quantifie sur ce nœud ;
- sinon → refus (``no_blueprint``), **jamais d'arrondi silencieux au-delà de
  la tolérance**.

⚠ Les constantes ci-dessous sont **PROVISOIRES** (marqueur Phase 0.7) : elles
doivent être recalibrées à partir des mises réellement observées en live
(logger ``src/runtime/bet_logger.py`` → ``evidence/bet_observations.jsonl``)
et de l'étude de coût d'abstraction (``research/bet_tolerance_study.py``).
Ne pas « figer » ces valeurs sans le rapport ``docs/bet_tolerance_report.md``.
"""

from __future__ import annotations

import os
from typing import Iterable

# Menu pratique solveurs (PioSOLVER & co.) — PROVISOIRE Phase 0.7.
DEFAULT_BET_MENU: tuple[float, ...] = (0.25, 0.33, 0.5, 0.66, 0.75, 1.0, 1.5)
# Tolérance ±2% du pot — PROVISOIRE Phase 0.7 (« à recalibrer » par télémétrie).
DEFAULT_BET_TOLERANCE = 0.02


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def bet_menu() -> tuple[float, ...]:
    """Menu effectif (override env ``POKER_BET_MENU="0.33,0.5,1.0"``)."""
    raw = os.getenv("POKER_BET_MENU")
    if raw:
        try:
            values = tuple(sorted({float(chunk) for chunk in raw.split(",") if chunk.strip()}))
            if values:
                return values
        except ValueError:
            pass
    return DEFAULT_BET_MENU


def bet_tolerance() -> float:
    """Tolérance effective (override env ``POKER_BET_TOLERANCE``)."""
    return _env_float("POKER_BET_TOLERANCE", DEFAULT_BET_TOLERANCE)


def nearest_menu_node(
    amount: float,
    pot_before_bet: float,
    *,
    menu: Iterable[float] | None = None,
) -> tuple[float, float] | None:
    """Nœud menu le plus proche de ``amount / pot_before_bet``.

    Retourne ``(node_fraction, delta)`` avec ``delta`` la distance absolue en
    fraction de pot, ou ``None`` si le pot est invalide.
    """
    pot_before_bet = float(pot_before_bet or 0.0)
    if pot_before_bet <= 0.0:
        return None
    fraction = float(amount) / pot_before_bet
    if fraction <= 0.0:
        return None
    menu_values = tuple(menu if menu is not None else bet_menu())
    if not menu_values:
        return None
    node = min(menu_values, key=lambda candidate: abs(candidate - fraction))
    return node, abs(node - fraction)


def quantize_observed_bet(
    amount: float,
    pot_before_bet: float,
    *,
    menu: Iterable[float] | None = None,
    tolerance: float | None = None,
) -> float | None:
    """Quantifie une mise adverse observée vers le menu, ou refuse.

    Retourne :
    - la fraction de menu à utiliser si ``|nearest - fraction| <= tolerance`` ;
    - ``None`` sinon (le spot doit être refusé : pas d'arrondi silencieux).
    """
    tol = bet_tolerance() if tolerance is None else float(tolerance)
    nearest = nearest_menu_node(amount, pot_before_bet, menu=menu)
    if nearest is None:
        return None
    node, delta = nearest
    return node if delta <= tol else None


def is_all_in_amount(amount: float, effective_stack: float) -> bool:
    """Heuristique stricte : amount >= stack restant ⇒ pas de quantification."""
    return float(amount) >= float(effective_stack) > 0.0
