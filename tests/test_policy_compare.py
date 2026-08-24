"""Tests unitaires du module policy_compare extrait (Phase 2.7/4.1)."""
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.policy_compare import (
    build_empty_policy_compare_summary,
    build_policy_compare_summary,
    build_runtime_ab_summary,
    compact_policy_compare_examples,
    dedupe_runtime_ab_decisions,
    extract_policy_compare_actions,
    extract_policy_compare_ev_by_action,
    extract_runtime_ab_decision,
    normalize_runtime_action_name,
    normalize_runtime_street_name,
    policy_compare_sample_id,
    policy_slug,
    runtime_ab_decision_key,
    safe_runtime_float,
)


def test_normalizers_handle_garbage():
    assert normalize_runtime_street_name(None) == "UNKNOWN"
    assert normalize_runtime_street_name(" flop ") == "FLOP"
    assert normalize_runtime_action_name(None) == ""
    assert normalize_runtime_action_name("bet_75") == "BET_75"
    assert policy_slug(None) == "runtime"
    assert policy_slug("Validated RL") == "validated_rl"
    assert policy_slug("", "fallback") == "fallback"


def test_safe_runtime_float_rejects_non_numeric():
    assert safe_runtime_float(1.5) == 1.5
    assert safe_runtime_float("2.25") == 2.25
    assert safe_runtime_float(True) is None
    assert safe_runtime_float(None) is None
    assert safe_runtime_float("abc") is None


def test_extract_ab_decision_from_metadata():
    entry = {"metadata": {"rl_ab": {"compared": True}}}
    assert extract_runtime_ab_decision(entry) == {"compared": True}
    assert extract_runtime_ab_decision({"ab_decision": {"applied": True}}) == {"applied": True}
    assert extract_runtime_ab_decision({}) is None
    assert extract_runtime_ab_decision("not-a-dict") is None


def test_ab_decision_key_prefers_spot_and_timestamp():
    entry = {"spot_id": "S1", "timestamp": "T1", "street": "FLOP"}
    assert runtime_ab_decision_key(entry) == ("spot_id_timestamp", "S1", "T1")
    fallback_entry = {"timestamp": "T1", "street": "flop", "chosen_action": "check", "source": "solver"}
    assert runtime_ab_decision_key(fallback_entry) == (
        "timestamp_street_action", "T1", "FLOP", "CHECK", "solver",
    )
    assert runtime_ab_decision_key({}) is None
    assert runtime_ab_decision_key("x") is None


def test_dedupe_keeps_first_and_passes_through_unkeyable():
    decisions = [
        {"spot_id": "S", "timestamp": "T", "kind": "first"},
        {"spot_id": "S", "timestamp": "T", "kind": "duplicate"},
        {"kind": "no-key"},
        {"kind": "no-key-2"},
    ]
    deduped = dedupe_runtime_ab_decisions(decisions)
    assert len(deduped) == 3
    assert deduped[0]["kind"] == "first"
    assert deduped[-1]["kind"] == "no-key-2"


def test_policy_actions_merges_solver_and_branches():
    entry = {
        "chosen_action": "BET_75",
        "source": "runtime",
        "metadata": {
            "rl_ab": {
                "gto_action": "CHECK",
                "final_action": "BET_75",
                "comparison": {
                    "rl_off": {"action": "check"},
                    "rl_on": {"action": "BET"},
                },
            }
        },
    }
    actions = extract_policy_compare_actions(entry)
    assert actions["runtime"] == "BET_75"
    assert actions["gto_solver"] == "CHECK"
    assert actions["rl_off"] == "CHECK"
    assert actions["rl_on"] == "BET"


def test_policy_actions_falls_back_for_missing_branches():
    entry = {
        "action": "CALL",
        "source": "runtime",
        "metadata": {"rl_ab": {"gto_action": "CALL"}},
    }
    actions = extract_policy_compare_actions(entry)
    # rl_off retombe sur gto/chosen ; rl_on sur final/chosen.
    assert actions["rl_off"] == "CALL"
    assert actions["rl_on"] == "CALL"


