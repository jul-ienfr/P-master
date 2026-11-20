"""Contrat de métriques stratégiques pour le gate go-live (constat F-03).

``evaluate_go_live_gate`` accepte ``strategy_metrics`` depuis la Phase 5.18, mais
aucun appelant ne le fournissait : les deux checks stratégiques étaient toujours
neutralisés (même schéma que le ``SessionManager`` orphelin de la spec ``004``).
De plus, la seule condition était ``winrate_bb100 >= 0`` : un winrate de
+0,1 bb/100 avec un IC95 de [−50 ; +50] passait, c'est-à-dire un résultat non
significatif présenté comme une preuve.

Ce module compose le payload du gate depuis les artefacts d'évaluation et le
relit depuis le disque. Il ne fabrique jamais de chiffre : un artefact absent ou
illisible donne ``{}`` (checks neutralisés, comportement historique préservé).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "research" / "results"
STRATEGY_METRICS_ENV = "POKER_STRATEGY_METRICS_PATH"

# Champs qui activent les checks de protocole dans le gate. Leur présence
# signifie « un artefact d'évaluation scientifique est disponible ».
PROTOCOL_FIELDS = (
    "winrate_ci_low",
    "winrate_ci_high",
    "evaluated_hands",
    "required_hands",
)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_strategy_metrics(
    winrate_report: dict[str, Any] | None,
    *,
    best_response_gap: float | None = None,
) -> dict[str, Any]:
    """Compose le payload ``strategy_metrics`` du gate depuis un artefact de winrate.

    Les champs de protocole (IC, effectif, effectif requis, politique de
    production) sont copiés **seulement** s'ils existent dans l'artefact : un
    artefact partiel neutralise les checks de protocole au lieu de les faire
    passer sur des valeurs par défaut.
    """
    if not winrate_report:
        return {}

    metrics: dict[str, Any] = {}

    winrate = _as_float(winrate_report.get("winrate_bb100"))
    if winrate is not None:
        metrics["winrate_bb100"] = winrate

    gap = best_response_gap
    if gap is None:
        gap = _as_float(winrate_report.get("best_response_gap"))
    if gap is not None:
        metrics["best_response_gap"] = gap

    ci_low = _as_float(winrate_report.get("ci95_low_bb100"))
    ci_high = _as_float(winrate_report.get("ci95_high_bb100"))
    evaluated = _as_int(winrate_report.get("hands"))
    required = _as_int(winrate_report.get("required_hands"))

    if ci_low is not None:
        metrics["winrate_ci_low"] = ci_low
    if ci_high is not None:
        metrics["winrate_ci_high"] = ci_high
    if evaluated is not None:
        metrics["evaluated_hands"] = evaluated
    if required is not None:
        metrics["required_hands"] = required

    metrics["hero_policy"] = str(winrate_report.get("hero_policy") or "unknown")
    metrics["hero_policy_is_production"] = bool(
        winrate_report.get("hero_policy_is_production", False)
    )
    generated_at = winrate_report.get("generated_at")
    if generated_at:
        metrics["artifact_generated_at"] = str(generated_at)

    status = winrate_report.get("status")
    if status:
        metrics["winrate_status"] = str(status)

    return metrics


def strategy_metrics_from_artifacts(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Lit l'artefact de winrate de production et compose les métriques du gate.

    Chemin : ``path``, sinon ``POKER_STRATEGY_METRICS_PATH``, sinon
    ``research/results/production_winrate.json``. Un fichier absent, illisible ou
    non-JSON retourne ``{}`` — jamais un winrate de zéro inventé.
    """
    resolved = path or os.environ.get(STRATEGY_METRICS_ENV)
    target = Path(resolved) if resolved else DEFAULT_ARTIFACT_DIR / "production_winrate.json"

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    return build_strategy_metrics(payload)
