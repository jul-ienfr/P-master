"""Cross-backend benchmark tooling for solves, hand ranking, and oracle parity."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable

from poker.decisionmaker.oracle_backends import detect_oracle_backends, rank_showdown_hand
from poker.decisionmaker.v2_contracts import BenchmarkResult, SolveRequestV2, SolveResponseV2


SolverCallable = Callable[[SolveRequestV2], SolveResponseV2 | dict[str, Any]]


@dataclass
class SolverProbe:
    name: str
    backend: str
    runner: SolverCallable


@dataclass
class HandRankCase:
    case_id: str
    cards: tuple[str, ...]
    expected_backend: str = "auto"
    metadata: dict[str, Any] = field(default_factory=dict)


class BenchmarkHarness:
    """Execute reproducible parity/performance checks on canonical requests."""

    def __init__(self, probes: list[SolverProbe] | None = None):
        self.probes = probes or []

    def register(self, probe: SolverProbe) -> None:
        self.probes.append(probe)

    def run(self, request: SolveRequestV2) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for probe in self.probes:
            started = time.perf_counter()
            payload = probe.runner(request)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response = payload if isinstance(payload, SolveResponseV2) else SolveResponseV2.from_dict(payload)
            score = 1.0 if response.chosen_action else 0.0
            results.append(
                BenchmarkResult(
                    name=probe.name,
                    backend=probe.backend,
                    metric="solve_response_presence",
                    score=score,
                    elapsed_ms=elapsed_ms,
                    passed=bool(response.chosen_action or response.actions),
                    metadata={
                        "spot_id": request.spot_id,
                        "chosen_action": response.chosen_action,
                        "backend": response.backend,
                        "cache_tier": getattr(response.cache_tier, "value", response.cache_tier),
                        "cache_hit": bool(response.cache_hit or response.metadata.get("cache_hit")),
                        "fallback_used": bool(response.fallback_reason or response.metadata.get("fallback_used")),
                        "source": response.metadata.get("source") or response.backend,
                        "latency_ms": elapsed_ms,
                        "hero_ev": response.hero_ev,
                        "exploitability": response.exploitability,
                        "decision_confidence": response.decision_confidence,
                        "action_count": len(response.actions or ()),
                        "warnings": list(response.warnings or ()),
                        "fallback_reason": response.fallback_reason,
                        "normalized_ranges": list(response.normalized_ranges or ()),
                    },
                )
            )
        return results

    def run_suite(self, requests: list[SolveRequestV2]) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for request in requests:
            results.extend(self.run(request))
        return results

    def oracle_status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "available": item.available,
                "reason": item.reason,
                "metadata": item.metadata,
            }
            for item in detect_oracle_backends()
        ]

    def run_hand_rank_suite(
        self,
        cases: list[HandRankCase] | tuple[HandRankCase, ...],
        *,
        allow_download: bool = False,
    ) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for case in cases:
            started = time.perf_counter()
            try:
                ranked = rank_showdown_hand(
                    list(case.cards),
                    backend=case.expected_backend,
                    allow_download=allow_download,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                results.append(
                    BenchmarkResult(
                        name=case.case_id,
                        backend=str(ranked.get("backend", case.expected_backend)),
                        metric="hand_rank_available",
                        score=1.0,
                        elapsed_ms=elapsed_ms,
                        passed=True,
                        metadata={
                            "cards": list(case.cards),
                            "ranked": ranked,
                            **case.metadata,
                        },
                    )
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                results.append(
                    BenchmarkResult(
                        name=case.case_id,
                        backend=case.expected_backend,
                        metric="hand_rank_available",
                        score=0.0,
                        elapsed_ms=elapsed_ms,
                        passed=False,
                        metadata={
                            "cards": list(case.cards),
                            "error": str(exc),
                            **case.metadata,
                        },
                    )
                )
        return results
