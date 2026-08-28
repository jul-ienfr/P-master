"""Module debug central — probe léger, settings, logging idempotent réversible."""

from __future__ import annotations

import asyncio
import contextvars
import copy
import json
import logging
import logging.handlers
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Root — robuste en python -m et binaire freeze (PyInstaller/Nuitka)
# En binaire freeze __file__ existe (pointe dans sys._MEIPASS) donc le
# try/except NameError ne se déclenche pas et parents[2] pointe hors bundle.
# On détecte d'abord le mode frozen / _MEIPASS.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass:
        ROOT = Path(_meipass).parent
    else:
        ROOT = Path(sys.executable).parent
else:
    try:
        ROOT = Path(__file__).resolve().parents[2]  # src/runtime/debug.py -> ROOT
    except (NameError, IndexError):
        ROOT = Path(sys.executable).parent

# ---------------------------------------------------------------------------
# Bool flag helper — inliné pour éviter import session.py (socket/uuid)
# ---------------------------------------------------------------------------

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _parse_bool_flag(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    return None


# ---------------------------------------------------------------------------
# Probe léger — cascade complète, I/O minimal
# ---------------------------------------------------------------------------

_CANDIDATE_RELATIVE = [
    Path("config.local.json"),
    Path("config.json"),
    Path("config.example.json"),
]


def _read_debug_enabled_from_file(path: Path) -> bool | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # Ne pas utiliser logging ici : probe s'exécute avant basicConfig,
        # le warning serait perdu sur lastResort. Throttle pour éviter spam.
        key = f"probe:corrupt:{path}"
        if _should_throttle(key, 60.0):
            print(f"probe: config illisible {path} — ignorée", file=sys.stderr)
        return None
    except Exception:
        return None
    raw = data.get("debug") if isinstance(data, dict) else None
    val = raw.get("enabled") if isinstance(raw, dict) else raw
    return _parse_bool_flag(val)


def probe_debug_enabled() -> bool:
    env = _parse_bool_flag(os.getenv("POKER_DEBUG"))
    if env is not None:
        return env
    candidates: list[Path] = []
    env_path = os.getenv("POKER_RUNTIME_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        candidates.append(p)
    for rel in _CANDIDATE_RELATIVE:
        p = (ROOT / rel).resolve()
        if p not in candidates:
            candidates.append(p)
    for p in candidates:
        if not p.is_file():
            continue
        flag = _read_debug_enabled_from_file(p)
        if flag is not None:
            return flag
    return False


# ---------------------------------------------------------------------------
# Coerce + DebugSettings
# ---------------------------------------------------------------------------

_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _coerce_debug_cfg(cfg: dict) -> dict:
    raw = cfg.get("debug")
    if isinstance(raw, bool):
        cfg["debug"] = {"enabled": raw}
    elif isinstance(raw, str):
        parsed = _parse_bool_flag(raw)
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


def _parse_level(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _LEVEL_MAP.get(value.strip().upper(), default)
    return default


@dataclass(frozen=True, eq=True)
class DebugSettings:
    enabled: bool = False
    file_level: int = logging.DEBUG
    console_level: int = logging.DEBUG
    log_file: Path = Path("log/debug.log")
    rust_log: str = "debug"


def resolve_debug_settings(cfg: dict | None = None) -> DebugSettings:
    if cfg is None:
        cfg = {}
    # Work on a shallow copy to allow coerce without mutating caller dict deeply,
    # but _coerce_debug_cfg mutates the dict — copy top-level.
    cfg_copy = dict(cfg)
    debug_cfg = _coerce_debug_cfg(cfg_copy)
    enabled = bool(_parse_bool_flag(debug_cfg.get("enabled")) or False)
    # Also accept truthy string/int via _parse_bool_flag already; bool cast above handles
    # Env overrides are already applied via _apply_env_overrides if cfg came from load_config.
    # For direct probe calls (cfg={"debug":{"enabled":True}}), this suffices.
    # Re-evaluate enabled through _parse_bool_flag to handle "1"/"yes" etc.
    parsed = _parse_bool_flag(debug_cfg.get("enabled"))
    if parsed is not None:
        enabled = parsed
    file_level = _parse_level(debug_cfg.get("file_level"), logging.DEBUG if enabled else logging.INFO)
    console_level = _parse_level(debug_cfg.get("console_level"), logging.DEBUG if enabled else logging.INFO)
    raw_log_file = debug_cfg.get("log_file", "log/debug.log")
    log_file = Path(str(raw_log_file)) if raw_log_file else Path("log/debug.log")
    rust_log = str(debug_cfg.get("rust_log", "debug") or "debug").strip() or "debug"
    return DebugSettings(
        enabled=enabled,
        file_level=file_level,
        console_level=console_level,
        log_file=log_file,
        rust_log=rust_log,
    )


# ---------------------------------------------------------------------------
# Context filter — correlation spot_id / table_id
# ---------------------------------------------------------------------------

_spot_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("spot_id", default="-")
_table_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("table_id", default="-")


class DebugContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        record.spot_id = _spot_id_var.get("-")  # type: ignore[attr-defined]
        record.table_id = _table_id_var.get("-")  # type: ignore[attr-defined]
        return True


def set_debug_context(*, spot_id: str | None = None, table_id: str | None = None) -> None:
    if spot_id is not None:
        _spot_id_var.set(spot_id)
    if table_id is not None:
        _table_id_var.set(table_id)


async def to_thread_with_context(func, /, *args, **kwargs):
    """asyncio.to_thread en propageant les contextvars (Python 3.10 compat)."""
    ctx = contextvars.copy_context()
    return await asyncio.to_thread(lambda: ctx.run(lambda: func(*args, **kwargs)))


# ---------------------------------------------------------------------------
# Redaction profonde
# ---------------------------------------------------------------------------

_REDACT_KEYS = {"api_key", "apikey", "dsn", "password", "passwd", "secret", "token", "authorization", "auth"}
_REDACT_URL_KEYS = {"base_url", "url"}

_TOKEN_RE = re.compile(r"(token=)[^&]+", re.IGNORECASE)
_CRED_RE = re.compile(r"://[^@]+@")


def _redact_cfg(obj):  # type: ignore[no-untyped-def]
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in _REDACT_KEYS:
                out[k] = "***"
            elif lk in _REDACT_URL_KEYS and isinstance(v, str) and ("token=" in v.lower() or "@" in v):
                cleaned = _TOKEN_RE.sub(r"\1***", v)
                cleaned = _CRED_RE.sub("://***@", cleaned)
                out[k] = cleaned
            else:
                out[k] = _redact_cfg(v)
        return out
    if isinstance(obj, list):
        return [_redact_cfg(x) for x in obj]
    return obj


# ---------------------------------------------------------------------------
# Throttle helper
# ---------------------------------------------------------------------------

_throttle_state: dict[str, float] = {}


def _should_throttle(key: str, interval_s: float = 1.0) -> bool:
    """Retourne True si le log doit être émis (intervalle écoulé), False sinon."""
    now = time.monotonic()
    last = _throttle_state.get(key, 0.0)
    if now - last >= interval_s:
        _throttle_state[key] = now
        return True
    return False


# Alias public pour les modules métier qui veulent importer depuis debug
should_throttle = _should_throttle
redact_cfg = _redact_cfg

# ---------------------------------------------------------------------------
# setup_debug_logging — idempotent réversible
# ---------------------------------------------------------------------------

_already_configured: bool = False
_applied_settings: DebugSettings | None = None
_debug_file_handler: logging.Handler | None = None
_debug_filter: DebugContextFilter | None = None
_original_rust_log: str | None = None
_rust_log_set_by_us: bool = False
_rust_log_value_set: str | None = None  # valeur posée par setdefault, pour éviter d'écraser un RUST_LOG injecté après coup


# Classe capturée avant tout mock (patch("logging.handlers.RotatingFileHandler")
# remplace logging.handlers.RotatingFileHandler par un MagicMock non-type)
_ROTATING_HANDLER_CLS = logging.handlers.RotatingFileHandler


def _is_console_handler(h: logging.Handler) -> bool:
    if not isinstance(h, logging.StreamHandler):
        return False
    # Utilise la référence capturée, pas logging.handlers.RotatingFileHandler (mocké)
    return not isinstance(h, _ROTATING_HANDLER_CLS)


def setup_debug_logging(cfg: dict | None = None) -> bool:
    global _already_configured, _applied_settings, _debug_file_handler, _debug_filter, _original_rust_log, _rust_log_set_by_us, _rust_log_value_set

    settings = resolve_debug_settings(cfg or {})

    # Normalise log_file : absolu via ROOT
    log_file: Path = settings.log_file
    if not log_file.is_absolute():
        log_file = (ROOT / log_file).resolve()
    # Garde-fou hors ROOT → fallback
    try:
        log_file.relative_to(ROOT.resolve())
    except ValueError:
        try:
            logging.getLogger("SuperBot2026").warning(
                "debug.log_file hors ROOT (%s) — fallback log/debug.log", log_file
            )
        except Exception:
            pass
        log_file = (ROOT / "log" / "debug.log").resolve()

    # Idempotence fine
    if _already_configured and _applied_settings == settings:
        return settings.enabled

    root = logging.getLogger()
    app_logger = logging.getLogger("SuperBot2026")

    # Retrait ancien handler debug si présent
    if _debug_file_handler is not None:
        try:
            root.removeHandler(_debug_file_handler)
        except Exception:
            pass
        if _debug_filter is not None:
            try:
                _debug_file_handler.removeFilter(_debug_filter)
            except Exception:
                pass
            try:
                root.removeFilter(_debug_filter)
            except Exception:
                pass
        try:
            _debug_file_handler.close()
        except Exception:
            pass
        _debug_file_handler = None

    if not settings.enabled:
        # Retirer le filtre des consoles (F06)
        if _debug_filter is not None:
            for h in list(root.handlers):
                if _is_console_handler(h):
                    try:
                        h.removeFilter(_debug_filter)
                    except Exception:
                        pass
            try:
                root.removeFilter(_debug_filter)
            except Exception:
                pass
        _debug_filter = None
        app_logger.setLevel(logging.INFO)
        if _already_configured:
            try:
                root.setLevel(logging.INFO)
            except Exception:
                pass
        # Restaurer RUST_LOG si on l'avait posé (F10)
        if _rust_log_set_by_us:
            if _original_rust_log is None:
                os.environ.pop("RUST_LOG", None)
            else:
                os.environ["RUST_LOG"] = _original_rust_log
            _rust_log_set_by_us = False
            _original_rust_log = None
        _already_configured = True
        _applied_settings = settings
        return False

    # ON
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = True

    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            handlers=[logging.StreamHandler()],
            force=True,
        )

    # Handler fichier dédié
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh: logging.Handler = logging.handlers.RotatingFileHandler(
            str(log_file), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
    except OSError as exc:
        try:
            logging.getLogger("SuperBot2026").warning(
                "debug.log non inscriptible (%s) — fallback console seule: %s", log_file, exc
            )
        except Exception:
            pass
        # Fallback console seule — ajuster consoles comme dans le bloc ON normal (F09)
        if _debug_filter is None:
            _debug_filter = DebugContextFilter()
        for h in list(root.handlers):
            if _is_console_handler(h):
                try:
                    h.setLevel(settings.console_level)
                except Exception:
                    pass
                if settings.console_level <= logging.DEBUG:
                    try:
                        h.setFormatter(
                            logging.Formatter(
                                "%(asctime)s [%(levelname)s] %(name)s [%(spot_id)s]: %(message)s",
                                defaults={"spot_id": "-", "table_id": "-"},
                            )
                        )
                    except Exception:
                        pass
                    if _debug_filter not in h.filters:
                        try:
                            h.addFilter(_debug_filter)
                        except Exception:
                            pass
        _already_configured = True
        _applied_settings = settings
        app_logger.setLevel(logging.DEBUG)
        return True

    fh.setLevel(settings.file_level)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s [%(spot_id)s] (%(filename)s:%(lineno)d): %(message)s",
            defaults={"spot_id": "-", "table_id": "-"},
        )
    )
    _debug_filter = DebugContextFilter()
    fh.addFilter(_debug_filter)
    root.addHandler(fh)
    _debug_file_handler = fh

    # Console : ajuster niveau + formatter
    for h in list(root.handlers):
        if _is_console_handler(h):
            try:
                h.setLevel(settings.console_level)
            except Exception:
                pass
            if settings.console_level <= logging.DEBUG:
                try:
                    h.setFormatter(
                        logging.Formatter(
                            "%(asctime)s [%(levelname)s] %(name)s [%(spot_id)s]: %(message)s",
                            defaults={"spot_id": "-", "table_id": "-"},
                        )
                    )
                except Exception:
                    pass
                if _debug_filter is not None and _debug_filter not in h.filters:
                    h.addFilter(_debug_filter)

    # Permissions restreintes
    try:
        os.chmod(log_file, 0o600)
    except Exception:
        pass

    # Propagation Rust — hiérarchie : RUST_LOG > POKER_RUST_LOG > debug.rust_log (F10 réversible)
    if os.getenv("RUST_LOG") is None:
        rust_val = os.getenv("POKER_RUST_LOG") or settings.rust_log
        if rust_val:
            _original_rust_log = os.getenv("RUST_LOG")  # None ici — sauvegardé avant setdefault
            os.environ.setdefault("RUST_LOG", rust_val)
            _rust_log_set_by_us = True
            _rust_log_value_set = rust_val

    _already_configured = True
    _applied_settings = settings
    return True


# Helper pour tests : reset état interne (F08 complet)
def _reset_debug_state() -> None:
    global _already_configured, _applied_settings, _debug_file_handler, _debug_filter
    global _original_rust_log, _rust_log_set_by_us, _rust_log_value_set
    root = logging.getLogger()
    app_logger = logging.getLogger("SuperBot2026")
    if _debug_filter is not None:
        for h in list(root.handlers):
            try:
                h.removeFilter(_debug_filter)
            except Exception:
                    pass
        try:
            root.removeFilter(_debug_filter)
        except Exception:
            pass
        try:
            if _debug_file_handler is not None:
                _debug_file_handler.removeFilter(_debug_filter)
        except Exception:
            pass
    if _debug_file_handler is not None:
        try:
            root.removeHandler(_debug_file_handler)
        except Exception:
            pass
        try:
            _debug_file_handler.close()
        except Exception:
            pass
    try:
        app_logger.setLevel(logging.INFO)
    except Exception:
        pass
    try:
        if root.level == logging.DEBUG:
            root.setLevel(logging.INFO)
    except Exception:
        pass
    # Restaurer RUST_LOG seulement si c'est toujours la valeur qu'on avait posée
    # (évite d'écraser un RUST_LOG injecté par patch.dict / l'appelant entre deux cycles)
    if _rust_log_set_by_us:
        cur = os.getenv("RUST_LOG")
        if _rust_log_value_set is not None and cur != _rust_log_value_set:
            # Valeur modifiée depuis notre setdefault — on ne la touche pas
            pass
        elif _original_rust_log is None:
            try:
                os.environ.pop("RUST_LOG", None)
            except Exception:
                pass
        else:
            os.environ["RUST_LOG"] = _original_rust_log
        _rust_log_set_by_us = False
        _original_rust_log = None
        _rust_log_value_set = None
    _already_configured = False
    _applied_settings = None
    _debug_file_handler = None
    _debug_filter = None
    _throttle_state.clear()
