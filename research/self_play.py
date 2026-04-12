"""Offline replay-based head-to-head and simplified best-response tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from poker.decisionmaker.v2_contracts import ReplayRecord


class Policy(Protocol):
    def choose_action(self, record: ReplayRecord) -> str: ...


@dataclass
class StaticActionPolicy:
    name: str
    default_action: str

    def choose_action(self, record: ReplayRecord) -> str:
        return self.default_action or record.decision.action


@dataclass
class ReplayDecisionPolicy:
    name: str

    def choose_action(self, record: ReplayRecord) -> str:
        return record.decision.action


@dataclass
class BestAlternativePolicy:
    name: str = "best_alternative"

    def choose_action(self, record: ReplayRecord) -> str:
        if record.decision.alternatives:
            ranked = sorted(
                record.decision.alternatives,
                key=lambda item: (item.ev, item.frequency),
                reverse=True,
            )
            return ranked[0].name
        return record.decision.action


@dataclass
class BoundedExploitPolicy:
    name: str = "bounded_exploit"
    max_ev_delta: float = 0.12

    def choose_action(self, record: ReplayRecord) -> str:
        if not record.decision.alternatives:
            return record.decision.action

        ranked = sorted(
            record.decision.alternatives,
            key=lambda item: (item.ev, item.frequency),
            reverse=True,
        )
        baseline = next((item for item in ranked if item.name == record.decision.action), None)
        baseline_ev = float(baseline.ev) if baseline is not None else float(ranked[0].ev)

        metadata = dict(getattr(record.decision, "metadata", {}) or {})
        exploit_metadata = dict(metadata.get("exploit") or {})
        profile_metadata = dict(metadata.get("profile") or {})
        pressure_bias = float(exploit_metadata.get("pressure_bias", profile_metadata.get("pressure_bias", 0.0)) or 0.0)
        call_bias = float(exploit_metadata.get("call_bias", profile_metadata.get("call_bias", 0.0)) or 0.0)
        fold_bias = float(exploit_metadata.get("fold_bias", profile_metadata.get("fold_bias", 0.0)) or 0.0)

        if pressure_bias >= max(call_bias, fold_bias) and pressure_bias >= 0.1:
            preferred_tokens = ("bet", "raise")
        elif max(call_bias, fold_bias) >= 0.1:
            preferred_tokens = ("check", "call")
        else:
            history = [str(action).strip().lower() for action in (record.spot.action_history or ())]
            passive_bias = sum(1 for action in history if any(token in action for token in ("call", "check")))
            aggressive_bias = sum(1 for action in history if any(token in action for token in ("bet", "raise", "jam")))

            preferred_tokens = ("bet", "raise") if passive_bias >= aggressive_bias else ("check", "call")
        for candidate in ranked:
            ev_delta = baseline_ev - float(candidate.ev)
            if ev_delta > self.max_ev_delta:
                continue
            candidate_name = str(candidate.name).lower()
            if any(token in candidate_name for token in preferred_tokens):
                return candidate.name
        return record.decision.action


def run_head_to_head(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
    *,
    baseline: Policy,
    challenger: Policy,
) -> dict[str, object]:
    baseline_score = 0.0
    challenger_score = 0.0
    decisive_records = 0
    challenger_win_records = 0
    baseline_win_records = 0
    tie_records = 0

    for record in records:
        alternatives = {item.name: float(item.ev) for item in record.decision.alternatives}
        if not alternatives:
            continue
        decisive_records += 1
        baseline_action = baseline.choose_action(record)
        challenger_action = challenger.choose_action(record)
        baseline_ev = alternatives.get(baseline_action, 0.0)
        challenger_ev = alternatives.get(challenger_action, 0.0)
        baseline_score += baseline_ev
        challenger_score += challenger_ev
        if challenger_ev > baseline_ev:
            challenger_win_records += 1
        elif challenger_ev < baseline_ev:
            baseline_win_records += 1
        else:
            tie_records += 1

    ev_delta = challenger_score - baseline_score

    return {
        "baseline_policy": getattr(baseline, "name", "baseline"),
        "challenger_policy": getattr(challenger, "name", "challenger"),
        "records": len(records),
        "decisive_records": decisive_records,
        "baseline_ev_sum": round(baseline_score, 4),
        "challenger_ev_sum": round(challenger_score, 4),
        "ev_delta": round(ev_delta, 4),
        "avg_ev_delta": round(ev_delta / decisive_records, 4) if decisive_records else 0.0,
        "challenger_win_records": challenger_win_records,
        "baseline_win_records": baseline_win_records,
        "tie_records": tie_records,
        "challenger_beats_baseline": challenger_score > baseline_score,
    }


def estimate_local_best_response(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
    *,
    policy: Policy,
) -> dict[str, object]:
    best_response_gap = 0.0
    evaluated_records = 0

    for record in records:
        if not record.decision.alternatives:
            continue
        alternatives = {item.name: float(item.ev) for item in record.decision.alternatives}
        chosen_action = policy.choose_action(record)
        best_ev = max(alternatives.values())
        chosen_ev = alternatives.get(chosen_action, 0.0)
        best_response_gap += max(0.0, best_ev - chosen_ev)
        evaluated_records += 1

    return {
        "policy": getattr(policy, "name", "policy"),
        "records": len(records),
        "evaluated_records": evaluated_records,
        "lbr_gap": round(best_response_gap, 4),
        "average_gap": round(best_response_gap / evaluated_records, 4) if evaluated_records else 0.0,
    }
