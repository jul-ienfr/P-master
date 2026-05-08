from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

from src.runtime.health import HealthMonitor

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency
    requests = None


logger = logging.getLogger(__name__)

DEFAULT_GTO_SERVER_URL = "http://127.0.0.1:8765/v2/solve"
DEFAULT_GTO_SERVER_TIMEOUT_S = 1.2


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class SolverProvider:
    def __init__(
        self,
        native_backend: Any = None,
        http_url: Optional[str] = None,
        timeout_s: float = DEFAULT_GTO_SERVER_TIMEOUT_S,
        request_post: Optional[Callable[..., Any]] = None,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self.native_backend = native_backend
        self.http_url = str(http_url or os.getenv("POKER_GTO_SERVER_URL") or DEFAULT_GTO_SERVER_URL).strip()
        self.timeout_s = max(0.05, float(timeout_s or DEFAULT_GTO_SERVER_TIMEOUT_S))
        self.request_post = request_post or (requests.post if requests is not None else None)
        self.health_monitor = health_monitor
        self._active_backend = "fallback"
        self._last_fallback_reason = "rust_solver_unavailable"
        self._last_success_at: Optional[str] = None

    def active_backend(self) -> str:
        return self._active_backend

    def fallback_reason(self) -> str:
        return self._last_fallback_reason

    def last_success_at(self) -> Optional[str]:
        return self._last_success_at

    def backend_name(self) -> str:
        return self.active_backend()

    def _native_backend_name(self) -> str:
        backend = self.native_backend
        if backend is None:
            return "fallback"
        module_name = getattr(backend, "__name__", "")
        if module_name == "postflop_solver_py":
            return "native_solver"
        return getattr(backend, "backend_name", backend.__class__.__name__)

    @staticmethod
    def _supports_action_payload(payload: dict) -> bool:
        chosen_action = str(payload.get("chosen_action") or payload.get("recommended_action") or "").strip()
        actions = payload.get("actions")
        return bool(chosen_action or (isinstance(actions, list) and actions))

    def _normalize_response(self, response: Any, *, backend: str) -> Optional[dict]:
        if response is None:
            return None
        if isinstance(response, dict):
            normalized = dict(response)
        elif hasattr(response, "to_dict") and callable(response.to_dict):
            normalized = dict(response.to_dict())
        else:
            return None

        normalized.setdefault("backend", backend)
        normalized.setdefault("fallback_used", False)
        normalized.setdefault("fallback_reason", "")
        if not self._supports_action_payload(normalized):
            return None
        return normalized

    def _invoke_native(self, payload: dict) -> tuple[Optional[dict], str]:
        backend = self.native_backend
        if backend is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "rust_solver_unavailable", status="degraded")
            return None, "rust_solver_unavailable"

        solver_fn = getattr(backend, "solve_spot_v2", None)
        if not callable(solver_fn):
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "solver_backend_missing_entrypoint", status="degraded")
            return None, "solver_backend_missing_entrypoint"

        try:
            result = solver_fn(**payload)
        except TypeError:
            try:
                result = solver_fn(payload)
            except Exception as exc:
                logger.debug("Native solver backend failed after payload fallback: %s", exc)
                if self.health_monitor is not None:
                    self.health_monitor.record_error("solver", str(exc) or "native_solver_error", status="degraded", cooldown_s=1.0)
                return None, str(exc) or "native_solver_error"
        except Exception as exc:
            logger.debug("Native solver backend failed: %s", exc)
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", str(exc) or "native_solver_error", status="degraded", cooldown_s=1.0)
            return None, str(exc) or "native_solver_error"

        normalized = self._normalize_response(result, backend=self._native_backend_name())
        if normalized is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "native_solver_no_result", status="degraded")
            return None, "native_solver_no_result"
        if self.health_monitor is not None:
            self.health_monitor.record_success("solver")
        return normalized, ""

    def _invoke_http(self, payload: dict) -> tuple[Optional[dict], str]:
        if not self.http_url:
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "http_solver_disabled", status="degraded")
            return None, "http_solver_disabled"
        if self.request_post is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "http_client_unavailable", status="degraded")
            return None, "http_client_unavailable"

        started = time.perf_counter()
        try:
            response = self.request_post(self.http_url, json=payload, timeout=self.timeout_s)
            status_code = getattr(response, "status_code", 200)
            if status_code != 200:
                if self.health_monitor is not None:
                    self.health_monitor.record_error("solver", f"http_status_{status_code}", status="degraded", cooldown_s=1.0)
                return None, f"http_status_{status_code}"
            result = response.json()
        except Exception as exc:
            logger.debug("HTTP solver backend failed: %s", exc)
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "http_solver_unavailable", status="degraded", cooldown_s=1.0)
            return None, "http_solver_unavailable"

        normalized = self._normalize_response(result, backend="gto_server")
        if normalized is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error("solver", "http_solver_no_result", status="degraded")
            return None, "http_solver_no_result"

        normalized.setdefault("backend_details", {})
        if isinstance(normalized["backend_details"], dict):
            normalized["backend_details"].setdefault("url", self.http_url)
        normalized.setdefault("metadata", {})
        if isinstance(normalized["metadata"], dict):
            normalized["metadata"].setdefault("transport", "local_http")
            normalized["metadata"].setdefault("elapsed_wall_ms", int((time.perf_counter() - started) * 1000))
        if self.health_monitor is not None:
            self.health_monitor.record_success("solver")
        return normalized, ""

    def _fallback_response(self, reason: str, *, native_reason: str = "", http_reason: str = "") -> dict:
        fallback_reason = str(reason or "no_backend_result")
        response = {
            "chosen_action": "",
            "actions": [],
            "hero_ev": 0.0,
            "exploitability": 1.0,
            "decision_confidence": 0.0,
            "cache_hit": False,
            "elapsed_ms": 0,
            "backend": "fallback",
            "fallback_used": True,
            "fallback_reason": fallback_reason,
            "warnings": ["fallback_used"],
            "backend_details": {
                "name": "fallback",
            },
            "metadata": {
                "native_reason": native_reason,
                "http_reason": http_reason,
            },
        }
        return response

    def solve_spot_v2(self, **payload: Any) -> dict:
        native_response, native_reason = self._invoke_native(payload)
        if native_response is not None:
            self._active_backend = str(native_response.get("backend") or self._native_backend_name())
            self._last_fallback_reason = ""
            self._last_success_at = _utc_now()
            return native_response

        http_response, http_reason = self._invoke_http(payload)
        if http_response is not None:
            self._active_backend = str(http_response.get("backend") or "gto_server")
            self._last_fallback_reason = ""
            self._last_success_at = _utc_now()
            return http_response

        fallback_reason = native_reason or http_reason or "no_backend_result"
        self._active_backend = "fallback"
        self._last_fallback_reason = fallback_reason
        return self._fallback_response(
            fallback_reason,
            native_reason=native_reason,
            http_reason=http_reason,
        )
