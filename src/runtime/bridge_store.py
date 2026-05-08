import json
import logging
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Callable, Optional

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc

from src.runtime.history_store import KNOWN_STREAMS, RuntimeHistoryStore


logger = logging.getLogger("RuntimeBridge")
WINDOWS_BRIDGE_WRITE_RETRIES = 8
WINDOWS_BRIDGE_RETRY_DELAY_S = 0.03


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _latest_timestamp(entries: list[dict]) -> Optional[str]:
    if entries and isinstance(entries[0], dict):
        timestamp = entries[0].get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            return timestamp
    return None


def _parse_runtime_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_local_metrics(history: dict) -> dict:
    decisions = history.get("decisions", []) or []
    decision_count = len(decisions)
    blocked_count = 0
    fallback_count = 0
    latencies: list[float] = []

    for entry in decisions:
        if not isinstance(entry, dict):
            continue
        gate_result = entry.get("gate_result", {}) or {}
        incidents = {str(item) for item in entry.get("incidents", [])}
        if not bool(gate_result.get("allowed", True)) or "gate_blocked" in incidents:
            blocked_count += 1
        if str(entry.get("source", "")).lower() == "fallback":
            fallback_count += 1
        latency_ms = entry.get("latency_ms")
        if isinstance(latency_ms, (int, float)):
            latencies.append(float(latency_ms))

    rolling_latency_ms = round(sum(latencies[:5]) / min(len(latencies), 5), 1) if latencies else 0.0
    block_rate = round(blocked_count / decision_count, 3) if decision_count else 0.0
    fallback_rate = round(fallback_count / decision_count, 3) if decision_count else 0.0

    timestamps = [
        parsed
        for parsed in (_parse_runtime_timestamp(entry.get("timestamp")) for entry in decisions)
        if parsed is not None
    ]
    if len(timestamps) >= 2:
        newest = max(timestamps)
        oldest = min(timestamps)
        span_seconds = max((newest - oldest).total_seconds(), 1.0)
        decision_rate = round((decision_count * 60.0) / span_seconds, 2)
    else:
        decision_rate = float(decision_count)

    return {
        "decision_count": decision_count,
        "blocked_count": blocked_count,
        "fallback_count": fallback_count,
        "block_rate": block_rate,
        "fallback_rate": fallback_rate,
        "rolling_latency_ms": rolling_latency_ms,
        "decision_rate": decision_rate,
        "window_size": decision_count,
    }


