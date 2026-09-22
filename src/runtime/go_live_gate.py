from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

DEFAULT_GO_LIVE_THRESHOLDS = {
    "min_decision_count": 20,
    "max_block_rate": 0.5,
    "max_fallback_rate": 0.5,
    "max_rolling_latency_ms": 2500.0,
    "max_incident_count": 10,
    "min_readiness_score": 0.6,
    "max_non_actionable_readiness_rate": 0.5,
    "max_invalid_validation_rate": 0.5,
    # Seuils stratégiques (Phase 5.18) : appliqués seulement quand les artifacts
    # d'évaluation scientifique sont fournis via ``strategy_metrics``.
    "min_winrate_bb100": 0.0,
    "max_best_response_gap_bb": 0.25,
    # Phase 0.6.7 / 0.7.3 : applicables quand ``blueprint_metrics`` est fourni.
    # Couverture du blueprint pour le format courant (bloque le go-live) et
    # présence d'un rapport de calibration de tolérance de mises à jour.
    "min_blueprint_coverage": 1.0,
    "require_bet_tolerance_report": True,
    "bet_tolerance_report_max_age_days": 30.0,
}


def _blueprint_current_coverage(blueprint_metrics: dict) -> float:
    """Couverture du format courant depuis le rapport `blueprint audit`."""
    formats = blueprint_metrics.get("formats") or {}
    current = str(blueprint_metrics.get("current_format") or "").strip()
    if current and current in formats:
        return float((formats[current] or {}).get("coverage", 0.0) or 0.0)
    if not formats:
        return 0.0
    coverages = [float((cfg or {}).get("coverage", 0.0) or 0.0) for cfg in formats.values()]
    return min(coverages)


def _bet_tolerance_report_ok(blueprint_metrics: dict, thresholds: dict | None = None) -> bool:
    """Le rapport de calibration `docs/bet_tolerance_report.md` existe et est frais."""
    report = blueprint_metrics.get("bet_tolerance_report") or {}
    if not report.get("present"):
        return False
    generated_at = str(report.get("generated_at") or "").strip()
    if not generated_at:
        return False
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    max_age_days = 30.0
    if thresholds:
        max_age_days = float(thresholds.get("bet_tolerance_report_max_age_days", max_age_days))
    age_s = time.time() - parsed.timestamp()
    return age_s <= max_age_days * 86400.0


@dataclass(frozen=True)
class GoLiveGateResult:
    status: str
    passed: bool
    reasons: tuple[str, ...]
    thresholds: dict[str, Any]
    metrics: dict[str, Any]
    verdict: str
    checks: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "thresholds": dict(self.thresholds),
            "metrics": dict(self.metrics),
            "verdict": self.verdict,
            "checks": dict(self.checks),
        }


