"""Snapshots opérateur/observation/HITL et état du bridge runtime (extrait de src/main.py)."""
import asyncio
import logging

import numpy as np

from src.bot.runtime_types import CanonicalTableState
from src.runtime.go_live_gate import evaluate_go_live_gate
from src.runtime.policy_compare import (
    build_policy_compare_summary,
    build_runtime_ab_summary,
    dedupe_runtime_ab_decisions,
)
from src.runtime.session import parse_bool_flag as _parse_bool_flag
from src.vision.models import TableState

logger = logging.getLogger("SuperBot2026")


class OperatorSnapshotMixin:
    def _build_operator_snapshot(self) -> dict[str, object]:
        controls = dict(getattr(self, "operator_controls", {}) or {})
        paused = bool(controls.get("paused", False))
        assisted_mode_enabled = bool(controls.get("assisted_mode_enabled", False))
        observation_mode_enabled = bool(controls.get("observation_mode_enabled", False))
        shadow_mode_enabled = bool(controls.get("shadow_mode_enabled", False))
        manual_override_enabled = bool(controls.get("manual_override_enabled", False))
        auto_refresh_enabled = bool(controls.get("auto_refresh_enabled", True))
        is_running = bool(getattr(self, "is_running", True))
        go_live_gate = dict(getattr(self, "last_go_live_gate", {}) or {})
        go_live_gate_passed = bool(go_live_gate.get("passed", False))
        if not is_running:
            status = "offline"
        elif paused:
            status = "paused"
        elif manual_override_enabled:
            status = "manual_override"
        elif observation_mode_enabled:
            status = "observation"
        elif shadow_mode_enabled:
            status = "shadow"
        elif assisted_mode_enabled:
            status = "assisted"
        elif not go_live_gate_passed:
            status = "go_live_blocked"
        else:
            status = "ready"
        return {
            "profile_name": str(controls.get("profile_name") or "live-runtime"),
            "surface": str(controls.get("surface") or "bot_cockpit"),
            "capture_source": str(controls.get("capture_source") or "ocr"),
            "auto_refresh_enabled": auto_refresh_enabled,
            "assisted_mode_enabled": assisted_mode_enabled,
            "observation_mode_enabled": observation_mode_enabled,
            "shadow_mode_enabled": shadow_mode_enabled,
            "manual_override_enabled": manual_override_enabled,
            "paused": paused,
            "status": status,
            "go_live_gate": go_live_gate,
            "updated_at": str(controls.get("updated_at") or self._utc_now()),
        }

    def _build_observation_snapshot(self) -> dict[str, object]:
        database = getattr(self, "db", None)
        summary = dict(database.summarize_observation(limit=5) or {}) if database is not None else {}
        operator = self._build_operator_snapshot()
        mode_enabled = bool(operator.get("observation_mode_enabled", False))
        operator_status = str(operator.get("status") or "offline")
        observation_dataset = getattr(self, "observation_dataset", None)
        vision_dataset_snapshot = (
            observation_dataset.snapshot()
            if observation_dataset is not None and hasattr(observation_dataset, "snapshot")
            else {}
        )
        return {
            "mode_enabled": mode_enabled,
            "collecting": bool(
                bool(getattr(self, "is_running", True))
                and operator_status in {"ready", "assisted", "observation", "shadow"}
                and not bool(operator.get("paused", False))
            ),
            "vision_dataset": vision_dataset_snapshot,
            **summary,
        }

    def _capture_observation_dataset_sample(
        self,
        frame: np.ndarray,
        canonical_state: CanonicalTableState,
        detector_state: TableState,
    ) -> None:
        collector = getattr(self, "observation_dataset", None)
        if collector is None:
            return
        try:
            collector.maybe_capture(frame=frame, canonical_state=canonical_state, detector_state=detector_state)
        except Exception as exc:
            logger.warning("Capture observation YOLO ignoree: %s", exc)

    async def _capture_observation_dataset_sample_async(
        self,
        frame: np.ndarray,
        canonical_state: CanonicalTableState,
        detector_state: TableState,
    ) -> None:
        if bool(getattr(self, "_observation_capture_task_running", False)):
            return
        self._observation_capture_task_running = True
        try:
            frame_copy = frame.copy() if isinstance(frame, np.ndarray) else frame
            canonical_copy = canonical_state.model_copy(deep=True) if hasattr(canonical_state, "model_copy") else canonical_state
            detector_copy = self._copy_table_state(detector_state) if detector_state is not None else detector_state
            await asyncio.to_thread(
                self._capture_observation_dataset_sample,
                frame_copy,
                canonical_copy,
                detector_copy,
            )
        finally:
            self._observation_capture_task_running = False

    def _export_observation_dataset(self, player_limit: int = 50, hand_limit: int = 100) -> dict[str, object]:
        dataset = dict(self.db.export_observation_dataset(player_limit=player_limit, hand_limit=hand_limit) or {})
        dataset["session_id"] = self._get_runtime_session_id()
        dataset["mode_enabled"] = bool(self._build_operator_snapshot().get("observation_mode_enabled", False))
        dataset["is_running"] = bool(self.is_running)
        return dataset

    def _operator_action_mode(self) -> str:
        return str(self._build_operator_snapshot().get("status") or "ready")

    def update_operator_controls(self, patch: dict[str, object]) -> dict[str, object]:
        if not isinstance(patch, dict):
            return self._build_operator_snapshot()

        controls = dict(getattr(self, "operator_controls", {}) or {})
        current_snapshot = self._build_operator_snapshot()
        normalized_patch: dict[str, bool] = {}
        aliases = {
            "paused": ("paused",),
            "assisted_mode_enabled": ("assisted_mode_enabled", "assistedModeEnabled"),
            "observation_mode_enabled": ("observation_mode_enabled", "observationModeEnabled"),
            "shadow_mode_enabled": ("shadow_mode_enabled", "shadowModeEnabled"),
            "manual_override_enabled": ("manual_override_enabled", "manualOverrideEnabled"),
            "auto_refresh_enabled": ("auto_refresh_enabled", "autoRefreshEnabled"),
        }

        for canonical_key, candidate_keys in aliases.items():
            for candidate_key in candidate_keys:
                if candidate_key not in patch:
                    continue
                parsed_value = _parse_bool_flag(patch.get(candidate_key))
                if parsed_value is not None:
                    normalized_patch[canonical_key] = parsed_value
                break

        if not normalized_patch:
            return current_snapshot

        controls.update(normalized_patch)
        if normalized_patch.get("assisted_mode_enabled"):
            controls["observation_mode_enabled"] = False
            controls["shadow_mode_enabled"] = False
            controls["manual_override_enabled"] = False
        if normalized_patch.get("observation_mode_enabled"):
            controls["assisted_mode_enabled"] = False
            controls["shadow_mode_enabled"] = False
            controls["manual_override_enabled"] = False
        if normalized_patch.get("shadow_mode_enabled"):
            controls["assisted_mode_enabled"] = False
            controls["observation_mode_enabled"] = False
            controls["manual_override_enabled"] = False
        if normalized_patch.get("manual_override_enabled"):
            controls["assisted_mode_enabled"] = False
            controls["observation_mode_enabled"] = False
            controls["shadow_mode_enabled"] = False
        controls["updated_at"] = self._utc_now()
        self.operator_controls = controls

        next_snapshot = self._build_operator_snapshot()
        changed_fields = {
            key: next_snapshot.get(key)
            for key in (
                "paused",
                "assisted_mode_enabled",
                "observation_mode_enabled",
                "shadow_mode_enabled",
                "manual_override_enabled",
                "auto_refresh_enabled",
                "status",
            )
            if next_snapshot.get(key) != current_snapshot.get(key)
        }
        if changed_fields:
            self._push_runtime_event(
                "operator",
                "controls_updated",
                previous_status=current_snapshot.get("status", "offline"),
                **changed_fields,
            )
        self._publish_runtime_bridge_state(force=True)

        return next_snapshot

    def _build_hitl_snapshot(self) -> dict[str, object]:
        current_issue = self.hitl.current_issue if isinstance(self.hitl.current_issue, dict) else None
        serialized_issue = None
        if current_issue is not None:
            serialized_issue = {
                "type": current_issue.get("type"),
                "reason": current_issue.get("reason"),
                "image_base64": current_issue.get("image_base64"),
                "width": current_issue.get("width"),
                "height": current_issue.get("height"),
                "resolution": current_issue.get("resolution"),
            }
        return {
            "ready_for_training": bool(self.hitl.check_convergence()),
            "collected_samples": int(getattr(self.hitl, "annotations_count", 0) or 0),
            "target_samples": int(getattr(self.hitl, "target_dataset_size", 0) or 0),
            "is_waiting_for_human": bool(getattr(self.hitl, "is_waiting_for_human", False)),
            "current_issue": serialized_issue,
        }

    def _build_runtime_bridge_state(self) -> dict[str, object]:
        health_snapshot = self.health_monitor.snapshot() if getattr(self, "health_monitor", None) is not None else {}
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
        metrics_snapshot = self._build_persisted_metrics_snapshot(local_metrics, history, self.runtime_history_store.summarize())
        current_readiness = dict(self.last_decision_summary.get("runtime_readiness", {}) or {})
        current_validation = dict((self.last_resolved_runtime_state or {}).get("metadata", {}).get("poker_state_validation", {}) or {}) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else {}
        go_live_gate = evaluate_go_live_gate(
            local_metrics,
            metrics_snapshot,
            readiness=current_readiness,
            validation=current_validation,
            thresholds=getattr(self, "go_live_gate_thresholds", {}),
        )
        self.last_go_live_gate = go_live_gate.to_dict()
        return {
            "generated_at": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "is_running": bool(self.is_running),
            "app_name": "PokerMaster",
            "service": "PokerMaster",
            "version": "v2",
            "runtime_api_port": self.runtime_api_port,
            "tracker": dict(self.last_tracker_snapshot),
            "canonical_spot": dict(self.last_canonical_spot_snapshot) if isinstance(self.last_canonical_spot_snapshot, dict) else None,
            "gate": self.last_gate_result.to_dict(),
            "decision": dict(self.last_decision_summary),
            "readiness": dict(self.last_decision_summary.get("runtime_readiness", {}) or {}),
            "go_live_gate": go_live_gate.to_dict(),
            "health": health_snapshot,
            "active_solver_backend": self.solver_provider.active_backend() if getattr(self, "solver_provider", None) is not None else "fallback",
            "degraded_reasons": self.health_monitor.degraded_reasons() if getattr(self, "health_monitor", None) is not None else [],
            "last_success_at": self.health_monitor.overall_last_success_at() if getattr(self, "health_monitor", None) is not None else None,
            "operator": self._build_operator_snapshot(),
            "observation": self._build_observation_snapshot(),
            "loop_stage": str(getattr(self, "_loop_stage", "")),
            "history": {
                "events": list(self.runtime_event_history),
                "decisions": list(self.decision_trace_history),
                "incidents": list(self.incident_history),
                "metrics": list(self.metric_snapshot_history),
            },
            "hitl": self._build_hitl_snapshot(),
        }

    def _publish_runtime_bridge_state(self, force: bool = False) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.publish_state(force=force)

    def _set_loop_stage(self, stage: str, publish: bool = False) -> None:
        self._loop_stage = str(stage or "")
        if publish:
            self._publish_runtime_bridge_state(force=True)

    def _apply_bridge_command(self, command: dict[str, object]) -> None:
        kind = str(command.get("kind") or "").strip().lower()
        payload = dict(command.get("payload") or {})
        command_id = str(command.get("command_id") or "")

        if kind == "operator_patch":
            applied = self.update_operator_controls(payload)
            self._push_runtime_event(
                "operator",
                "bridge_operator_patch_applied",
                command_id=command_id,
                status=applied.get("status", "unknown"),
            )
            return

        if kind == "hitl_resolve":
            boxes = payload.get("boxes", [])
            if bool(self.hitl.is_waiting_for_human):
                self.hitl.resolve_human_intervention(list(boxes or []))
                self._push_runtime_event(
                    "hitl",
                    "bridge_hitl_resolved",
                    command_id=command_id,
                    box_count=len(list(boxes or [])),
                )
            else:
                self._push_runtime_event(
                    "hitl",
                    "bridge_hitl_ignored",
                    command_id=command_id,
                    reason="not_waiting_for_human",
                )
            return

        self._push_incident(
            "bridge_unknown_command",
            severity="warning",
            command_id=command_id,
            kind=kind or "unknown",
        )

    def _process_bridge_commands(self) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.process_pending_commands(limit=8)

    def _start_runtime_api_process(self) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.start_api_process()

    def _stop_runtime_api_process(self) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.stop_api_process()

    def _get_runtime_status(self) -> dict:
        persistence = self.runtime_history_store.summarize()
        persisted_history = {
            "events": self.runtime_history_store.read_recent("events", limit=10),
            "decisions": self.runtime_history_store.read_recent("decisions", limit=10),
            "incidents": self.runtime_history_store.read_recent("incidents", limit=10),
            "metrics": self.runtime_history_store.read_recent("metrics", limit=10),
        }
        history = {
            "events": list(self.runtime_event_history),
            "decisions": list(self.decision_trace_history),
            "incidents": list(self.incident_history),
            "metrics": list(self.metric_snapshot_history),
            "persisted": persisted_history,
        }
        local_metrics = self._build_local_metrics(history)
        metrics_snapshot = self._build_persisted_metrics_snapshot(local_metrics, history, persistence)
        current_readiness = dict(self.last_decision_summary.get("runtime_readiness", {}) or {})
        current_validation = dict((self.last_resolved_runtime_state or {}).get("metadata", {}).get("poker_state_validation", {}) or {}) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else {}
        go_live_gate = evaluate_go_live_gate(
            local_metrics,
            metrics_snapshot,
            readiness=current_readiness,
            validation=current_validation,
            thresholds=getattr(self, "go_live_gate_thresholds", {}),
        )
        self.last_go_live_gate = go_live_gate.to_dict()
        runtime_ab_summary = build_runtime_ab_summary(history["decisions"])
        persisted_ab_summary = build_runtime_ab_summary(persisted_history["decisions"])
        combined_decisions = dedupe_runtime_ab_decisions(
            list(history["decisions"]) + list(persisted_history["decisions"])
        )
        combined_ab_summary = build_runtime_ab_summary(
            combined_decisions
        )
        runtime_policy_compare_summary = build_policy_compare_summary(history["decisions"])
        persisted_policy_compare_summary = build_policy_compare_summary(persisted_history["decisions"])
        combined_policy_compare_summary = build_policy_compare_summary(combined_decisions)
        if not history["metrics"]:
            history["metrics"] = [metrics_snapshot]
        observation = self._build_observation_snapshot()
        return {
            "is_running": self.is_running,
            "app_name": "PokerMaster",
            "service": "PokerMaster",
            "version": "v2",
            "session_id": self._get_runtime_session_id(),
            "tracker": self.last_tracker_snapshot,
            "canonical_spot": dict(getattr(self, "last_resolved_runtime_state", None)) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else (dict(self.last_canonical_spot_snapshot) if isinstance(self.last_canonical_spot_snapshot, dict) else None),
            "gate": self.last_gate_result.to_dict(),
            "decision": self.last_decision_summary,
            "readiness": dict(self.last_decision_summary.get("runtime_readiness", {}) or {}),
            "go_live_gate": go_live_gate.to_dict(),
            "operator": self._build_operator_snapshot(),
            "observation": observation,
            "history": history,
            "metrics": {
                **local_metrics,
                "latest_snapshot": metrics_snapshot,
            },
            "history_summary": {
                "event_count": len(history["events"]),
                "decision_count": len(history["decisions"]),
                "incident_count": len(history["incidents"]),
                "metrics_count": len(history["metrics"]),
                "latest_event_at": history["events"][0]["timestamp"] if history["events"] else None,
                "latest_decision_at": history["decisions"][0]["timestamp"] if history["decisions"] else None,
                "latest_incident_at": history["incidents"][0]["timestamp"] if history["incidents"] else None,
                "latest_metrics_at": history["metrics"][0]["timestamp"] if history["metrics"] else None,
                "metrics_window_size": local_metrics["window_size"],
                "persisted_event_count": len(persisted_history["events"]),
                "persisted_decision_count": len(persisted_history["decisions"]),
                "persisted_incident_count": len(persisted_history["incidents"]),
                "persisted_metrics_count": len(persisted_history["metrics"]),
                "latest_persisted_event_at": persisted_history["events"][0]["timestamp"] if persisted_history["events"] else None,
                "latest_persisted_decision_at": persisted_history["decisions"][0]["timestamp"] if persisted_history["decisions"] else None,
                "latest_persisted_incident_at": persisted_history["incidents"][0]["timestamp"] if persisted_history["incidents"] else None,
                "latest_persisted_metrics_at": persisted_history["metrics"][0]["timestamp"] if persisted_history["metrics"] else None,
                "rl_ab": {
                    "runtime": runtime_ab_summary,
                    "persisted": persisted_ab_summary,
                    "combined": combined_ab_summary,
                },
                "policy_compare": {
                    "runtime": runtime_policy_compare_summary,
                    "persisted": persisted_policy_compare_summary,
                    "combined": combined_policy_compare_summary,
                },
                "persistence": persistence,
            },
        }