class RuntimeBridgeStore:
    def __init__(self, bridge_dir: str = "log/runtime_bridge") -> None:
        self.bridge_dir = Path(bridge_dir)
        self.state_path = self.bridge_dir / "runtime_state.json"
        self.commands_dir = self.bridge_dir / "commands"
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        self.commands_dir.mkdir(parents=True, exist_ok=True)
        self._state_cache_payload: dict = {}
        self._state_cache_mtime_ns: Optional[int] = None

    @classmethod
    def from_env(cls, default_dir: str = "log/runtime_bridge") -> "RuntimeBridgeStore":
        return cls(os.getenv("POKER_RUNTIME_BRIDGE_DIR") or default_dir)

    def _atomic_write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=True, default=_json_default)
        last_error: Optional[Exception] = None

        for attempt in range(1, WINDOWS_BRIDGE_WRITE_RETRIES + 1):
            temp_path = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
            try:
                with temp_path.open("w", encoding="utf-8") as handle:
                    handle.write(serialized)
                    handle.flush()
                os.replace(temp_path, path)
                return
            except PermissionError as exc:
                last_error = exc
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                if attempt < WINDOWS_BRIDGE_WRITE_RETRIES:
                    time.sleep(WINDOWS_BRIDGE_RETRY_DELAY_S * attempt)
                    continue
            except Exception:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

        for attempt in range(1, WINDOWS_BRIDGE_WRITE_RETRIES + 1):
            try:
                with path.open("w", encoding="utf-8") as handle:
                    handle.write(serialized)
                    handle.flush()
                return
            except PermissionError as exc:
                last_error = exc
                if attempt < WINDOWS_BRIDGE_WRITE_RETRIES:
                    time.sleep(WINDOWS_BRIDGE_RETRY_DELAY_S * attempt)
                    continue
                break

        if last_error is not None:
            raise last_error

    def publish_runtime_state(self, payload: dict) -> dict:
        envelope = {
            **dict(payload or {}),
            "bridge": {
                "updated_at": _utc_now(),
                "state_path": str(self.state_path),
            },
        }
        self._atomic_write_json(self.state_path, envelope)
        try:
            self._state_cache_mtime_ns = self.state_path.stat().st_mtime_ns
        except OSError:
            self._state_cache_mtime_ns = None
        self._state_cache_payload = dict(envelope)
        return envelope

    def read_runtime_state(self) -> dict:
        if not self.state_path.exists():
            self._state_cache_payload = {}
            self._state_cache_mtime_ns = None
            return {}
        try:
            mtime_ns = self.state_path.stat().st_mtime_ns
            if self._state_cache_mtime_ns == mtime_ns and self._state_cache_payload:
                return dict(self._state_cache_payload)
            with self.state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            normalized = dict(payload) if isinstance(payload, dict) else {}
            self._state_cache_payload = normalized
            self._state_cache_mtime_ns = mtime_ns
            return dict(normalized)
        except Exception as exc:
            logger.warning("Impossible de lire l'etat runtime bridge %s: %s", self.state_path, exc)
            return {}

    def queue_command(self, kind: str, payload: Optional[dict] = None) -> dict:
        command = {
            "command_id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}",
            "kind": str(kind or "").strip() or "unknown",
            "created_at": _utc_now(),
            "payload": dict(payload or {}),
        }
        filename = f"{int(time.time() * 1_000_000)}-{uuid.uuid4().hex}.json"
        self._atomic_write_json(self.commands_dir / filename, command)
        return command

    def consume_pending_commands(self, limit: int = 10) -> list[dict]:
        commands: list[dict] = []
        for path in sorted(self.commands_dir.glob("*.json"))[: max(0, int(limit))]:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    commands.append(payload)
            except Exception as exc:
                logger.warning("Impossible de lire la commande bridge %s: %s", path, exc)
            finally:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
        return commands

    @staticmethod
    def _operator_patch_applied(operator: dict, patch: dict) -> bool:
        operator = dict(operator or {})
        for key, expected_value in dict(patch or {}).items():
            if operator.get(key) != expected_value:
                return False
        return True

    def queue_operator_patch(self, patch: dict, timeout_s: float = 0.75, poll_interval_s: float = 0.05) -> dict:
        normalized_patch = dict(patch or {})
        self.queue_command("operator_patch", normalized_patch)
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        last_state: dict = {}

        while time.monotonic() <= deadline:
            last_state = self.read_runtime_state()
            operator = dict(last_state.get("operator", {}) or {})
            if self._operator_patch_applied(operator, normalized_patch):
                return operator
            time.sleep(max(0.01, float(poll_interval_s)))

        return dict(last_state.get("operator", {}) or {})

    def queue_hitl_resolution(self, boxes: list) -> dict:
        return self.queue_command("hitl_resolve", {"boxes": list(boxes or [])})


class BridgeHitlProxy:
    def __init__(self, bridge_store: RuntimeBridgeStore, default_target_dataset_size: int = 100) -> None:
        self.bridge_store = bridge_store
        self._default_target_dataset_size = int(default_target_dataset_size or 100)

    def _snapshot(self) -> dict:
        state = self.bridge_store.read_runtime_state()
        hitl = state.get("hitl", {}) if isinstance(state, dict) else {}
        return dict(hitl or {})

    @property
    def annotations_count(self) -> int:
        return int(self._snapshot().get("collected_samples", 0) or 0)

    @property
    def target_dataset_size(self) -> int:
        return int(self._snapshot().get("target_samples", self._default_target_dataset_size) or self._default_target_dataset_size)

    @property
    def is_waiting_for_human(self) -> bool:
        return bool(self._snapshot().get("is_waiting_for_human", False))

    @property
    def current_issue(self):
        issue = self._snapshot().get("current_issue")
        return dict(issue) if isinstance(issue, dict) else None

    def check_convergence(self) -> bool:
        snapshot = self._snapshot()
        if "ready_for_training" in snapshot:
            return bool(snapshot.get("ready_for_training", False))
        return self.annotations_count >= self.target_dataset_size

    def resolve_human_intervention(self, human_boxes: list):
        self.bridge_store.queue_hitl_resolution(human_boxes)
        return {"status": "queued", "boxes": list(human_boxes or [])}


