from __future__ import annotations

import json
import sys
import types

sys.modules.setdefault(
    "aiohttp_cors",
    types.SimpleNamespace(
        ResourceOptions=lambda **kwargs: kwargs,
        setup=lambda app, defaults=None: types.SimpleNamespace(add=lambda route: route),
    ),
)

from src.api.server import BotAPI
from research.policy_compare import build_policy_compare_summary, load_policy_compare_corpus
from research.run_policy_compare import main as run_policy_compare_main


class StubHITL:
    is_waiting_for_human = False
    current_issue = None
    annotations_count = 0
    target_dataset_size = 0

    @staticmethod
    def check_convergence() -> bool:
        return False


class FakeQueryRequest:
    def __init__(self, query: dict[str, str] | None = None):
        self.query = query or {}


class FakeJsonRequest(FakeQueryRequest):
    def __init__(self, payload: dict, query: dict[str, str] | None = None):
        super().__init__(query=query)
        self._payload = payload

    async def json(self):
        return self._payload


class FakeHistoryStore:
    def __init__(self, records: list[dict]):
        self.records = list(records)

    def export_records(self, stream=None):
        if stream is None:
            return list(self.records)
        return [record for record in self.records if record.get("stream") == stream]


def test_botapi_policy_compare_export_includes_ab_variants_same_spot():
    decision_record = {
        "stream": "decisions",
        "timestamp": "2026-04-11T12:00:01Z",
        "spot_id": "live:PREFLOP:001",
        "street": "PREFLOP",
        "board": [],
        "hero_cards": ["Ah", "Kd"],
        "pot": 5.5,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "action_history": ["open_2.5x"],
        "chosen_action": "BET",
        "chosen_action_raw": "BET_75",
        "source": "validated_rl",
        "ev": 0.41,
        "backend": "native_rust",
        "cache_hit": True,
        "solver_elapsed_ms": 9.0,
        "node_count": 512,
        "exploitability": 0.021,
        "solver_warning_details": [{"code": "subtree_reused", "detail": "cached node"}],
        "solver_id": "native-postflop",
        "preset_id": "preflop_open_btn",
        "action_buckets": ["FOLD", "BET_75"],
        "metadata": {
            "solver": {
                "elapsed_ms": 9,
                "node_count": 512,
                "exploitability": 0.021,
                "warning_details": [{"code": "subtree_reused", "detail": "cached node"}],
                "solver_id": "native-postflop",
                "preset_id": "preflop_open_btn",
                "action_buckets": ["FOLD", "BET_75"],
                "alternatives": [
                    {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
                    {"action": "BET", "raw_action": "BET_75", "freq": 0.38, "ev": 0.41},
                ]
            }
        },
        "ab_decision": {
            "gto_action": "FOLD",
            "rl_action": "BET",
            "comparison": {
                "rl_off": {"action": "FOLD", "ev": -0.15},
                "rl_on": {"action": "BET", "ev": 0.41},
            },
        },
    }
    api = BotAPI(
        StubHITL(),
        runtime_status_provider=lambda: {
            "session_id": "runtime-session-001",
            "canonical_spot": {
                "spot_id": "live:PREFLOP:001",
                "street": "PREFLOP",
                "pot": 5.5,
                "board": [],
                "hero_cards": ["Ah", "Kd"],
                "players": [{"seat_id": "hero", "stack": 100.0, "is_hero": True}],
                "legal_actions": ["FOLD", "CALL", "BET"],
                "metadata": {"hero_seat_id": "btn"},
            }
        },
        runtime_history_store=FakeHistoryStore([decision_record]),
    )

    payload = json.loads(
        __import__("asyncio").run(
            api.handle_runtime_history_export(FakeQueryRequest({"stream": "decisions", "format": "policy_compare"}))
        ).text
    )

    assert payload["kind"] == "policy_compare_corpus"
    assert payload["meta"]["artifact_type"] == "policy_compare_corpus"
    assert payload["runtime_review"]["artifact_type"] == "policy_compare_corpus"
    assert payload["meta"]["contract"] == {
        "name": "runtime_review",
        "version": "v1",
        "artifact_type": "policy_compare_corpus",
    }
    assert payload["contract"]["artifact_type"] == "policy_compare_corpus"
    assert payload["records"][0]["policy_actions"] == {
        "validated_rl": "BET",
        "gto_solver": "FOLD",
        "rl_off": "FOLD",
        "rl_on": "BET",
    }
    assert payload["records"][0]["ev_by_action"] == {"FOLD": -0.15, "BET": 0.41}
    assert payload["records"][0]["chosen_action_raw"] == "BET_75"
    assert payload["records"][0]["backend"] == "native_rust"
    assert payload["records"][0]["cache_hit"] is True
    assert payload["records"][0]["elapsed_ms"] == 9.0
    assert payload["records"][0]["node_count"] == 512
    assert payload["records"][0]["exploitability"] == 0.021
    assert payload["records"][0]["solver_id"] == "native-postflop"
    assert payload["records"][0]["preset_id"] == "preflop_open_btn"
    assert payload["records"][0]["action_buckets"] == ["FOLD", "BET_75"]
    assert payload["records"][0]["warning_details"] == [{"code": "subtree_reused", "detail": "cached node"}]
    assert payload["records"][0]["alternatives"] == [
        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
        {"action": "BET", "raw_action": "BET_75", "freq": 0.38, "ev": 0.41},
    ]
    assert payload["records"][0]["metadata"]["session_id"] == "runtime-session-001"
    assert payload["records"][0]["metadata"]["chosen_action_raw"] == "BET_75"
    assert payload["records"][0]["metadata"]["backend"] == "native_rust"
    assert payload["records"][0]["metadata"]["cache_hit"] is True
    assert payload["records"][0]["metadata"]["elapsed_ms"] == 9.0
    assert payload["records"][0]["metadata"]["node_count"] == 512
    assert payload["records"][0]["metadata"]["warning_details"] == [{"code": "subtree_reused", "detail": "cached node"}]


def test_policy_compare_loader_and_summary_support_runtime_ab_variants(tmp_path):
    bundle_path = tmp_path / "runtime_bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "format": "runtime_history_v1",
                "bundle": {
                    "kind": "runtime_replay_bundle",
                    "runtime": {
                        "canonical_spot": {
                            "spot_id": "live:PREFLOP:001",
                            "street": "PREFLOP",
                            "pot": 5.5,
                            "board": [],
                            "hero_cards": ["Ah", "Kd"],
                            "players": [{"seat_id": "hero", "stack": 100.0, "is_hero": True}],
                            "legal_actions": ["FOLD", "CALL", "BET"],
                            "metadata": {"hero_seat_id": "btn"},
                        }
                    },
                    "records": [
                        {
                            "stream": "decisions",
                            "timestamp": "2026-04-11T12:00:01Z",
                            "spot_id": "live:PREFLOP:001",
                            "street": "PREFLOP",
                            "hero_cards": ["Ah", "Kd"],
                            "board": [],
                            "pot": 5.5,
                            "legal_actions": ["FOLD", "CALL", "BET"],
                            "chosen_action": "BET",
                            "chosen_action_raw": "BET_75",
                            "source": "validated_rl",
                            "ev": 0.41,
                            "backend": "native_rust",
                            "cache_hit": True,
                            "metadata": {
                                "solver": {
                                    "alternatives": [
                                        {"action": "FOLD", "raw_action": "FOLD", "freq": 0.62, "ev": -0.15},
                                        {"action": "BET", "raw_action": "BET_75", "freq": 0.38, "ev": 0.41},
                                    ]
                                }
                            },
                            "ab_decision": {
                                "gto_action": "FOLD",
                                "rl_action": "BET",
                                "comparison": {
                                    "rl_off": {"action": "FOLD", "ev": -0.15},
                                    "rl_on": {"action": "BET", "ev": 0.41},
                                },
                            },
                        }
                    ],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([bundle_path])

    assert len(records) == 1
    assert records[0].policy_actions == {
        "validated_rl": "BET",
        "gto_solver": "FOLD",
        "rl_off": "FOLD",
        "rl_on": "BET",
    }
    assert records[0].ev_by_action == {"FOLD": -0.15, "BET": 0.41}

    summary = build_policy_compare_summary(records, baseline_policy="rl_off", challenger_policy="rl_on")

    assert summary["available_policies"] == ["gto_solver", "rl_off", "rl_on", "validated_rl"]
    assert summary["pairwise"][0]["comparable_records"] == 1
    assert summary["pairwise"][0]["agreements"] == 0
    assert summary["pairwise"][0]["action_pair_counts"] == {"FOLD->BET": 1}
    assert summary["pairwise"][0]["baseline_ev_sum"] == -0.15
    assert summary["pairwise"][0]["challenger_ev_sum"] == 0.41


def test_botapi_policy_compare_export_uses_existing_compact_ev_by_action_when_present():
    api = BotAPI(
        StubHITL(),
        runtime_status_provider=lambda: {"session_id": "runtime-session-compact"},
        runtime_history_store=FakeHistoryStore(
            [
                {
                    "stream": "decisions",
                    "timestamp": "2026-04-11T12:00:01Z",
                    "spot_id": "live:TURN:001",
                    "street": "TURN",
                    "chosen_action": "CALL",
                    "source": "validated_rl",
                    "ev": 0.18,
                    "ev_by_action": {"call": 0.18, "fold": -0.22},
                }
            ]
        ),
    )

    payload = json.loads(
        __import__("asyncio").run(
            api.handle_runtime_history_export(FakeQueryRequest({"stream": "decisions", "format": "policy_compare"}))
        ).text
    )

    assert payload["records"][0]["ev_by_action"] == {"CALL": 0.18, "FOLD": -0.22}


def test_botapi_policy_compare_summary_exposes_compact_spot_examples():
    summary = BotAPI._build_policy_compare_summary_from_records(
        [
            {
                "timestamp": "2026-04-11T12:00:01Z",
                "spot_id": "live:PREFLOP:001",
                "street": "PREFLOP",
                "hero_cards": ["Ah", "Kd"],
                "board": [],
                "pot": 5.5,
                "chosen_action": "BET",
                "source": "validated_rl",
                "ev": 0.41,
                "metadata": {
                    "solver": {
                        "alternatives": [
                            {"action": "FOLD", "ev": -0.15},
                            {"action": "BET", "ev": 0.41},
                        ]
                    }
                },
                "ab_decision": {
                    "gto_action": "FOLD",
                    "rl_action": "BET",
                    "comparison": {
                        "rl_off": {"action": "FOLD", "ev": -0.15},
                        "rl_on": {"action": "BET", "ev": 0.41},
                    },
                },
            }
        ]
    )

    rl_pair = next(
        comparison
        for comparison in summary["comparisons"]
        if comparison["baseline_policy"] == "rl_off"
        and comparison["challenger_policy"] == "rl_on"
    )
    assert rl_pair["sample_ids"] == ["live:PREFLOP:001@2026-04-11T12:00:01Z"]
    assert rl_pair["top_spots"] == [
        {
            "sample_id": "live:PREFLOP:001@2026-04-11T12:00:01Z",
            "spot_id": "live:PREFLOP:001",
            "street": "PREFLOP",
            "baseline_action": "FOLD",
            "challenger_action": "BET",
            "action_pair": "FOLD->BET",
            "hero_cards": ["Ah", "Kd"],
            "pot": 5.5,
            "baseline_ev": -0.15,
            "challenger_ev": 0.41,
            "ev_delta": 0.56,
        }
    ]
    assert summary["highlights"]["most_divergent_pair"]["divergence_examples"][0]["sample_id"] == "live:PREFLOP:001@2026-04-11T12:00:01Z"
    assert summary["highlights"]["top_spots"][0]["spot_id"] == "live:PREFLOP:001"


def test_botapi_policy_compare_batch_export_is_loadable_as_multi_session_corpus(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "stream": "decisions",
                        "timestamp": "2026-04-11T12:00:01Z",
                        "spot_id": "live:PREFLOP:001",
                        "street": "PREFLOP",
                        "hero_cards": ["Ah", "Kd"],
                        "board": [],
                        "pot": 5.5,
                        "legal_actions": ["FOLD", "CALL", "BET"],
                        "chosen_action": "FOLD",
                        "source": "gto_solver",
                        "ev": -0.15,
                        "session_id": "runtime-session-a",
                    }
                ),
                json.dumps(
                    {
                        "stream": "decisions",
                        "timestamp": "2026-04-11T12:00:02Z",
                        "spot_id": "live:PREFLOP:002",
                        "street": "PREFLOP",
                        "hero_cards": ["Qs", "Qc"],
                        "board": [],
                        "pot": 6.0,
                        "legal_actions": ["FOLD", "CALL", "BET"],
                        "chosen_action": "BET",
                        "source": "validated_rl",
                        "ev": 0.41,
                        "session_id": "runtime-session-b",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from src.runtime.history_store import RuntimeHistoryStore

    api = BotAPI(
        StubHITL(),
        runtime_status_provider=lambda: {
            "canonical_spot": {
                "spot_id": "live:PREFLOP:999",
                "street": "PREFLOP",
                "pot": 5.5,
                "board": [],
                "hero_cards": ["Ah", "Kd"],
                "players": [{"seat_id": "hero", "stack": 100.0, "is_hero": True}],
                "legal_actions": ["FOLD", "CALL", "BET"],
                "metadata": {"hero_seat_id": "btn"},
            }
        },
        runtime_history_store=RuntimeHistoryStore(file_path=str(history_path)),
    )

    payload = json.loads(
        __import__("asyncio").run(
            api.handle_runtime_history_export(FakeQueryRequest({"stream": "decisions", "format": "policy_compare_batch"}))
        ).text
    )

    assert payload["kind"] == "policy_compare_corpus_batch"
    assert payload["meta"]["artifact_type"] == "policy_compare_batch"
    assert payload["contract"]["artifact_type"] == "policy_compare_batch"
    assert payload["runtime_review"]["artifact_type"] == "policy_compare_batch"
    assert payload["runtime_review"]["artifact"]["sessions"][0]["session_id"] == "runtime-session-a"
    assert payload["review_pack"]["contract"]["artifact_type"] == "review_pack"
    assert [session["session_id"] for session in payload["sessions"]] == ["runtime-session-a", "runtime-session-b"]
    assert payload["sessions"][0]["record_count"] == 1
    assert payload["sessions"][1]["record_count"] == 1

    batch_path = tmp_path / "policy_compare_batch.json"
    batch_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    records = load_policy_compare_corpus([batch_path])
    summary = build_policy_compare_summary(records)

    assert len(records) == 2
    assert records[0].metadata["session_id"] == "runtime-session-a"
    assert records[1].metadata["session_id"] == "runtime-session-b"
    assert summary["available_policies"] == ["gto_solver", "validated_rl"]


def test_botapi_review_contract_export_and_import_coerce_nested_wrappers(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"

    from src.runtime.history_store import RuntimeHistoryStore

    store = RuntimeHistoryStore(file_path=str(history_path))
    store.import_records(
        [
            {
                "stream": "decisions",
                "timestamp": "2026-04-11T12:00:01Z",
                "spot_id": "live:PREFLOP:001",
                "street": "PREFLOP",
                "chosen_action": "BET",
                "source": "validated_rl",
            }
        ],
        replace=True,
    )
    api = BotAPI(StubHITL(), runtime_status_provider=lambda: {}, runtime_history_store=store)

    export_response = __import__("asyncio").run(api.handle_runtime_history_export(FakeQueryRequest()))
    export_payload = json.loads(export_response.text)

    assert export_payload["format"] == "runtime_history_v1"
    assert export_payload["format_version"] == "v1"
    assert export_payload["meta"] == {
        "format": "runtime_review",
        "format_version": "v1",
        "name": "runtime_review",
        "version": "v1",
        "contract_name": "runtime_review",
        "contract_version": "v1",
        "artifact_type": "review_session",
        "kind": "runtime_replay_bundle",
        "contract": {
            "name": "runtime_review",
            "version": "v1",
            "artifact_type": "review_session",
        },
        "stream": "all",
        "record_count": 1,
    }
    assert export_payload["contract"]["name"] == "runtime_review"
    assert export_payload["contract"]["version"] == "v1"
    assert export_payload["contract"]["artifact_type"] == "review_session"
    assert export_payload["contract"]["stream"] == "all"
    assert export_payload["contract"]["record_count"] == 1
    assert export_payload["contract"]["exported_at"]
    assert export_payload["contract"]["compatibility"]["imports_records_from"] == [
        "runtime_review.artifact.records",
        "runtime_review.artifact.bundle.records",
        "runtime_review.artifact.sessions[*].records",
        "records",
        "bundle.records",
        "sessions[*].records",
        "review_session.records",
        "review_session.bundle.records",
        "review_pack.sessions[*].raw.records",
        "review_pack.records",
        "review_pack.sessions[*].records",
        "review_pack.raw.*",
        "review_pack.currentReplay.timeline[*]",
        "review_pack.current_replay.timeline[*]",
    ]
    assert export_payload["runtime_review"]["name"] == "runtime_review"
    assert export_payload["runtime_review"]["version"] == "v1"
    assert export_payload["runtime_review"]["artifact_type"] == "review_session"
    assert export_payload["runtime_review"]["artifact"]["bundle"]["records"][0]["spot_id"] == "live:PREFLOP:001"
    assert export_payload["review_session"]["version"] == "v1"
    assert export_payload["review_session"]["meta"] == export_payload["meta"]
    assert export_payload["review_session"]["contract"]["artifact_type"] == "review_session"
    assert export_payload["review_session"]["bundle"]["records"][0]["spot_id"] == "live:PREFLOP:001"
    assert "runtime_review_session_all.json" in export_response.headers["Content-Disposition"]

    import_store = RuntimeHistoryStore(file_path=str(tmp_path / "imported_runtime_history.jsonl"))
    import_api = BotAPI(StubHITL(), runtime_status_provider=lambda: {}, runtime_history_store=import_store)
    import_response = __import__("asyncio").run(
        import_api.handle_runtime_history_import(FakeJsonRequest({"review_session": export_payload["review_session"]}))
    )
    import_payload = json.loads(import_response.text)

    assert import_payload["success"] is True
    assert import_payload["contract"]["name"] == "runtime_review"
    assert import_payload["contract"]["version"] == "v1"
    assert import_payload["contract"]["artifact_type"] == "review_session"
    assert import_payload["contract"]["coerced_record_count"] == 1
    imported_records = import_store.export_records()
    assert len(imported_records) == 1
    assert imported_records[0]["spot_id"] == "live:PREFLOP:001"

    batch_payload = {
        "review_pack": {
            "format": "runtime_review",
            "version": "v1",
            "sessions": [
                {
                    "session_id": "session-a",
                    "records": [
                        {
                            "stream": "events",
                            "timestamp": "2026-04-11T12:00:02Z",
                            "kind": "info",
                            "message": "first",
                        }
                    ],
                },
                {
                    "session_id": "session-b",
                    "records": [
                        {
                            "stream": "incidents",
                            "timestamp": "2026-04-11T12:00:03Z",
                            "id": "incident-1",
                        }
                    ],
                },
            ],
        }
    }
    batch_records = RuntimeHistoryStore.coerce_records_payload(batch_payload)
    assert [record["stream"] for record in batch_records] == ["events", "incidents"]


def test_policy_compare_loader_supports_contract_wrapped_review_session_and_pack(tmp_path):
    review_session_path = tmp_path / "review_session_contract.json"
    review_session_path.write_text(
        json.dumps(
            {
                "format": "runtime_history_v1",
                "format_version": "v1",
                "contract": {
                    "name": "runtime_review",
                    "version": "v1",
                    "artifact_type": "review_session",
                },
                "review_session": {
                    "format": "runtime_review",
                    "version": "v1",
                    "bundle": {
                        "kind": "runtime_replay_bundle",
                        "records": [
                            {
                                "stream": "decisions",
                                "timestamp": "2026-04-11T12:00:01Z",
                                "spot_id": "live:PREFLOP:100",
                                "street": "PREFLOP",
                                "hero_cards": ["Ah", "Kd"],
                                "board": [],
                                "pot": 3.0,
                                "legal_actions": ["FOLD", "CALL", "BET"],
                                "chosen_action": "BET",
                                "source": "validated_rl",
                            }
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    review_pack_path = tmp_path / "review_pack_contract.json"
    review_pack_path.write_text(
        json.dumps(
            {
                "kind": "review_pack",
                "version": "v1",
                "contract": {
                    "name": "runtime_review",
                    "version": "v1",
                    "artifact_type": "review_pack",
                },
                "review_pack": {
                    "format": "runtime_review",
                    "version": "v1",
                    "sessions": [
                        {
                            "session_id": "session-a",
                            "records": [
                                {
                                    "replay_id": "corpus-001",
                                    "spot": {
                                        "spot_id": "live:FLOP:200",
                                        "game_stage": "flop",
                                        "hero_cards": ["Ah", "Kd"],
                                        "board": ["2c", "7d", "Ts"],
                                        "legal_actions": ["CHECK", "BET"],
                                    },
                                    "policy_actions": {
                                        "gto_solver": "CHECK",
                                        "validated_rl": "BET",
                                    },
                                    "metadata": {
                                        "session_id": "session-a",
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    session_records = load_policy_compare_corpus([review_session_path])
    assert len(session_records) == 1
    assert session_records[0].policy_actions == {"validated_rl": "BET"}

    pack_records = load_policy_compare_corpus([review_pack_path])
    assert len(pack_records) == 1
    assert pack_records[0].policy_actions == {"gto_solver": "CHECK", "validated_rl": "BET"}


def test_policy_compare_loader_supports_new_policy_compare_artifact_aliases(tmp_path):
    corpus_path = tmp_path / "policy_compare_alias.json"
    corpus_path.write_text(
        json.dumps(
            {
                "kind": "policy_compare_corpus",
                "meta": {
                    "artifact_type": "policy_compare_corpus",
                    "contract": {
                        "name": "runtime_review",
                        "version": "v1",
                        "artifact_type": "policy_compare_corpus",
                    },
                },
                "records": [
                    {
                        "replay_id": "corpus-001",
                        "spot": {
                            "spot_id": "live:FLOP:300",
                            "game_stage": "flop",
                            "legal_actions": ["CHECK", "BET"],
                        },
                        "policy_actions": {
                            "gto_solver": "CHECK",
                            "validated_rl": "BET",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    batch_path = tmp_path / "policy_compare_batch_alias.json"
    batch_path.write_text(
        json.dumps(
            {
                "kind": "policy_compare_corpus_batch",
                "meta": {
                    "artifact_type": "policy_compare_batch",
                },
                "sessions": [
                    {
                        "session_id": "alias-session",
                        "records": [
                            {
                                "replay_id": "corpus-002",
                                "spot": {
                                    "spot_id": "live:TURN:301",
                                    "game_stage": "turn",
                                    "legal_actions": ["CHECK", "BET"],
                                },
                                "policy_actions": {
                                    "gto_solver": "CHECK",
                                    "validated_rl": "BET",
                                },
                                "metadata": {
                                    "session_id": "alias-session",
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    corpus_records = load_policy_compare_corpus([corpus_path])
    batch_records = load_policy_compare_corpus([batch_path])

    assert len(corpus_records) == 1
    assert corpus_records[0].policy_actions == {"gto_solver": "CHECK", "validated_rl": "BET"}
    assert len(batch_records) == 1
    assert batch_records[0].metadata["session_id"] == "alias-session"


def test_policy_compare_loader_supports_canonical_runtime_review_wrapper(tmp_path):
    session_path = tmp_path / "runtime_review_session.json"
    session_path.write_text(
        json.dumps(
            {
                "runtime_review": {
                    "name": "runtime_review",
                    "version": "v1",
                    "artifact_type": "review_session",
                    "contract": {
                        "name": "runtime_review",
                        "version": "v1",
                        "artifact_type": "review_session",
                    },
                    "artifact": {
                        "bundle": {
                            "kind": "runtime_replay_bundle",
                            "runtime": {
                                "canonical_spot": {
                                    "spot_id": "live:PREFLOP:501",
                                    "street": "PREFLOP",
                                    "pot": 5.5,
                                    "board": [],
                                    "hero_cards": ["Ah", "Kd"],
                                    "players": [{"seat_id": "hero", "stack": 100.0, "is_hero": True}],
                                    "legal_actions": ["FOLD", "CALL", "BET"],
                                    "metadata": {"hero_seat_id": "btn"},
                                }
                            },
                            "records": [
                                {
                                    "stream": "decisions",
                                    "timestamp": "2026-04-11T12:00:01Z",
                                    "spot_id": "live:PREFLOP:501",
                                    "street": "PREFLOP",
                                    "hero_cards": ["Ah", "Kd"],
                                    "board": [],
                                    "pot": 5.5,
                                    "legal_actions": ["FOLD", "CALL", "BET"],
                                    "chosen_action": "BET",
                                    "source": "validated_rl",
                                    "ab_decision": {
                                        "gto_action": "FOLD",
                                        "comparison": {
                                            "rl_off": {"action": "FOLD", "ev": -0.15},
                                            "rl_on": {"action": "BET", "ev": 0.41},
                                        },
                                    },
                                }
                            ],
                        }
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    batch_path = tmp_path / "runtime_review_batch.json"
    batch_path.write_text(
        json.dumps(
            {
                "runtime_review": {
                    "name": "runtime_review",
                    "version": "v1",
                    "artifact_type": "policy_compare_batch",
                    "contract": {
                        "name": "runtime_review",
                        "version": "v1",
                        "artifact_type": "policy_compare_batch",
                    },
                    "artifact": {
                        "sessions": [
                            {
                                "session_id": "canonical-session-a",
                                "records": [
                                    {
                                        "replay_id": "corpus-a",
                                        "spot": {
                                            "spot_id": "live:FLOP:510",
                                            "game_stage": "flop",
                                            "legal_actions": ["CHECK", "BET"],
                                        },
                                        "policy_actions": {
                                            "gto_solver": "CHECK",
                                            "validated_rl": "BET",
                                        },
                                        "metadata": {
                                            "session_id": "canonical-session-a",
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    session_records = load_policy_compare_corpus([session_path])
    batch_records = load_policy_compare_corpus([batch_path])

    assert len(session_records) == 1
    assert session_records[0].policy_actions["rl_off"] == "FOLD"
    assert session_records[0].policy_actions["rl_on"] == "BET"
    assert len(batch_records) == 1
    assert batch_records[0].metadata["session_id"] == "canonical-session-a"


def test_policy_compare_loader_prefers_runtime_review_over_conflicting_legacy_records(tmp_path):
    payload_path = tmp_path / "runtime_review_priority.json"
    payload_path.write_text(
        json.dumps(
            {
                "kind": "policy_compare_corpus",
                "records": [
                    {
                        "replay_id": "legacy-001",
                        "spot": {
                            "spot_id": "legacy:FLOP:001",
                            "game_stage": "flop",
                            "legal_actions": ["CHECK", "BET"],
                        },
                        "policy_actions": {
                            "gto_solver": "CHECK",
                            "validated_rl": "CHECK",
                        },
                    }
                ],
                "runtime_review": {
                    "name": "runtime_review",
                    "version": "v1",
                    "artifact_type": "policy_compare_corpus",
                    "artifact": {
                        "records": [
                            {
                                "replay_id": "canonical-001",
                                "spot": {
                                    "spot_id": "live:FLOP:777",
                                    "game_stage": "flop",
                                    "legal_actions": ["CHECK", "BET"],
                                },
                                "policy_actions": {
                                    "gto_solver": "CHECK",
                                    "validated_rl": "BET",
                                },
                            }
                        ]
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([payload_path])

    assert len(records) == 1
    assert records[0].replay_id == "canonical-001"
    assert records[0].policy_actions == {"gto_solver": "CHECK", "validated_rl": "BET"}


def test_policy_compare_loader_keeps_legacy_alias_fallback_without_runtime_review(tmp_path):
    payload_path = tmp_path / "legacy_policy_compare_alias.json"
    payload_path.write_text(
        json.dumps(
            {
                "kind": "policy_compare_corpus",
                "records": [
                    {
                        "replay_id": "legacy-keep-001",
                        "spot": {
                            "spot_id": "legacy:FLOP:111",
                            "game_stage": "flop",
                            "legal_actions": ["CHECK", "BET"],
                        },
                        "policy_actions": {
                            "gto_solver": "CHECK",
                            "validated_rl": "BET",
                        },
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([payload_path])

    assert len(records) == 1
    assert records[0].replay_id == "legacy-keep-001"
    assert records[0].policy_actions == {"gto_solver": "CHECK", "validated_rl": "BET"}


def test_policy_compare_loader_supports_runtime_review_batch_wrapping_frontend_review_pack(tmp_path):
    payload_path = tmp_path / "runtime_review_batch_frontend_pack.json"
    payload_path.write_text(
        json.dumps(
            {
                "runtime_review": {
                    "name": "runtime_review",
                    "version": "v1",
                    "artifact_type": "policy_compare_batch",
                    "artifact": {
                        "raw": {
                            "kind": "review_pack",
                            "sessionLabel": "wrapped-front-session",
                            "currentReplay": {
                                "selectedSpot": {
                                    "id": "spot-990",
                                    "street": "RIVER",
                                    "timestamp": "2026-04-11T12:55:00Z",
                                    "action": "BET",
                                    "heroEv": "0.35",
                                    "actionShift": "CHECK -> BET"
                                }
                            }
                        }
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([payload_path])

    assert len(records) == 1
    assert records[0].replay_id == "spot-990"
    assert records[0].metadata["session_label"] == "wrapped-front-session"
    assert records[0].policy_actions == {
        "review_pack_baseline": "CHECK",
        "review_pack_challenger": "BET",
    }


def test_policy_compare_loader_does_not_treat_arbitrary_raw_payload_as_review_pack(tmp_path):
    payload_path = tmp_path / "raw_records_only.json"
    payload_path.write_text(
        json.dumps(
            {
                "raw": {
                    "records": [
                        {
                            "replay_id": "raw-001",
                            "spot": {
                                "spot_id": "raw:FLOP:001",
                                "game_stage": "flop",
                                "legal_actions": ["CHECK", "BET"],
                            },
                            "policy_actions": {
                                "gto_solver": "CHECK",
                                "validated_rl": "CHECK",
                            },
                        }
                    ]
                },
                "records": [
                    {
                        "replay_id": "top-001",
                        "spot": {
                            "spot_id": "top:FLOP:001",
                            "game_stage": "flop",
                            "legal_actions": ["CHECK", "BET"],
                        },
                        "policy_actions": {
                            "gto_solver": "CHECK",
                            "validated_rl": "BET",
                        },
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([payload_path])

    assert len(records) == 1
    assert records[0].replay_id == "top-001"
    assert records[0].policy_actions == {"gto_solver": "CHECK", "validated_rl": "BET"}


def test_policy_compare_loader_supports_frontend_review_pack_raw_runtime_bundle(tmp_path):
    pack_path = tmp_path / "review_pack_frontend_raw.json"
    pack_path.write_text(
        json.dumps(
            {
                "kind": "review_pack",
                "version": 1,
                "raw": {
                    "format": "runtime_history_v1",
                    "bundle": {
                        "kind": "runtime_replay_bundle",
                        "runtime": {
                            "canonical_spot": {
                                "spot_id": "live:RIVER:001",
                                "street": "RIVER",
                                "pot": 28.0,
                                "board": ["Ah", "Kd", "7c", "2d", "2s"],
                                "hero_cards": ["Qs", "Qd"],
                                "players": [{"seat_id": "hero", "stack": 72.0, "is_hero": True}],
                                "legal_actions": ["CHECK", "BET"],
                                "metadata": {"hero_seat_id": "btn"},
                            }
                        },
                        "records": [
                            {
                                "stream": "decisions",
                                "timestamp": "2026-04-11T12:00:09Z",
                                "spot_id": "live:RIVER:001",
                                "street": "RIVER",
                                "hero_cards": ["Qs", "Qd"],
                                "board": ["Ah", "Kd", "7c", "2d", "2s"],
                                "pot": 28.0,
                                "legal_actions": ["CHECK", "BET"],
                                "chosen_action": "BET",
                                "source": "validated_rl",
                                "ab_decision": {
                                    "gto_action": "CHECK",
                                    "comparison": {
                                        "rl_off": {"action": "CHECK", "ev": 0.1},
                                        "rl_on": {"action": "BET", "ev": 0.35},
                                    }
                                },
                            }
                        ],
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([pack_path])
    summary = build_policy_compare_summary(records, baseline_policy="rl_off", challenger_policy="rl_on")

    assert len(records) == 1
    assert records[0].policy_actions["rl_off"] == "CHECK"
    assert records[0].policy_actions["rl_on"] == "BET"
    assert summary["pairwise"][0]["action_pair_counts"] == {"CHECK->BET": 1}


def test_policy_compare_loader_supports_frontend_review_pack_timeline_partial_summary(tmp_path):
    pack_path = tmp_path / "review_pack_frontend_timeline.json"
    pack_path.write_text(
        json.dumps(
            {
                "kind": "review_pack",
                "version": 1,
                "sessionLabel": "review-ui-session",
                "currentReplay": {
                    "selectedSpot": {
                        "id": "spot-777",
                        "title": "River bluff candidate",
                        "street": "RIVER",
                        "timestamp": "2026-04-11T12:15:00Z",
                        "action": "BET",
                        "heroEv": "0.35",
                        "actionShift": "CHECK -> BET",
                        "impactLabel": "High",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([pack_path])
    summary = build_policy_compare_summary(records, baseline_policy="review_pack_baseline", challenger_policy="review_pack_challenger")

    assert len(records) == 1
    assert records[0].metadata["session_label"] == "review-ui-session"
    assert records[0].policy_actions == {
        "review_pack_baseline": "CHECK",
        "review_pack_challenger": "BET",
    }
    assert summary["pairwise"][0]["comparable_records"] == 1
    assert summary["pairwise"][0]["action_pair_counts"] == {"CHECK->BET": 1}


def test_policy_compare_loader_supports_nested_review_pack_contract_and_raw_bundle(tmp_path):
    pack_path = tmp_path / "review_pack_nested_contract_raw.json"
    pack_path.write_text(
        json.dumps(
            {
                "review_pack": {
                    "format": "runtime_review",
                    "format_version": "v1",
                    "contract": {
                        "name": "runtime_review",
                        "version": "v1",
                        "artifact_type": "review_pack",
                    },
                    "raw": {
                        "review_session": {
                            "format": "runtime_review",
                            "version": "v1",
                            "bundle": {
                                "kind": "runtime_replay_bundle",
                                "runtime": {
                                    "canonical_spot": {
                                        "spot_id": "live:TURN:123",
                                        "street": "TURN",
                                        "pot": 14.5,
                                        "board": ["Ah", "Kd", "7c", "2d"],
                                        "hero_cards": ["Qs", "Qd"],
                                        "players": [{"seat_id": "hero", "stack": 85.0, "is_hero": True}],
                                        "legal_actions": ["CHECK", "BET"],
                                    }
                                },
                                "records": [
                                    {
                                        "stream": "decisions",
                                        "timestamp": "2026-04-11T12:30:00Z",
                                        "spot_id": "live:TURN:123",
                                        "street": "TURN",
                                        "hero_cards": ["Qs", "Qd"],
                                        "board": ["Ah", "Kd", "7c", "2d"],
                                        "pot": 14.5,
                                        "legal_actions": ["CHECK", "BET"],
                                        "chosen_action": "BET",
                                        "source": "validated_rl",
                                        "ab_decision": {
                                            "gto_action": "CHECK",
                                            "comparison": {
                                                "rl_off": {"action": "CHECK", "ev": 0.02},
                                                "rl_on": {"action": "BET", "ev": 0.21},
                                            },
                                        },
                                    }
                                ],
                            },
                        }
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([pack_path])
    summary = build_policy_compare_summary(records, baseline_policy="rl_off", challenger_policy="rl_on")

    assert len(records) == 1
    assert records[0].policy_actions["rl_off"] == "CHECK"
    assert records[0].policy_actions["rl_on"] == "BET"
    assert summary["pairwise"][0]["action_pair_counts"] == {"CHECK->BET": 1}


def test_policy_compare_loader_supports_nested_review_pack_contract_and_timeline(tmp_path):
    pack_path = tmp_path / "review_pack_nested_contract_timeline.json"
    pack_path.write_text(
        json.dumps(
            {
                "review_pack": {
                    "format": "runtime_review",
                    "version": "v1",
                    "meta": {
                        "contract_name": "runtime_review",
                        "contract_version": "v1",
                        "artifact_type": "review_pack",
                    },
                    "sessionLabel": "nested-envelope-session",
                    "currentReplay": {
                        "selectedSpot": {
                            "id": "spot-900",
                            "title": "Turn barrel",
                            "street": "TURN",
                            "timestamp": "2026-04-11T12:31:00Z",
                            "action": "BET",
                            "heroEv": "0.21",
                            "actionShift": "CHECK -> BET",
                        }
                    },
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = load_policy_compare_corpus([pack_path])

    assert len(records) == 1
    assert records[0].metadata["session_label"] == "nested-envelope-session"
    assert records[0].policy_actions == {
        "review_pack_baseline": "CHECK",
        "review_pack_challenger": "BET",
    }


def test_run_policy_compare_cli_loads_nested_review_pack_envelope(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "review_pack_cli.json"
    output_path = tmp_path / "policy_compare_summary.json"
    input_path.write_text(
        json.dumps(
            {
                "review_pack": {
                    "format": "runtime_review",
                    "version": "v1",
                    "sessions": [
                        {
                            "session_id": "session-cli",
                            "records": [
                                {
                                    "replay_id": "cli-001",
                                    "spot": {
                                        "spot_id": "live:FLOP:321",
                                        "game_stage": "flop",
                                        "hero_cards": ["Ah", "Kd"],
                                        "board": ["2c", "7d", "Ts"],
                                        "legal_actions": ["CHECK", "BET"],
                                    },
                                    "policy_actions": {
                                        "gto_solver": "CHECK",
                                        "validated_rl": "BET",
                                    },
                                }
                            ],
                        }
                    ],
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_policy_compare.py",
            str(input_path),
            "--baseline",
            "gto_solver",
            "--challenger",
            "validated_rl",
            "--list-policies",
            "--output",
            str(output_path),
        ],
    )

    run_policy_compare_main()
    stdout = capsys.readouterr().out
    summary = json.loads(output_path.read_text(encoding="utf-8"))

    assert "policies=gto_solver,validated_rl" in stdout
    assert summary["available_policies"] == ["gto_solver", "validated_rl"]
    assert summary["pairwise"][0]["action_pair_counts"] == {"CHECK->BET": 1}