def test_ev_by_action_reads_alternatives_and_branches():
    entry = {
        "chosen_action": "BET_75",
        "ev": 0.8,
        "metadata": {
            "solver": {
                "alternatives": [
                    {"action": "CHECK", "ev": 0.1},
                    {"action": "BET_75", "ev": 0.9},
                    "garbage",
                ],
            },
            "rl_ab": {
                "comparison": {
                    "rl_off": {"action": "CHECK", "ev": 0.12},
                    "rl_on": {"action": "BET", "ev": "bad"},
                },
            },
        },
    }
    ev = extract_policy_compare_ev_by_action(entry)
    # Premier vu gagne : les alternatives solver priment sur l'EV racine.
    assert ev == {"CHECK": 0.1, "BET_75": 0.9}


def test_sample_id_priority():
    assert policy_compare_sample_id({"spot_id": "S", "timestamp": "T"}, "fb") == "S@T"
    assert policy_compare_sample_id({"timestamp": "T"}, "fb") == "T"
    assert policy_compare_sample_id({}, "fb") == "fb"
    assert policy_compare_sample_id("junk", "fb") == "fb"


def test_compact_examples_ranks_by_abs_delta_then_id():
    examples = [
        {"sample_id": "b", "ev_delta": -3.0},
        {"sample_id": "a", "ev_delta": 5.0},
        {"sample_id": "c", "ev_delta": 0.0},
    ]
    top = compact_policy_compare_examples(examples, limit=2)
    assert [item["sample_id"] for item in top] == ["a", "b"]


def test_build_policy_compare_summary_counts_agreement_and_divergence():
    decisions = [
        {
            "spot_id": "S1",
            "timestamp": "T1",
            "street": "flop",
            "chosen_action": "CHECK",
            "source": "runtime",
            "pot": 10.0,
            "hero_cards": ["Ah", "Kd"],
            "board": ["2c", "7d", "Jh"],
            "metadata": {
                "rl_ab": {
                    "gto_action": "CHECK",
                    "comparison": {
                        "rl_off": {"action": "CHECK", "ev": 0.1},
                        "rl_on": {"action": "BET", "ev": 0.6},
                    },
                }
            },
        },
        "garbage",
    ]
    summary = build_policy_compare_summary(decisions)
    assert summary["sample_count"] == 1
    assert summary["comparable_count"] == 1
    assert summary["agreement_count"] + summary["changed_action_count"] == 1
    assert set(summary["policies"]) >= {"runtime", "gto_solver", "rl_off", "rl_on"}
    assert summary["highlights"]["top_spots"][0]["spot_id"] == "S1"


def test_build_policy_compare_summary_empty_and_invalid():
    empty = build_empty_policy_compare_summary()
    assert build_policy_compare_summary([]) == empty
    assert build_policy_compare_summary(None)["sample_count"] == 0


def test_build_runtime_ab_summary_tallies_and_averages():
    decisions = [
        {
            "street": "turn",
            "ab_decision": {
                "compared": True,
                "eligible": True,
                "applied": False,
                "rl_differs_from_gto": True,
                "comparison": {"action_changed": True, "ev_delta": 0.2, "freq_delta": 0.5},
            },
        },
        {
            "street": "TURN",
            "metadata": {
                "rl_ab": {
                    "compared": True,
                    "comparison": {"ev_delta": 0.4, "freq_delta": 0.7},
                }
            },
        },
        {},
    ]
    summary = build_runtime_ab_summary(decisions)
    assert summary["sample_count"] == 2
    assert summary["compared_count"] == 2
    assert summary["eligible_count"] == 1
    assert summary["diff_count"] == 1
    assert summary["action_change_count"] == 1
    assert summary["avg_delta_ev"] == pytest.approx(0.3)
    assert summary["avg_delta_freq"] == pytest.approx(0.6)
    assert summary["impacted_streets"] == ["TURN"]
