"""Détecteur de drift temporel (pot figé / street bloquée) + confirmation Jev.

Compare deux snapshots successifs (dicts ``tracker``-like) avec des règles
pures — aucun appel réseau ici. La confirmation Jev éventuelle réutilise la
décision du gate (zéro appel supplémentaire), via ``confirm_with_jev``.
``observer_drift_check`` enrobe détection + confirmation pour un usage
observer : loggue "pause conseillée", ne bloque jamais.

Règles (transposées de table_tracker / sanity_checker / temporal_ocr) :
  - ``street_stalled`` : street identique mais board qui grandit ou pot qui
    change -> la street est décrochée du board.
  - ``pot_frozen`` : ``pot_total == last_pot`` alors que des mises sont
    observées (``total_bets_this_frame > 0``) ou que la street vient de
    changer -> pot figé.
  - ``promotion_pending`` : ``pending_street_promotion`` non vide pendant
    plus de 2 frames -> promotion jamais confirmée.
  - ``validation_stuck`` : même état de validation non-``fully_valid`` avec
    les mêmes raisons sur 2 snapshots de suite.
  - ``stale_repeated`` : ``frame_age_ms > 300`` sur 2 snapshots de suite.

En ``observer`` : loggue "pause conseillée", ne bloque jamais. En
``enforcing`` : le signal remonte au gate heuristique existant (seul
décideur), jamais un nouveau chemin de clic. Pas de pause automatique.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.bot.jev_gate import JevGateConfig

logger = logging.getLogger(__name__)

STALE_FRAME_AGE_MS = 300.0
PROMOTION_MAX_FRAMES = 2


@dataclass
class DriftSignal:
    kind: str  # street_stalled | pot_frozen | promotion_pending | validation_stuck | stale_repeated
    detail: str = ""


def _get(snapshot: Any, *names: str, default: Any = None) -> Any:
    if isinstance(snapshot, dict):
        for name in names:
            if snapshot.get(name) not in (None, ""):
                return snapshot[name]
        meta = snapshot.get("metadata")
        if isinstance(meta, dict):
            for name in names:
                if meta.get(name) not in (None, ""):
                    return meta[name]
    return default


def detect_drift(prev: dict[str, Any] | None, curr: dict[str, Any] | None) -> DriftSignal | None:
    """Compare deux snapshots successifs. Pur, jamais d'exception."""
    if not isinstance(prev, dict) or not isinstance(curr, dict):
        return None
    try:
        # 1. stale répété : deux frames trop vieilles d'affilée.
        prev_age = _get(prev, "frame_age_ms", default=0.0) or 0.0
        curr_age = _get(curr, "frame_age_ms", default=0.0) or 0.0
        if float(prev_age) > STALE_FRAME_AGE_MS and float(curr_age) > STALE_FRAME_AGE_MS:
            return DriftSignal("stale_repeated", f"frame_age_ms {prev_age:.0f}/{curr_age:.0f} > 300")

        # 2. street bloquée : même street mais board/pot qui bougent.
        prev_street = _get(prev, "street")
        curr_street = _get(curr, "street")
        if prev_street and curr_street and prev_street == curr_street:
            prev_board = _get(prev, "board", default=[]) or []
            curr_board = _get(curr, "board", default=[]) or []
            prev_pot = _get(prev, "pot", "pot_total", default=None)
            curr_pot = _get(curr, "pot", "pot_total", default=None)
            if len(curr_board) > len(prev_board):
                return DriftSignal(
                    "street_stalled",
                    f"street {curr_street} fixe mais board {len(prev_board)}->{len(curr_board)}",
                )
            if prev_pot != curr_pot and prev_pot is not None and curr_pot is not None:
                pending = _get(curr, "pending_street_promotion", default="")
                if pending:
                    return DriftSignal(
                        "street_stalled",
                        f"street {curr_street} fixe, pot {prev_pot}->{curr_pot}, promotion {pending} en attente",
                    )

        # 3. pot figé : pot inchangé malgré des mises ou un changement de street.
        prev_pot = _get(prev, "pot", "pot_total", "last_pot", default=None)
        curr_pot = _get(curr, "pot", "pot_total", default=None)
        bets = _get(curr, "total_bets_this_frame", "total_bets", default=0) or 0
        street_changed = _get(curr, "street_changed", default=False)
        if prev_pot is not None and curr_pot is not None and prev_pot == curr_pot:
            if float(bets) > 0:
                return DriftSignal("pot_frozen", f"pot {curr_pot} inchangé malgré mises={bets}")
            if street_changed and prev_street != curr_street:
                return DriftSignal(
                    "pot_frozen", f"pot {curr_pot} inchangé malgré street {prev_street}->{curr_street}"
                )

        # 4. promotion en attente trop longtemps.
        pending_frames = _get(curr, "pending_street_promotion_frames", default=0) or 0
        pending = _get(curr, "pending_street_promotion", default="")
        if pending and int(pending_frames) > PROMOTION_MAX_FRAMES:
            return DriftSignal(
                "promotion_pending", f"{pending} en attente depuis {pending_frames} frames (>2)"
            )

        # 5. validation invalide répétée à l'identique.
        prev_state = _get(prev, "validation_state", default="fully_valid")
        curr_state = _get(curr, "validation_state", default="fully_valid")
        if curr_state != "fully_valid" and prev_state == curr_state:
            prev_reasons = _get(prev, "validation_reasons", default=[]) or []
            curr_reasons = _get(curr, "validation_reasons", default=[]) or []
            if list(prev_reasons) == list(curr_reasons):
                return DriftSignal("validation_stuck", f"{curr_state}: {','.join(map(str, curr_reasons))}")
    except Exception:
        return None
    return None


