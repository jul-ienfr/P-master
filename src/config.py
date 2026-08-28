"""Config loader — Phase 0.1

Resolution order: env var > config.local.json > config.json (legacy compat) > config.example.json.
Env vars expand inside JSON values: ${VAR} / ${VAR:-default}.

No hard-coded secrets. All credentials come from env or config.local.json (gitignored).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

# Robustesse binaire freeze (PyInstaller/Nuitka) : __file__ peut exister
# dans _MEIPASS sans lever NameError, parents[1] pointe alors hors bundle.
if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        ROOT = Path(_meipass).parent
    else:
        ROOT = Path(sys.executable).parent
else:
    try:
        ROOT = Path(__file__).resolve().parents[1]
    except (NameError, IndexError):
        ROOT = Path(sys.executable).parent

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Map JSON leaf paths that must be overridable by env.
# Consomme par _apply_env_overrides via _set_nested (boucle generique).
_ENV_OVERRIDES = {
    "database.dsn": "POKER_DB_DSN",
    "database.mode": "POKER_DB_MODE",
    "database.observation_persistence_path": "POKER_OBSERVATION_STORE_PATH",
}


def _set_nested(cfg: dict, dotted: str, value: str) -> None:
    parts = dotted.split(".")
    cur = cfg
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
        if not isinstance(cur, dict):
            return
    cur[parts[-1]] = value


def _warn_change_me(obj) -> None:
    """Log warning si une valeur contient encore __CHANGE_ME__ apres expansion."""
    logger = logging.getLogger("SuperBot2026")
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            if "__CHANGE_ME__" in cur:
                logger.warning("config placeholder non resolu: %r", cur)
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


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


def _coerce_debug_cfg(cfg: dict) -> dict:
    raw = cfg.get("debug")
    if isinstance(raw, bool):
        cfg["debug"] = {"enabled": raw}
    elif isinstance(raw, str):
        parsed = _parse_bool_env(raw)
        if parsed is not None:
            cfg["debug"] = {"enabled": parsed}
        else:
            cfg["debug"] = {}
    elif isinstance(raw, (int, float)):
        cfg["debug"] = {"enabled": bool(raw)}
    elif raw is None:
        cfg["debug"] = {}
    elif not isinstance(raw, dict):
        cfg["debug"] = {}
    return cfg["debug"]


def _parse_bool_env(value: str | None) -> bool | None:
    if value is None:
        return None
    s = value.strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return None


def _apply_env_overrides(cfg: dict) -> dict:
    _coerce_debug_cfg(cfg)
    # Debug overrides (env > config)
    dbg = cfg["debug"]
    v = _parse_bool_env(os.getenv("POKER_DEBUG"))
    if v is not None:
        dbg["enabled"] = v
    fl = os.getenv("POKER_DEBUG_FILE_LEVEL")
    if fl:
        dbg["file_level"] = fl.strip()
    cl = os.getenv("POKER_DEBUG_CONSOLE_LEVEL")
    if cl:
        dbg["console_level"] = cl.strip()
    lf = os.getenv("POKER_DEBUG_LOG_FILE")
    if lf:
        dbg["log_file"] = lf.strip()
    prl = os.getenv("POKER_RUST_LOG")
    if prl:
        dbg["rust_log"] = prl.strip()

    # Generic env overrides via _ENV_OVERRIDES (env > config)
    for dotted, env_name in _ENV_OVERRIDES.items():
        val = os.getenv(env_name)
        if val and val.strip():
            _set_nested(cfg, dotted, val.strip())

    gto_url = os.getenv("POKER_GTO_SERVER_URL")
    if gto_url:
        # not stored in config.json today, but keep for completeness
        cfg["gto_server_url"] = gto_url

    # POKER_YOLO_MODEL — override modèle YOLO (documenté .env.example)
    yolo_model = os.getenv("POKER_YOLO_MODEL")
    if yolo_model and yolo_model.strip():
        cfg.setdefault("yolo", {})["model_path"] = yolo_model.strip()

    yolo_conf = os.getenv("POKER_YOLO_CONFIDENCE_THRESHOLD")
    if yolo_conf and yolo_conf.strip():
        try:
            cfg.setdefault("yolo", {})["confidence_threshold"] = float(yolo_conf.strip())
        except ValueError:
            pass

    # POKER_VRAM_CAP — expose via hardware.vram_cap_override (hardware module own parsing)
    vram_cap = os.getenv("POKER_VRAM_CAP")
    if vram_cap and vram_cap.strip():
        cfg.setdefault("hardware", {})["vram_cap_override"] = vram_cap.strip()

    # POKER_WINDOW_KEYWORDS — override window_title_keywords (documenté .env.example, sinon .env mort)
    window_kw = os.getenv("POKER_WINDOW_KEYWORDS")
    if window_kw and window_kw.strip():
        cfg.setdefault("bot", {})["window_title_keywords"] = window_kw.strip()

    v = _parse_bool_env(os.getenv("POKER_ENABLE_TIMESFM"))
    if v is not None:
        cfg.setdefault("timesfm", {})["enabled"] = v

    # POKER_MULTIWAY_MAX_PLAYERS — wire env into solver.multiway_max_players (Rust lit aussi l'env directement)
    raw_multiway = os.getenv("POKER_MULTIWAY_MAX_PLAYERS")
    if raw_multiway and raw_multiway.strip():
        try:
            cfg.setdefault("solver", {})["multiway_max_players"] = int(raw_multiway.strip())
        except ValueError:
            pass

    openai_key = os.getenv("OPENAI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    local_key = os.getenv("POKER_AUTO_ANNOTATOR_API_KEY")
    base_url_override = os.getenv("POKER_AUTO_ANNOTATOR_BASE_URL")
    # Auto-annotator providers: three independent keys, no shared guard
    # so local_key alone still applies. Supports 127.0.0.1 and localhost.
    if openai_key or groq_key or local_key or base_url_override:
        providers = (cfg.get("auto_annotator") or {}).get("providers") or []
        for p in providers:
            base = (p.get("base_url") or "").lower()
            if openai_key and "api.openai.com" in base:
                p["api_key"] = openai_key
            if groq_key and "api.groq.com" in base:
                p["api_key"] = groq_key
            if local_key and ("127.0.0.1" in base or "localhost" in base):
                p["api_key"] = local_key
            if base_url_override and base_url_override.strip():
                if "127.0.0.1" in base or "localhost" in base:
                    p["base_url"] = base_url_override.strip()

    _warn_change_me(cfg)
    return cfg


def _load_json_file(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None  # type: ignore[return-value]  # noqa: RET503 — non-dict blocks cascade
    except Exception:
        return None


def load_config(config_path: str | os.PathLike | None = None) -> dict:
    """Load merged config respecting env > local > json > example.

    If config_path is explicitly provided, that file is used as base
    (still with env expansion and overrides).
    """
    if config_path is not None:
        # Explicit config_path has priority over env-forced path
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
