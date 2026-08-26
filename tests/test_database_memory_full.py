"""Tests du backend mémoire de DatabaseManager : cache, profils, fusion, persistance."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.database import DatabaseManager


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = DatabaseManager(mode="memory")
    asyncio.run(manager.connect())
    return manager


def run(coro):
    return asyncio.run(coro)


def test_memory_backend_available(db):
    assert db.is_available is True
    # la persistance locale est désactivée par défaut
    assert db.persistence_active is False
    snapshot = db._persistence_snapshot()
    assert snapshot["mode"] == "volatile_memory"
    assert snapshot["enabled"] is False


def test_record_observed_hand_updates_cache_and_profile(db):
    run(db.record_observed_hand("Villain1", street="flop"))
    profile = run(db.get_player_profile("Villain1"))
    assert profile is not None
    assert int(profile["observed_hands"]) >= 1
    # main vide ignorée proprement
    run(db.record_observed_hand(""))
    run(db.get_player_profile(""))


def test_update_player_action_counters(db):
    run(
        db.update_player_action(
            "Villain2",
            {"action": "RAISE", "street": "FLOP", "amount": 25.0},
        )
    )
    profile = run(db.get_player_profile("Villain2"))
    assert profile is not None
    raw = profile.get("raw_stats") or {}
    assert (raw.get("action_counts") or {}).get("RAISE") == 1
    assert int(profile.get("vpip_count", 0)) == 1
    assert int(profile.get("pfr_count", 0)) == 1

    # action passive : call -> vpip mais pas pfr
    run(db.update_player_action("Villain2", {"action": "CALL", "street": "FLOP"}))
    refreshed = run(db.get_player_profile("Villain2"))
    assert int(refreshed["vpip_count"]) == 2
    assert int(refreshed["pfr_count"]) == 1

    # fold : ni vpip ni pfr
    run(db.update_player_action("Villain2", {"action": "FOLD", "street": "TURN"}))
    final = run(db.get_player_profile("Villain2"))
    assert int(final["vpip_count"]) == 2
    assert (final["raw_stats"]["action_counts"]).get("FOLD") == 1


def test_update_player_action_ignores_empty_name_and_overrides(db, tmp_path):
    run(db.update_player_action("", {"action": "BET"}))
    run(db.update_player_action(None, {"action": "BET"}))
    # override manuel des compteurs
    run(
        db.update_player_action(
            "VillainX",
            {"action": "CALL", "street": "TURN", "counts_towards_vpip": 0, "counts_towards_pfr": 0},
        )
    )
    profile = run(db.get_player_profile("VillainX"))
    assert int(profile.get("vpip_count", 0)) == 0


def test_insert_hand_history_stores_in_memory(db):
    board = ["Ah", "Kd", "7h"]
    actions = [{"player": "Villain3", "action": "BET", "amount": 10}]
    run(db.insert_hand_history("Table1", board, actions))
    summary = db.summarize_observation(limit=5)
    assert summary["hands_recorded"] >= 1
    dataset = db.export_observation_dataset(player_limit=5, hand_limit=5)
    hands = dataset["hands"] if isinstance(dataset, dict) else []
    assert any(hand.get("table_name") == "Table1" for hand in hands)


def test_merge_player_profiles_merges_and_rewrites_history(db):
    run(db.update_player_action("OldName", {"action": "RAISE", "street": "FLOP"}))
    run(db.record_observed_hand("OldName"))
    run(db.update_player_action("NewName", {"action": "CALL", "street": "FLOP"}))
    run(db.insert_hand_history("T", [], [{"player": "OldName", "action": "CHECK"}]))

    run(db.merge_player_profiles("OldName", "NewName"))

    assert run(db.get_player_profile("OldName")) is None
    merged = run(db.get_player_profile("NewName"))
    raw = merged.get("raw_stats") or {}
    counts = raw.get("action_counts") or {}
    assert counts.get("RAISE") == 1 and counts.get("CALL") == 1

    # les mains d'historique ont été réécrites vers le nom cible
    dataset = db.export_observation_dataset(player_limit=10, hand_limit=50)
    for hand in dataset.get("hands", []):
        for action in hand.get("actions", []) or []:
            if isinstance(action, dict) and "player" in action:
                assert action["player"] != "OldName"

    # fusion avec soi-même ou noms vides : no-op
    run(db.merge_player_profiles("NewName", "NewName"))
    run(db.merge_player_profiles("", ""))
    # source inconnue : no-op
    run(db.merge_player_profiles("GhostPlayer", "NewName"))


def test_local_persistence_roundtrip(tmp_path):
    store = str(tmp_path / "log" / "observation_store.json")

    async def scenario():
        first = DatabaseManager(
            mode="memory", persistence_enabled=True, persistence_path=store
        )
        await first.connect()
        assert first.persistence_active is True
        await first.record_observed_hand("Persisted")
        await first.close()

        reloaded = DatabaseManager(
            mode="memory", persistence_enabled=True, persistence_path=store
        )
        await reloaded.connect()
        return await reloaded.get_player_profile("Persisted")

    profile = run(scenario())
    assert profile is not None
    assert int(profile["observed_hands"]) == 1


def test_normalize_player_row_static():
    from src.data.database import DatabaseManager as DM

    normalized = DM._normalize_player_row({"player_name": "X", "hands_played": "3"})
    assert normalized["player_name"] == "X"
    # pas de coercition : la valeur brute est conservée
    assert normalized["hands_played"] == "3"

    hand = DM._normalize_hand_row({"hand_id": "7", "board": ["Ah", "Kd"]})
    assert hand["hand_id"] == "7"  # pas de coercition d'id
    assert hand["board"] == ["Ah", "Kd"]
    assert hand["actions"] == []
