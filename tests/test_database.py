import asyncio
import conftest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.data.database import (
    DatabaseManager,
    _classify_player_style,
    _coerce_datetime_value,
    _coerce_json_array,
    _coerce_json_object,
    _safe_rate,
)


class FakeConnection:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, query, player_name):
        return self.row


class FakeAcquire:
    def __init__(self, row):
        self.row = row

    async def __aenter__(self):
        return FakeConnection(self.row)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, row):
        self.row = row

    def acquire(self):
        return FakeAcquire(self.row)


def run(coro):
    return asyncio.run(coro)


def test_safe_rate_handles_empty_denominator():
    assert _safe_rate(3, 0) == 0.0


def test_safe_rate_is_capped_to_one():
    assert _safe_rate(3, 2) == 1.0


def test_json_coercion_helpers_accept_serialized_values():
    assert _coerce_json_object('{"foo": 1}') == {"foo": 1}
    assert _coerce_json_array('[{"bar": 2}]') == [{"bar": 2}]


def test_datetime_coercion_accepts_serialized_timestamp():
    parsed = _coerce_datetime_value("2026-04-13 10:19:35.042699")

    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.month == 4
    assert parsed.day == 13


def test_classify_player_style_distinguishes_profiles():
    assert _classify_player_style(0.42, 0.28, 0.5) == "LooseAggressive"
    assert _classify_player_style(0.15, 0.08, 0.1) == "TightPassive"
    assert _classify_player_style(0.26, 0.15, 0.3) == "Balanced"


def test_get_player_profile_derives_rates_without_real_database():
    manager = DatabaseManager(dsn="postgresql://unused")
    manager.pool = FakePool(
        {
            "player_name": "Villain",
            "hands_played": 18,
            "observed_hands": 12,
            "vpip_count": 6,
            "pfr_count": 3,
            "player_type": "Unknown",
            "raw_stats": {
                "observed_hands": 12,
                "aggressive_actions": 5,
                "passive_actions": 5,
                "fold_actions": 2,
                "action_counts": {"CALL": 3, "RAISE/BET": 2},
                "street_counts": {"PREFLOP": 8, "FLOP": 4},
                "last_action": "CALL",
                "last_street": "FLOP",
                "last_observed_street": "TURN",
                "rl_ready": True,
            },
        }
    )

    profile = run(manager.get_player_profile("Villain"))
    derived = profile["derived_profile"]

    assert profile["player_type"] == "LooseAggressive"
    assert derived["hands_played"] == 12
    assert derived["observed_hands"] == 12
    assert derived["vpip_rate"] == 0.5
    assert derived["pfr_rate"] == 0.25
    assert derived["aggression_frequency"] == 0.5
    assert derived["aggression_ratio"] == 1.0
    assert derived["fold_rate"] == 0.1667
    assert derived["reliability"] == 0.1
    assert derived["last_action"] == "CALL"
    assert derived["last_observed_street"] == "TURN"
    assert derived["rl_ready"] is True


def test_hydrate_profile_snapshot_handles_stringified_raw_stats():
    manager = DatabaseManager(mode="memory")
    hydrated = manager._hydrate_profile_snapshot(
        {
            "player_name": "Villain",
            "hands_played": 4,
            "observed_hands": 2,
            "vpip_count": 1,
            "pfr_count": 1,
            "raw_stats": '{"observed_hands": 2, "aggressive_actions": 1, "passive_actions": 1, "fold_actions": 0}',
            "player_type": "Unknown",
        }
    )

    assert hydrated["raw_stats"]["observed_hands"] == 2
    assert hydrated["derived_profile"]["vpip_rate"] == 0.5


def test_memory_profiles_can_merge_placeholder_into_real_name():
    async def scenario():
        manager = DatabaseManager(mode="memory")
        await manager.connect()

        await manager.record_observed_hand("seat_5", "FLOP")
        await manager.update_player_action("seat_5", {"action": "CALL", "street": "FLOP"})
        await manager.record_observed_hand("oigbluffa28", "TURN")
        await manager.merge_player_profiles("seat_5", "oigbluffa28")

        profile = await manager.get_player_profile("oigbluffa28")
        summary = manager.summarize_observation(limit=5)

        assert profile is not None
        assert profile["observed_hands"] == 2
        assert profile["vpip_count"] == 1
        assert "seat_5" not in manager.players_memory
        assert summary["player_count"] == 1
        assert summary["top_profiles"][0]["player_name"] == "oigbluffa28"

    run(scenario())