class BridgeRuntimeStatusProvider:
    def __init__(
        self,
        bridge_store: RuntimeBridgeStore,
        history_store: Optional[RuntimeHistoryStore] = None,
        observation_provider: Optional[Callable[[], dict]] = None,
    ) -> None:
        self.bridge_store = bridge_store
        self.history_store = history_store
        self.observation_provider = observation_provider
        self._persisted_history_cache: dict = {stream: [] for stream in KNOWN_STREAMS}
        self._persisted_history_cached_at: float = 0.0
        self._persisted_history_ttl_seconds: float = 0.9
        self._status_cache: dict = {}
        self._status_cached_at: float = 0.0
        self._status_cache_ttl_seconds: float = 0.2
        self._status_cache_token: tuple = ()
        self._observation_cache: dict = {}
        self._observation_cached_at: float = 0.0
        self._observation_cache_ttl_seconds: float = 0.2

    def _persisted_history(self) -> dict:
        now = time.monotonic()
        if (
            self._persisted_history_cache
            and (now - self._persisted_history_cached_at) <= self._persisted_history_ttl_seconds
        ):
            return {
                stream: list(self._persisted_history_cache.get(stream, []) or [])
                for stream in KNOWN_STREAMS
            }
        if self.history_store is None:
            return {stream: [] for stream in KNOWN_STREAMS}
        history = {
            stream: self.history_store.read_recent(stream, limit=10)
            for stream in KNOWN_STREAMS
        }
        self._persisted_history_cache = {
            stream: list(history.get(stream, []) or [])
            for stream in KNOWN_STREAMS
        }
        self._persisted_history_cached_at = now
        return {
            stream: list(history.get(stream, []) or [])
            for stream in KNOWN_STREAMS
        }

    def _history_summary(self, runtime_history: dict, persisted_history: dict) -> dict:
        persistence = self.history_store.summarize() if self.history_store is not None else {}
        return {
            "event_count": len(runtime_history.get("events", []) or []),
            "decision_count": len(runtime_history.get("decisions", []) or []),
            "incident_count": len(runtime_history.get("incidents", []) or []),
            "metrics_count": len(runtime_history.get("metrics", []) or []),
            "latest_event_at": _latest_timestamp(runtime_history.get("events", []) or []),
            "latest_decision_at": _latest_timestamp(runtime_history.get("decisions", []) or []),
            "latest_incident_at": _latest_timestamp(runtime_history.get("incidents", []) or []),
            "latest_metrics_at": _latest_timestamp(runtime_history.get("metrics", []) or []),
            "persisted_event_count": len(persisted_history.get("events", []) or []),
            "persisted_decision_count": len(persisted_history.get("decisions", []) or []),
            "persisted_incident_count": len(persisted_history.get("incidents", []) or []),
            "persisted_metrics_count": len(persisted_history.get("metrics", []) or []),
            "latest_persisted_event_at": _latest_timestamp(persisted_history.get("events", []) or []),
            "latest_persisted_decision_at": _latest_timestamp(persisted_history.get("decisions", []) or []),
            "latest_persisted_incident_at": _latest_timestamp(persisted_history.get("incidents", []) or []),
            "latest_persisted_metrics_at": _latest_timestamp(persisted_history.get("metrics", []) or []),
            "persistence": persistence,
        }

    def _metrics_payload(self, state: dict, history: dict) -> dict:
        local_metrics = _build_local_metrics(history)
        metrics = dict(state.get("metrics", {}) or {})
        latest_snapshot = None
        metrics_entries = history.get("metrics", []) or []
        if metrics_entries and isinstance(metrics_entries[0], dict):
            latest_snapshot = dict(metrics_entries[0])
        elif metrics:
            latest_snapshot = dict(metrics.get("latest_snapshot", {}) or {})
        if latest_snapshot is None:
            latest_snapshot = {
                "timestamp": _utc_now(),
                "session_id": str(state.get("session_id") or ""),
                **local_metrics,
            }
        return {
            **local_metrics,
            **metrics,
            "latest_snapshot": latest_snapshot,
        }

    def get_observation_snapshot(self) -> dict:
        now = time.monotonic()
        if self._observation_cache and (now - self._observation_cached_at) <= self._observation_cache_ttl_seconds:
            return dict(self._observation_cache)

        state = self.bridge_store.read_runtime_state()
        observation = dict(state.get("observation", {}) or {})
        if not observation and self.observation_provider is not None:
            observation = dict(self.observation_provider() or {})
        self._observation_cache = dict(observation)
        self._observation_cached_at = now
        return dict(observation)

    def get_status(self) -> dict:
        state = self.bridge_store.read_runtime_state()
        bridge = dict(state.get("bridge", {}) or {}) if isinstance(state, dict) else {}
        cache_token = (
            str(bridge.get("updated_at") or ""),
            round(self._persisted_history_cached_at, 3),
        )
        now = time.monotonic()
        if (
            state
            and self._status_cache
            and cache_token == self._status_cache_token
            and (now - self._status_cached_at) <= self._status_cache_ttl_seconds
        ):
            return dict(self._status_cache)
        if not state:
            persisted_history = self._persisted_history()
            payload = {
                "is_running": False,
                "app_name": "PokerMaster",
                "service": "PokerMaster",
                "version": "v2",
                "tracker": {},
                "canonical_spot": None,
                "gate": {},
                "decision": {},
                "health": {},
                "active_solver_backend": "fallback",
                "degraded_reasons": [],
                "last_success_at": None,
                "operator": {
                    "profile_name": "live-runtime",
                    "surface": "bot_cockpit",
                    "capture_source": "ocr",
                    "auto_refresh_enabled": True,
                    "assisted_mode_enabled": True,
                    "observation_mode_enabled": False,
                    "shadow_mode_enabled": False,
                    "manual_override_enabled": False,
                    "paused": False,
                    "status": "offline",
                },
                "observation": self.get_observation_snapshot(),
                "history": {
                    "events": [],
                    "decisions": [],
                    "incidents": [],
                    "metrics": [],
                    "persisted": persisted_history,
                },
                "metrics": {
                    **_build_local_metrics({"decisions": []}),
                    "latest_snapshot": {
                        "timestamp": _utc_now(),
                        "decision_count": 0,
                    },
                },
                "history_summary": self._history_summary(
                    {stream: [] for stream in KNOWN_STREAMS},
                    persisted_history,
                ),
            }
            self._status_cache = dict(payload)
            self._status_cached_at = now
            self._status_cache_token = cache_token
            return payload

        runtime_history = {
            "events": list(state.get("history", {}).get("events", []) or []),
            "decisions": list(state.get("history", {}).get("decisions", []) or []),
            "incidents": list(state.get("history", {}).get("incidents", []) or []),
            "metrics": list(state.get("history", {}).get("metrics", []) or []),
        }
        persisted_history = self._persisted_history()
        combined_history = {
            **runtime_history,
            "persisted": persisted_history,
        }
        observation = self.get_observation_snapshot()

        payload = {
            **state,
            "health": dict(state.get("health", {}) or {}),
            "active_solver_backend": str(state.get("active_solver_backend") or "fallback"),
            "degraded_reasons": list(state.get("degraded_reasons", []) or []),
            "last_success_at": state.get("last_success_at"),
            "history": combined_history,
            "metrics": self._metrics_payload(state, runtime_history),
            "history_summary": self._history_summary(runtime_history, persisted_history),
            "observation": observation,
        }
        self._status_cache = dict(payload)
        self._status_cached_at = now
        self._status_cache_token = cache_token
        return payload
