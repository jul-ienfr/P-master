from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_GO_LIVE_THRESHOLDS = {
    "min_decision_count": 20,
    "max_block_rate": 0.5,
    "max_fallback_rate": 0.5,
    "max_rolling_latency_ms": 2500.0,
    "max_incident_count": 10,
    "min_readiness_score": 0.6,
    "max_non_actionable_readiness_rate": 0.5,
    "max_invalid_validation_rate": 0.5,
}


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
) -> GoLiveGateResult:
    thresholds = {**DEFAULT_GO_LIVE_THRESHOLDS, **dict(thresholds or {})}
    metrics = {
        "decision_count": int(local_metrics.get("decision_count", 0) or 0),
        "block_rate": float(local_metrics.get("block_rate", 0.0) or 0.0),
        "fallback_rate": float(local_metrics.get("fallback_rate", 0.0) or 0.0),
        "rolling_latency_ms": float(local_metrics.get("rolling_latency_ms", 0.0) or 0.0),
        "incident_count": int((metrics_snapshot.get("runtime", {}) or {}).get("incident_count", 0) or 0),
        "readiness_score": float((readiness or {}).get("score", 0.0) or 0.0),
        "readiness_state": str((readiness or {}).get("state") or "unknown"),
        "validation_state": str((validation or {}).get("state") or "unknown"),
        "non_actionable_readiness_rate": 1.0 if str((readiness or {}).get("state") or "unknown") in {"blocked_local", "conservative"} else 0.0,
        "invalid_validation_rate": 1.0 if str((validation or {}).get("state") or "unknown") in {"soft_invalid", "hard_invalid"} else 0.0,
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
            "ok": metrics["non_actionable_readiness_rate"] <= thresholds["max_non_actionable_readiness_rate"],
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