def test_memory_backend_respects_explicit_vpip_and_pfr_flags():
    async def scenario():
        manager = DatabaseManager(mode="memory")
        await manager.connect()

        await manager.record_observed_hand("Villain", "PREFLOP")
        await manager.update_player_action(
            "Villain",
            {"action": "RAISE/BET", "street": "PREFLOP", "counts_towards_vpip": 1, "counts_towards_pfr": 1},
        )
        await manager.update_player_action(
            "Villain",
            {"action": "RAISE/BET", "street": "PREFLOP", "counts_towards_vpip": 0, "counts_towards_pfr": 0},
        )

        profile = await manager.get_player_profile("Villain")

        assert profile is not None
        assert profile["vpip_count"] == 1
        assert profile["pfr_count"] == 1
        assert profile["derived_profile"]["vpip_rate"] == 1.0
        assert profile["derived_profile"]["pfr_rate"] == 1.0

    run(scenario())


def test_observation_summary_prefers_named_profiles_over_seat_placeholders():
    async def scenario():
        manager = DatabaseManager(mode="memory")
        await manager.connect()

        await manager.record_observed_hand("seat_5", "FLOP")
        await manager.record_observed_hand("seat_5", "TURN")
        await manager.record_observed_hand("Brucy20", "FLOP")

        summary = manager.summarize_observation(limit=5)

        assert summary["player_count"] == 2
        assert summary["top_profiles"][0]["player_name"] == "Brucy20"

    run(scenario())


def test_observation_summary_ignores_invalid_ocr_profile_names():
    async def scenario():
        manager = DatabaseManager(mode="memory")
        await manager.connect()

        await manager.record_observed_hand("M", "FLOP")
        await manager.record_observed_hand("ah uffi au 26", "FLOP")
        await manager.record_observed_hand("Brucy20", "FLOP")

        summary = manager.summarize_observation(limit=5)

        assert summary["player_count"] == 1
        assert summary["top_profiles"][0]["player_name"] == "Brucy20"

    run(scenario())


def test_memory_backend_can_reload_persisted_observation_state(tmp_path):
    async def scenario():
        store_path = tmp_path / "observation_store.json"
        first_manager = DatabaseManager(
            mode="memory",
            persistence_enabled=True,
            persistence_path=str(store_path),
        )
        await first_manager.connect()

        await first_manager.record_observed_hand("VillainA", "FLOP")
        await first_manager.update_player_action("VillainA", {"action": "CALL", "street": "FLOP"})
        await first_manager.insert_hand_history(
            "Table_1",
            ["Ah", "Kd", "2c"],
            [{"player": "VillainA", "action": "CALL", "street": "FLOP"}],
        )
        await first_manager.close()

        second_manager = DatabaseManager(
            mode="memory",
            persistence_enabled=True,
            persistence_path=str(store_path),
        )
        await second_manager.connect()

        summary = second_manager.summarize_observation(limit=5)
        profile = await second_manager.get_player_profile("VillainA")
        exported = second_manager.export_observation_dataset(player_limit=10, hand_limit=10)

        assert store_path.exists()
        assert summary["persistence"]["mode"] == "json_file"
        assert summary["player_count"] == 1
        assert summary["hands_recorded"] == 1
        assert profile is not None
        assert profile["observed_hands"] == 1
        assert profile["vpip_count"] == 1
        assert exported["persistence"]["path"] == str(store_path)
        assert exported["hands"][0]["board"] == "AhKd2c"

        await second_manager.close()

    run(scenario())


class DummyConfig:
    def __init__(self, **options):
        self.options = options

    def getoption(self, name):
        return self.options.get(name)


def test_postgres_test_dsn_prefers_cli_option(monkeypatch):
    monkeypatch.setenv("POKER_TEST_DSN", "postgresql://env-primary")
    monkeypatch.setenv("POSTGRES_TEST_DSN", "postgresql://env-secondary")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env-database-url")

    config = DummyConfig(**{"--postgres-dsn": "postgresql://cli-override"})

    assert conftest._postgres_test_dsn(config) == "postgresql://cli-override"


def test_postgres_test_dsn_falls_back_through_env_vars(monkeypatch):
    monkeypatch.delenv("POKER_TEST_DSN", raising=False)
    monkeypatch.setenv("POSTGRES_TEST_DSN", "postgresql://env-secondary")
    monkeypatch.setenv("DATABASE_URL", "postgresql://env-database-url")

    config = DummyConfig(**{"--postgres-dsn": None})

    assert conftest._postgres_test_dsn(config) == "postgresql://env-secondary"


def test_postgres_tests_explicitly_enabled_reads_cli_and_env(monkeypatch):
    config = DummyConfig(**{"--run-postgres": False})
    monkeypatch.setenv("POKER_RUN_POSTGRES_TESTS", "yes")

    assert conftest._postgres_tests_explicitly_enabled(config) is True
    assert conftest._postgres_tests_disabled(config) is False

    config = DummyConfig(**{"--run-postgres": False, "--no-postgres": True})
    assert conftest._postgres_tests_disabled(config) is True
