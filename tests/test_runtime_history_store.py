import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.history_store import RuntimeHistoryStore


def test_runtime_history_store_can_export_and_import_records(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    store = RuntimeHistoryStore(file_path=str(history_path))

    store.append("events", {"timestamp": "2026-04-11T10:00:00Z", "message": "boot"})
    store.append("decisions", {"timestamp": "2026-04-11T10:00:01Z", "chosen_action": "CALL"})

    exported = store.export_records()

    assert [record["stream"] for record in exported] == ["events", "decisions"]

    imported_store = RuntimeHistoryStore(file_path=str(tmp_path / "imported_history.jsonl"))
    result = imported_store.import_records(exported)

    assert result["imported_count"] == 2
    assert result["rejected_count"] == 0
    assert imported_store.read_recent("events", limit=5)[0]["message"] == "boot"
    assert imported_store.read_recent("decisions", limit=5)[0]["chosen_action"] == "CALL"


def test_runtime_history_store_can_summarize_exported_records(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    store = RuntimeHistoryStore(file_path=str(history_path))

    store.append("events", {"timestamp": "2026-04-11T10:00:00Z", "message": "boot"})
    store.append("events", {"timestamp": "2026-04-11T10:00:02Z", "message": "tick"})
    store.append("decisions", {"timestamp": "2026-04-11T10:00:03Z", "chosen_action": "CALL"})
    store.append("metrics", {"timestamp": "2026-04-11T10:00:01Z", "decision_count": 2})

    summary = store.summarize_records()

    assert summary == {
        "stream": "all",
        "record_count": 4,
        "counts": {
            "events": 2,
            "decisions": 1,
            "incidents": 0,
            "metrics": 1,
        },
        "latest_at": {
            "events": "2026-04-11T10:00:00Z",
            "decisions": "2026-04-11T10:00:03Z",
            "incidents": None,
            "metrics": "2026-04-11T10:00:01Z",
        },
    }


def test_runtime_history_store_import_can_replace_and_skip_invalid_records(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    store = RuntimeHistoryStore(file_path=str(history_path))
    store.append("events", {"timestamp": "2026-04-11T10:00:00Z", "message": "old"})

    result = store.import_records(
        [
            {"stream": "events", "timestamp": "2026-04-11T10:00:05Z", "message": "new"},
            {"timestamp": "2026-04-11T10:00:06Z", "message": "missing_stream"},
            "bad-record",
        ],
        replace=True,
    )

    assert result == {
        "enabled": True,
        "imported_count": 1,
        "rejected_count": 2,
        "replaced": True,
    }
    exported = store.export_records()
    assert len(exported) == 1
    assert exported[0]["message"] == "new"
    assert json.loads(history_path.read_text(encoding="utf-8").strip())["message"] == "new"


def test_runtime_history_store_export_combines_backup_and_current_file(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    backup_path = history_path.with_suffix(history_path.suffix + ".bak")

    backup_path.write_text(
        "\n".join(
            [
                json.dumps({"stream": "events", "timestamp": "2026-04-11T10:00:00Z", "message": "older"}),
                json.dumps({"stream": "events", "timestamp": "2026-04-11T10:00:01Z", "message": "old"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps({"stream": "events", "timestamp": "2026-04-11T10:00:02Z", "message": "new"}) + "\n",
        encoding="utf-8",
    )

    store = RuntimeHistoryStore(file_path=str(history_path))

    exported = store.export_records("events")

    assert [record["message"] for record in exported] == ["older", "old", "new"]


def test_runtime_history_store_read_recent_uses_backup_when_rotation_moved_old_records(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    backup_path = history_path.with_suffix(history_path.suffix + ".bak")

    backup_path.write_text(
        json.dumps({"stream": "events", "timestamp": "2026-04-11T10:00:01Z", "message": "older"}) + "\n",
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps({"stream": "events", "timestamp": "2026-04-11T10:00:02Z", "message": "newer"}) + "\n",
        encoding="utf-8",
    )

    store = RuntimeHistoryStore(file_path=str(history_path))

    recent = store.read_recent("events", limit=3)

    assert [record["message"] for record in recent] == ["newer", "older"]


def test_runtime_history_store_rotation_keeps_multiple_numbered_backups(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    store = RuntimeHistoryStore(
        file_path=str(history_path),
        max_size_bytes=1,
        backup_count=3,
    )

    for index in range(1, 6):
        store.append("events", {"timestamp": f"2026-04-11T10:00:0{index}Z", "message": f"entry-{index}"})

    assert json.loads(history_path.read_text(encoding="utf-8").strip())["message"] == "entry-5"
    assert json.loads((tmp_path / "runtime_history.jsonl.bak.1").read_text(encoding="utf-8").strip())["message"] == "entry-4"
    assert json.loads((tmp_path / "runtime_history.jsonl.bak.2").read_text(encoding="utf-8").strip())["message"] == "entry-3"
    assert json.loads((tmp_path / "runtime_history.jsonl.bak.3").read_text(encoding="utf-8").strip())["message"] == "entry-2"
    assert not (tmp_path / "runtime_history.jsonl.bak.4").exists()
    assert store.summarize()["backup_count"] == 3


def test_runtime_history_store_can_export_record_batches_per_persisted_segment(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    backup_path = history_path.with_suffix(history_path.suffix + ".bak")

    backup_path.write_text(
        json.dumps({"stream": "decisions", "timestamp": "2026-04-11T10:00:01Z", "spot_id": "old", "chosen_action": "FOLD"}) + "\n",
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps({"stream": "decisions", "timestamp": "2026-04-11T10:00:02Z", "spot_id": "new", "chosen_action": "CALL"}) + "\n",
        encoding="utf-8",
    )

    store = RuntimeHistoryStore(file_path=str(history_path))

    batches = store.export_record_batches("decisions")

    assert [batch["session_id"] for batch in batches] == ["backup_legacy", "current"]
    assert [batch["records"][0]["spot_id"] for batch in batches] == ["old", "new"]


def test_runtime_history_store_append_injects_default_runtime_session_id(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    store = RuntimeHistoryStore(file_path=str(history_path), session_id="runtime-abc123")

    store.append("events", {"timestamp": "2026-04-11T10:00:00Z", "message": "boot"})

    exported = store.export_records("events")

    assert exported[0]["session_id"] == "runtime-abc123"


def test_runtime_history_store_export_record_batches_prefers_explicit_session_ids(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"stream": "decisions", "timestamp": "2026-04-11T10:00:01Z", "spot_id": "spot-a", "chosen_action": "CALL", "session_id": "runtime-a"}),
                json.dumps({"stream": "decisions", "timestamp": "2026-04-11T10:00:02Z", "spot_id": "spot-b", "chosen_action": "BET", "session_id": "runtime-a"}),
                json.dumps({"stream": "decisions", "timestamp": "2026-04-11T10:00:03Z", "spot_id": "spot-c", "chosen_action": "FOLD", "session_id": "runtime-b"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = RuntimeHistoryStore(file_path=str(history_path))

    batches = store.export_record_batches("decisions")

    assert [batch["session_id"] for batch in batches] == ["runtime-a", "runtime-b"]
    assert [[record["spot_id"] for record in batch["records"]] for batch in batches] == [["spot-a", "spot-b"], ["spot-c"]]


def test_runtime_history_store_can_coerce_frontend_review_pack_raw_payload():
    payload = {
        "kind": "review_pack",
        "version": 1,
        "raw": {
            "format": "runtime_history_v1",
            "bundle": {
                "kind": "runtime_replay_bundle",
                "records": [
                    {
                        "stream": "decisions",
                        "timestamp": "2026-04-11T12:00:01Z",
                        "spot_id": "live:PREFLOP:001",
                        "chosen_action": "BET",
                        "source": "validated_rl",
                    }
                ],
            },
        },
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)
    summary = RuntimeHistoryStore.describe_records_payload(payload)

    assert len(records) == 1
    assert records[0]["spot_id"] == "live:PREFLOP:001"
    assert summary["artifact_type"] == "review_pack"
    assert summary["counts"]["decisions"] == 1


def test_runtime_history_store_can_coerce_frontend_review_pack_timeline_partially():
    payload = {
        "kind": "review_pack",
        "version": 1,
        "sessionLabel": "session-ui-a",
        "currentReplay": {
            "timeline": [
                {
                    "id": "spot-001",
                    "timestamp": "2026-04-11T12:00:01Z",
                    "street": "TURN",
                    "action": "BET",
                    "chosenActionRaw": "BET_75",
                    "heroEv": "0.42",
                    "confidence": "0.91",
                    "incidents": ["latency_warning"],
                    "backend": "native_rust",
                    "backendDetails": {"name": "native_rust", "version": "1.2.3"},
                    "cacheHit": True,
                    "cacheDetails": {"hit": True, "tier": "memory"},
                    "evByAction": {"CHECK": -0.1, "BET": 0.42},
                    "freqByAction": {"CHECK": 0.33, "BET": 0.67},
                    "actionMetadata": {
                        "CHECK": {"ev": -0.1, "freq": 0.33},
                        "BET": {"raw_action": "BET_75", "ev": 0.42, "freq": 0.67},
                    },
                    "solverAlternatives": [
                        {"action": "CHECK", "ev": -0.1},
                        {"action": "BET", "rawAction": "BET_75", "freq": 0.67, "ev": 0.42},
                    ],
                    "solverWarnings": ["subtree_reused"],
                    "gtoAction": "CHECK",
                    "finalAction": "BET",
                    "actionShift": "CHECK -> BET",
                    "title": "Turn barrel",
                }
            ]
        },
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)

    assert records == [
        {
            "stream": "decisions",
            "spot_id": "spot-001",
            "source": "review_pack",
            "metadata": {
                "review_pack_title": "Turn barrel",
                "canonical_spot": None,
                "gate_result": None,
                "runtime_metrics": [],
                "decision_trace": [],
                "tags": [],
                "note": None,
                "chosen_action_raw": "BET_75",
                "cache_hit": True,
                "ev_by_action": {"CHECK": -0.1, "BET": 0.42},
                "freq_by_action": {"CHECK": 0.33, "BET": 0.67},
                "action_metadata": {
                    "CHECK": {"ev": -0.1, "freq": 0.33},
                    "BET": {"raw_action": "BET_75", "ev": 0.42, "freq": 0.67},
                },
                "backend_details": {"name": "native_rust", "version": "1.2.3"},
                "cache_details": {"hit": True, "tier": "memory"},
                "warnings": ["subtree_reused"],
                "gto_action": "CHECK",
                "final_action": "BET",
                "alternatives": [
                    {"action": "CHECK", "ev": -0.1},
                    {"action": "BET", "rawAction": "BET_75", "freq": 0.67, "ev": 0.42},
                ],
                "alternatives_complete": [
                    {"action": "CHECK", "ev": -0.1},
                    {"action": "BET", "rawAction": "BET_75", "freq": 0.67, "ev": 0.42},
                ],
            },
            "session_id": "session-ui-a",
            "timestamp": "2026-04-11T12:00:01Z",
            "street": "TURN",
            "chosen_action": "BET",
            "chosen_action_raw": "BET_75",
            "ev": 0.42,
            "confidence": "0.91",
            "backend": "native_rust",
            "backend_details": {"name": "native_rust", "version": "1.2.3"},
            "cache_hit": True,
            "cache_details": {"hit": True, "tier": "memory"},
            "ev_by_action": {"CHECK": -0.1, "BET": 0.42},
            "freq_by_action": {"CHECK": 0.33, "BET": 0.67},
            "action_metadata": {
                "CHECK": {"ev": -0.1, "freq": 0.33},
                "BET": {"raw_action": "BET_75", "ev": 0.42, "freq": 0.67},
            },
            "gto_action": "CHECK",
            "final_action": "BET",
            "incidents": ["latency_warning"],
            "ab_decision": {
                "comparison": {
                    "rl_off": {"action": "CHECK"},
                    "rl_on": {"action": "BET"},
                }
            },
        }
    ]


def test_runtime_history_store_describes_and_coerces_policy_compare_artifact_aliases():
    payload = {
        "kind": "policy_compare_corpus_batch",
        "meta": {
            "artifact_type": "policy_compare_batch",
            "contract": {
                "name": "runtime_review",
                "version": "v1",
                "artifact_type": "policy_compare_batch",
            },
        },
        "sessions": [
            {
                "session_id": "alias-session",
                "records": [
                    {"stream": "events", "timestamp": "2026-04-11T10:00:00Z", "message": "batch event"},
                    {"stream": "decisions", "timestamp": "2026-04-11T10:00:01Z", "spot_id": "spot-1", "chosen_action": "BET"},
                ],
            }
        ],
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)
    summary = RuntimeHistoryStore.describe_records_payload(payload)

    assert [record["stream"] for record in records] == ["events", "decisions"]
    assert summary == {
        "detected": True,
        "artifact_type": "review_pack",
        "record_count": 2,
        "counts": {
            "events": 1,
            "decisions": 1,
            "incidents": 0,
            "metrics": 0,
        },
    }


def test_runtime_history_store_describes_policy_compare_corpus_records_alias():
    payload = {
        "kind": "policy_compare_corpus",
        "meta": {
            "artifact_type": "policy_compare_corpus",
        },
        "records": [
            {"stream": "decisions", "timestamp": "2026-04-11T10:00:01Z", "spot_id": "spot-1", "chosen_action": "CALL"}
        ],
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)
    summary = RuntimeHistoryStore.describe_records_payload(payload)

    assert len(records) == 1
    assert summary["artifact_type"] == "policy_compare_corpus"
    assert summary["counts"]["decisions"] == 1


def test_runtime_history_store_coerces_canonical_runtime_review_wrapper():
    payload = {
        "runtime_review": {
            "name": "runtime_review",
            "version": "v1",
            "artifact_type": "review_session",
            "artifact": {
                "bundle": {
                    "records": [
                        {
                            "stream": "decisions",
                            "timestamp": "2026-04-11T10:00:01Z",
                            "spot_id": "spot-9",
                            "chosen_action": "BET",
                        }
                    ]
                }
            },
        }
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)
    summary = RuntimeHistoryStore.describe_records_payload(payload)

    assert len(records) == 1
    assert records[0]["spot_id"] == "spot-9"
    assert summary["artifact_type"] == "review_session"
    assert summary["counts"]["decisions"] == 1


def test_runtime_history_store_prefers_runtime_review_over_conflicting_legacy_aliases():
    payload = {
        "records": [
            {
                "stream": "decisions",
                "timestamp": "2026-04-11T10:00:02Z",
                "spot_id": "legacy-spot",
                "chosen_action": "FOLD",
            }
        ],
        "runtime_review": {
            "name": "runtime_review",
            "version": "v1",
            "artifact_type": "review_session",
            "artifact": {
                "bundle": {
                    "records": [
                        {
                            "stream": "decisions",
                            "timestamp": "2026-04-11T10:00:01Z",
                            "spot_id": "canonical-spot",
                            "chosen_action": "BET",
                        }
                    ]
                }
            },
        },
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)

    assert len(records) == 1
    assert records[0]["spot_id"] == "canonical-spot"


def test_runtime_history_store_keeps_legacy_review_session_fallback_without_runtime_review():
    payload = {
        "review_session": {
            "bundle": {
                "records": [
                    {
                        "stream": "decisions",
                        "timestamp": "2026-04-11T10:00:01Z",
                        "spot_id": "legacy-review-session",
                        "chosen_action": "CALL",
                    }
                ]
            }
        },
        "records": [
            {
                "stream": "decisions",
                "timestamp": "2026-04-11T10:00:02Z",
                "spot_id": "top-level-record",
                "chosen_action": "FOLD",
            }
        ],
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)
    summary = RuntimeHistoryStore.describe_records_payload(payload)

    assert len(records) == 1
    assert records[0]["spot_id"] == "legacy-review-session"
    assert summary["artifact_type"] == "review_session"


def test_runtime_history_store_coerces_runtime_review_batch_raw_review_pack_payload():
    payload = {
        "runtime_review": {
            "name": "runtime_review",
            "version": "v1",
            "artifact_type": "policy_compare_batch",
            "artifact": {
                "raw": {
                    "kind": "review_pack",
                    "currentReplay": {
                        "selectedSpot": {
                            "id": "spot-raw-pack",
                            "timestamp": "2026-04-11T12:00:01Z",
                            "street": "TURN",
                            "action": "BET",
                            "actionShift": "CHECK -> BET",
                        }
                    },
                }
            },
        }
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)
    summary = RuntimeHistoryStore.describe_records_payload(payload)

    assert len(records) == 1
    assert records[0]["spot_id"] == "spot-raw-pack"
    assert summary["artifact_type"] == "policy_compare_batch"


def test_runtime_history_store_does_not_treat_arbitrary_raw_payload_as_review_pack():
    payload = {
        "raw": {
            "records": [
                {
                    "stream": "decisions",
                    "timestamp": "2026-04-11T12:00:01Z",
                    "spot_id": "raw-record-only",
                    "chosen_action": "BET",
                }
            ]
        },
        "records": [
            {
                "stream": "decisions",
                "timestamp": "2026-04-11T12:00:02Z",
                "spot_id": "top-level-record",
                "chosen_action": "CALL",
            }
        ],
    }

    records = RuntimeHistoryStore.coerce_records_payload(payload)

    assert len(records) == 1
    assert records[0]["spot_id"] == "top-level-record"
