"""Validation helpers for oracle parity, replay safety, latency, and gate observability."""

from __future__ import annotations

from typing import Any, Callable
import statistics
import time

from poker.decisionmaker.v2_contracts import (
    BenchmarkResult,
    DecisionSnapshot,
    ReplayRecord,
    SolveRequestV2,
    SpotSnapshot,
)
from research.benchmark_harness import BenchmarkHarness, HandRankCase, SolverProbe


DecisionRunner = Callable[[SpotSnapshot], DecisionSnapshot | dict[str, Any]]


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _normalize_reason(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def summarize_gate_decisions(
    decisions: list[DecisionSnapshot] | tuple[DecisionSnapshot, ...],
) -> dict[str, Any]:
    allowed = 0
    blocked = 0
    fallback = 0
    cache_hits = 0
    incident_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    confidence_samples: list[float] = []
    latency_samples: list[float] = []
    cache_hit_latency_samples: list[float] = []
    fallback_latency_samples: list[float] = []

    for decision in decisions:
        gate = decision.gate_result
        gate_allowed = bool(gate.allowed) if gate is not None else True
        gate_reason = _normalize_reason(gate.reason if gate is not None else None, "ready")
        if gate_allowed:
            allowed += 1
        else:
            blocked += 1
        reason_counts[gate_reason] = reason_counts.get(gate_reason, 0) + 1

        metadata = dict(gate.metadata) if gate is not None and gate.metadata else {}
        used_fallback = bool(metadata.get("fallback_used")) or str(decision.source or "").lower() == "fallback"
        if used_fallback:
            fallback += 1
            if decision.latency_ms is not None:
                fallback_latency_samples.append(float(decision.latency_ms))

        cache_hit = bool(metadata.get("cache_hit")) or bool(decision.metadata.get("cache_hit"))
        if cache_hit:
            cache_hits += 1
            if decision.latency_ms is not None:
                cache_hit_latency_samples.append(float(decision.latency_ms))

        confidence_value = gate.confidence if gate is not None else decision.confidence
        if confidence_value is not None:
            confidence_samples.append(float(confidence_value))

        if decision.latency_ms is not None:
            latency_samples.append(float(decision.latency_ms))

        incidents = tuple(decision.warnings or ()) + (tuple(gate.warnings) if gate is not None else ())
        for incident in incidents:
            incident_key = _normalize_reason(incident, "unknown")
            incident_counts[incident_key] = incident_counts.get(incident_key, 0) + 1

    total = len(decisions)
    ordered_latency = sorted(latency_samples)
    p95_index = min(len(ordered_latency) - 1, max(0, int(round((len(ordered_latency) - 1) * 0.95)))) if ordered_latency else 0
    return {
        "total": total,
        "allowed": allowed,
        "blocked": blocked,
        "fallback": fallback,
        "cache_hits": cache_hits,
        "allow_rate": _safe_ratio(allowed, total),
        "block_rate": _safe_ratio(blocked, total),
        "fallback_rate": _safe_ratio(fallback, total),
        "cache_hit_rate": _safe_ratio(cache_hits, total),
        "avg_confidence": round(statistics.fmean(confidence_samples), 4) if confidence_samples else 0.0,
        "avg_latency_ms": round(statistics.fmean(latency_samples), 3) if latency_samples else 0.0,
        "min_latency_ms": round(min(latency_samples), 3) if latency_samples else 0.0,
        "max_latency_ms": round(max(latency_samples), 3) if latency_samples else 0.0,
        "p95_latency_ms": round(ordered_latency[p95_index], 3) if ordered_latency else 0.0,
        "avg_cache_hit_latency_ms": round(statistics.fmean(cache_hit_latency_samples), 3) if cache_hit_latency_samples else 0.0,
        "avg_fallback_latency_ms": round(statistics.fmean(fallback_latency_samples), 3) if fallback_latency_samples else 0.0,
        "top_gate_reasons": sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:8],
        "top_incidents": sorted(incident_counts.items(), key=lambda item: (-item[1], item[0]))[:8],
        "reason_counts": reason_counts,
        "incident_counts": incident_counts,
    }


