"""Tests pour src/runtime/debug.py — probe, coerce, settings, setup, redaction, throttle."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.runtime import debug as dbg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# _parse_bool_flag matrice (repris de session.py)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("1", True),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("  YeS  ", True),
        ("", None),
        ("maybe", None),
        (None, None),
    ],
)
def test_parse_bool_flag_matrix(value, expected):
    assert dbg._parse_bool_flag(value) is expected


# ---------------------------------------------------------------------------
# _coerce_debug_cfg
# ---------------------------------------------------------------------------

def test_coerce_bool_true():
    cfg: dict = {"debug": True}
    out = dbg._coerce_debug_cfg(cfg)
    assert out == {"enabled": True}
    assert cfg["debug"] == {"enabled": True}


def test_coerce_bool_false():
    cfg: dict = {"debug": False}
    out = dbg._coerce_debug_cfg(cfg)
    assert out == {"enabled": False}


def test_coerce_none():
    cfg: dict = {}
    out = dbg._coerce_debug_cfg(cfg)
    assert out == {}


def test_coerce_invalid_type():
    cfg: dict = {"debug": "weird"}
    out = dbg._coerce_debug_cfg(cfg)
    assert out == {}


def test_coerce_dict_passthrough():
    cfg: dict = {"debug": {"enabled": True, "file_level": "DEBUG"}}
    out = dbg._coerce_debug_cfg(cfg)
    assert out["enabled"] is True


# ---------------------------------------------------------------------------
# probe_debug_enabled — cascade
# ---------------------------------------------------------------------------

def test_probe_env_priority(tmp_path: Path):
    # Même si fichier dit True, env False prime.
    cfg_path = tmp_path / "config.json"
    _write_json(cfg_path, {"debug": {"enabled": True}})
    with patch.dict(os.environ, {"POKER_DEBUG": "0", "POKER_RUNTIME_CONFIG_PATH": str(cfg_path)}):
        assert dbg.probe_debug_enabled() is False
    with patch.dict(os.environ, {"POKER_DEBUG": "1"}):
        assert dbg.probe_debug_enabled() is True


def test_probe_runtime_config_path_cascade(tmp_path: Path):
    env_cfg = tmp_path / "env_cfg.json"
    _write_json(env_cfg, {"debug": True})
    # Place ROOT candidates ailleurs pour s'assurer que env_path est lu
    with patch.dict(os.environ, {"POKER_RUNTIME_CONFIG_PATH": str(env_cfg)}, clear=False):
        # Supprime POKER_DEBUG pour forcer lecture fichier
        env = dict(os.environ)
        env.pop("POKER_DEBUG", None)
        with patch.dict(os.environ, env, clear=True):
            # Monkeypatch ROOT temporairement non nécessaire — le fichier env_path suffit
            assert dbg.probe_debug_enabled() is True


def test_probe_bool_and_dict(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    _write_json(tmp_path / "config.json", {"debug": True})
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG", "POKER_RUNTIME_CONFIG_PATH"}}
    with patch.dict(os.environ, env, clear=True):
        assert dbg.probe_debug_enabled() is True
    _write_json(tmp_path / "config.json", {"debug": {"enabled": False}})
    with patch.dict(os.environ, env, clear=True):
        assert dbg.probe_debug_enabled() is False


def test_probe_missing_returns_false(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG", "POKER_RUNTIME_CONFIG_PATH"}}
    with patch.dict(os.environ, env, clear=True):
        assert dbg.probe_debug_enabled() is False


def test_probe_corrupted_json(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text("{ not json", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG", "POKER_RUNTIME_CONFIG_PATH"}}
    with patch.dict(os.environ, env, clear=True):
        assert dbg.probe_debug_enabled() is False


# ---------------------------------------------------------------------------
# resolve_debug_settings
# ---------------------------------------------------------------------------

def test_resolve_defaults_off():
    s = dbg.resolve_debug_settings({})
    assert s.enabled is False
    assert s.log_file == Path("log/debug.log")


def test_resolve_enabled_on():
    s = dbg.resolve_debug_settings({"debug": {"enabled": True}})
    assert s.enabled is True
    assert s.file_level == logging.DEBUG


def test_resolve_bool_enabled():
    s = dbg.resolve_debug_settings({"debug": True})
    assert s.enabled is True


def test_resolve_string_levels():
    s = dbg.resolve_debug_settings({"debug": {"enabled": True, "file_level": "INFO", "console_level": "WARNING"}})
    assert s.file_level == logging.INFO
    assert s.console_level == logging.WARNING


# ---------------------------------------------------------------------------
# setup_debug_logging — idempotence, toggle, handlers
# ---------------------------------------------------------------------------

def test_setup_off_no_handler(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    result = dbg.setup_debug_logging({"debug": {"enabled": False}})
    assert result is False
    assert dbg._debug_file_handler is None


def test_setup_on_creates_handler(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    result = dbg.setup_debug_logging({"debug": {"enabled": True, "log_file": str(tmp_path / "log/debug.log")}})
    assert result is True
    assert dbg._debug_file_handler is not None
    # Fichier créé (RotatingFileHandler crée le fichier au premier emit ou à l'open — selon impl)
    # On vérifie au moins que le parent existe
    assert (tmp_path / "log").is_dir()


def test_setup_idempotence_same_settings(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    cfg = {"debug": {"enabled": True, "log_file": str(tmp_path / "log/debug.log")}}
    dbg.setup_debug_logging(cfg)
    handler_first = dbg._debug_file_handler
    dbg.setup_debug_logging(cfg)
    assert dbg._debug_file_handler is handler_first


def test_setup_toggle_off_removes_handler(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    dbg.setup_debug_logging({"debug": {"enabled": True, "log_file": str(tmp_path / "log/debug.log")}})
    assert dbg._debug_file_handler is not None
    dbg.setup_debug_logging({"debug": {"enabled": False}})
    assert dbg._debug_file_handler is None
    assert logging.getLogger("SuperBot2026").level == logging.INFO


def test_setup_rust_log_setdefault(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    env = {k: v for k, v in os.environ.items() if k not in {"RUST_LOG", "POKER_RUST_LOG"}}
    with patch.dict(os.environ, env, clear=True):
        dbg.setup_debug_logging({"debug": {"enabled": True, "rust_log": "trace", "log_file": str(tmp_path / "log/debug.log")}})
        assert os.getenv("RUST_LOG") == "trace"
    # Ne doit pas écraser RUST_LOG déjà set
    with patch.dict(os.environ, {"RUST_LOG": "info"}, clear=False):
        dbg._reset_debug_state()
        dbg.setup_debug_logging({"debug": {"enabled": True, "rust_log": "trace", "log_file": str(tmp_path / "log2/debug.log")}})
        assert os.getenv("RUST_LOG") == "info"


def test_setup_traversal_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    # Chemin hors ROOT doit fallback
    result = dbg.setup_debug_logging({"debug": {"enabled": True, "log_file": "/tmp/evil.log"}})
    assert result is True
    assert dbg._debug_file_handler is not None
    # Handler pointe vers fallback, pas /tmp/evil.log
    handler_path = getattr(dbg._debug_file_handler, "baseFilename", "")
    assert "/tmp/evil.log" not in handler_path


def test_setup_oserror_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    dbg._reset_debug_state()
    with patch("logging.handlers.RotatingFileHandler", side_effect=OSError("read-only")):
        result = dbg.setup_debug_logging({"debug": {"enabled": True, "log_file": str(tmp_path / "log/debug.log")}})
        assert result is True  # fallback console-only
        assert dbg._debug_file_handler is None


# ---------------------------------------------------------------------------
# Filter / Formatter
# ---------------------------------------------------------------------------

def test_debug_context_filter_injection():
    filt = dbg.DebugContextFilter()
    record = logging.LogRecord("test", logging.INFO, "f.py", 1, "msg", (), None)
    # Par défaut spot_id = "-"
    filt.filter(record)
    assert getattr(record, "spot_id", None) == "-"
    dbg.set_debug_context(spot_id="S123")
    record2 = logging.LogRecord("test", logging.INFO, "f.py", 1, "msg", (), None)
    filt.filter(record2)
    assert record2.spot_id == "S123"  # type: ignore[attr-defined]
    dbg.set_debug_context(spot_id="-")


def test_formatter_defaults_no_keyerror():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(spot_id)s] (%(filename)s:%(lineno)d): %(message)s",
        defaults={"spot_id": "-", "table_id": "-"},
    )
    record = logging.LogRecord("SuperBot2026", logging.DEBUG, "foo.py", 10, "hello", (), None)
    # Sans filtre, defaults doit éviter KeyError
    out = fmt.format(record)
    assert "hello" in out


# ---------------------------------------------------------------------------
# Redaction profonde
# ---------------------------------------------------------------------------

def test_redact_shallow_key():
    payload = {"api_key": "secret123", "user": "bob"}
    out = dbg._redact_cfg(payload)
    assert out["api_key"] == "***"
    assert out["user"] == "bob"


def test_redact_nested_dict():
    payload = {"database": {"dsn": "postgres://user:pass@host/db"}, "ok": 1}
    out = dbg._redact_cfg(payload)
    assert out["database"]["dsn"] == "***"


def test_redact_list_of_dicts():
    payload = {"providers": [{"api_key": "k1"}, {"api_key": "k2"}]}
    out = dbg._redact_cfg(payload)
    assert out["providers"][0]["api_key"] == "***"
    assert out["providers"][1]["api_key"] == "***"


def test_redact_url_token():
    payload = {"base_url": "https://api.example.com/v1?token=SECRET123&x=1"}
    out = dbg._redact_cfg(payload)
    assert "SECRET123" not in out["base_url"]
    assert "token=***" in out["base_url"]


def test_redact_url_credentials():
    payload = {"url": "https://user:pass@example.com/path"}
    out = dbg._redact_cfg(payload)
    assert "user:pass" not in out["url"]
    assert "://***@" in out["url"]


# ---------------------------------------------------------------------------
# to_thread_with_context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_to_thread_with_context_propagates():
    dbg.set_debug_context(spot_id="CTX42")
    filt = dbg.DebugContextFilter()

    def check_context():
        rec = logging.LogRecord("test", logging.INFO, "f.py", 1, "msg", (), None)
        filt.filter(rec)
        return getattr(rec, "spot_id", None)

    result = await dbg.to_thread_with_context(check_context)
    assert result == "CTX42"
    dbg.set_debug_context(spot_id="-")


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------

def test_probe_runtime_path_relative(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    rel = "rel_cfg.json"
    _write_json(tmp_path / rel, {"debug": True})
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG", "POKER_RUNTIME_CONFIG_PATH"}}
    with patch.dict(os.environ, {**env, "POKER_RUNTIME_CONFIG_PATH": rel}, clear=True):
        assert dbg.probe_debug_enabled() is True


def test_probe_runtime_path_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    _write_json(tmp_path / "config.json", {"debug": True})
    missing = str(tmp_path / "nope.json")
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG"}}
    base = {k: v for k, v in env.items() if k != "POKER_RUNTIME_CONFIG_PATH"}
    with patch.dict(os.environ, {**base, "POKER_RUNTIME_CONFIG_PATH": missing}, clear=True):
        assert dbg.probe_debug_enabled() is True


def test_probe_runtime_path_corrupted(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    _write_json(tmp_path / "config.json", {"debug": True})
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG"}}
    base = {k: v for k, v in env.items() if k != "POKER_RUNTIME_CONFIG_PATH"}
    with patch.dict(os.environ, {**base, "POKER_RUNTIME_CONFIG_PATH": str(bad)}, clear=True):
        assert dbg.probe_debug_enabled() is True


def test_probe_runtime_config_path_relative(tmp_path: Path, monkeypatch):
    """POKER_RUNTIME_CONFIG_PATH='relative.json' résolu via (ROOT/rel).resolve()."""
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    _write_json(tmp_path / "relative.json", {"debug": True})
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG", "POKER_RUNTIME_CONFIG_PATH"}}
    with patch.dict(os.environ, {**env, "POKER_RUNTIME_CONFIG_PATH": "relative.json"}, clear=True):
        assert dbg.probe_debug_enabled() is True
    # Valeur False depuis le fichier relatif doit être retournée
    _write_json(tmp_path / "relative.json", {"debug": False})
    with patch.dict(os.environ, {**env, "POKER_RUNTIME_CONFIG_PATH": "relative.json"}, clear=True):
        assert dbg.probe_debug_enabled() is False


def test_probe_env_path_missing_fallback(tmp_path: Path, monkeypatch):
    """env_path vers fichier inexistant -> fallback sur candidat suivant."""
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    _write_json(tmp_path / "config.json", {"debug": True})
    missing = "/nonexistent.json"
    # S'assurer que le fichier n'existe pas (sur Windows /nonexistent.json -> C:/nonexistent.json)
    assert not Path(missing).is_file()
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG"}}
    base = {k: v for k, v in env.items() if k != "POKER_RUNTIME_CONFIG_PATH"}
    with patch.dict(os.environ, {**base, "POKER_RUNTIME_CONFIG_PATH": missing}, clear=True):
        assert dbg.probe_debug_enabled() is True  # fallback vers config.json
    # Sans fallback valide -> False
    (tmp_path / "config.json").unlink()
    with patch.dict(os.environ, {**base, "POKER_RUNTIME_CONFIG_PATH": missing}, clear=True):
        assert dbg.probe_debug_enabled() is False


def test_probe_env_path_corrupted_continues(tmp_path: Path, monkeypatch):
    """env_path vers JSON corrompu -> continue cascade au lieu de crasher."""
    monkeypatch.setattr(dbg, "ROOT", tmp_path)
    bad = tmp_path / "bad_env.json"
    bad.write_text("{ not json", encoding="utf-8")
    _write_json(tmp_path / "config.json", {"debug": True})
    env = {k: v for k, v in os.environ.items() if k not in {"POKER_DEBUG"}}
    base = {k: v for k, v in env.items() if k != "POKER_RUNTIME_CONFIG_PATH"}
    with patch.dict(os.environ, {**base, "POKER_RUNTIME_CONFIG_PATH": str(bad)}, clear=True):
        # Ne doit pas lever, doit continuer vers config.json
        assert dbg.probe_debug_enabled() is True
    # Sans fallback valide -> False (pas de crash)
    (tmp_path / "config.json").unlink()
    with patch.dict(os.environ, {**base, "POKER_RUNTIME_CONFIG_PATH": str(bad)}, clear=True):
        assert dbg.probe_debug_enabled() is False


def test_should_throttle():
    dbg._throttle_state.clear()
    assert dbg._should_throttle("k:test", interval_s=10.0) is True
    assert dbg._should_throttle("k:test", interval_s=10.0) is False
    # Autre clé non affectée
    assert dbg._should_throttle("k:other", interval_s=10.0) is True
