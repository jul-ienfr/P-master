"""Resserrement bayésien des ranges villain par street (Phase 2.9).

Après chaque action villain observée (call / bet / raise), les mains incompatibles
avec l'action perdent du poids avant chaque solve. La range mise à jour est
injectée au solveur via la range villain (équivalent node-locking côté runtime).
"""

from __future__ import annotations

from dataclasses import dataclass, field

_RANKS = "23456789TJQKA"
_CHEN_POINTS = {"A": 10.0, "K": 8.0, "Q": 7.0, "J": 6.0}

# Multiplicateurs de poids par type d'action et par force de main.
_AGGRESSIVE_WEIGHTS = {"strong": 1.3, "medium": 0.7, "weak": 0.25}
_PASSIVE_WEIGHTS = {"strong": 0.9, "medium": 1.2, "weak": 0.8}
_WEAK_PASSIVE_WEIGHTS = {"strong": 0.4, "medium": 0.9, "weak": 1.1}


def combo_strength(combo: str) -> str:
    """Classe un combo ('AKs', '72o', 'QQ') en strong / medium / weak."""
    combo = (combo or "").strip()
    if len(combo) < 2:
        return "medium"

    def points(rank: str) -> float:
        # Chen : A=10, K=8, Q=7, J=6 ; sinon rang/2 (T=5 ... 2=1)
        return _CHEN_POINTS.get(rank, (_RANKS.index(rank) + 2) / 2.0)

    high, low = combo[0], combo[1]
    if len(combo) == 2 and high == low:
        score = max(points(high) * 2.0, 5.0)
    else:
        score = points(high)
        gap = (
            _RANKS.index(high if points(high) >= points(low) else low)
            - _RANKS.index(low if points(high) >= points(low) else high)
            - 1
        )
        score -= {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}.get(max(gap, 0), 5.0)
        if len(combo) == 3 and combo[2].lower() == "s":
            score += 2.0

    if score >= 9.0:
        return "strong"
    if score >= 5.0:
        return "medium"
    return "weak"


def expand_range_items(range_text: str) -> list[str]:
    """Éclate une range texte en items simples (sans expansion des '+')."""
    return [
        item.strip().rstrip("+")
        for item in str(range_text or "").split(",")
        if item and item.strip()
    ]


@dataclass
class BayesianRangeUpdater:
    """Met à jour la range villain observée action par action."""

    min_weight: float = 0.35  # seuil de suppression d'un combo
    board_tightening: bool = True  # resserre davantage sur board sec

    observations: list[dict] = field(default_factory=list)

    def update(
        self,
        base_range: str,
        action_history: list[dict] | None,
        *,
        street: int | None = None,
        board_texture: str | None = None,
    ) -> str:
        """Retourne la range resserrée après prise en compte de l'historique.

        Les entrées de ``action_history`` sont des dicts avec ``action`` (et
        optionnellement ``street``/``player``). Seules les actions passives ou
        agressives modifient les poids ; les checks/folds n'élargissent pas.
        """
        weights: dict[str, float] = dict.fromkeys(expand_range_items(base_range), 1.0)
        self.observations = []

        for entry in action_history or []:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("action") or "").strip().upper()
            if not action:
                continue
            kind = self._classify(action)
            if kind is None:
                continue
            self.observations.append({"action": action, "kind": kind})
            for item in weights:
                strength = combo_strength(item)
                if kind == "aggressive":
                    weights[item] *= _AGGRESSIVE_WEIGHTS[strength]
                elif kind == "passive":
                    weights[item] *= _PASSIVE_WEIGHTS[strength]
                elif kind == "weak_passive":
                    weights[item] *= _WEAK_PASSIVE_WEIGHTS[strength]

        # Resserrement supplémentaire par street : plus on avance, moins les mains
        # faibles survivent chez un joueur qui reste dans le coup.
        if self.board_tightening and isinstance(street, int) and street >= 1:
            decay = {1: 0.95, 2: 0.85}.get(street, 0.75)
            for item in weights:
                if combo_strength(item) == "weak":
                    weights[item] *= decay
            if board_texture in {"DRY"}:
                for item in weights:
                    if combo_strength(item) == "weak":
                        weights[item] *= 0.9

        kept = [item for item, weight in weights.items() if weight >= self.min_weight]
        if not kept:
            # Jamais de range vide : garder les combos forts restants.
            strong = [item for item in weights if combo_strength(item) == "strong"]
            kept = strong or list(weights)[: max(1, len(weights) // 4)]

        preserved_order = [item for item in expand_range_items(base_range) if item in set(kept)]
        return ", ".join(preserved_order)

    @staticmethod
    def _classify(action: str) -> str | None:
        if action.startswith(("BET", "RAISE", "ALLIN", "ALL_IN", "3BET", "4BET", "OPEN")):
            return "aggressive"
        if action.startswith("CALL"):
            return "passive"
        if action.startswith("CHECK") or action.startswith("LIMP"):
            return "weak_passive"
        return None  # FOLD et actions inconnues : pas de mise à jour
