"""Flux de décision/gate live (extrait de src/main.py)."""
import logging
import time
from collections import deque

import numpy as np

from src.bot.runtime_types import CanonicalTableState
from src.bot.sanity_checker import ActionIntent, GateReason, GateResult
from src.vision.models import TableState

logger = logging.getLogger("SuperBot2026")


def compact_solver_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}

    original = dict(payload)
    compact = dict(payload)
    alternatives = compact.get("alternatives")
    if not isinstance(alternatives, list):
        alternatives = []
    compact["alternatives"] = [dict(item) for item in alternatives if isinstance(item, dict)]

    if "alternatives_complete" in original and isinstance(compact.get("alternatives_complete"), list):
        compact["alternatives_complete"] = [
            dict(item) for item in compact.get("alternatives_complete", []) if isinstance(item, dict)
        ]
    else:
        compact.pop("alternatives_complete", None)

    for map_key in ("ev_by_action", "freq_by_action", "action_metadata", "backend_details", "cache_details"):
        value = compact.get(map_key)
        if not isinstance(value, dict):
            compact.pop(map_key, None)

    for float_key in ("elapsed_ms", "exploitability"):
        value = compact.get(float_key)
        if isinstance(value, (int, float)):
            compact[float_key] = float(value)
        else:
            compact.pop(float_key, None)

    node_count = compact.get("node_count")
    if isinstance(node_count, (int, float)):
        compact["node_count"] = int(node_count)
    else:
        compact.pop("node_count", None)

    for string_key in ("backend", "solver_id", "preset_id"):
        value = compact.get(string_key)
        if value in (None, ""):
            compact.pop(string_key, None)
        else:
            compact[string_key] = str(value)

    warnings = compact.get("warnings")
    if isinstance(warnings, list):
        compact["warnings"] = [str(item) for item in warnings if str(item).strip()]
    elif warnings is not None:
        compact.pop("warnings", None)

    for list_key in ("warning_details", "action_buckets"):
        values = compact.get(list_key)
        if isinstance(values, list):
            compact[list_key] = [dict(item) if isinstance(item, dict) else str(item) for item in values if str(item).strip()]
        elif values is not None:
            compact.pop(list_key, None)

    return compact