def build_drift_state(prev: dict[str, Any], curr: dict[str, Any], signal: DriftSignal) -> str:
    """Phrase d'état textuelle pour la confirmation Jev (texte seul, jamais d'image)."""
    street = _get(curr, "street", default="?")
    board = _get(curr, "board", default=[]) or []
    pot = _get(curr, "pot", "pot_total", default="?")
    prev_pot = _get(prev, "pot", "pot_total", default="?")
    prev_street = _get(prev, "street", default="?")
    conf = _get(curr, "state_confidence", "confidence", default="?")
    return (
        f"temporal drift {signal.kind} ({signal.detail}). "
        f"street {prev_street}->{street}. "
        f"board {' '.join(str(c) for c in board) if board else 'empty'}. "
        f"pot {prev_pot}->{pot}. state confidence {conf}"
    )


def confirm_with_jev(signal: DriftSignal, jev: Any) -> tuple[bool, str]:
    """Confirme un drift avec la décision Jev du gate (zéro appel réseau).

    Retourne (pause_conseillee, raison). ``pause_conseillee`` True seulement
    si Jev déclare lui-même l'état incohérent (tier deep) ou risqué (> 0.7) —
    sinon le drift seul ne suffit pas (évite les faux positifs du filtre
    TemporalOCR qui stabilise le pot à dessein).
    """
    try:
        if isinstance(jev, dict):
            tier = jev.get("tier")
            risky = jev.get("risky")
        else:
            tier = getattr(jev, "tier", None)
            risky = getattr(jev, "risky", None)
        if tier == "deep":
            return True, f"drift {signal.kind} confirmé par Jev (tier deep)"
        if isinstance(risky, (int, float)) and risky > 0.7:
            return True, f"drift {signal.kind} confirmé par Jev (risky {risky:.2f})"
        return False, f"drift {signal.kind} non confirmé par Jev (tier={tier})"
    except Exception:
        return False, "drift confirm fail-open"


def observer_drift_check(
    prev: dict[str, Any] | None,
    curr: dict[str, Any] | None,
    *,
    jev: Any = None,
    config: JevGateConfig | None = None,
) -> tuple[DriftSignal | None, bool, str]:
    """Détecte un drift puis le confirme avec la décision Jev du gate.

    Zéro appel réseau : ``jev`` est la décision déjà calculée par le gate
    (``None`` = pas de confirmation possible, avis seul). En observer :
    loggue "pause conseillée" si confirmé, ne bloque jamais — le retour
    ``pause_conseillee`` est purement consultatif. Fail-open : tout échec
    -> (signal|None, False, raison).
    """
    cfg = config or JevGateConfig.from_env()
    if cfg.mode == "off":
        return None, False, "off"
    try:
        signal = detect_drift(prev, curr)
    except Exception:
        return None, False, "drift detect fail-open"
    if signal is None:
        return None, False, "no drift"
    if jev is None:
        logger.info(
            "JEV drift | %s (%s) — sans confirmation Jev (avis seul, pas de pause)",
            signal.kind,
            signal.detail,
        )
        return signal, False, "drift without jev confirmation (advisory only)"
    try:
        pause, reason = confirm_with_jev(signal, jev)
    except Exception:
        return signal, False, "drift confirm fail-open"
    if pause:
        logger.info("JEV drift | %s — pause conseillée (%s)", signal.kind, reason)
    else:
        logger.debug("JEV drift | %s — %s", signal.kind, reason)
    return signal, pause, reason
