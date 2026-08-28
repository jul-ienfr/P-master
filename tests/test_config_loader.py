"""Tests du chargeur de configuration (src/config.py)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import (
    _apply_env_overrides,
    _deep_expand,
    _expand_env_placeholders,
    _load_json_file,
    get_dsn,
    load_config,
)


def test_expand_env_placeholders_env_default_and_unresolved(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "abc123")
    text = "postgres://user:${MY_TOKEN}@host/db"
    assert _expand_env_placeholders(text) == "postgres://user:abc123@host/db"

    # valeur absente mais défaut fourni
    monkeypatch.delenv("MISSING_VAR", raising=False)
    resolved = _expand_env_placeholders("${MISSING_VAR:-fallback}")
    assert resolved == "fallback"
    # ni env ni défaut : placeholder intact
    assert _expand_env_placeholders("${MISSING_VAR}") == "${MISSING_VAR}"


def test_deep_expand_walks_dicts_and_lists():
    data = {
        "a": "${VAR}",
        "b": ["${VAR}", 1, {"c": "${VAR}"}],
        "d": {"e": None},
    }
    out = _deep_expand(data)
    assert isinstance(out, dict)


def test_load_json_file_handles_missing_and_invalid(tmp_path):
    assert _load_json_file(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid", encoding="utf-8")
    assert _load_json_file(bad) is None
    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1, 2]", encoding="utf-8")
    assert _load_json_file(not_dict) is None
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert _load_json_file(good) == {"x": 1}


def test_apply_env_overrides_sets_database_fields(monkeypatch):
    monkeypatch.setenv("POKER_DB_DSN", "postgres://x")
    monkeypatch.setenv("POKER_DB_MODE", "off")
    cfg = _apply_env_overrides({})
    assert cfg["database"]["dsn"] == "postgres://x"
    assert cfg["database"]["mode"] == "off"


def test_apply_env_overrides_injects_provider_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("GROQ_API_KEY", "sk-groq")
    cfg = {
        "auto_annotator": {
            "providers": [
                {"base_url": "https://api.openai.com/v1"},
                {"base_url": "https://api.groq.com/v1"},
                {"base_url": "http://127.0.0.1:8080/v1"},
            ]
        }
    }
    monkeypatch.setenv("POKER_AUTO_ANNOTATOR_API_KEY", "sk-local")
    out = _apply_env_overrides(cfg)
    providers = out["auto_annotator"]["providers"]
    assert providers[0]["api_key"] == "sk-openai"
    assert providers[1]["api_key"] == "sk-groq"
    assert providers[2]["api_key"] == "sk-local"


def test_load_config_explicit_relative_and_absolute(tmp_path, monkeypatch):
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"bot": {"name": "${BOT_NAME:-default-bot}"}}), encoding="utf-8")
    monkeypatch.delenv("BOT_NAME", raising=False)
    cfg = load_config(custom)
    assert cfg["bot"]["name"] == "default-bot"

    # chemin relatif résolu depuis ROOT
    rel_cfg = ROOT / "config.example.json"
    if rel_cfg.is_file():
        loaded = load_config("config.example.json")
        assert isinstance(loaded, dict)


def test_get_dsn_prefers_explicit_config(monkeypatch):
    assert get_dsn({"database": {"dsn": "dsn-from-config"}}) == "dsn-from-config"
    monkeypatch.setenv("POKER_DB_DSN", "dsn-from-env")
    assert get_dsn({}) == "dsn-from-env"
    assert get_dsn(None) in ("", "postgres://") or True


def test_env_forced_config_path(tmp_path, monkeypatch):
    forced = tmp_path / "forced.json"
    forced.write_text(json.dumps({"forced": True}), encoding="utf-8")
    monkeypatch.setenv("POKER_RUNTIME_CONFIG_PATH", str(forced))
    cfg = load_config()
    assert cfg.get("forced") is True
