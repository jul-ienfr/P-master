import asyncio
import logging
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Debug logging — snapshot/restore autour de chaque test pour éviter
# que setup_debug_logging() (idempotent) pollue les tests pytest.
@pytest.fixture(autouse=True)
def _restore_debug_logging_state():
    import src.runtime.debug as _dbg  # noqa: WPS433

    root = logging.getLogger()
    app_logger = logging.getLogger("SuperBot2026")
    saved_root_level = root.level
    saved_app_level = app_logger.level
    saved_handlers = list(root.handlers)
    # Mieux: sauver les filters de chaque handler au setup et les restaurer au teardown
    saved_handler_filters: dict[int, list] = {id(h): list(h.filters) for h in saved_handlers}
    saved_root_filters = list(root.filters)
    saved_cfg = _dbg._already_configured  # type: ignore[attr-defined]
    saved_settings = _dbg._applied_settings  # type: ignore[attr-defined]
    saved_handler = _dbg._debug_file_handler  # type: ignore[attr-defined]
    saved_filter = _dbg._debug_filter  # type: ignore[attr-defined]
    saved_throttle: dict = dict(_dbg._throttle_state or {})  # type: ignore[attr-defined]
    try:
        yield
    finally:
        # Fix: retirer le DebugContextFilter collé au StreamHandler console (h.addFilter)
        # Avant root.handlers[:] = saved_handlers, purger le filtre sur les handlers conservés
        live_filter = _dbg._debug_filter  # type: ignore[attr-defined]
        # Au minimum: pour chaque h dans saved_handlers, si filtre présent le retirer
        for h in saved_handlers:
            for f in (live_filter, saved_filter):
                if f is not None:
                    try:
                        if f in h.filters:
                            h.removeFilter(f)
                    except Exception:
                        pass
        # Purger aussi le live_filter sur tout handler live (y compris ceux ajoutés par le test)
        if live_filter is not None:
            for h in list(root.handlers):
                try:
                    if live_filter in h.filters:
                        h.removeFilter(live_filter)
                except Exception:
                    pass
            try:
                if live_filter in root.filters:
                    root.removeFilter(live_filter)
            except Exception:
                pass
        # Retirer handlers ajoutés par le test
        for h in list(root.handlers):
            if h not in saved_handlers:
                try:
                    root.removeHandler(h)
                    h.close()
                except Exception:
                    pass
        # Restaurer les filters exacts de chaque handler conservé
        for h in saved_handlers:
            try:
                for f in list(h.filters):
                    try:
                        h.removeFilter(f)
                    except Exception:
                        pass
                for f in saved_handler_filters.get(id(h), []):
                    try:
                        if f not in h.filters:
                            h.addFilter(f)
                    except Exception:
                        pass
            except Exception:
                pass
        # Restaurer les filters du root
        try:
            for f in list(root.filters):
                try:
                    root.removeFilter(f)
                except Exception:
                    pass
            for f in saved_root_filters:
                try:
                    if f not in root.filters:
                        root.addFilter(f)
                except Exception:
                    pass
        except Exception:
            pass
        # Restaure les listes/niveaux exactement
        root.handlers[:] = saved_handlers
        root.setLevel(saved_root_level)
        app_logger.setLevel(saved_app_level)
        _dbg._already_configured = saved_cfg  # type: ignore[attr-defined]
        _dbg._applied_settings = saved_settings  # type: ignore[attr-defined]
        _dbg._debug_file_handler = saved_handler  # type: ignore[attr-defined]
        _dbg._debug_filter = saved_filter  # type: ignore[attr-defined]
        _dbg._throttle_state.clear()  # type: ignore[attr-defined]
        _dbg._throttle_state.update(saved_throttle)  # type: ignore[attr-defined]


from src.data.database import DatabaseManager

DEFAULT_TEST_DSN = (
    os.getenv("POKER_TEST_DSN")
    or os.getenv("POKER_DB_DSN")
    or "postgresql://poker_bot:__CHANGE_ME__@localhost:5432/poker_db"
)


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
        pytest.skip(
            "PostgreSQL integration tests disabled via --no-postgres or POKER_RUN_POSTGRES_TESTS=0."
        )

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
            reason = f"{reason}. Check --postgres-dsn or set POKER_TEST_DSN/POSTGRES_TEST_DSN/DATABASE_URL."
        pytest.skip(reason)

    try:
        yield manager
    finally:
        asyncio.run(manager.close())
