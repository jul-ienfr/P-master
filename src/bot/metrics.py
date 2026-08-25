"""Snapshots de métriques runtime (extrait de src/main.py)."""

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime

    UTC = UTC


class MetricsMixin:
    @staticmethod
    def _parse_runtime_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _build_local_metrics(self, history: dict) -> dict:
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
            for parsed in (self._parse_runtime_timestamp(entry.get("timestamp")) for entry in decisions)
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

    @staticmethod
    def _latest_timestamp(entries: list[dict]) -> str | None:
        if entries and isinstance(entries[0], dict):
            return entries[0].get("timestamp")
        return None

    def _build_persisted_metrics_snapshot(self, local_metrics: dict, history: dict, persistence: dict) -> dict:
        runtime_history = {
            "events": history.get("events", []) or [],
            "decisions": history.get("decisions", []) or [],
            "incidents": history.get("incidents", []) or [],
        }
        persisted_history = history.get("persisted", {}) or {}
        store_summary = self.runtime_history_store.summarize_records()

        return {
            "timestamp": self._utc_now(),
            "decision_count": int(local_metrics.get("decision_count", 0) or 0),
            "blocked_count": int(local_metrics.get("blocked_count", 0) or 0),
            "fallback_count": int(local_metrics.get("fallback_count", 0) or 0),
            "block_rate": float(local_metrics.get("block_rate", 0.0) or 0.0),
            "fallback_rate": float(local_metrics.get("fallback_rate", 0.0) or 0.0),
            "rolling_latency_ms": float(local_metrics.get("rolling_latency_ms", 0.0) or 0.0),
            "decision_rate": float(local_metrics.get("decision_rate", 0.0) or 0.0),
            "window_size": int(local_metrics.get("window_size", 0) or 0),
            "runtime": {
                "event_count": len(runtime_history["events"]),
                "decision_count": len(runtime_history["decisions"]),
                "incident_count": len(runtime_history["incidents"]),
                "latest_event_at": self._latest_timestamp(runtime_history["events"]),
                "latest_decision_at": self._latest_timestamp(runtime_history["decisions"]),
                "latest_incident_at": self._latest_timestamp(runtime_history["incidents"]),
            },
            "persisted": {
                "event_count": int(store_summary["counts"].get("events", len(persisted_history.get("events", []))) or 0),
                "decision_count": int(store_summary["counts"].get("decisions", len(persisted_history.get("decisions", []))) or 0),
                "incident_count": int(store_summary["counts"].get("incidents", len(persisted_history.get("incidents", []))) or 0),
                "metrics_count": int(store_summary["counts"].get("metrics", 0) or 0),
                "latest_event_at": store_summary["latest_at"].get("events") or self._latest_timestamp(persisted_history.get("events", [])),
                "latest_decision_at": store_summary["latest_at"].get("decisions") or self._latest_timestamp(persisted_history.get("decisions", [])),
                "latest_incident_at": store_summary["latest_at"].get("incidents") or self._latest_timestamp(persisted_history.get("incidents", [])),
                "latest_metrics_at": store_summary["latest_at"].get("metrics"),
            },
            "storage": {
                "path": persistence.get("path"),
                "available": bool(persistence.get("available", False)),
                "size_bytes": int(persistence.get("size_bytes", 0) or 0),
                "write_failed": bool(persistence.get("write_failed", False)),
            },
        }

    def _persist_runtime_metrics_snapshot(self, force: bool = False) -> dict | None:
        persistence = self.runtime_history_store.summarize()
        history = {
            "events": list(self.runtime_event_history),
            "decisions": list(self.decision_trace_history),
            "incidents": list(self.incident_history),
            "persisted": {
                "events": self.runtime_history_store.read_recent("events", limit=10),
                "decisions": self.runtime_history_store.read_recent("decisions", limit=10),
                "incidents": self.runtime_history_store.read_recent("incidents", limit=10),
                "metrics": self.runtime_history_store.read_recent("metrics", limit=10),
            },
        }
        local_metrics = self._build_local_metrics(history)
        snapshot = self._build_persisted_metrics_snapshot(local_metrics, history, persistence)
        signature = (
            snapshot["decision_count"],
            snapshot["blocked_count"],
            snapshot["fallback_count"],
            snapshot["runtime"]["event_count"],
            snapshot["runtime"]["incident_count"],
            snapshot["persisted"]["event_count"],
            snapshot["persisted"]["decision_count"],
            snapshot["persisted"]["incident_count"],
            snapshot["storage"]["size_bytes"],
            snapshot["storage"]["write_failed"],
        )
        now = datetime.now(UTC)
        should_persist = force

        if not should_persist and self._last_metrics_snapshot_signature != signature:
            should_persist = True
        if not should_persist and self._last_metrics_persisted_at is not None:
            should_persist = (now - self._last_metrics_persisted_at).total_seconds() >= 30.0

        if should_persist:
            self.runtime_history_store.append("metrics", snapshot)
            self._last_metrics_persisted_at = now
            self._last_metrics_snapshot_signature = signature
            self.metric_snapshot_history.appendleft(snapshot)
            self._publish_runtime_bridge_state()

        return snapshot
