from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from src.runtime.health import HealthMonitor

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency
    requests = None


logger = logging.getLogger(__name__)

DEFAULT_GTO_SERVER_URL = "http://127.0.0.1:8765/v2/solve"
DEFAULT_GTO_SERVER_TIMEOUT_S = 1.2

_AGGRESSIVE_ACTIONS = {"bet", "raise", "all_in", "allin", "all-in"}


def _env_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class SolverProvider:
    def __init__(
        self,
        native_backend: Any = None,
        http_url: str | None = None,
        timeout_s: float = DEFAULT_GTO_SERVER_TIMEOUT_S,
        request_post: Callable[..., Any] | None = None,
        health_monitor: HealthMonitor | None = None,
        blueprint_store: Any = None,
    ) -> None:
        self.native_backend = native_backend
        self.http_url = str(
            http_url or os.getenv("POKER_GTO_SERVER_URL") or DEFAULT_GTO_SERVER_URL
        ).strip()
        self.timeout_s = max(0.05, float(timeout_s or DEFAULT_GTO_SERVER_TIMEOUT_S))
        self.request_post = request_post or (requests.post if requests is not None else None)
        self.health_monitor = health_monitor
        self._active_backend = "fallback"
        self._last_fallback_reason = "rust_solver_unavailable"
        self._last_success_at: str | None = None
        # Phase 0.6.6 / 1.4 — mode live « lookup blueprint only » : quand
        # POKER_LIVE_LOOKUP_ONLY=1, le solve en ligne est interdit ; MISS ⇒
        # refus d'agir (fallback_reason="no_blueprint").
        self._lookup_only = _env_truthy(os.getenv("POKER_LIVE_LOOKUP_ONLY", ""))
        self._blueprint_store = blueprint_store

    def active_backend(self) -> str:
        return self._active_backend

    def fallback_reason(self) -> str:
        return self._last_fallback_reason

    def last_success_at(self) -> str | None:
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
        chosen_action = str(
            payload.get("chosen_action") or payload.get("recommended_action") or ""
        ).strip()
        actions = payload.get("actions")
        return bool(chosen_action or (isinstance(actions, list) and actions))

    def _normalize_response(self, response: Any, *, backend: str) -> dict | None:
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

    def _invoke_native(self, payload: dict) -> tuple[dict | None, str]:
        backend = self.native_backend
        if backend is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "rust_solver_unavailable", status="degraded"
                )
            return None, "rust_solver_unavailable"

        solver_fn = getattr(backend, "solve_spot_v2", None)
        if not callable(solver_fn):
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "solver_backend_missing_entrypoint", status="degraded"
                )
            return None, "solver_backend_missing_entrypoint"

        try:
            result = solver_fn(**payload)
        except TypeError:
            try:
                result = solver_fn(payload)
            except Exception as exc:
                logger.debug("Native solver backend failed after payload fallback: %s", exc)
                if self.health_monitor is not None:
                    self.health_monitor.record_error(
                        "solver",
                        str(exc) or "native_solver_error",
                        status="degraded",
                        cooldown_s=1.0,
                    )
                return None, str(exc) or "native_solver_error"
        except Exception as exc:
            logger.debug("Native solver backend failed: %s", exc)
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", str(exc) or "native_solver_error", status="degraded", cooldown_s=1.0
                )
            return None, str(exc) or "native_solver_error"

        normalized = self._normalize_response(result, backend=self._native_backend_name())
        if normalized is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "native_solver_no_result", status="degraded"
                )
            return None, "native_solver_no_result"
        if self.health_monitor is not None:
            self.health_monitor.record_success("solver")
        return normalized, ""

    def _invoke_http(self, payload: dict) -> tuple[dict | None, str]:
        if not self.http_url:
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "http_solver_disabled", status="degraded"
                )
            return None, "http_solver_disabled"
        if self.request_post is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "http_client_unavailable", status="degraded"
                )
            return None, "http_client_unavailable"

        started = time.perf_counter()
        try:
            response = self.request_post(self.http_url, json=payload, timeout=self.timeout_s)
            status_code = getattr(response, "status_code", 200)
            if status_code != 200:
                if self.health_monitor is not None:
                    self.health_monitor.record_error(
                        "solver", f"http_status_{status_code}", status="degraded", cooldown_s=1.0
                    )
                return None, f"http_status_{status_code}"
            result = response.json()
        except Exception as exc:
            logger.debug("HTTP solver backend failed: %s", exc)
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "http_solver_unavailable", status="degraded", cooldown_s=1.0
                )
            return None, "http_solver_unavailable"

        normalized = self._normalize_response(result, backend="gto_server")
        if normalized is None:
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "http_solver_no_result", status="degraded"
                )
            return None, "http_solver_no_result"

        normalized.setdefault("backend_details", {})
        if isinstance(normalized["backend_details"], dict):
            normalized["backend_details"].setdefault("url", self.http_url)
        normalized.setdefault("metadata", {})
        if isinstance(normalized["metadata"], dict):
            normalized["metadata"].setdefault("transport", "local_http")
            normalized["metadata"].setdefault(
                "elapsed_wall_ms", int((time.perf_counter() - started) * 1000)
            )
        if self.health_monitor is not None:
            self.health_monitor.record_success("solver")
        return normalized, ""

    def _fallback_response(
        self, reason: str, *, native_reason: str = "", http_reason: str = ""
    ) -> dict:
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

    # ------------------------------------------------------ blueprint (live)
    def _get_blueprint_store(self) -> Any:
        if self._blueprint_store is None:
            from src.solver.blueprint_store import default_blueprint_store

            self._blueprint_store = default_blueprint_store()
        return self._blueprint_store

    @staticmethod
    def _blueprint_key(payload: dict) -> str:
        """Clé de lookup blueprint — exactement la même normalisation que le
        générateur offline (``spot_cache_key`` partagé, parité par construction).
        """
        from src.solver.blueprint_store import blueprint_key

        return blueprint_key(
            hero_hand=str(payload.get("hero_range") or ""),
            villain_range=str(
                (payload.get("villain_ranges") or [""])[0]
                if payload.get("villain_ranges")
                else ""
            ),
            board=list(payload.get("board") or []),
            pot=float(payload.get("starting_pot") or 0.0),
            effective_stack=float(payload.get("effective_stack") or 0.0),
            legal_actions=list(payload.get("legal_actions") or []),
            spot_id=str(payload.get("spot_id") or ""),
            hero_position=str(payload.get("hero_position") or ""),
            action_history=list(payload.get("action_history") or []),
            rake=float(payload.get("rake") or 0.0),
        )

    def _check_bet_quantization(self, payload: dict) -> str | None:
        """Refuse les mises adverses hors tolérance de quantification (0.6.5.i).

        Retourne un motif de refus (str) ou None si tout est quantifiable.
        """
        from src.solver.bet_quantization import quantize_observed_bet

        pot = float(payload.get("starting_pot") or 0.0)
        stack = float(payload.get("effective_stack") or 0.0)
        for raw in payload.get("action_history") or []:
            parts = str(raw).split(":")
            if len(parts) < 3:
                continue
            action = parts[1].strip().lower()
            if action not in _AGGRESSIVE_ACTIONS:
                continue
            try:
                amount = float(parts[2])
            except (TypeError, ValueError):
                continue
            if amount <= 0.0 or amount >= stack > 0.0:
                continue  # all-in : pas de quantification à appliquer
            if quantize_observed_bet(amount, pot) is None:
                return "bet_out_of_quantization_tolerance"
        return None

    def _solve_from_blueprint(self, payload: dict) -> dict:
        store = self._get_blueprint_store()
        spot_for_log = {
            "spot_id": payload.get("spot_id"),
            "board": list(payload.get("board") or []),
            "pot": payload.get("starting_pot"),
            "stack": payload.get("effective_stack"),
        }
        quantization_refusal = self._check_bet_quantization(payload)
        key = self._blueprint_key(payload)
        if quantization_refusal is not None:
            store.record_miss(key, spot_for_log, reason=quantization_refusal)
            self._active_backend = "fallback"
            self._last_fallback_reason = "no_blueprint"
            if self.health_monitor is not None:
                self.health_monitor.record_error(
                    "solver", "no_blueprint", status="degraded", cooldown_s=1.0
                )
            return self._fallback_response(
                "no_blueprint",
                native_reason=quantization_refusal,
                http_reason="live_lookup_only",
            )
        response = store.lookup(key)
        if response is not None:
            self._active_backend = "blueprint"
            self._last_fallback_reason = ""
            self._last_success_at = _utc_now()
            if self.health_monitor is not None:
                self.health_monitor.record_success("solver")
            return response
        store.record_miss(key, spot_for_log, reason="miss")
        self._active_backend = "fallback"
        self._last_fallback_reason = "no_blueprint"
        if self.health_monitor is not None:
            self.health_monitor.record_error(
                "solver", "no_blueprint", status="degraded", cooldown_s=1.0
            )
        return self._fallback_response(
            "no_blueprint",
            native_reason="blueprint_miss",
            http_reason="live_lookup_only",
        )

    def solve_spot_v2(self, **payload: Any) -> dict:
        # Phase 0.6.6 / 1.4 — live lookup-only : JAMAIS de solve en ligne.
        if self._lookup_only:
            return self._solve_from_blueprint(payload)
        native_response, native_reason = self._invoke_native(payload)
        if native_response is not None:
            self._active_backend = str(
                native_response.get("backend") or self._native_backend_name()
            )
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