def evaluate_go_live_gate(
    local_metrics: dict,
    metrics_snapshot: dict,
    *,
    readiness: dict | None = None,
    validation: dict | None = None,
    thresholds: dict | None = None,
    strategy_metrics: dict | None = None,
    blueprint_metrics: dict | None = None,
) -> GoLiveGateResult:
    """Évalue le gate go-live.

    ``strategy_metrics`` porte les artifacts d'évaluation scientifique (Phase 5) :
    ``winrate_bb100`` (simulateur Monte-Carlo, research.monte_carlo_sim) et
    ``best_response_gap`` (MES du solveur natif, research.best_response). Quand il est
    absent, les checks stratégiques sont neutralisés (non bloquants).

    ``blueprint_metrics`` porte le rapport de ``blueprint audit``
    (``formats`` → ``coverage``) ainsi que ``current_format`` et
    ``bet_tolerance_report`` ({present, generated_at_iso}). Quand il est
    absent, les checks blueprint sont neutralisés (non bloquants) — le mode
    zéro-approximation exige de les fournir avant un go-live réel.
    """
    strategy_metrics = dict(strategy_metrics or {})
    has_strategy_artifacts = bool(strategy_metrics)
    blueprint_metrics = dict(blueprint_metrics or {})
    has_blueprint_artifacts = bool(blueprint_metrics)

    thresholds = {**DEFAULT_GO_LIVE_THRESHOLDS, **dict(thresholds or {})}
    metrics = {
        "decision_count": int(local_metrics.get("decision_count", 0) or 0),
        "block_rate": float(local_metrics.get("block_rate", 0.0) or 0.0),
        "fallback_rate": float(local_metrics.get("fallback_rate", 0.0) or 0.0),
        "rolling_latency_ms": float(local_metrics.get("rolling_latency_ms", 0.0) or 0.0),
        "incident_count": int(
            (metrics_snapshot.get("runtime", {}) or {}).get("incident_count", 0) or 0
        ),
        "readiness_score": float((readiness or {}).get("score", 0.0) or 0.0),
        "readiness_state": str((readiness or {}).get("state") or "unknown"),
        "validation_state": str((validation or {}).get("state") or "unknown"),
        "non_actionable_readiness_rate": 1.0
        if str((readiness or {}).get("state") or "unknown") in {"blocked_local", "conservative"}
        else 0.0,
        "invalid_validation_rate": 1.0
        if str((validation or {}).get("state") or "unknown") in {"soft_invalid", "hard_invalid"}
        else 0.0,
        "strategy_evaluated": 1.0 if has_strategy_artifacts else 0.0,
        "winrate_bb100": float(strategy_metrics.get("winrate_bb100", 0.0) or 0.0),
        "best_response_gap": float(strategy_metrics.get("best_response_gap", 0.0) or 0.0),
        "blueprint_coverage": (
            _blueprint_current_coverage(blueprint_metrics) if has_blueprint_artifacts else 0.0
        ),
        "bet_tolerance_report_ok": (
            1.0 if _bet_tolerance_report_ok(blueprint_metrics, thresholds) else 0.0
        )
        if has_blueprint_artifacts
        else 0.0,
    }
    checks = {
        "decision_count": {
            "ok": metrics["decision_count"] >= thresholds["min_decision_count"],
            "metric": metrics["decision_count"],
            "threshold": thresholds["min_decision_count"],
            "operator": ">=",
            "reason": "insufficient_decision_count",
        },
        "block_rate": {
            "ok": metrics["block_rate"] <= thresholds["max_block_rate"],
            "metric": metrics["block_rate"],
            "threshold": thresholds["max_block_rate"],
            "operator": "<=",
            "reason": "block_rate_too_high",
        },
        "fallback_rate": {
            "ok": metrics["fallback_rate"] <= thresholds["max_fallback_rate"],
            "metric": metrics["fallback_rate"],
            "threshold": thresholds["max_fallback_rate"],
            "operator": "<=",
            "reason": "fallback_rate_too_high",
        },
        "rolling_latency_ms": {
            "ok": metrics["rolling_latency_ms"] <= thresholds["max_rolling_latency_ms"],
            "metric": metrics["rolling_latency_ms"],
            "threshold": thresholds["max_rolling_latency_ms"],
            "operator": "<=",
            "reason": "latency_too_high",
        },
        "incident_count": {
            "ok": metrics["incident_count"] <= thresholds["max_incident_count"],
            "metric": metrics["incident_count"],
            "threshold": thresholds["max_incident_count"],
            "operator": "<=",
            "reason": "incident_count_too_high",
        },
        "readiness_score": {
            "ok": metrics["readiness_score"] >= thresholds["min_readiness_score"],
            "metric": metrics["readiness_score"],
            "threshold": thresholds["min_readiness_score"],
            "operator": ">=",
            "reason": "readiness_score_too_low",
        },
        "non_actionable_readiness_rate": {
            "ok": metrics["non_actionable_readiness_rate"]
            <= thresholds["max_non_actionable_readiness_rate"],
            "metric": metrics["non_actionable_readiness_rate"],
            "threshold": thresholds["max_non_actionable_readiness_rate"],
            "operator": "<=",
            "reason": "readiness_state_not_actionable",
        },
        "invalid_validation_rate": {
            "ok": metrics["invalid_validation_rate"] <= thresholds["max_invalid_validation_rate"],
            "metric": metrics["invalid_validation_rate"],
            "threshold": thresholds["max_invalid_validation_rate"],
            "operator": "<=",
            "reason": "validation_state_invalid",
        },
        "winrate_bb100": {
            "ok": (not has_strategy_artifacts)
            or metrics["winrate_bb100"] >= thresholds["min_winrate_bb100"],
            "metric": metrics["winrate_bb100"],
            "threshold": thresholds["min_winrate_bb100"],
            "operator": ">=",
            "reason": "winrate_below_threshold",
        },
        "best_response_gap": {
            "ok": (not has_strategy_artifacts)
            or metrics["best_response_gap"] <= thresholds["max_best_response_gap_bb"],
            "metric": metrics["best_response_gap"],
            "threshold": thresholds["max_best_response_gap_bb"],
            "operator": "<=",
            "reason": "exploitability_above_threshold",
        },
        # Phase 0.6.7 — bloquant live : couverture du format courant à 1.0.
        "blueprint_coverage": {
            "ok": (not has_blueprint_artifacts)
            or metrics["blueprint_coverage"] >= thresholds["min_blueprint_coverage"],
            "metric": metrics["blueprint_coverage"],
            "threshold": thresholds["min_blueprint_coverage"],
            "operator": ">=",
            "reason": "blueprint_coverage_below_1",
        },
        # Phase 0.7.3 — bloquant : tolérance de quantification sans rapport
        # de calibration à jour ne peut pas fonder un go-live.
        "bet_tolerance_report": {
            "ok": (not has_blueprint_artifacts)
            or (not thresholds["require_bet_tolerance_report"])
            or bool(metrics["bet_tolerance_report_ok"]),
            "metric": metrics["bet_tolerance_report_ok"],
            "threshold": thresholds["require_bet_tolerance_report"],
            "operator": "bool",
            "reason": "bet_tolerance_report_missing_or_stale",
        },
    }
    reasons = [str(check["reason"]) for check in checks.values() if not bool(check["ok"])]

    passed = not reasons
    verdict = "go" if passed else "no_go"
    return GoLiveGateResult(
        status="ready" if passed else "blocked",
        passed=passed,
        reasons=tuple(reasons),
        thresholds=thresholds,
        metrics=metrics,
        verdict=verdict,
        checks=checks,
    )
