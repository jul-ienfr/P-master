"""Extended offline RL/replay lab helpers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from poker.decisionmaker.tree_presets import list_tree_presets
from src.contracts.v2_contracts import (
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


def estimate_solver_best_response(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
    *,
    max_iterations: int = 20,
    bet_sizes: str | None = "50%",
) -> dict[str, Any]:
    """Évalue le corpus du lab avec le solveur natif au lieu des EV inventées.

    Chaque snapshot est converti en spot solveur, ses ranges sont rendues
    disjointes par ``measure_spot_best_response``, puis l'action de politique
    est rapprochée de l'action solveur la plus proche (``bet_50`` → ``bet_9``).
    Un arbre réduit (``bet_sizes``) est utilisé pour tenir un budget court.
    """
    from research.best_response import (
        bet_sizes_from_legal_actions,
        measure_corpus_best_response,
        measure_spot_best_response,
        spots_from_replay_records,
    )

    spots: list[dict[str, Any]] = []
    for spot in spots_from_replay_records(records):
        action = str(spot.get("policy_action") or "")
        if not spot.get("board") or action in {"", "NoAction"}:
            continue
        is_bet = action.lower().startswith("bet_")
        spots.append(
            dict(
                spot,
                bet_sizes=(bet_sizes_from_legal_actions([action]) or bet_sizes)
                if is_bet
                else bet_sizes,
                map_single_bet=is_bet,
            )
        )

    corpus = measure_corpus_best_response(
        spots,
        gap_fn=lambda spot: measure_spot_best_response(spot, max_iterations=max_iterations),
    )
    evaluated = int(corpus.get("evaluated_spots", 0))
    mean_gap = float(corpus.get("mean_best_response_gap", 0.0))
    return {
        "policy": "baseline_trace",
        "records": len(records),
        "evaluated_records": evaluated,
        "solver_evaluated_records": evaluated,
        "backend": "native_mes" if evaluated else "alternatives_fallback",
        "lbr_gap": round(mean_gap * evaluated, 4),
        "average_gap": round(mean_gap, 4),
        "max_iterations": max_iterations,
        "bet_sizes": bet_sizes,
        "corpus": corpus,
    }


def build_rl_lab_payload(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...] | None = None,
    *,
    solver_eval: bool = False,
    max_iterations: int = 20,
    bet_sizes: str | None = "50%",
) -> dict[str, Any]:
    selected_records = list(records or build_rl_replay_suite())
    tournament = run_policy_round_robin(selected_records)
    smoke = run_challenger_smoke_suite(selected_records)
    if solver_eval:
        best_response = estimate_solver_best_response(
            selected_records,
            max_iterations=max_iterations,
            bet_sizes=bet_sizes,
        )
    else:
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


def write_rl_lab_payload(
    payload: dict[str, Any],
    output_path: str | Path | None = None,
) -> Path:
    """Écrit un payload déjà calculé (évite de résoudre deux fois le corpus)."""
    path = Path(output_path) if output_path is not None else RESULTS_DIR / "rl_lab_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_rl_lab_summary(
    output_path: str | Path | None = None,
    *,
    records: list[ReplayRecord] | tuple[ReplayRecord, ...] | None = None,
    solver_eval: bool = False,
    max_iterations: int = 20,
    bet_sizes: str | None = "50%",
) -> Path:
    payload = build_rl_lab_payload(
        records,
        solver_eval=solver_eval,
        max_iterations=max_iterations,
        bet_sizes=bet_sizes,
    )
    return write_rl_lab_payload(payload, output_path)
