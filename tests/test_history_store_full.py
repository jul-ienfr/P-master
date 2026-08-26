# -*- coding: utf-8 -*-
"""Tests complémentaires du RuntimeHistoryStore : erreurs d'écriture, imports, coercion."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.history_store import RuntimeHistoryStore


@pytest.fixture()
def store(tmp_path):
    return RuntimeHistoryStore(file_path=tmp_path / "history" / "store.jsonl")


def test_append_disabled_is_noop(tmp_path):
    store = RuntimeHistoryStore(file_path=tmp_path / "h.jsonl", enabled=False)
    store.append("events", {"x": 1})
    assert store.read_recent() == []
    assert list(store._iter_records()) == []


def test_append_write_failure_is_swallow_and_flagged(tmp_path):
    import os
    import shutil

    store = RuntimeHistoryStore(file_path=tmp_path / "h.jsonl")
    # répertoire au lieu du fichier -> l'ouverture échoue
    (tmp_path / "h.jsonl").mkdir()
    store.append("events", {"x": 1})
    assert store._write_failed is True
    # une écriture réussie réinitialise le drapeau
    shutil.rmtree(tmp_path / "h.jsonl")
    if not (tmp_path / "h.jsonl").exists():
        pass
    os.makedirs(tmp_path, exist_ok=True)
    store.append("events", {"x": 1})
    assert store._write_failed is False


def test_iter_records_skips_corrupted_lines(store, tmp_path):
    store.file_path.parent.mkdir(parents=True, exist_ok=True)
    with store.file_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"stream": "events", "a": 1}) + "\n")
        handle.write("\n")
        handle.write("{corrupted\n")
        handle.write(json.dumps({"stream": "unknown_stream", "b": 2}) + "\n")
    records = list(store._iter_records())
    # la ligne corrompue est ignorée, les autres conservées
    assert len(records) == 2
    assert records[0]["a"] == 1


def test_session_id_for_path_backups():
    from src.runtime.history_store import RuntimeHistoryStore as S

    assert S._session_id_for_path(Path("store.jsonl.bak.1")) == "backup_1"
    assert S._session_id_for_path(Path("store.jsonl.bak.2")) == "backup_2"
    assert S._session_id_for_path(Path("store.jsonl.bak")) == "backup_legacy"


def test_rotate_creates_numbered_backups(tmp_path):
    file_path = tmp_path / "h" / "store.jsonl"
    store = RuntimeHistoryStore(file_path=file_path, max_size_bytes=200)
    # dépasse volontairement max_size_bytes pour déclencher la rotation
    for index in range(6):
        store.append("events", {"n": index, "payload": "x" * 80})
        store._rotate_if_needed()
    backups = sorted(p.name for p in file_path.parent.glob("*.bak*"))
    assert backups


def test_coerce_records_payload_accepts_list_and_rejects_garbage(store):
    records = [{"stream": "events", "message": "hello"}]
    assert store.coerce_records_payload(records) == records
    with pytest.raises(ValueError):
        store.coerce_records_payload("garbage")


def test_import_records_replace_mode(store):
    store.append("events", {"old": True})
    imported = [
        {"stream": "events", "message": "new1"},
        {"stream": "decisions", "action": "BET"},
    ]
    summary = store.import_records(imported, replace=True)
    assert summary["imported_count"] == 2
    assert summary["replaced"] is True
    events = store.read_recent(stream="events")
    assert all(not record.get("old") for record in events)


def test_summarize_reports_storage_state(store):
    store.append("events", {"x": 1})
    summary = store.summarize()
    assert summary["available"] is True
    assert summary["path"] == str(store.file_path)
    assert summary["size_bytes"] > 0


def test_describe_records_payload_counts_streams():
    payload = {"records": [{"stream": "events", "a": 1}, {"stream": "decisions"}]}
    described = RuntimeHistoryStore.describe_records_payload(payload)
    assert described["record_count"] == 2
    assert described["counts"]["events"] == 1
    assert described["detected"] is True

    undetected = RuntimeHistoryStore.describe_records_payload("garbage")
    assert undetected["detected"] is False


def test_normalize_record_rejects_non_dict():
    assert RuntimeHistoryStore._normalize_record("nope") is None
    normalized = RuntimeHistoryStore._normalize_record({"stream": "  events  ", "a": 1})
    assert normalized["stream"] == "events"


def test_normalize_session_id_variants():
    assert RuntimeHistoryStore._normalize_session_id("  sess-1 ") == "sess-1"
    assert RuntimeHistoryStore._normalize_session_id(None) is None
    assert RuntimeHistoryStore._normalize_session_id(123) == "123"
