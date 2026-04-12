"""Extended offline RL/replay lab helpers."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from poker.decisionmaker.tree_presets import list_tree_presets
from poker.decisionmaker.v2_contracts import (
    ActionEstimate,
    DecisionGateResult,
    DecisionSnapshot,
    ReplayRecord,
    build_mock_replay_record,
)
from research.challengers import challenger_payload
from research.self_play import (
    BestAlternativePolicy,
    BoundedExploitPolicy,
    ReplayDecisionPolicy,
    StaticActionPolicy,
    estimate_local_best_response,
    run_head_to_head,
)


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "research" / "results"


def build_rl_replay_suite() -> list[ReplayRecord]:
    records = [build_mock_replay_record()]
    for index, preset in enumerate(list_tree_presets(), start=1):
        spot = preset.build_spot_snapshot()
        alternatives = tuple(
            ActionEstimate(
                name=action,
                size=0.0,
                frequency=round(1.0 / max(1, len(spot.legal_actions)), 3),
                ev=round(0.18 - (offset * 0.02), 3),
                metadata={"preset_id": preset.preset_id},
            )
            for offset, action in enumerate(spot.legal_actions or ("check",))
        )
        if alternatives:
            baseline_action = alternatives[min(1, len(alternatives) - 1)].name
        else:
            baseline_action = "check"
        decision = DecisionSnapshot(
            action=baseline_action,
            alternatives=alternatives,
            ev_by_action={item.name: item.ev for item in alternatives},
            exploitability=0.06,
            source="rl_lab",
            warnings=(),
            latency_ms=10 + index,
            confidence=0.9,
            gate_result=DecisionGateResult(
                allowed=True,
                confidence=0.95,
                reason="ready",
                warnings=(),
                metadata={"source": "rl_lab"},
            ),
            metadata={"preset_id": preset.preset_id},
        )
        records.append(
            ReplayRecord(
                replay_id=f"rl-lab-{index:03d}",
                spot=spot,
                decision=decision,
                result_metadata={"result_bb": round(0.25 + (index * 0.12), 3)},
                tags=("rl_lab", preset.preset_id),
            )
        )

    blocked = records[0]
    records.append(
        replace(
            blocked,
            replay_id="rl-lab-blocked",
            decision=DecisionSnapshot(
                action="NoAction",
                alternatives=(),
                ev_by_action={},
                exploitability=0.0,
                source="rl_lab",
                warnings=("ocr_low_confidence",),
                latency_ms=0,
                confidence=0.15,
                gate_result=DecisionGateResult(
                    allowed=False,
                    confidence=0.15,
                    reason="ocr_low_confidence",
                    warnings=("ocr_low_confidence",),
                    metadata={"source": "rl_lab"},
                ),
                metadata={"variant": "blocked"},
            ),
        )
    )
    return records


def build_policy_lineup() -> list[object]:
    return [
        ReplayDecisionPolicy(name="baseline_trace"),
        BoundedExploitPolicy(name="bounded_exploit", max_ev_delta=0.12),
        BestAlternativePolicy(name="best_alt"),
        StaticActionPolicy(name="always_check", default_action="check"),
        StaticActionPolicy(name="always_bet_50", default_action="bet_50"),
        StaticActionPolicy(name="always_jam", default_action="jam"),
    ]


def run_policy_round_robin(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
    *,
    lineup: list[object] | None = None,
) -> dict[str, Any]:
    policies = lineup or build_policy_lineup()
    standings: dict[str, dict[str, Any]] = {
        getattr(policy, "name", f"policy_{index}"): {
            "policy": getattr(policy, "name", f"policy_{index}"),
            "matches": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points": 0,
            "ev_sum": 0.0,
        }
        for index, policy in enumerate(policies)
    }
    matchups: list[dict[str, Any]] = []

    for index, baseline in enumerate(policies):
        for challenger in policies[index + 1 :]:
            result = run_head_to_head(records, baseline=baseline, challenger=challenger)
            baseline_name = str(result["baseline_policy"])
            challenger_name = str(result["challenger_policy"])
            baseline_ev = float(result["baseline_ev_sum"])
            challenger_ev = float(result["challenger_ev_sum"])

            standings[baseline_name]["matches"] += 1
            standings[challenger_name]["matches"] += 1
            standings[baseline_name]["ev_sum"] += baseline_ev
            standings[challenger_name]["ev_sum"] += challenger_ev

            if challenger_ev > baseline_ev:
                standings[challenger_name]["wins"] += 1
                standings[challenger_name]["points"] += 3
                standings[baseline_name]["losses"] += 1
                winner = challenger_name
            elif baseline_ev > challenger_ev:
                standings[baseline_name]["wins"] += 1
                standings[baseline_name]["points"] += 3
                standings[challenger_name]["losses"] += 1
                winner = baseline_name
            else:
                standings[baseline_name]["draws"] += 1
                standings[challenger_name]["draws"] += 1
                standings[baseline_name]["points"] += 1
                standings[challenger_name]["points"] += 1
                winner = "draw"

            matchups.append(
                {
                    **result,
                    "winner": winner,
                }
            )

    ordered = sorted(
        standings.values(),
        key=lambda item: (item["points"], item["ev_sum"], item["wins"]),
        reverse=True,
    )
    champion = ordered[0]["policy"] if ordered else ""
    return {
        "kind": "round_robin",
        "records": len(records),
        "lineup": [getattr(policy, "name", "policy") for policy in policies],
        "matchups": matchups,
        "standings": ordered,
        "champion": champion,
    }


def run_challenger_smoke_suite(records: list[ReplayRecord]) -> list[dict[str, Any]]:
    sample_spot = records[0].spot if records else build_mock_replay_record().spot
    entries = challenger_payload(sample_spot)
    smoke_rows: list[dict[str, Any]] = []

    for entry in entries:
        loaded = bool(entry.get("loaded"))
        capabilities = list(entry.get("capabilities", []))
        sample_payload = dict(entry.get("sample_payload", {}))
        smoke_rows.append(
            {
                "challenger_id": entry["id"],
                "kind": entry["kind"],
                "available": bool(entry.get("available")),
                "loaded": loaded,
                "status": "ready" if loaded else "unavailable",
                "factory_hint": entry.get("factory_hint", ""),
                "capabilities": capabilities,
                "entry_points": list(entry.get("entry_points", [])),
                "sample_payload_keys": sorted(sample_payload.keys()),
                "reason": entry.get("reason", ""),
            }
        )

    return smoke_rows


def build_rl_lab_payload(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...] | None = None,
) -> dict[str, Any]:
    selected_records = list(records or build_rl_replay_suite())
    tournament = run_policy_round_robin(selected_records)
    smoke = run_challenger_smoke_suite(selected_records)
    best_response = estimate_local_best_response(
        selected_records,
        policy=ReplayDecisionPolicy(name="baseline_trace"),
    )
    ready_challengers = [entry["challenger_id"] for entry in smoke if entry["status"] == "ready"]

    return {
        "kind": "rl_lab",
        "records": len(selected_records),
        "policy_lineup": tournament["lineup"],
        "tournament": tournament,
        "challenger_smoke": smoke,
        "best_response": best_response,
        "ready_challengers": ready_challengers,
        "champion": tournament["champion"],
    }


def write_rl_lab_summary(
    output_path: str | Path | None = None,
    *,
    records: list[ReplayRecord] | tuple[ReplayRecord, ...] | None = None,
) -> Path:
    payload = build_rl_lab_payload(records)
    path = Path(output_path) if output_path is not None else RESULTS_DIR / "rl_lab_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
