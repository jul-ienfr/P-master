"""Tests Phase 3.1 — migrations versionnées et index hot-paths."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.data.database import DatabaseManager


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, applied_migrations=None):
        self.applied = list(applied_migrations or [])
        self.executed: list[str] = []
        self.inserted: list[str] = []

    async def execute(self, sql, *args):
        self.executed.append(" ".join(sql.split()))
        if "INSERT INTO schema_migrations" in sql and args:
            self.inserted.append(args[0])

    async def fetch(self, sql, *args):
        self.executed.append(" ".join(sql.split()))
        return [{"migration_id": mid} for mid in self.applied]

    def transaction(self):
        return FakeTransaction()


def _run(coroutine):
    return asyncio.run(coroutine)


def _manager():
    return object.__new__(DatabaseManager)


def test_fresh_database_applies_all_migrations():
    conn = FakeConn()
    manager = _manager()

    _run(manager._apply_migrations(conn))

    assert conn.inserted == [m[0] for m in manager._MIGRATIONS]
    joined = "\n".join(conn.executed)
    assert "idx_players_last_seen" in joined
    assert "idx_hands_history_timestamp" in joined
    assert "idx_hands_history_table_name" in joined
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in joined


def test_already_applied_migrations_are_skipped():
    manager = _manager()
    conn = FakeConn(applied_migrations=[m[0] for m in manager._MIGRATIONS])

    _run(manager._apply_migrations(conn))

    assert conn.inserted == []
    migration_sql = [
        s for s in conn.executed if "CREATE INDEX IF NOT EXISTS" in s or "INSERT INTO schema_migrations" in s
    ]
    assert migration_sql == []


def test_partial_application_is_idempotent():
    manager = _manager()
    first_migration = manager._MIGRATIONS[0][0]
    conn = FakeConn(applied_migrations=[first_migration])

    _run(manager._apply_migrations(conn))

    assert conn.inserted == [m[0] for m in manager._MIGRATIONS if m[0] != first_migration]


def test_migration_table_created_before_select():
    """Sur une base vierge, le SELECT ne doit pas précéder la CREATE TABLE."""
    conn = FakeConn()
    manager = _manager()

    _run(manager._apply_migrations(conn))

    executed_normalized = [" ".join(s.split()) for s in conn.executed]
    create_idx = next(
        i for i, s in enumerate(executed_normalized) if "CREATE TABLE IF NOT EXISTS schema_migrations" in s
    )
    select_idx = next(i for i, s in enumerate(executed_normalized) if "SELECT migration_id" in s)
    assert create_idx < select_idx
