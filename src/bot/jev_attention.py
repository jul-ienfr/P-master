"""Suggestion d'attention multi-tables assistée Jev (lecture seule, jamais de clic).

Constat : en prod (``src/main.py``) ``MultiTableLoop`` n'a ni ``signal_provider``
ni ``session_handler`` — la boucle réelle est mono-table. Ce module ne prétend
donc pas fournir un ``signal_provider`` (signature par-session, incapable de
départager). Il fournit ``suggest_attention_order`` : ordonnancement suggéré
lecture seule, à appeler après ``ordered_sessions`` quand le loop multi-table
sera câblé, sans jamais changer l'ordre des règles ni déclencher d'action.

Règles d'abord : l'ordre retourné conserve le tri par priorité des règles
(OUR_TURN > TIMEBANK > IDLE). Jev ne départage que les égalités de priorité
et seulement en mode != off ; tout échec -> ordre des règles inchangé.
Zéro appel réseau si moins de 2 sessions ex-aequo au top.
"""

from __future__ import annotations

import logging
from typing import Any

from src.bot.jev_gate import JevGateConfig, query
from src.runtime.multi_table_loop import PRIORITY_OUR_TURN, SessionTurnSignal

logger = logging.getLogger(__name__)


def build_attention_state(sessions: list[Any]) -> str:
    """Phrase d'état textuelle résumant les sessions ex-aequo."""
    parts = []
    for session in sessions:
        snap = session.snapshot() if hasattr(session, "snapshot") else {}
        tracker = snap.get("tracker_state", {}) if isinstance(snap, dict) else {}
        street = tracker.get("street", "?")
        pot = tracker.get("pot", "?")
        conf = tracker.get("state_confidence", "?")
        readiness = snap.get("readiness", {}) if isinstance(snap, dict) else {}
        sid = snap.get("session_id", "?") if isinstance(snap, dict) else "?"
        parts.append(
            f"table {sid}: street {street}, pot {pot}, "
            f"confidence {conf}, readiness {readiness.get('state', '?')}"
        )
    return (
        "Multiple poker tables need attention at equal rule priority. "
        + " ".join(parts) + ". "
        + "Which table most urgently needs a careful look?"
    )


def build_attention_questions(n: int) -> dict[str, Any]:
    criteria = {
        f"table_{i}": f"Table candidate #{i} needs attention first."
        for i in range(n)
    }
    return {
        "pick": {
            "type": "choice",
            "instructions": "Which table should the operator review first?",
            "criteria": criteria,
        },
        "risky": {
            "type": "noul",
            "instructions": "Acting on any of these tables now would risk real money.",
        },
    }


def suggest_attention_order(
    sessions: list[Any],
    signals: dict[str, SessionTurnSignal],
    *,
    config: JevGateConfig | None = None,
) -> list[str]:
    """Ordre suggéré de session_id. Règles d'abord, Jev tie-break seulement.

    Pur côté ordre : ne mute ni sessions ni signaux, ne déclenche aucune
    action. Fail-open : ordre des règles (tri stable par priorité).
    """
    cfg = config or JevGateConfig.from_env()
    ordered = sorted(
        sessions,
        key=lambda s: (signals.get(s.session_id) or SessionTurnSignal()).priority(),
        reverse=True,
    )
    rule_order = [s.session_id for s in ordered]
    if cfg.mode == "off" or len(ordered) < 2:
        return rule_order
    top = (signals.get(ordered[0].session_id) or SessionTurnSignal()).priority()
    if top < PRIORITY_OUR_TURN:
        return rule_order  # pas d'urgence : les règles suffisent
    contenders = [
        s for s in ordered
        if (signals.get(s.session_id) or SessionTurnSignal()).priority() == top
    ]
    if len(contenders) < 2:
        return rule_order
    try:
        decision = query(
            build_attention_state(contenders),
            build_attention_questions(len(contenders)),
            config=cfg,
        )
        answers = decision.raw.get("answers", {}) or {}
        pick = answers.get("pick", {}) or {}
        choice = pick.get("choice", "")
        idx = int(str(choice).split("_")[-1]) if str(choice).startswith("table_") else -1
        if 0 <= idx < len(contenders):
            picked = contenders[idx].session_id
            rest = [sid for sid in rule_order if sid != picked]
            # Le pick remonte en tête du groupe ex-aequo, sans dépasser
            # une priorité supérieure (il est déjà au top par construction).
            top_group = [s.session_id for s in contenders]
            top_group.remove(picked)
            new_top = [picked] + top_group
            logger.info(
                "JEV attention | mode=%s pick=%s among %d tables (advisory only)",
                cfg.mode, picked, len(contenders),
            )
            return new_top + [sid for sid in rest if sid not in new_top]
        logger.info("JEV attention | unparsable pick %r, rule order kept", choice)
    except Exception as exc:  # fail-open : règles seules
        logger.debug("JEV attention fail-open: %s", exc)
    return rule_order


def attention_snapshot_extra(
    sessions: list[Any],
    signals: dict[str, SessionTurnSignal],
    *,
    config: JevGateConfig | None = None,
) -> dict[str, Any]:
    """Brique lecture seule pour l'UI : suggestion d'attention sans effet."""
    cfg = config or JevGateConfig.from_env()
    return {
        "mode": cfg.mode,
        "suggested_order": suggest_attention_order(sessions, signals, config=cfg),
        "rule_priorities": {
            s.session_id: (signals.get(s.session_id) or SessionTurnSignal()).priority()
            for s in sessions
        },
        "note": "rule order only; jev tie-break is advisory",
    }