def build_default_hand_rank_cases() -> list[HandRankCase]:
    return [
        HandRankCase(
            case_id="royal_flush_boarded",
            cards=("As", "Ks", "Qs", "Js", "Ts"),
            metadata={"category": "made_hand", "street": "river"},
        ),
        HandRankCase(
            case_id="quads_full_board",
            cards=("Ah", "Ad", "Ac", "As", "2d", "7c", "9h"),
            metadata={"category": "made_hand", "street": "river"},
        ),
        HandRankCase(
            case_id="straight_flush_seven",
            cards=("9h", "8h", "7h", "6h", "5h", "Kd", "2c"),
            metadata={"category": "made_hand", "street": "river"},
        ),
        HandRankCase(
            case_id="full_house_seven",
            cards=("Kh", "Kd", "Kc", "7s", "7d", "2h", "3c"),
            metadata={"category": "made_hand", "street": "river"},
        ),
    ]


def summarize_benchmark_results(
    results: list[BenchmarkResult] | tuple[BenchmarkResult, ...],
) -> dict[str, Any]:
    passed = [item for item in results if item.passed]
    elapsed = [int(item.elapsed_ms) for item in results]
    return {
        "cases": len(results),
        "passed": len(passed),
        "failed": len(results) - len(passed),
        "pass_rate": round(len(passed) / len(results), 4) if results else 0.0,
        "avg_elapsed_ms": round(sum(elapsed) / len(elapsed), 2) if elapsed else 0.0,
        "max_elapsed_ms": max(elapsed) if elapsed else 0,
    }


def run_oracle_conformance_suite(
    *,
    allow_download: bool = False,
    cases: list[HandRankCase] | tuple[HandRankCase, ...] | None = None,
) -> dict[str, Any]:
    harness = BenchmarkHarness()
    selected_cases = list(cases or build_default_hand_rank_cases())
    results = harness.run_hand_rank_suite(selected_cases, allow_download=allow_download)
    return {
        "kind": "oracle_conformance",
        "summary": summarize_benchmark_results(results),
        "results": [item.to_dict() for item in results],
        "oracles": harness.oracle_status(),
    }


def measure_solver_probe_latency(
    probes: list[SolverProbe] | tuple[SolverProbe, ...],
    request: SolveRequestV2,
    *,
    iterations: int = 7,
) -> list[dict[str, Any]]:
    measurements: list[dict[str, Any]] = []
    sample_count = max(1, int(iterations))

    for probe in probes:
        elapsed_samples: list[float] = []
        for _ in range(sample_count):
            started = time.perf_counter()
            probe.runner(request)
            elapsed_samples.append((time.perf_counter() - started) * 1000.0)

        ordered = sorted(elapsed_samples)
        p95_index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * 0.95))))
        measurements.append(
            {
                "probe": probe.name,
                "backend": probe.backend,
                "iterations": sample_count,
                "avg_ms": round(statistics.fmean(elapsed_samples), 3),
                "median_ms": round(statistics.median(elapsed_samples), 3),
                "p95_ms": round(ordered[p95_index], 3),
                "max_ms": round(max(elapsed_samples), 3),
                "min_ms": round(min(elapsed_samples), 3),
                "first_run_ms": round(elapsed_samples[0], 3),
                "last_run_ms": round(elapsed_samples[-1], 3),
                "warm_delta_ms": round(elapsed_samples[0] - elapsed_samples[-1], 3),
                "warm_speedup_ratio": round(elapsed_samples[-1] / elapsed_samples[0], 4) if elapsed_samples[0] else 0.0,
            }
        )

    return measurements


def _coerce_decision_snapshot(payload: DecisionSnapshot | dict[str, Any]) -> DecisionSnapshot:
    if isinstance(payload, DecisionSnapshot):
        return payload
    return DecisionSnapshot.from_dict(payload)


