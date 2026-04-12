import asyncio
import conftest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.data.database import DatabaseManager, _classify_player_style, _safe_rate


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
