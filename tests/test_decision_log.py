from __future__ import annotations

import json
from pathlib import Path

from src.runtime.decision_log import (
    SCHEMA_VERSION,
    build_decision_record,
    coerce_decision_record,
    load_decision_records,
    record_from_runtime_trace,
    spot_hash,
    summarize_decision_records,
    validate_decision_record,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _record(name: str = "decision_replay_validated_rl.json") -> dict:
    fixture = _fixture(name)
    return build_decision_record(
        fixture["request"],
        fixture["expected"],
        gate={"allowed": True, "reason": "ready", "source": "jev", "mode": "observer"},
        solver={"backend": "fixture_solver", "mode": "native", "budget_ms": 1000},
        timestamp="2026-11-14T22:00:00+00:00",
    )


def test_build_record_is_valid_and_deterministic():
    first = _record()
    second = _record()
    assert first == second
    assert first["schema_version"] == SCHEMA_VERSION
    assert validate_decision_record(first) == []
    assert first["gate"]["reason"] == "ready"
    assert first["solver"]["budget_ms"] == 1000


def test_spot_hash_depends_on_spot_not_on_decision():
    fixture = _fixture("decision_replay_validated_rl.json")
    request = fixture["request"]
    base = spot_hash(request)
    changed_decision = dict(fixture["expected"], action="CALL")
    assert spot_hash(request) == base
    assert build_decision_record(request, changed_decision)["spot_hash"] == base
    changed_request = dict(request, pot=request["pot"] + 1.0)
    assert spot_hash(changed_request) != base


def test_spot_hash_includes_multiway_identity():
    request = _fixture("decision_replay_validated_rl.json")["request"]
    base = spot_hash(request)
    multiway = dict(
        request,
        num_players=3,
        active_positions=["SB", "BTN", "BB"],
        hero_player_index=1,
        villain_ranges=["range:utg", "range:bb"],
    )
    assert spot_hash(multiway) != base
    assert spot_hash(multiway) != spot_hash(
        dict(multiway, villain_ranges=["range:utg", "range:other"])
    )


def test_runtime_trace_preserves_multiway_identity():
    trace = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": "2026-11-17T12:00:00+00:00",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 12.5,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "chosen_action": "BET",
        "source": "GTO_RUST",
        "backend": "multiway_mccfr",
        "latency_ms": 50.0,
        "num_players": 4,
        "active_positions": ["SB", "CO", "BTN", "BB"],
        "hero_player_index": 0,
        "villain_ranges": ["range:utg", "range:co", "range:bb"],
        "multiway_mode": "multiway",
        "converged": False,
        "sampled": True,
        "metadata": {
            "effective_stack": 100.0,
            "hero_position": "btn",
            "solver": {"backend": "multiway_mccfr", "sampled": True},
            "multiway": {
                "num_players": 4,
                "active_positions": ["SB", "CO", "BTN", "BB"],
                "hero_player_index": 2,
                "villain_ranges": ["range:utg", "range:co", "range:bb"],
                "mode": "multiway",
                "converged": False,
                "warnings": ["multiway_approximation"],
            },
        },
    }
    record = record_from_runtime_trace(trace)
    assert validate_decision_record(record) == []
    assert record["request"]["num_players"] == 4
    assert record["request"]["multiway_mode"] == "multiway"
    assert record["request"]["active_positions"] == ["SB", "CO", "BTN", "BB"]
    assert record["request"]["hero_player_index"] == 0
    assert record["decision"]["converged"] is False
    assert record["solver"]["sampled"] is True
    assert record["decision"]["multiway"]["warnings"] == ["multiway_approximation"]


def test_validate_rejects_missing_and_bad_values():
    record = _record()
    record["decision"].pop("action")
    record["request"]["pot"] = -1
    record["decision"]["elapsed_ms"] = "fast"
    record["decision"]["fallback_used"] = "yes"
    errors = validate_decision_record(record)
    assert any("decision.action" in error for error in errors)
    assert any("request.pot" in error for error in errors)
    assert any("decision.elapsed_ms" in error for error in errors)
    assert any("decision.fallback_used" in error for error in errors)


def test_summary_reports_latency_and_fallback():
    first = _record("decision_replay_validated_rl.json")
    second = _record("decision_replay_fallback_low_confidence.json")
    second["decision"]["elapsed_ms"] = 200
    summary = summarize_decision_records([first, second])
    assert summary["count"] == 2
    assert summary["valid"] == 2
    assert summary["invalid"] == 0
    assert summary["fallback_count"] == 1
    assert summary["fallback_rate"] == 0.5
    assert summary["latency_ms"]["max"] >= summary["latency_ms"]["p50"]
    assert summary["actions"]["BET"] == 1
    assert summary["actions"]["FOLD"] == 1


def test_load_jsonl_roundtrip(tmp_path):
    record = _record()
    path = tmp_path / "decisions.jsonl"
    path.write_text(json.dumps(record) + "\n\n" + json.dumps(record) + "\n", encoding="utf-8")
    loaded = load_decision_records(path)
    assert len(loaded) == 2
    assert loaded[0] == record


def test_runtime_trace_is_coerced_to_canonical_record():
    trace = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": "2026-11-14T22:10:00+00:00",
        "session_id": "runtime-test",
        "spot_id": "spot-1",
        "spot_hash": "a" * 64,
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 12.5,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "action_history": ["hero:check"],
        "chosen_action": "BET",
        "source": "GTO_RUST",
        "backend": "native",
        "confidence": 0.84,
        "latency_ms": 123.0,
        "ev": 1.2,
        "warnings": [],
        "incidents": [],
        "cache_hit": False,
        "metadata": {"effective_stack": 100.0, "hero_position": "ip", "fallback_used": False},
        "gate_result": {"allowed": True, "reason": "ready", "status": "ok"},
    }
    record = record_from_runtime_trace(trace)
    assert validate_decision_record(record) == []
    assert record["spot_hash"] == "a" * 64
    assert record["request"]["hero_hand"] == "AhKd"
    assert record["decision"]["action"] == "BET"
    assert record["decision"]["fallback_used"] is False
    assert record["gate"]["reason"] == "ready"
    assert coerce_decision_record(record) is record
    assert coerce_decision_record(trace)["decision"]["action"] == "BET"
