"""Logger de mises adverses brutes (Phase 0.7.1).

Append-only JSONL dans ``evidence/bet_observations.jsonl`` : chaque mise
adversaire observée (bet/raise/all-in) avec le pot au moment de l'action.
Ce fichier alimente ``research/bet_tolerance_study.py`` pour recalibrer le
menu de quantification et sa tolérance (Phase 0.6.5 → 0.7).

Déduplication en mémoire : (action, amount arrondi, pot arrondi) n'est loggé
qu'une fois par processus — les frames répétées du même état ne polluent pas
l'histogramme.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

logger = logging.getLogger(__name__)

DEFAULT_BET_LOG_PATH = Path("evidence/bet_observations.jsonl")
_BET_ACTIONS = {"bet", "raise", "all_in", "allin", "all-in"}

_lock = threading.Lock()
_seen: set[tuple[str, float, float]] = set()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_bet_observation(
    *,
    player: str,
    action: str,
    amount: float,
    pot: float,
    street: str = "",
    path: str | Path = DEFAULT_BET_LOG_PATH,
) -> bool:
    """Log une mise adverse. Retourne True si une ligne a été écrite.

    ``street`` est optionnel (le chemin d'appel live ne le connaît pas
    toujours) ; l'histogramme de la Phase 0.7 le prend quand disponible.
    """
    action_norm = str(action or "").strip().lower()
    if action_norm not in _BET_ACTIONS:
        return False
    try:
        amount_f = round(float(amount), 2)
        pot_f = round(float(pot), 2)
    except (TypeError, ValueError):
        return False
    if amount_f <= 0.0:
        return False

    dedup_key = (action_norm, amount_f, pot_f)
    with _lock:
        if dedup_key in _seen:
            return False
        _seen.add(dedup_key)

    record = {
        "ts": _utc_now(),
        "player": str(player or ""),
        "action": action_norm,
        "amount": amount_f,
        "pot": pot_f,
        "street": str(street or ""),
        "pot_fraction": round(amount_f / pot_f, 4) if pot_f > 0 else None,
    }
    try:
        path = Path(os.getenv("POKER_BET_LOG_PATH") or path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return True
    except OSError as exc:
        logger.debug("bet_logger: écriture impossible : %s", exc)
        with _lock:
            _seen.discard(dedup_key)
        return False


def log_action_history_bets(
    action_history: list[dict] | None, *, pot: float, street: str = ""
) -> int:
    """Log toutes les mises adverses d'un historique d'actions.

    Appelé depuis le chemin de décision live ; chaque item attendu au format
    ``{"player": ..., "action": ..., "amount": ...}``.
    """
    count = 0
    for item in action_history or []:
        if not isinstance(item, dict):
            continue
        if log_bet_observation(
            player=str(item.get("player") or ""),
            action=str(item.get("action") or ""),
            amount=item.get("amount") or 0.0,
            pot=pot,
            street=street,
        ):
            count += 1
    return count
