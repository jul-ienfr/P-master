"""Helpers de session runtime : horodatage, session id, flags et port API."""

import logging
import os
import socket
import uuid

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime

    UTC = UTC

logger = logging.getLogger("SuperBot2026")

RUNTIME_PORT_CANDIDATES = (8005, 8080)


def parse_bool_flag(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_runtime_session_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"runtime-{timestamp}-{uuid.uuid4().hex[:8]}"


def resolve_runtime_flag(config_value: object, env_var_name: str, default: bool) -> bool:
    env_value = parse_bool_flag(os.getenv(env_var_name))
    if env_value is not None:
        return env_value

    configured_value = parse_bool_flag(config_value)
    if configured_value is not None:
        return configured_value

    return default


def select_available_runtime_port(candidates: tuple[int, ...] = RUNTIME_PORT_CANDIDATES) -> int:
    for port in candidates:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            probe.close()
    return candidates[0]


def resolve_runtime_api_port(candidates: tuple[int, ...] = RUNTIME_PORT_CANDIDATES) -> int:
    configured = os.getenv("POKER_RUNTIME_API_PORT")
    if configured:
        try:
            return int(configured)
        except ValueError:
            logger.warning(
                "POKER_RUNTIME_API_PORT invalide (%s), selection automatique.", configured
            )
    return select_available_runtime_port(candidates)


class RuntimeSessionMixin:
    """Bindings conservés sur le controller : les tests surchargent ces seams par instance."""

    _parse_bool_flag = staticmethod(parse_bool_flag)
    _utc_now = staticmethod(utc_now)
    _build_runtime_session_id = staticmethod(build_runtime_session_id)
    _resolve_runtime_flag = staticmethod(resolve_runtime_flag)
    _select_available_runtime_port = staticmethod(select_available_runtime_port)
    _resolve_runtime_api_port = staticmethod(resolve_runtime_api_port)

    def _get_runtime_session_id(self) -> str:
        return getattr(self, "runtime_session_id", None) or self._build_runtime_session_id()

    def _build_rl_runtime_config(self) -> dict:
        rl_cfg = self.config.get("rl", {}) or {}
        bot_cfg = self.config.get("bot", {}) or {}

        enable_rl = self._resolve_runtime_flag(
            rl_cfg.get("enable", bot_cfg.get("enable_rl")),
            "POKER_ENABLE_RL",
            True,
        )
        autoload_rl_model = self._resolve_runtime_flag(
            rl_cfg.get("autoload_model", bot_cfg.get("autoload_rl_model")),
            "POKER_AUTOLOAD_RL_MODEL",
            enable_rl,
        )
        enable_validated_rl = self._resolve_runtime_flag(
            rl_cfg.get("enable_validated", bot_cfg.get("enable_validated_rl")),
            "POKER_ENABLE_VALIDATED_RL",
            False,
        )

        if not enable_rl:
            autoload_rl_model = False
            enable_validated_rl = False

        logger.info(
            "Runtime RL config resolved: enable_rl=%s, enable_validated_rl=%s, autoload_rl_model=%s",
            enable_rl,
            enable_validated_rl,
            autoload_rl_model,
        )

        return {
            "enable_rl": enable_rl,
            "enable_validated_rl": enable_validated_rl,
            "autoload_rl_model": autoload_rl_model,
        }