def validate_replay_decision_suite(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
    *,
    decision_runner: DecisionRunner | None = None,
) -> dict[str, Any]:
    illegal_actions = 0
    gated_records = 0
    consistent_records = 0
    fallback_records = 0
    cache_hit_records = 0
    samples: list[dict[str, Any]] = []
    decisions: list[DecisionSnapshot] = []
    incident_counts: dict[str, int] = {}
    gate_reason_counts: dict[str, int] = {}

    for record in records:
        decision = (
            _coerce_decision_snapshot(decision_runner(record.spot))
            if decision_runner is not None
            else record.decision
        )
        decisions.append(decision)
        legal_actions = {str(item).lower() for item in record.spot.legal_actions}
        chosen_action = str(decision.action or "").lower()
        gate_allowed = bool(decision.gate_result.allowed) if decision.gate_result else True
        gate_reason = _normalize_reason(
            decision.gate_result.reason if decision.gate_result else None,
            "ready",
        )
        no_action = chosen_action in {"", "no_action", "noaction"}
        metadata = dict(decision.gate_result.metadata) if decision.gate_result and decision.gate_result.metadata else {}
        used_fallback = bool(metadata.get("fallback_used")) or str(decision.source or "").lower() == "fallback"
        cache_hit = bool(metadata.get("cache_hit")) or bool(decision.metadata.get("cache_hit"))

        if used_fallback:
            fallback_records += 1
        if cache_hit:
            cache_hit_records += 1
        gate_reason_counts[gate_reason] = gate_reason_counts.get(gate_reason, 0) + 1
        for incident in tuple(decision.warnings or ()) + (
            tuple(decision.gate_result.warnings) if decision.gate_result else ()
        ):
            incident_key = _normalize_reason(incident, "unknown")
            incident_counts[incident_key] = incident_counts.get(incident_key, 0) + 1

        if gate_allowed:
            if legal_actions and chosen_action and chosen_action not in legal_actions:
                illegal_actions += 1
            else:
                consistent_records += 1
        else:
            gated_records += 1
            if not no_action:
                illegal_actions += 1
            else:
                consistent_records += 1

        if len(samples) < 16:
            samples.append(
                {
                    "replay_id": record.replay_id,
                    "spot_id": record.spot.spot_id,
                    "chosen_action": decision.action,
                    "legal_actions": list(record.spot.legal_actions),
                    "gate_allowed": gate_allowed,
                    "gate_reason": gate_reason,
                    "fallback_used": used_fallback,
                    "cache_hit": cache_hit,
                    "decision_confidence": float(decision.confidence or 0.0),
                    "incidents": list(tuple(decision.warnings or ())),
                }
            )

    total = len(records)
    gate_summary = summarize_gate_decisions(decisions)
    return {
        "kind": "replay_validation",
        "records": total,
        "illegal_actions": illegal_actions,
        "gated_records": gated_records,
        "fallback_records": fallback_records,
        "cache_hit_records": cache_hit_records,
        "consistent_records": consistent_records,
        "zero_illegal_actions": illegal_actions == 0,
        "consistency_rate": _safe_ratio(consistent_records, total),
        "illegal_action_rate": _safe_ratio(illegal_actions, total),
        "gated_rate": _safe_ratio(gated_records, total),
        "fallback_rate": _safe_ratio(fallback_records, total),
        "cache_hit_rate": _safe_ratio(cache_hit_records, total),
        "gate_decisions": gate_summary,
        "gate_reason_counts": gate_reason_counts,
        "incident_counts": incident_counts,
        "samples": samples,
    }


def build_validation_lab_payload(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
    *,
    probes: list[SolverProbe] | tuple[SolverProbe, ...] | None = None,
    request: SolveRequestV2 | None = None,
    allow_download: bool = False,
) -> dict[str, Any]:
    payload = {
        "oracle_conformance": run_oracle_conformance_suite(allow_download=allow_download),
        "replay_validation": validate_replay_decision_suite(records),
    }
    if probes and request is not None:
        payload["latency"] = measure_solver_probe_latency(probes, request)
    return payload
