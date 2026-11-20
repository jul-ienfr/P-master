"""Objectifs de niveau de service (SLO) et alertes — constat F-10, spec 008.

L'audit le dit explicitement : « le taux de fallback n'est pas un SLO bloquant ».
Il existe des seuils d'**admission** au go-live et un moniteur de santé par
sous-système, mais rien n'évalue en continu un objectif de **fonctionnement** sur
les décisions réelles : un taux de fallback de 40 % en session ne lève aucun
signal, il n'est visible qu'en relisant un snapshot.

Ce module est **pur** : métriques + cibles → statut par objectif + alertes. Il
n'écrit dans aucun état global, ne lit aucun journal et ne connaît pas le gate
go-live. « Apte à démarrer » et « en bonne santé maintenant » restent deux
notions distinctes et nommées.

Fail-closed : un objectif sans effectif suffisant est ``insufficient_data``,
**jamais** ``ok`` ; une cible absente ou non numérique est ``ignored`` avec sa
raison, jamais un ``breached`` implicite ; aucun objectif configuré rend un
ensemble vide, jamais une fausse alerte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.runtime.stage_timing import percentile

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

STATUS_OK = "ok"
STATUS_BREACHED = "breached"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_IGNORED = "ignored"

_OPERATORS = {
    "<=": lambda value, target: value <= target,
    "<": lambda value, target: value < target,
    ">=": lambda value, target: value >= target,
    ">": lambda value, target: value > target,
    "==": lambda value, target: value == target,
}

DEFAULT_SAMPLE_METRIC = "decision_count"
DEFAULT_MIN_SAMPLES = 5


@dataclass(frozen=True)
class SloObjective:
    """Un objectif de service : métrique, opérateur, cible, sévérité.

    ``min_samples`` est l'effectif minimal sous lequel l'objectif n'est pas
    évaluable : en dessous, le statut est ``insufficient_data`` — un objectif
    tenu sur trois décisions n'est pas un objectif tenu.
    """

    name: str
    metric: str
    operator: str
    target: float
    severity: str = "warning"
    min_samples: int = DEFAULT_MIN_SAMPLES
    sample_metric: str = DEFAULT_SAMPLE_METRIC

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "target": self.target,
            "severity": self.severity,
            "min_samples": self.min_samples,
            "sample_metric": self.sample_metric,
        }


# Valeurs par défaut déclarées **en un seul endroit** (FR-010). Elles sont
# volontairement plus strictes que les seuils d'admission du go-live
# (`max_fallback_rate` 0,5 ; `max_rolling_latency_ms` 2500) : le gate dit
# « apte à démarrer », le SLO dit « en bonne santé maintenant ». Les confondre
# reviendrait à ne plus détecter une dégradation en session.
DEFAULT_SLO_OBJECTIVES: tuple[SloObjective, ...] = (
    SloObjective(
        name="fallback_rate",
        metric="fallback_rate",
        operator="<=",
        target=0.1,
        severity="warning",
    ),
    SloObjective(
        name="block_rate",
        metric="block_rate",
        operator="<=",
        target=0.2,
        severity="warning",
    ),
    SloObjective(
        name="latency_p95_ms",
        metric="latency_p95_ms",
        operator="<=",
        target=500.0,
        severity="warning",
    ),
    SloObjective(
        name="solver_p95_ms",
        metric="solver_p95_ms",
        operator="<=",
        target=450.0,
        severity="warning",
    ),
)


@dataclass(frozen=True)
class SloEvaluation:
    """Résultat d'une évaluation : statut par objectif et alertes nommées."""

    objectives: tuple[dict[str, Any], ...] = ()
    alerts: tuple[dict[str, Any], ...] = ()
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectives": [dict(item) for item in self.objectives],
            "alerts": [dict(item) for item in self.alerts],
            "evaluated_at": self.evaluated_at,
        }

    @property
    def breached(self) -> tuple[str, ...]:
        return tuple(
            str(item.get("name")) for item in self.objectives if item.get("status") == STATUS_BREACHED
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evaluate_objective(objective: SloObjective, metrics: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        **objective.to_dict(),
        "value": None,
        "samples": None,
        "status": STATUS_IGNORED,
        "reason": "",
    }
    compare = _OPERATORS.get(str(objective.operator or "").strip())
    if compare is None:
        entry["reason"] = "unknown_operator"
        return entry

    target = _as_float(objective.target)
    if target is None:
        entry["reason"] = "invalid_target"
        return entry
    entry["target"] = target

    # Une métrique **absente** est ``ignored`` avec sa raison, quelle que soit la
    # taille de l'échantillon : on ne compare pas à une cible une valeur qui n'a
    # pas été mesurée. L'effectif insuffisant, lui, porte sur une valeur mesurée
    # et reste ``insufficient_data`` — deux manques distincts, jamais confondus.
    value = _as_float(metrics.get(objective.metric))
    if value is None:
        entry["reason"] = "metric_missing"
        return entry

    samples = _as_float(metrics.get(objective.sample_metric))
    entry["samples"] = None if samples is None else int(samples)
    min_samples = max(0, int(objective.min_samples))
    if samples is None or int(samples) < min_samples:
        entry["status"] = STATUS_INSUFFICIENT_DATA
        entry["reason"] = "insufficient_samples"
        return entry

    entry["value"] = round(value, 4)

    if compare(value, target):
        entry["status"] = STATUS_OK
        return entry
    entry["status"] = STATUS_BREACHED
    entry["reason"] = f"{objective.metric}{objective.operator.replace('=', '')}_target"
    return entry


def evaluate_slo(
    metrics: dict[str, Any],
    objectives: tuple[SloObjective, ...] | list[SloObjective] | None = None,
    *,
    evaluated_at: str | None = None,
) -> SloEvaluation:
    """Évalue les objectifs sur des métriques réelles — sans aucun effet de bord.

    ``objectives`` absent : les valeurs par défaut du module. Une séquence vide
    (SLO explicitement désactivés) rend un ensemble vide, jamais une alerte.
    """
    resolved = DEFAULT_SLO_OBJECTIVES if objectives is None else tuple(objectives)
    if not resolved:
        return SloEvaluation(objectives=(), alerts=(), evaluated_at=evaluated_at or _utc_now())

    entries: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for objective in resolved:
        entry = _evaluate_objective(objective, dict(metrics or {}))
        entries.append(entry)
        if entry["status"] != STATUS_BREACHED:
            continue
        alerts.append(
            {
                "name": entry["name"],
                "metric": entry["metric"],
                "value": entry["value"],
                "target": entry["target"],
                "operator": entry["operator"],
                "severity": entry["severity"],
                "reason": entry["reason"],
            }
        )
    return SloEvaluation(
        objectives=tuple(entries),
        alerts=tuple(alerts),
        evaluated_at=evaluated_at or _utc_now(),
    )


def breached_names(evaluation: SloEvaluation | dict[str, Any]) -> tuple[str, ...]:
    """Noms des objectifs franchis — pour l'alerte de transition côté appelant."""
    if isinstance(evaluation, SloEvaluation):
        return evaluation.breached
    objectives = (evaluation or {}).get("objectives") or []
    return tuple(
        str(item.get("name"))
        for item in objectives
        if isinstance(item, dict) and item.get("status") == STATUS_BREACHED
    )


def parse_slo_objectives(raw: Any) -> tuple[SloObjective, ...]:
    """Objectifs depuis la configuration (``bot.slo``) ; défauts si absents.

    Une liste vide est honorée (SLO explicitement désactivés). Une entrée
    malformée est écartée — un objectif illisible ne doit pas empêcher
    l'évaluation des autres ni faire échouer le snapshot opérateur.
    """
    if raw is None:
        return DEFAULT_SLO_OBJECTIVES
    if isinstance(raw, dict):
        raw = [{"name": name, **(spec if isinstance(spec, dict) else {})} for name, spec in raw.items()]
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_SLO_OBJECTIVES

    objectives: list[SloObjective] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        metric = str(item.get("metric") or name).strip()
        if not name or not metric:
            continue
        operator = str(item.get("operator") or "<=").strip()
        if operator not in _OPERATORS:
            continue
        target = _as_float(item.get("target"))
        if target is None:
            continue
        objectives.append(
            SloObjective(
                name=name,
                metric=metric,
                operator=operator,
                target=target,
                severity=str(item.get("severity") or "warning"),
                min_samples=int(item.get("min_samples", DEFAULT_MIN_SAMPLES) or 0),
                sample_metric=str(item.get("sample_metric") or DEFAULT_SAMPLE_METRIC),
            )
        )
    return tuple(objectives)


def slo_objectives_from_config(config: Any) -> tuple[SloObjective, ...]:
    """Objectifs déclarés par la configuration du bot, sinon les défauts."""
    bot = config.get("bot") if isinstance(config, dict) else None
    raw = bot.get("slo") if isinstance(bot, dict) else None
    return parse_slo_objectives(raw)


def _latency_ms(entry: dict[str, Any]) -> float | None:
    value = entry.get("latency_ms")
    if value is None and isinstance(entry.get("decision"), dict):
        value = entry["decision"].get("elapsed_ms")
    return _as_float(value)


def _stage_ms(entry: dict[str, Any], stage: str) -> float | None:
    from src.runtime.stage_timing import extract_stages_ms

    stages = extract_stages_ms(entry)
    return _as_float(stages.get(stage)) if stages else None


def slo_metrics_from_history(local_metrics: dict[str, Any], decisions: Any) -> dict[str, Any]:
    """Métriques de SLO depuis l'historique réel — aucune nouvelle source.

    Un p95 sans latence enregistrée vaut ``None`` (l'objectif sera ``ignored``
    avec sa raison) plutôt que zéro : zéro serait un succès inventé.
    """
    entries = [entry for entry in (decisions or []) if isinstance(entry, dict)]
    latencies = sorted(
        value for value in (_latency_ms(entry) for entry in entries) if value is not None
    )
    solver_latencies = sorted(
        value
        for value in (_stage_ms(entry, "solver") for entry in entries)
        if value is not None
    )

    def _p95(values: list[float]) -> float | None:
        if not values:
            return None
        return round(percentile(values, 0.95), 1)

    return {
        "decision_count": int((local_metrics or {}).get("decision_count", 0) or 0),
        "fallback_rate": float((local_metrics or {}).get("fallback_rate", 0.0) or 0.0),
        "block_rate": float((local_metrics or {}).get("block_rate", 0.0) or 0.0),
        "rolling_latency_ms": float((local_metrics or {}).get("rolling_latency_ms", 0.0) or 0.0),
        "latency_p95_ms": _p95(latencies),
        "solver_p95_ms": _p95(solver_latencies),
    }


@dataclass
class SloTracker:
    """Mémoire de transition : quel ensemble d'objectifs est franchi.

    L'alerte n'est émise qu'au **changement** de l'ensemble franchi — un SLO
    franchi ne doit pas produire un événement par snapshot.
    """

    breached: tuple[str, ...] = field(default_factory=tuple)
    seen: bool = False

    def observe(self, evaluation: SloEvaluation | dict[str, Any]) -> dict[str, Any] | None:
        """Retourne la transition à signaler, ou ``None`` s'il n'y en a pas."""
        current = tuple(sorted(breached_names(evaluation)))
        previous = self.breached
        first = not self.seen
        self.breached = current
        self.seen = True
        if first or current == previous:
            return None
        if current:
            return {
                "kind": "slo_breached",
                "breached": list(current),
                "resolved": [name for name in previous if name not in current],
            }
        return {
            "kind": "slo_recovered",
            "breached": [],
            "resolved": list(previous),
        }
