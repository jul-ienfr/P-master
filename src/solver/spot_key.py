"""Clé de spot partagée : cache LRU solve, lookup blueprint (live) et
générateur offline utilisent exactement la même normalisation
(Phase 0.5.6 / 0.6.4 — parité de clé Python partout).

Module volontairement sans dépendances lourdes (importable depuis
src.solver.provider comme depuis src.bot.decision_maker).
"""

from __future__ import annotations

import hashlib
import json

_BLUEPRINT_VERSION = 1


def spot_cache_key(
    *,
    hero_hand: str,
    villain_range: str,
    board: list[str],
    pot: float,
    effective_stack: float,
    legal_actions: list[str],
    spot_id: str,
    hero_position: str,
    action_history: list[str],
    rake: float = 0.0,
    state_confidence: float | None = None,
    epsilon: float | None = None,
    hero_range: str = "",
    num_players: int | None = None,
    villain_ranges: list[str] | tuple[str, ...] | None = None,
    hero_player_index: int | None = None,
    active_positions: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Clé canonique d'un spot.

    ``state_confidence`` est quantifiée à 2 décimales et incluse quand elle est
    fournie (Phase 0.5.6/4.1 — H3). ``epsilon`` identifie la cible de
    convergence du blueprint (Phase 0.5.6). Quand les deux sont ``None`` la
    clé est byte-identique au format historique de ``_solve_cache_key``.
    ``hero_range`` est inclus quand il est non vide : deux combos cibles de la
    même range ne doivent jamais partager l'EV d'un autre combo.
    """
    payload = {
        "hero": hero_hand,
        "villain": villain_range,
        "board": list(board or []),
        "pot": round(float(pot), 4),
        "stack": round(float(effective_stack), 4),
        "legal": list(legal_actions or []),
        "spot": spot_id,
        "pos": hero_position,
        "hist": list(action_history or []),
        "rake": round(float(rake), 4),
    }
    if state_confidence is not None:
        payload["conf"] = round(float(state_confidence), 2)
    if epsilon is not None:
        payload["eps"] = round(float(epsilon), 6)
        payload["bpv"] = _BLUEPRINT_VERSION
    if str(hero_range or "").strip():
        payload["hr"] = str(hero_range).strip()
    if num_players is not None and int(num_players) > 2:
        payload["n"] = int(num_players)
        payload["vr"] = [str(value) for value in (villain_ranges or [])]
        payload["hpi"] = int(hero_player_index or 0)
        payload["po"] = [str(value) for value in (active_positions or [])]
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
