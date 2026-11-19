"""Modèle de range texte : normalisation, taille et appartenance.

Le runtime envoie au solveur une range héros complète (plusieurs combos) et la
main cible séparément. Ce module fournit les primitives partagées pour compter
les combos d'une notation standard (`AA`, `AKs`, `A2o+`, `TT+`) sans dépendre
du format lourd du solveur.
"""

from __future__ import annotations

from functools import lru_cache

RANKS = "23456789TJQKA"

_COMBOS_PER_PAIR = 6
_COMBOS_PER_SUITED = 4
_COMBOS_PER_OFFSUIT = 12
_COMBOS_PER_UNSPECIFIED = _COMBOS_PER_SUITED + _COMBOS_PER_OFFSUIT


def _rank_index(rank: str) -> int:
    try:
        return RANKS.index(rank.upper())
    except ValueError:
        return -1


def _token_classes(token: str) -> list[str]:
    """Éclate un token en classes (`AA`, `AKs`, `AKo`) sans dénombrer les cartes."""
    raw = str(token or "").strip().replace(" ", "")
    if not raw:
        return []
    plus = raw.endswith("+")
    body = raw.rstrip("+")
    if len(body) == 2 and body[0] == body[1]:
        high = _rank_index(body[0])
        if high < 0:
            return []
        if plus:
            return [f"{RANKS[index]}{RANKS[index]}" for index in range(high, len(RANKS))]
        return [f"{body[0].upper()}{body[1].upper()}"]
    if len(body) == 3:
        high, low = body[0].upper(), body[1].upper()
        suffix = body[2].lower()
        high_index, low_index = _rank_index(high), _rank_index(low)
        if high_index < 0 or low_index < 0 or low_index >= high_index:
            return []
        if suffix not in {"s", "o"}:
            return []
        if plus:
            return [
                f"{high}{RANKS[index]}{suffix}" for index in range(low_index, high_index)
            ]
        return [f"{high}{low}{suffix}"]
    if len(body) == 2:
        high, low = body[0].upper(), body[1].upper()
        high_index, low_index = _rank_index(high), _rank_index(low)
        if high_index < 0 or low_index < 0 or low_index >= high_index:
            return []
        if plus:
            return [
                f"{high}{RANKS[index]}" for index in range(low_index, high_index)
            ]
        return [f"{high}{low}"]
    return []


def _class_combo_count(combo_class: str) -> int:
    if len(combo_class) == 2:
        return _COMBOS_PER_PAIR
    if combo_class.endswith("s"):
        return _COMBOS_PER_SUITED
    if combo_class.endswith("o"):
        return _COMBOS_PER_OFFSUIT
    return _COMBOS_PER_UNSPECIFIED


@lru_cache(maxsize=512)
def range_classes(range_text: str) -> tuple[str, ...]:
    """Classes distinctes couvertes par la notation, ordre d'apparition conservé."""
    seen: dict[str, None] = {}
    for token in str(range_text or "").split(","):
        for combo_class in _token_classes(token):
            seen.setdefault(combo_class, None)
    return tuple(seen)


@lru_cache(maxsize=512)
def range_class_count(range_text: str) -> int:
    return len(range_classes(range_text))


@lru_cache(maxsize=512)
def range_combo_count(range_text: str) -> int:
    """Nombre de combos concrets (cartes) couverts par la notation."""
    return sum(_class_combo_count(combo_class) for combo_class in range_classes(range_text))
