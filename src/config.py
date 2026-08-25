"""Config loader — Phase 0.1

Resolution order: env var > config.local.json > config.json (legacy compat) > config.example.json.
Env vars expand inside JSON values: ${VAR} / ${VAR:-default}.

No hard-coded secrets. All credentials come from env or config.local.json (gitignored).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Map JSON leaf paths that must be overridable by env
_ENV_OVERRIDES = {
    "database.dsn": "POKER_DB_DSN",
    "database.mode": "POKER_DB_MODE",
    "database.observation_persistence_path": "POKER_OBSERVATION_STORE_PATH",
    # auto_annotator providers — index 0..n
    # We expand generically below
}

_CANDIDATE_CONFIGS = [
    ROOT / "config.local.json",
    ROOT / "config.json",
    ROOT / "config.example.json",
]


def _expand_env_placeholders(value: str) -> str:
    def repl(m: re.Match) -> str:
        var, default = m.group(1), m.group(2)
        env_val = os.getenv(var)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        return m.group(0)  # leave unresolved placeholder as-is

    return _ENV_PATTERN.sub(repl, value)


def _deep_expand(obj):
    if isinstance(obj, str):
        return _expand_env_placeholders(obj)
    if isinstance(obj, dict):
        return {k: _deep_expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_expand(v) for v in obj]
    return obj


def _apply_env_overrides(cfg: dict) -> dict:
    # Top-level env overrides
    dsn = os.getenv("POKER_DB_DSN")
    if dsn:
        cfg.setdefault("database", {})["dsn"] = dsn

    mode = os.getenv("POKER_DB_MODE")
    if mode:
        cfg.setdefault("database", {})["mode"] = mode

    gto_url = os.getenv("POKER_GTO_SERVER_URL")
    if gto_url:
        # not stored in config.json today, but keep for completeness
        cfg["gto_server_url"] = gto_url

    openai_key = os.getenv("OPENAI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    if openai_key or groq_key:
        providers = (cfg.get("auto_annotator") or {}).get("providers") or []
        for p in providers:
            base = (p.get("base_url") or "").lower()
            if openai_key and "api.openai.com" in base:
                p["api_key"] = openai_key
            if groq_key and "api.groq.com" in base:
                p["api_key"] = groq_key
            # local annotator key
            local_key = os.getenv("POKER_AUTO_ANNOTATOR_API_KEY")
            if local_key and "127.0.0.1" in base:
                p["api_key"] = local_key

    return cfg


def _load_json_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return None


def load_config(config_path: str | os.PathLike | None = None) -> dict:
    """Load merged config respecting env > local > json > example.

    If config_path is explicitly provided, that file is used as base
    (still with env expansion and overrides).
    """
    if config_path is not None:
        explicit = Path(config_path)
        if not explicit.is_absolute():
            explicit = (ROOT / explicit).resolve()
        base = _load_json_file(explicit) or {}
        base = _deep_expand(base)
        return _apply_env_overrides(base)

    # Env-forced config path
    env_path = os.getenv("POKER_RUNTIME_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        data = _load_json_file(p)
        if data is not None:
            return _apply_env_overrides(_deep_expand(data))

    # Candidate cascade: local > json > example
    merged: dict | None = None
    for candidate in _CANDIDATE_CONFIGS:
        data = _load_json_file(candidate)
        if data is not None:
            merged = _deep_expand(data)
            break

    if merged is None:
        merged = {}

    return _apply_env_overrides(merged)


def get_dsn(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return str((cfg.get("database") or {}).get("dsn") or os.getenv("POKER_DB_DSN") or "")