class GateFlowMixin:
    def _record_runtime_failure(
        self,
        *,
        category: str,
        incident_id: str,
        severity: str = "warning",
        context: dict | None = None,
    ) -> None:
        dataset = getattr(self, "runtime_failure_dataset", None)
        if dataset is None:
            return
        payload = {
            "timestamp": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "category": str(category or "incident"),
            "incident_id": str(incident_id or "unknown"),
            "severity": str(severity or "warning"),
            "context": dict(context or {}),
            "decision": dict(self.last_decision_summary or {}),
            "tracker": dict(self.last_tracker_snapshot or {}),
            "canonical_spot": dict(self.last_resolved_runtime_state or {}) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else None,
            "runtime_readiness": dict(self.last_decision_summary.get("runtime_readiness", {}) or {}),
            "fallback_execution_readiness": dict(self.last_decision_summary.get("fallback_execution_readiness", {}) or {}),
            "frame": self.last_valid_frame.copy() if isinstance(getattr(self, "last_valid_frame", None), np.ndarray) else None,
            "crops": self._build_runtime_failure_crops(),
        }
        dataset.record_incident(payload)

        operator = self._build_operator_snapshot() if hasattr(self, "_build_operator_snapshot") else {}
        shadow_mode_enabled = bool(operator.get("shadow_mode_enabled", False))
        hitl = getattr(self, "hitl", None)
        if shadow_mode_enabled and hitl is not None and hasattr(hitl, "record_shadow_failure"):
            try:
                hitl.record_shadow_failure(
                    payload.get("frame"),
                    issue_type=str(incident_id or category or "runtime_failure"),
                    reason=str((context or {}).get("reason") or incident_id or category or "runtime_failure"),
                    context={
                        "category": str(category or "incident"),
                        "severity": str(severity or "warning"),
                        "runtime_context": dict(context or {}),
                        "tracker": dict(self.last_tracker_snapshot or {}),
                    },
                )
            except Exception as exc:
                logger.debug("Shadow mode capture ignoree: %s", exc)

    def _record_shadow_mode_failure(self, issue_type: str, reason: str, **context) -> None:
        operator = self._build_operator_snapshot()
        if not bool(operator.get("shadow_mode_enabled", False)):
            return
        hitl = getattr(self, "hitl", None)
        if hitl is None or not hasattr(hitl, "record_shadow_failure"):
            return
        frame = self.last_valid_frame.copy() if isinstance(getattr(self, "last_valid_frame", None), np.ndarray) else None
        hitl.record_shadow_failure(frame, issue_type=issue_type, reason=reason, context=context)

    def _on_action_gate_failure(
        self,
        gate_result: GateResult,
        canonical_state: CanonicalTableState,
        action_intent: ActionIntent,
    ) -> None:
        reason_codes = [reason.code for reason in (gate_result.reasons or [])]
        if any(code in {"HERO_CARDS_UNCERTAIN", "STATE_INCOHERENT", "BOARD_UNCERTAIN", "MISSING_POSTFLOP_POT", "LOW_STATE_CONFIDENCE"} for code in reason_codes):
            self._record_shadow_mode_failure(
                issue_type="sanity_gate_failure",
                reason=gate_result.reason,
                spot_id=str(canonical_state.spot_id or ""),
                action=action_intent.action,
                street=str(canonical_state.street or "IDLE"),
                board=list(canonical_state.board),
                hero_cards=list(canonical_state.hero_cards),
                reason_codes=reason_codes,
            )

    async def _run_decision_gate_flow(
        self,
        canonical_state: CanonicalTableState,
        state: TableState,
        primary_villain,
        effective_stack: float,
        gate_tracker_snapshot: dict[str, object] | None = None,
        frame_age_ms: float | None = None,
    ) -> dict:
        dynamic_coords = self._get_dynamic_coordinates(state)
        hero_position = self._derive_live_hero_position(primary_villain)
        locked_skip = self._build_locked_decision_skip(canonical_state)
        if locked_skip:
            reason = str(locked_skip.get("reason", "same_spot_locked") or "same_spot_locked")
            action_name = str(locked_skip.get("action", "") or "").strip().upper()
            self.last_gate_result = GateResult(allowed=True, status="locked_skip", reasons=[])
            self.last_decision_summary.update(
                {
                    "action": action_name,
                    "source": "LOCKED_SPOT_SKIP",
                    "confidence": float(self.last_decision_summary.get("confidence", 0.0) or 0.0),
                    "cache_hit": True,
                    "elapsed_ms": 0.0,
                    "backend": "locked_skip",
                    "action_history": list(self.tracker.current_hand_actions),
                    "spot_id": canonical_state.spot_id,
                    "street": canonical_state.street,
                    "hero_cards": list(canonical_state.hero_cards),
                    "board": list(canonical_state.board),
                    "frame_age_ms": float(frame_age_ms or 0.0),
                    "hero_position": hero_position,
                    "effective_stack": float(effective_stack or 0.0),
                    "villain_name": primary_villain.name,
                    "gate_confidence": 1.0,
                    "gate_reason": reason,
                    "gate_allowed": True,
                    "trace_updated_at": self._utc_now(),
                    "history": {
                        "fallback": list(self.last_decision_summary.get("history", {}).get("fallback", []) or []),
                        "warnings": [],
                        "incidents": [reason],
                    },
                    "execution": {
                        "status": "decision_locked",
                        "reason": reason,
                    },
                }
            )
            if locked_skip.get("log_now"):
                logger.info(
                    "DECISION | skipped reason=%s action=%s street=%s hero=%s legal=%s",
                    reason,
                    action_name or "-",
                    canonical_state.street,
                    self._format_log_cards(canonical_state.hero_cards),
                    self._format_log_list(canonical_state.legal_actions),
                )
                self._push_runtime_event(
                    "decision",
                    "decision_skipped_locked",
                    action=action_name,
                    reason=reason,
                    spot_id=canonical_state.spot_id,
                )
            return {
                "decision": self._build_minimal_skipped_decision(canonical_state, action_name, reason),
                "gate_result": self.last_gate_result,
                "dynamic_coords": dynamic_coords,
            }

        decision = self._get_cached_live_decision(canonical_state)
        if decision is None:
            decision = await self.decision_maker.get_best_action(
                hero_hand="".join(canonical_state.hero_cards),
                board=list(canonical_state.board),
                pot=canonical_state.pot,
                effective_stack=effective_stack,
                villain_name=primary_villain.name,
                legal_actions=list(canonical_state.legal_actions),
                spot_id=canonical_state.spot_id,
                hero_position=hero_position,
                state_confidence=canonical_state.state_confidence,
                action_history=self.tracker.current_hand_actions,
            )
            self._remember_cached_live_decision(canonical_state, decision)
        else:
            decision["cache_hit"] = True
        normalized_incidents = self._normalize_incidents(list(decision.get("incidents", [])))
        self.last_decision_summary = {
            "action": decision.get("action", ""),
            "source": decision.get("source", "unknown"),
            "confidence": decision.get("confidence", 0.0),
            "observed_hands": int(decision.get("profile", {}).get("observed_hands", 0) or 0),
            "cache_hit": bool(decision.get("cache_hit", False)),
            "fallback_used": bool(decision.get("fallback_used", False)),
            "fallback_reason": decision.get("fallback_reason"),
            "warnings": list(decision.get("warnings", [])),
            "incidents": normalized_incidents,
            "elapsed_ms": decision.get("elapsed_ms", 0),
            "backend": decision.get("backend", "unknown"),
            "action_history": list(self.tracker.current_hand_actions),
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "hero_cards": list(canonical_state.hero_cards),
            "board": list(canonical_state.board),
            "frame_age_ms": float(frame_age_ms or 0.0),
            "hero_position": hero_position,
            "effective_stack": float(effective_stack or 0.0),
            "villain_name": primary_villain.name,
            "ab_decision": decision.get("ab_decision"),
            "profile": dict(decision.get("metadata", {}).get("profile", {})),
            "solver": compact_solver_payload(decision.get("metadata", {}).get("solver", {})),
            "confidence_details": dict(decision.get("metadata", {}).get("confidence", {})),
        }

        action_intent = ActionIntent.from_payload(decision)
        gate_tracker_state = dict(gate_tracker_snapshot or self._build_gate_tracker_snapshot(canonical_state))
        gate_result = self.runtime_sanity.evaluate_action_gate(
            action_intent=action_intent,
            tracker_state=gate_tracker_state,
            coords_mapping=dynamic_coords,
            on_failure=lambda result: self._on_action_gate_failure(result, canonical_state, action_intent),
        )
        fallback_execution_readiness = self._evaluate_fallback_execution_readiness(
            canonical_state,
            frame_age_ms=frame_age_ms,
        )
        self.last_gate_result = gate_result
        self.last_decision_summary["gate_confidence"] = float(gate_result.confidence or 0.0)
        self.last_decision_summary["gate_reason"] = gate_result.reason
        self.last_decision_summary["gate_allowed"] = gate_result.allowed
        self.last_decision_summary["fallback_execution_readiness"] = fallback_execution_readiness
        assisted_result = self._evaluate_assisted_execution(canonical_state, decision, gate_result)
        self.last_decision_summary["assisted"] = assisted_result
        self.last_decision_summary["trace_updated_at"] = self._utc_now()
        self.last_decision_summary["history"] = {
            "fallback": [decision.get("fallback_reason")] if decision.get("fallback_reason") else [],
            "warnings": list(decision.get("warnings", [])),
            "incidents": self._normalize_incidents(normalized_incidents + (["gate_blocked"] if not gate_result.allowed else [])),
        }
        logger.info(
            "DECISION | street=%s hero=%s board=%s action=%s source=%s conf=%.2f fallback=%s gate=%s/%s assisted=%s",
            canonical_state.street,
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_cards(canonical_state.board),
            decision.get("action", ""),
            decision.get("source", "unknown"),
            float(decision.get("confidence", 0.0) or 0.0),
            "yes" if decision.get("fallback_used", False) else "no",
            "ok" if gate_result.allowed else "blocked",
            gate_result.reason,
            assisted_result.get("reason", "unknown"),
        )
        self._record_decision_trace(canonical_state, decision, gate_result)
        self._push_runtime_event(
            "decision",
            "decision_ready",
            action=decision.get("action", ""),
            source=decision.get("source", "unknown"),
            spot_id=canonical_state.spot_id,
            confidence=float(decision.get("confidence", 0.0) or 0.0),
            gate_allowed=bool(gate_result.allowed),
        )

        for warning in decision.get("warnings", []):
            self._push_runtime_event("warning", warning, spot_id=canonical_state.spot_id)
        for incident in normalized_incidents:
            self._push_incident(str(incident), severity="warning", spot_id=canonical_state.spot_id)
        if not gate_result.allowed:
            self.last_decision_summary["execution"] = {
                "status": "blocked_by_gate",
                "reason": gate_result.reason,
            }
            logger.warning(
                "CLICK | blocked_by_gate action=%s reason=%s legal=%s hero=%s board=%s",
                decision.get("action", ""),
                gate_result.reason,
                self._format_log_list(canonical_state.legal_actions),
                self._format_log_cards(canonical_state.hero_cards),
                self._format_log_cards(canonical_state.board),
            )
            self._push_incident("gate_blocked", severity="error", reason=gate_result.reason)
            self._push_runtime_event(
                "gate",
                "action_blocked",
                action=decision.get("action", ""),
                reason=gate_result.reason,
                spot_id=canonical_state.spot_id,
            )
        else:
            operator_mode = self._operator_action_mode()
            self.last_decision_summary["operator_status"] = operator_mode
            if operator_mode in {"paused", "observation", "shadow", "manual_override", "go_live_blocked"}:
                self.last_decision_summary["execution"] = {
                    "status": "suppressed_by_operator",
                    "reason": operator_mode,
                }
                logger.info(
                    "CLICK | suppressed action=%s operator=%s",
                    decision.get("action", ""),
                    operator_mode,
                )
                self._push_runtime_event(
                    "operator",
                    "action_suppressed",
                    action=decision.get("action", ""),
                    spot_id=canonical_state.spot_id,
                    operator_status=operator_mode,
                )
            elif operator_mode == "assisted" and not assisted_result.get("auto_execute", False):
                self.last_decision_summary["execution"] = {
                    "status": "manual_required",
                    "reason": assisted_result.get("reason", "manual_review_required"),
                }
                logger.info(
                    "CLICK | manual_required action=%s reason=%s hero=%s board=%s legal=%s",
                    decision.get("action", ""),
                    assisted_result.get("reason", "manual_review_required"),
                    self._format_log_cards(canonical_state.hero_cards),
                    self._format_log_cards(canonical_state.board),
                    self._format_log_list(canonical_state.legal_actions),
                )
                self._push_runtime_event(
                    "operator",
                    "manual_action_required",
                    action=decision.get("action", ""),
                    spot_id=canonical_state.spot_id,
                    operator_status=operator_mode,
                    assisted_reason=assisted_result.get("reason", "manual_review_required"),
                )
            else:
                action_name = str(decision.get("action", "") or "").strip().upper()
                if self._should_suppress_recent_live_execution(canonical_state):
                    suppression_reason = "same_spot_unconfirmed" if str(getattr(self, "_last_live_execution_settle_status", "") or "").strip().lower() == "timeout" else "same_hand_post_action_guard"
                    self._remember_locked_decision(canonical_state, action_name or decision.get("action", ""), suppression_reason)
                    self.last_decision_summary["execution"] = {
                        "status": "suppressed_recent_execution",
                        "reason": suppression_reason,
                    }
                    if self._should_log_locked_decision(canonical_state, suppression_reason):
                        logger.warning(
                            "CLICK | recent_execution_suppressed action=%s hero=%s board=%s legal=%s",
                            decision.get("action", ""),
                            self._format_log_cards(canonical_state.hero_cards),
                            self._format_log_cards(canonical_state.board),
                            self._format_log_list(canonical_state.legal_actions),
                        )
                        self._push_runtime_event(
                            "action",
                            "suppressed_recent_execution",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                        )
                    return {
                        "decision": decision,
                        "gate_result": gate_result,
                        "dynamic_coords": dynamic_coords,
                    }
                if self._should_suppress_duplicate_live_action(canonical_state, action_name):
                    self._remember_locked_decision(canonical_state, action_name or decision.get("action", ""), "same_live_spot_cooldown")
                    self.last_decision_summary["execution"] = {
                        "status": "suppressed_duplicate",
                        "reason": "same_live_spot_cooldown",
                    }
                    if self._should_log_locked_decision(canonical_state, "same_live_spot_cooldown"):
                        logger.warning(
                            "CLICK | duplicate_suppressed action=%s hero=%s board=%s legal=%s",
                            decision.get("action", ""),
                            self._format_log_cards(canonical_state.hero_cards),
                            self._format_log_cards(canonical_state.board),
                            self._format_log_list(canonical_state.legal_actions),
                        )
                        self._push_runtime_event(
                            "action",
                            "suppressed_duplicate",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                        )
                    return {
                        "decision": decision,
                        "gate_result": gate_result,
                        "dynamic_coords": dynamic_coords,
                    }
                async def _update_jit_baseline():
                    frame = self.camera.get_latest_frame()
                    if frame is not None:
                        self._last_visual_previews = self._capture_live_visual_previews(frame)

                try:
                    try:
                        execution_result = await self.action_controller.execute_action(
                            action_intent,
                            dynamic_coords,
                            jit_check=self._jit_action_validator,
                            update_jit_baseline=_update_jit_baseline
                        )
                    except TypeError as action_err:
                        if "update_jit_baseline" not in str(action_err):
                            raise
                        execution_result = await self.action_controller.execute_action(
                            action_intent,
                            dynamic_coords,
                            jit_check=self._jit_action_validator,
                        )
                except Exception as jit_err:
                    if "JIT Check Failed" in str(jit_err):
                        self._clear_live_decision_summary(canonical_state)
                        self.last_decision_summary["execution"] = {
                            "status": "aborted_jit",
                            "reason": "JIT Check Failed",
                        }
                        logger.warning("CLICK | aborted_jit action=%s", decision.get("action", ""))
                        self._push_incident("jit_abort", severity="warning", reason="Actions region mutated")
                        execution_result = {"ok": False, "reason": "JIT Abort"}
                    else:
                        raise
                execution_ok = bool((execution_result or {}).get("ok"))
                execution_reason = (
                    "assisted_runtime" if operator_mode == "assisted" else "live_runtime"
                ) if execution_ok else str((execution_result or {}).get("reason", "click_failed"))
                self.last_decision_summary["execution"] = {
                    "status": "executed" if execution_ok else "click_failed",
                    "reason": execution_reason,
                    "details": dict(execution_result or {}),
                }
                if execution_ok:
                    logger.info(
                        "CLICK | applied action=%s operator=%s target=%s",
                        decision.get("action", ""),
                        operator_mode,
                        (execution_result or {}).get("target"),
                    )
                    settle_result = await self._wait_for_action_settle()
                    self.last_decision_summary["execution"]["settle"] = dict(settle_result)
                    settle_status = "ok" if settle_result.get("settled") else "timeout"
                    if settle_status == "timeout":
                        self.last_decision_summary["execution"]["status"] = "unsettled_timeout"
                        self.last_decision_summary["execution"]["reason"] = "same_spot_unconfirmed"
                    logger.info(
                        "CLICK | settle status=%s elapsed_ms=%.1f buttons=%s",
                        settle_status,
                        float(settle_result.get("elapsed_ms", 0.0) or 0.0),
                        self._format_log_list(settle_result.get("buttons", [])),
                    )
                    self._remember_live_execution(
                        canonical_state,
                        action_name or decision.get("action", ""),
                        "executed",
                        settle_status=settle_status,
                    )
                    if settle_status == "timeout":
                        self._remember_locked_decision(canonical_state, action_name or decision.get("action", ""), "same_spot_unconfirmed")
                    else:
                        self._clear_live_decision_lock()
                    if settle_status == "timeout":
                        self._push_incident(
                            "action_unsettled_lock",
                            severity="warning",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                            buttons=list(settle_result.get("buttons", [])),
                        )
                        self._push_runtime_event(
                            "action",
                            "unsettled_timeout",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                            buttons=list(settle_result.get("buttons", [])),
                        )
                    self._push_runtime_event(
                        "action",
                        "executed_action",
                        action=decision.get("action", ""),
                        spot_id=canonical_state.spot_id,
                        operator_status=operator_mode,
                        execution=dict(execution_result or {}),
                    )
                else:
                    self._clear_live_decision_lock()
                    self._remember_live_execution(
                        canonical_state,
                        action_name or decision.get("action", ""),
                        self.last_decision_summary["execution"]["status"],
                    )
                    logger.error(
                        "CLICK | failed action=%s operator=%s reason=%s coords=%s",
                        decision.get("action", ""),
                        operator_mode,
                        execution_reason,
                        dynamic_coords,
                    )
                    self._push_incident(
                        "action_click_failed",
                        severity="error",
                        action=decision.get("action", ""),
                        reason=execution_reason,
                        operator_status=operator_mode,
                    )
                    self._push_runtime_event(
                        "action",
                        "click_failed",
                        action=decision.get("action", ""),
                        spot_id=canonical_state.spot_id,
                        operator_status=operator_mode,
                        execution=dict(execution_result or {}),
                    )

        return {
            "decision": decision,
            "gate_result": gate_result,
            "dynamic_coords": dynamic_coords,
        }

    def _evaluate_fallback_execution_readiness(
        self,
        canonical_state: CanonicalTableState,
        *,
        frame_age_ms: float | None = None,
    ) -> dict[str, object]:
        legal_actions = {str(action).strip().upper() for action in (canonical_state.legal_actions or ())}
        action_buttons = tuple(sorted(str(button).strip().lower() for button in (canonical_state.action_buttons or ()) if str(button).strip()))
        target_action = "CHECK" if "CHECK" in legal_actions else ("FOLD" if "FOLD" in legal_actions else "")
        target_button = "check_button" if target_action == "CHECK" else ("fold_button" if target_action == "FOLD" else "")

        signature_history = getattr(self, "_recent_runtime_action_button_signatures", None)
        if signature_history is None:
            signature_history = deque(maxlen=5)
            self._recent_runtime_action_button_signatures = signature_history
        signature_history.append(action_buttons)
        stable_signature_count = sum(1 for signature in signature_history if signature and signature == action_buttons)
        button_signature_stable = bool(action_buttons) and stable_signature_count >= 3

        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        vision_metadata = dict(metadata.get("vision", {}) or {})
        visual_changed_regions = {str(region).lower() for region in (vision_metadata.get("visual_changed_regions", []) or [])}
        actions_region_stable = "actions" not in visual_changed_regions

        action_controller = getattr(self, "action_controller", None)
        target_hwnd = int(getattr(action_controller, "hwnd", 0) or 0)
        window_bound = target_hwnd > 0
        foreground_confirmed = False
        foreground_getter = getattr(action_controller, "_get_foreground_window", None)
        if window_bound and callable(foreground_getter):
            try:
                foreground_confirmed = int(foreground_getter() or 0) == target_hwnd
            except Exception:
                foreground_confirmed = False

        frame_fresh = frame_age_ms is not None and float(frame_age_ms or 0.0) <= 300.0
        hero_turn_confirmed = bool(legal_actions) and bool(
            set(action_buttons).intersection(
                {
                    "fold_button",
                    "call_button",
                    "check_button",
                    "bet_button",
                    "raise_button",
                    "all_in_call_button",
                }
            )
        )
        target_button_present = bool(target_button) and target_button in action_buttons

        reasons = []
        if not window_bound:
            reasons.append("window_unbound")
        if not foreground_confirmed:
            reasons.append("window_not_foreground")
        if not frame_fresh:
            reasons.append("stale_frame")
        if not hero_turn_confirmed:
            reasons.append("hero_turn_unconfirmed")
        if not target_action:
            reasons.append("no_conservative_action")
        if not target_button_present:
            reasons.append("target_button_missing")
        if not button_signature_stable:
            reasons.append("buttons_not_stable")
        if not actions_region_stable:
            reasons.append("actions_region_changed")

        ready = not reasons
        score_parts = [
            1.0 if window_bound else 0.0,
            1.0 if foreground_confirmed else 0.0,
            1.0 if frame_fresh else 0.0,
            1.0 if hero_turn_confirmed else 0.0,
            1.0 if target_button_present else 0.0,
            1.0 if button_signature_stable else 0.0,
            1.0 if actions_region_stable else 0.0,
        ]
        score = round(sum(score_parts) / len(score_parts), 3)
        return {
            "status": "ready" if ready else "blocked",
            "score": score,
            "recommended_action": target_action or None,
            "target_button": target_button or None,
            "reasons": reasons,
            "signals": {
                "window_bound": window_bound,
                "foreground_confirmed": foreground_confirmed,
                "frame_fresh": frame_fresh,
                "hero_turn_confirmed": hero_turn_confirmed,
                "target_button_present": target_button_present,
                "button_signature_stable": button_signature_stable,
                "actions_region_stable": actions_region_stable,
                "stable_signature_count": stable_signature_count,
                "visual_changed_regions": sorted(visual_changed_regions),
                "frame_age_ms": None if frame_age_ms is None else round(float(frame_age_ms or 0.0), 1),
            },
        }

    def _handle_stale_live_frame(self, canonical_state: CanonicalTableState, frame_age_s: float) -> None:
        frame_age_ms = round(max(frame_age_s, 0.0) * 1000.0, 1)
        max_age_ms = round(self._max_live_frame_age_s * 1000.0, 1)
        self._clear_live_decision_summary(canonical_state)
        self.last_gate_result = GateResult(
            allowed=False,
            status="blocked",
            reasons=[
                GateReason(
                    code="STALE_FRAME",
                    message="La frame live est trop ancienne pour une action fiable.",
                    context={
                        "frame_age_ms": frame_age_ms,
                        "max_age_ms": max_age_ms,
                    },
                )
            ],
            confidence=0.0,
        )
        self.last_decision_summary["gate_confidence"] = 0.0
        self.last_decision_summary["gate_reason"] = "STALE_FRAME"
        self.last_decision_summary["gate_allowed"] = False
        self.last_decision_summary["frame_age_ms"] = frame_age_ms
        self.last_decision_summary["fallback_execution_readiness"] = self._evaluate_fallback_execution_readiness(
            canonical_state,
            frame_age_ms=frame_age_ms,
        )
        self.last_decision_summary["assisted"] = {
            **dict(self.last_decision_summary.get("assisted", {}) or {}),
            "enabled": bool(self._build_operator_snapshot().get("assisted_mode_enabled", False)),
            "auto_execute": False,
            "requires_operator_action": False,
            "status": "stale_frame",
            "reason": "stale_frame",
        }
        self.last_decision_summary["execution"] = {
            "status": "stale_frame",
            "reason": "STALE_FRAME",
            "frame_age_ms": frame_age_ms,
        }
        logger.warning(
            "CLICK | stale_frame hero=%s board=%s legal=%s age_ms=%.1f max_age_ms=%.1f",
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_cards(canonical_state.board),
            self._format_log_list(canonical_state.legal_actions),
            frame_age_ms,
            max_age_ms,
        )
        self._push_incident(
            "stale_frame",
            severity="warning",
            frame_age_ms=frame_age_ms,
            max_age_ms=max_age_ms,
            spot_id=canonical_state.spot_id,
        )
        self._push_runtime_event(
            "warning",
            "stale_frame",
            frame_age_ms=frame_age_ms,
            max_age_ms=max_age_ms,
            spot_id=canonical_state.spot_id,
        )
    def _push_runtime_event(self, kind: str, message: str, **context) -> None:
        event = {
            "timestamp": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "kind": kind,
            "message": message,
            "context": context,
        }
        self.runtime_event_history.appendleft(event)
        self.runtime_history_store.append("events", event)
        self._publish_runtime_bridge_state()

    def _push_incident(self, incident_id: str, severity: str = "warning", **context) -> None:
        entry = {
            "id": incident_id,
            "severity": severity,
            "timestamp": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "context": context,
        }
        if entry not in self.incident_history:
            self.incident_history.appendleft(entry)
            self.runtime_history_store.append("incidents", entry)
            self._record_runtime_failure(
                category="incident",
                incident_id=incident_id,
                severity=severity,
                context=context,
            )
            self._publish_runtime_bridge_state()

    def _build_runtime_failure_crops(self) -> dict[str, np.ndarray]:
        frame = getattr(self, "last_valid_frame", None)
        canonical = getattr(self, "last_resolved_runtime_state", None)
        if not isinstance(frame, np.ndarray) or not isinstance(canonical, dict):
            return {}
        vision = dict((canonical.get("metadata") or {}).get("vision", {}) or {})
        crops = {}
        region_resolutions = dict(vision.get("region_resolutions", {}) or {})
        for field_name in ("pot", "hero", "actions"):
            selected = dict((region_resolutions.get(field_name) or {}).get("selected", {}) or {})
            bbox = selected.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                crop = self._safe_crop(frame, tuple(int(value) for value in bbox))
                if isinstance(crop, np.ndarray) and crop.size:
                    crops[field_name] = crop
        return crops

    def _record_runtime_transition(self, tracker_snapshot: dict) -> None:
        current_street = str(tracker_snapshot.get("street", "IDLE") or "IDLE")
        if current_street != self._last_runtime_street:
            self._push_runtime_event(
                "tracker",
                "street_changed",
                previous_street=self._last_runtime_street,
                street=current_street,
                board=list(tracker_snapshot.get("board", [])),
                pot=float(tracker_snapshot.get("pot", 0.0) or 0.0),
            )
            self._last_runtime_street = current_street

    def _should_record_runtime_readiness_failure(
        self,
        canonical_state: CanonicalTableState,
        validation,
        readiness,
    ) -> bool:
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        hero_participation = str(metadata.get("hero_participation", "") or "idle")
        if hero_participation in {"idle", "waiting_next_hand", "sitting_out", "observing_hand"}:
            return False

        signature = (
            str(canonical_state.spot_id or ""),
            str(getattr(validation, "state", "") or ""),
            str(getattr(readiness, "state", "") or ""),
            tuple(getattr(readiness, "degraded_fields", ()) or ()),
            tuple(getattr(readiness, "reasons", ()) or ()),
        )
        now = time.monotonic()
        last_signature = getattr(self, "_last_runtime_readiness_failure_signature", ())
        last_at = float(getattr(self, "_last_runtime_readiness_failure_at", 0.0) or 0.0)
        cooldown_s = float(getattr(self, "_runtime_readiness_failure_cooldown_s", 2.0) or 2.0)
        if signature == last_signature and (now - last_at) < cooldown_s:
            return False
        self._last_runtime_readiness_failure_signature = signature
        self._last_runtime_readiness_failure_at = now
        return True
