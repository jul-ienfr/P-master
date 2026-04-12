"""Run the remaining validation checks for the V2 refonte."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import replace
import json
from pathlib import Path
from random import Random
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poker.decisionmaker.oracle_backends import detect_oracle_backends, rank_showdown_hand
from poker.decisionmaker.tree_presets import list_tree_presets
from poker.decisionmaker.v2_contracts import (  # noqa: E402
    ActionEstimate,
    DecisionGateResult,
    DecisionSnapshot,
    ReplayRecord,
    build_mock_replay_record,
)
from research.validation import validate_replay_decision_suite  # noqa: E402


def _build_gate_metadata(
    *,
    source: str,
    fallback_used: bool = False,
    cache_hit: bool = False,
    incident_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": source,
        "fallback_used": fallback_used,
        "cache_hit": cache_hit,
    }
    if incident_id:
        metadata["incident_id"] = incident_id
    return metadata


DECK = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")
JS_ORACLE_COMPARE = ROOT / "research" / "oracle_randomized_compare.js"


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return value.to_dict()
    try:
        return asdict(value)
    except Exception:
        return str(value)


def run_oracle_randomized_suite(*, count: int = 500, seed: int = 20260411) -> dict[str, Any]:
    rng = Random(seed)
    failures: list[dict[str, Any]] = []
    phevaluator_ok = 0
    js_summary = json.loads(
        subprocess.run(
            ["node", str(JS_ORACLE_COMPARE), str(count), str(seed)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )

    for index in range(count):
        cards = rng.sample(DECK, 7)
        try:
            phe = rank_showdown_hand(cards, backend="phevaluator")
        except Exception as exc:
            failures.append({"case": index, "cards": cards, "error": str(exc)})
            continue

        phevaluator_ok += 1 if phe.get("rank") is not None else 0

    successful = count - len(failures)
    return {
        "kind": "oracle_randomized",
        "cases": count,
        "successful": successful,
        "failures": len(failures),
        "poker_evaluator_vs_pokersolver_agreements": int(js_summary["agreements"]),
        "poker_evaluator_vs_pokersolver_agreement_rate": float(js_summary["agreement_rate"]),
        "phevaluator_success_rate": round(phevaluator_ok / successful, 4)
        if successful
        else 0.0,
        "mismatches": js_summary["mismatch_samples"],
        "failure_samples": failures[:16],
        "oracles": [oracle.__dict__ for oracle in detect_oracle_backends()],
    }


def build_representative_replay_suite() -> list[ReplayRecord]:
    records = [build_mock_replay_record()]
    for index, preset in enumerate(list_tree_presets(), start=1):
        spot = preset.build_spot_snapshot()
        primary = spot.legal_actions[0] if spot.legal_actions else "check"
        alternatives = tuple(
            ActionEstimate(
                name=action,
                size=0.0,
                frequency=round(1.0 / max(1, len(spot.legal_actions)), 3),
                ev=round(0.1 + (offset * 0.03), 3),
            )
            for offset, action in enumerate(spot.legal_actions or ("check",))
        )
        decision = DecisionSnapshot(
            action=primary,
            alternatives=alternatives,
            ev_by_action={item.name: item.ev for item in alternatives},
            exploitability=0.08,
            source="representative_replay",
            warnings=(),
            latency_ms=12,
            confidence=0.9,
            gate_result=DecisionGateResult(
                allowed=True,
                confidence=0.95,
                reason="ready",
                warnings=(),
                metadata=_build_gate_metadata(
                    source="representative_replay",
                    cache_hit=index % 2 == 0,
                ),
            ),
            metadata={
                "preset_id": preset.preset_id,
                "cache_hit": index % 2 == 0,
                "decision_path": "primary",
            },
        )
        records.append(
            ReplayRecord(
                replay_id=f"representative-{index:03d}",
                spot=spot,
                decision=decision,
                result_metadata={"result_bb": 0.5 + (index * 0.1)},
                tags=("representative", preset.preset_id),
            )
        )

    blocked_spot = replace(
        list_tree_presets()[0].build_spot_snapshot(),
        spot_id="representative-blocked",
        legal_actions=("check", "bet_33"),
    )
    blocked_decision = DecisionSnapshot(
        action="NoAction",
        alternatives=(),
        ev_by_action={},
        exploitability=0.0,
        source="representative_replay",
        warnings=("ocr_low_confidence",),
        latency_ms=0,
        confidence=0.2,
        gate_result=DecisionGateResult(
            allowed=False,
            confidence=0.2,
            reason="ocr_low_confidence",
            warnings=("ocr_low_confidence",),
            metadata=_build_gate_metadata(
                source="representative_replay",
                fallback_used=True,
                cache_hit=False,
                incident_id="ocr_low_confidence",
            ),
        ),
        metadata={
            "preset_id": "blocked",
            "cache_hit": False,
            "decision_path": "gate_blocked",
            "incident_id": "ocr_low_confidence",
        },
    )
    records.append(
        ReplayRecord(
            replay_id="representative-blocked",
            spot=blocked_spot,
            decision=blocked_decision,
            result_metadata={"result_bb": 0.0},
            tags=("representative", "blocked"),
        )
    )
    return records


def main() -> None:
    output_dir = ROOT / "research" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    oracle_summary = run_oracle_randomized_suite()
    replay_summary = validate_replay_decision_suite(build_representative_replay_suite())
    payload = {
        "oracle_randomized": oracle_summary,
        "replay_validation": replay_summary,
        "decision_observability": {
            "gate_decisions": replay_summary.get("gate_decisions", {}),
            "incident_counts": replay_summary.get("incident_counts", {}),
            "gate_reason_counts": replay_summary.get("gate_reason_counts", {}),
            "suite_ready": bool(replay_summary.get("zero_illegal_actions")),
        },
    }
    output_path = output_dir / "validation_suite.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
