from __future__ import annotations

import time
from copy import deepcopy
from typing import Optional

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc


DEFAULT_SUBSYSTEMS = (
    "capture",
    "ocr",
    "solver",
    "db",
    "bridge",
    "api",
    "persistence",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class HealthMonitor:
    def __init__(self, subsystems: tuple[str, ...] = DEFAULT_SUBSYSTEMS) -> None:
        self._subsystems = tuple(subsystems)
        self._states = {name: self._empty_state() for name in self._subsystems}
        self._overall_last_success_at: Optional[str] = None

    @staticmethod
    def _empty_state() -> dict:
        return {
            "status": "healthy",
            "last_success_at": None,
            "last_error_at": None,
            "error_count": 0,
            "cooldown_until": None,
            "reasons": [],
        }

    def _ensure(self, subsystem: str) -> dict:
        key = str(subsystem or "unknown").strip().lower() or "unknown"
        if key not in self._states:
            self._states[key] = self._empty_state()
        return self._states[key]

    def record_success(self, subsystem: str) -> None:
        state = self._ensure(subsystem)
        timestamp = _utc_now()
        state["status"] = "healthy"
        state["last_success_at"] = timestamp
        state["cooldown_until"] = None
        state["reasons"] = []
        self._overall_last_success_at = timestamp

    def record_error(
        self,
        subsystem: str,
        reason: str,
        *,
        status: str = "degraded",
        cooldown_s: float = 0.0,
    ) -> None:
        state = self._ensure(subsystem)
        timestamp = _utc_now()
        state["status"] = status if status in {"healthy", "degraded", "unavailable"} else "degraded"
        state["last_error_at"] = timestamp
        state["error_count"] = int(state.get("error_count", 0) or 0) + 1
        normalized_reason = str(reason or "unknown_error").strip() or "unknown_error"
        reasons = [item for item in state.get("reasons", []) if item != normalized_reason]
        reasons.append(normalized_reason)
        state["reasons"] = reasons[-5:]
        if cooldown_s and float(cooldown_s) > 0.0:
            state["cooldown_until"] = _utc_now_from_epoch(time.time() + float(cooldown_s))

    def subsystem_status(self, subsystem: str) -> dict:
        return deepcopy(self._ensure(subsystem))

    def degraded_reasons(self) -> list[str]:
        reasons: list[str] = []
        for subsystem, state in self._states.items():
            if state.get("status") == "healthy":
                continue
            for reason in state.get("reasons", []) or []:
                reasons.append(f"{subsystem}:{reason}")
        return reasons

    def snapshot(self) -> dict:
        return {name: deepcopy(state) for name, state in self._states.items()}

    def overall_last_success_at(self) -> Optional[str]:
        return self._overall_last_success_at


def _utc_now_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(float(epoch_s), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
