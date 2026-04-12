import asyncio
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.data.database import DatabaseManager


DEFAULT_TEST_DSN = "postgresql://poker_bot:supersecretpassword@localhost:5432/poker_db"


def _env_flag(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower()


def pytest_addoption(parser):
    parser.addoption(
        "--run-postgres",
        action="store_true",
        default=False,
        help="Run PostgreSQL integration tests when the database is reachable.",
    )
    parser.addoption(
        "--postgres-dsn",
        action="store",
        default=None,
        help="Override the PostgreSQL DSN used by integration tests.",
    )
    parser.addoption(
        "--no-postgres",
        action="store_true",
        default=False,
        help="Force-skip PostgreSQL integration tests.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: integration tests that may require external services",
    )
    config.addinivalue_line(
        "markers",
        "postgres: PostgreSQL-backed tests that are skipped when the database is unavailable",
    )


def _postgres_tests_disabled(config) -> bool:
    if config.getoption("--no-postgres"):
        return True

    flag = _env_flag("POKER_RUN_POSTGRES_TESTS")
    return flag in {"0", "false", "no", "off"}


def _postgres_tests_explicitly_enabled(config) -> bool:
    return config.getoption("--run-postgres") or _env_flag("POKER_RUN_POSTGRES_TESTS") in {
        "1",
        "true",
        "yes",
        "on",
    }


def _postgres_test_dsn(config) -> str:
    return (
        config.getoption("--postgres-dsn")
        or os.getenv("POKER_TEST_DSN")
        or os.getenv("POSTGRES_TEST_DSN")
        or os.getenv("DATABASE_URL")
        or DEFAULT_TEST_DSN
    )


@pytest.fixture
def postgres_test_dsn(request):
    return _postgres_test_dsn(request.config)


@pytest.fixture
def postgres_database_manager(request):
    if _postgres_tests_disabled(request.config):
        pytest.skip("PostgreSQL integration tests disabled via --no-postgres or POKER_RUN_POSTGRES_TESTS=0.")

    manager = DatabaseManager(
        dsn=_postgres_test_dsn(request.config),
        mode="postgres",
    )

    try:
        asyncio.run(manager.connect())
    except Exception as exc:
        explicit_run = _postgres_tests_explicitly_enabled(request.config)
        reason = f"PostgreSQL unavailable for integration tests: {exc}"
        if explicit_run:
            reason = (
                f"{reason}. Check --postgres-dsn or set POKER_TEST_DSN/POSTGRES_TEST_DSN/DATABASE_URL."
            )
        pytest.skip(reason)

    try:
        yield manager
    finally:
        asyncio.run(manager.close())
