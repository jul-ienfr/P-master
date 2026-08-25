"""Signatures, verrous et caches de décision live (extrait de src/main.py)."""
import asyncio
import logging
import time
from types import SimpleNamespace
from typing import Dict, List, Optional
from collections.abc import Iterable

from src.bot.gate_flow import compact_solver_payload as _compact_solver_payload
from src.bot.runtime_types import CanonicalTableState
from src.bot.sanity_checker import GateResult
from src.vision.models import TableState

logger = logging.getLogger("SuperBot2026")

ASSISTED_MIN_STATE_CONFIDENCE = 0.72
ASSISTED_MIN_DECISION_CONFIDENCE = 0.67
ASSISTED_MIN_GATE_CONFIDENCE = 0.95
ASSISTED_MIN_PROFILE_RELIABILITY = 0.12
ASSISTED_MIN_OBSERVED_HANDS = 12
ASSISTED_PROFILE_REQUIRED_SOURCES = {"EXPLOIT_PROFILE", "RL_VALIDATED"}
ASSISTED_FALLBACK_PASSIVE_ACTIONS = {"CHECK", "FOLD"}
ASSISTED_FALLBACK_MIN_DECISION_CONFIDENCE = 0.42


class LiveExecutionMixin:
    @staticmethod
    def _normalize_live_execution_pot(value: object) -> float:
        try:
            return round(max(0.0, float(value or 0.0)), 1)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_live_execution_actions(values: Iterable[object]) -> tuple[str, ...]:
        normalized = []
        for value in values or ():
            text = str(value or "").strip().upper()
            if text and text not in normalized:
                normalized.append(text)
        return tuple(normalized)

    @staticmethod
    def _normalize_live_execution_buttons(values: Iterable[object]) -> tuple[str, ...]:
        normalized = []
        for value in values or ():
            text = str(value or "").strip().lower()
            if text and text not in normalized:
                normalized.append(text)
        return tuple(sorted(normalized))

    @staticmethod
    def _extract_actionable_runtime_buttons(action_buttons: Iterable[str]) -> tuple[str, ...]:
        actionable_button_labels = {
            "fold_button",
            "check_button",
            "call_button",
            "all_in_call_button",
            "bet_button",
            "raise_button",
        }
        return tuple(
            str(button_name)
            for button_name in action_buttons
            if str(button_name) in actionable_button_labels
        )

    def _build_live_execution_material_signature(self, canonical_state: CanonicalTableState) -> tuple:
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        metadata_signature = metadata.get("spot_signature")
        if isinstance(metadata_signature, (list, tuple)) and len(metadata_signature) >= 6:
            normalized_metadata_signature = list(metadata_signature)
            normalized_metadata_signature[4] = list(self._normalize_live_execution_actions(metadata_signature[4]))
            normalized_metadata_signature[5] = list(self._normalize_live_execution_buttons(metadata_signature[5]))
            metadata_signature = tuple(normalized_metadata_signature)
        actionable_buttons = self._normalize_live_execution_buttons(
            self._extract_actionable_runtime_buttons(canonical_state.action_buttons)
        )
        hero_seat_id = str(
            metadata.get("hero_seat_id")
            or (self.last_tracker_snapshot or {}).get("hero_seat_id", "")
            or ""
        ).strip()
        return (
            str(canonical_state.spot_id or "").strip(),
            str(canonical_state.street or "").strip().upper(),
            tuple(canonical_state.hero_cards),
            tuple(canonical_state.board),
            self._normalize_live_execution_pot(canonical_state.pot),
            self._normalize_live_execution_actions(canonical_state.legal_actions),
            actionable_buttons,
            hero_seat_id,
            tuple(metadata_signature) if isinstance(metadata_signature, (list, tuple)) else metadata_signature,
        )

    def _build_live_execution_signature(self, canonical_state: CanonicalTableState) -> tuple:
        return (
            self._build_live_execution_material_signature(canonical_state),
        )

    def _build_live_execution_context_signature(self, canonical_state: CanonicalTableState) -> tuple:
        return (
            self._build_live_execution_material_signature(canonical_state),
        )

    def _build_live_decision_signature(self, canonical_state: CanonicalTableState) -> tuple:
        return self._build_live_execution_material_signature(canonical_state)

    def _clear_live_decision_lock(self) -> None:
        self._last_locked_decision_signature = ()
        self._last_locked_decision_action = ""
        self._last_locked_decision_reason = ""
        self._last_locked_decision_at = 0.0
        self._last_locked_decision_log_signature = ()
        self._last_locked_decision_log_at = 0.0

    def _clear_live_decision_cache(self) -> None:
        self._last_decision_signature = ()
        self._last_decision_payload = None
        self._last_decision_cached_at = 0.0

    def _clear_live_execution_guard(self) -> None:
        self._last_live_execution_signature = ()
        self._last_live_execution_context_signature = ()
        self._last_live_execution_action = ""
        self._last_live_execution_at = 0.0
        self._last_live_execution_status = ""
        self._last_live_execution_settle_status = ""
        self._clear_live_decision_lock()
        self._clear_live_decision_cache()

    def _remember_locked_decision(self, canonical_state: CanonicalTableState, action_name: str, reason: str) -> None:
        self._last_locked_decision_signature = self._build_live_decision_signature(canonical_state)
        self._last_locked_decision_action = str(action_name or "").strip().upper()
        self._last_locked_decision_reason = str(reason or "").strip()
        self._last_locked_decision_at = time.monotonic()

    def _should_log_locked_decision(self, canonical_state: CanonicalTableState, reason: str) -> bool:
        signature = (self._build_live_decision_signature(canonical_state), str(reason or "").strip())
        interval_s = float(getattr(self, "_locked_spot_log_interval_s", 1.0) or 1.0)
        now = time.monotonic()
        if (
            signature == getattr(self, "_last_locked_decision_log_signature", ())
            and (now - float(getattr(self, "_last_locked_decision_log_at", 0.0) or 0.0)) < interval_s
        ):
            return False
        self._last_locked_decision_log_signature = signature
        self._last_locked_decision_log_at = now
        return True

    def _build_locked_decision_skip(self, canonical_state: CanonicalTableState) -> dict[str, object] | None:
        decision_signature = self._build_live_decision_signature(canonical_state)
        locked_signature = getattr(self, "_last_locked_decision_signature", ())
        if not locked_signature or decision_signature != locked_signature:
            return None
        reason = str(getattr(self, "_last_locked_decision_reason", "") or "").strip() or "same_spot_locked"
        action_name = str(getattr(self, "_last_locked_decision_action", "") or "").strip().upper()
        return {
            "signature": decision_signature,
            "reason": reason,
            "action": action_name,
            "log_now": self._should_log_locked_decision(canonical_state, reason),
        }

    def _build_minimal_skipped_decision(
        self,
        canonical_state: CanonicalTableState,
        action_name: str,
        reason: str,
    ) -> dict[str, object]:
        return {
            "action": str(action_name or "").strip().upper(),
            "source": "LOCKED_SPOT_SKIP",
            "confidence": float(self.last_decision_summary.get("confidence", 0.0) or 0.0),
            "cache_hit": True,
            "fallback_used": bool(self.last_decision_summary.get("fallback_used", False)),
            "fallback_reason": self.last_decision_summary.get("fallback_reason"),
            "warnings": [],
            "incidents": [str(reason or "same_spot_locked")],
            "elapsed_ms": 0.0,
            "backend": "locked_skip",
            "metadata": {
                "profile": dict(self.last_decision_summary.get("profile", {}) or {}),
                "solver": dict(self.last_decision_summary.get("solver", {}) or {}),
                "confidence": dict(self.last_decision_summary.get("confidence_details", {}) or {}),
            },
        }

    def _get_cached_live_decision(self, canonical_state: CanonicalTableState) -> dict[str, object] | None:
        decision_signature = self._build_live_decision_signature(canonical_state)
        if decision_signature != getattr(self, "_last_decision_signature", ()):
            return None
        payload = getattr(self, "_last_decision_payload", None)
        if not isinstance(payload, dict):
            return None
        ttl_s = float(getattr(self, "_decision_cache_ttl_s", 0.35) or 0.35)
        cached_at = float(getattr(self, "_last_decision_cached_at", 0.0) or 0.0)
        if (time.monotonic() - cached_at) >= ttl_s:
            return None
        return dict(payload)

    def _remember_cached_live_decision(self, canonical_state: CanonicalTableState, decision: dict[str, object]) -> None:
        self._last_decision_signature = self._build_live_decision_signature(canonical_state)
        self._last_decision_payload = dict(decision)
        self._last_decision_cached_at = time.monotonic()

    def _should_suppress_duplicate_live_action(
        self,
        canonical_state: CanonicalTableState,
        action_name: str,
    ) -> bool:
        normalized_action = str(action_name or "").strip().upper()
        last_signature = getattr(self, "_last_live_execution_signature", ())
        last_action = str(getattr(self, "_last_live_execution_action", "") or "").strip().upper()
        cooldown_s = float(getattr(self, "_live_action_repeat_cooldown_s", 3.5) or 3.5)
        last_at = float(getattr(self, "_last_live_execution_at", 0.0) or 0.0)
        if not normalized_action or not last_signature or not last_action:
            return False
        if normalized_action != last_action:
            return False
        if self._build_live_execution_signature(canonical_state) != last_signature:
            return False
        return (time.monotonic() - last_at) < cooldown_s

    def _should_suppress_recent_live_execution(self, canonical_state: CanonicalTableState) -> bool:
        last_context_signature = getattr(self, "_last_live_execution_context_signature", ())
        if not last_context_signature:
            return False
        if self._build_live_execution_context_signature(canonical_state) != last_context_signature:
            return False
        last_settle_status = str(getattr(self, "_last_live_execution_settle_status", "") or "").strip().lower()
        last_at = float(getattr(self, "_last_live_execution_at", 0.0) or 0.0)
        if last_settle_status == "timeout":
            # Si l'action a expiré sans que l'interface ne valide (miss-click, lag serveur),
            # on bloque les redondances pendant 5.0 secondes avant de s'autoriser à réessayer.
            return (time.monotonic() - last_at) < 5.0
        if str(getattr(self, "_last_live_execution_status", "") or "") != "executed":
            return False
        cooldown_s = float(getattr(self, "_post_action_context_guard_s", 2.25) or 2.25)
        return (time.monotonic() - last_at) < cooldown_s

    def _remember_live_execution(
        self,
        canonical_state: CanonicalTableState,
        action_name: str,
        status: str,
        settle_status: str = "",
    ) -> None:
        normalized_action = str(action_name or "").strip().upper()
        if not normalized_action:
            return
        self._last_live_execution_signature = self._build_live_execution_signature(canonical_state)
        self._last_live_execution_context_signature = self._build_live_execution_context_signature(canonical_state)
        self._last_live_execution_action = normalized_action
        self._last_live_execution_at = time.monotonic()
        self._last_live_execution_status = str(status or "")
        self._last_live_execution_settle_status = str(settle_status or "")

    def _evaluate_assisted_execution(
        self,
        canonical_state: CanonicalTableState,
        decision: dict,
        gate_result: GateResult,
    ) -> dict:
        decision_metadata = dict(decision.get("metadata", {}) or {})
        profile = dict(decision_metadata.get("profile", {}) or {})
        confidence_details = dict(decision_metadata.get("confidence", {}) or {})
        decision_source = str(decision.get("source", "unknown") or "unknown").strip().upper()
        observed_hands = int(
            profile.get("observed_hands", decision.get("profile", {}).get("observed_hands", 0) or 0) or 0
        )
        profile_reliability = float(
            profile.get("reliability", confidence_details.get("profile_reliability", 0.0) or 0.0) or 0.0
        )
        exploit_confidence = float(profile.get("exploit_confidence", 0.0) or 0.0)
        decision_confidence = float(decision.get("confidence", 0.0) or 0.0)
        gate_confidence = float(gate_result.confidence or 0.0)
        final_action = str(decision.get("action", "") or "").strip().upper()
        legal_actions = {str(action).strip().upper() for action in canonical_state.legal_actions}
        state_confidence = float(
            confidence_details.get("state_confidence", canonical_state.state_confidence or 0.0) or 0.0
        )
        fallback_used = bool(decision.get("fallback_used", False))
        requires_profile_sample = decision_source in ASSISTED_PROFILE_REQUIRED_SOURCES
        runtime_readiness = dict((canonical_state.metadata or {}).get("runtime_readiness", {}) or {})
        readiness_state = str(runtime_readiness.get("state") or "")
        readiness_score = float(runtime_readiness.get("score", state_confidence) or state_confidence or 0.0)

        result = {
            "enabled": bool((getattr(self, "operator_controls", {}) or {}).get("assisted_mode_enabled", False)),
            "learning_live": True,
            "auto_execute": False,
            "requires_operator_action": True,
            "status": "manual_required",
            "reason": "manual_review_required",
            "signals": {
                "decision_source": decision_source,
                "state_confidence": round(state_confidence, 3),
                "decision_confidence": round(decision_confidence, 3),
                "gate_confidence": round(gate_confidence, 3),
                "observed_hands": observed_hands,
                "profile_reliability": round(profile_reliability, 3),
                "exploit_confidence": round(exploit_confidence, 3),
                "fallback_used": fallback_used,
                "runtime_readiness_state": readiness_state,
                "runtime_readiness_score": round(readiness_score, 3),
            },
            "thresholds": {
                "min_state_confidence": ASSISTED_MIN_STATE_CONFIDENCE,
                "min_decision_confidence": ASSISTED_MIN_DECISION_CONFIDENCE,
                "min_gate_confidence": ASSISTED_MIN_GATE_CONFIDENCE,
                "min_profile_reliability": ASSISTED_MIN_PROFILE_RELIABILITY,
                "min_observed_hands": ASSISTED_MIN_OBSERVED_HANDS,
            },
        }

        if not gate_result.allowed:
            result["reason"] = "gate_blocked"
            return result
        if readiness_state == "blocked_local":
            result["reason"] = "runtime_blocked"
            return result
        if readiness_state == "conservative" and not fallback_used:
            result["reason"] = "runtime_conservative"
            return result
        if fallback_used:
            if (
                final_action in ASSISTED_FALLBACK_PASSIVE_ACTIONS
                and final_action in legal_actions
                and readiness_score >= ASSISTED_MIN_STATE_CONFIDENCE
                and gate_confidence >= ASSISTED_MIN_GATE_CONFIDENCE
                and decision_confidence >= ASSISTED_FALLBACK_MIN_DECISION_CONFIDENCE
            ):
                result.update(
                    {
                        "auto_execute": True,
                        "requires_operator_action": False,
                        "status": "auto_execute",
                        "reason": "fallback_passive_ready",
                    }
                )
                return result
            result["reason"] = "solver_fallback"
            return result
        if state_confidence < ASSISTED_MIN_STATE_CONFIDENCE:
            result["reason"] = "low_state_confidence"
            return result
        if decision_confidence < ASSISTED_MIN_DECISION_CONFIDENCE:
            result["reason"] = "low_decision_confidence"
            return result
        if gate_confidence < ASSISTED_MIN_GATE_CONFIDENCE:
            result["reason"] = "low_gate_confidence"
            return result
        if (
            requires_profile_sample
            and observed_hands < ASSISTED_MIN_OBSERVED_HANDS
            and profile_reliability < ASSISTED_MIN_PROFILE_RELIABILITY
        ):
            result["reason"] = "insufficient_profile_data"
            return result

        result.update(
            {
                "auto_execute": True,
                "requires_operator_action": False,
                "status": "auto_execute",
                "reason": "ready",
            }
        )
        return result

    @staticmethod
    def _format_log_cards(cards: object) -> str:
        if not cards:
            return "-"
        return " ".join(str(card) for card in cards if str(card).strip()) or "-"

    @staticmethod
    def _format_log_list(values: object) -> str:
        if not values:
            return "-"
        return ", ".join(str(value) for value in values if str(value).strip()) or "-"

    def _log_live_details(self, canonical_state: CanonicalTableState, state: TableState) -> None:
        table_detected = bool((state.metadata or {}).get("table_detected"))
        button_names = tuple(str(button.class_name) for button in (state.action_buttons or []))
        actionable_buttons = self._extract_actionable_runtime_buttons(button_names)
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        hero_participation = str(metadata.get("hero_participation", "idle") or "idle")
        observed_street = str(metadata.get("observed_street", canonical_state.street) or canonical_state.street)
        tracker_street = str(metadata.get("tracker_street", canonical_state.street) or canonical_state.street)
        background_idle = (
            hero_participation == "idle"
            and table_detected
            and canonical_state.street == "IDLE"
            and not canonical_state.hero_cards
            and not canonical_state.board
            and float(canonical_state.pot or 0.0) <= 0.0
            and not canonical_state.legal_actions
            and not actionable_buttons
        )
        signature = (
            table_detected,
            hero_participation,
            "background_idle" if background_idle else canonical_state.street,
            tuple() if background_idle else tuple(canonical_state.hero_cards),
            tuple() if background_idle else tuple(canonical_state.board),
            0.0 if background_idle else round(float(canonical_state.pot or 0.0), 1),
            tuple() if background_idle else tuple(canonical_state.legal_actions),
            tuple(sorted(set(button_names))), # Toujours ignorer l'ordre d'apparition
            # Ne pas inclure la confidence dans la signature pour éviter le spam aux micro-décimales
        )
        
        # Debouncer absolu : on n'affiche plus jamais le log si l'état exact (la signature) n'a pas changé.
        if signature == self._last_live_details_signature:
            return

        self._last_live_details_signature = signature
        self._last_live_details_logged_at = time.monotonic()

        logger.info(
            "LIVE | table=%s mode=%s street=%s hero=%s board=%s pot=%.1f buttons=%s legal=%s conf=%.2f",
            "yes" if table_detected else "no",
            hero_participation,
            canonical_state.street,
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_cards(canonical_state.board),
            float(canonical_state.pot or 0.0),
            self._format_log_list(button_names),
            self._format_log_list(canonical_state.legal_actions),
            float(canonical_state.state_confidence or 0.0),
        )
        if observed_street != canonical_state.street or tracker_street != canonical_state.street:
            logger.info(
                "LIVE_STATE | observed=%s tracker=%s resolved=%s raw_board=%s validated_board=%s pending=%s spot=%s",
                observed_street,
                tracker_street,
                canonical_state.street,
                self._format_log_cards(metadata.get("raw_board", canonical_state.board)),
                self._format_log_cards(metadata.get("validated_board", canonical_state.board)),
                str(metadata.get("pending_street_promotion", "") or "-") or "-",
                canonical_state.spot_id,
            )
        self._last_live_details_signature = signature
        self._last_live_details_logged_at = time.monotonic()

    @staticmethod
    def _normalize_incidents(incidents: list[object]) -> list[str]:
        normalized: list[str] = []
        for incident in incidents:
            if isinstance(incident, dict):
                incident_id = incident.get("id") or incident.get("label") or incident.get("kind")
                if incident_id:
                    normalized.append(str(incident_id))
            elif incident:
                normalized.append(str(incident))
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _derive_live_hero_position(primary_villain) -> str:
        if primary_villain is None:
            return "unknown"
        return "oop" if bool(primary_villain.has_button) else "ip"

    def _resolve_live_decision_context(
        self,
        canonical_state: CanonicalTableState,
    ) -> tuple[object | None, float]:
        primary_villain = self.tracker.get_primary_villain()
        effective_stack = float(self.tracker.get_effective_stack() or 0.0)
        if primary_villain is not None and effective_stack > 0.0:
            return primary_villain, effective_stack

        hero_tracker = next(
            (player for player in self.tracker.players.values() if getattr(player, "is_hero", False)),
            None,
        )
        tracker_villains = [
            player
            for player in self.tracker.players.values()
            if not getattr(player, "is_hero", False) and not getattr(player, "has_folded", False)
        ]
        canonical_hero = next((player for player in canonical_state.players if player.is_hero), None)
        canonical_villains = [player for player in canonical_state.players if not player.is_hero and not player.has_folded]

        if primary_villain is None:
            if tracker_villains:
                primary_villain = min(
                    tracker_villains,
                    key=lambda player: getattr(player, "current_stack", 0.0) or getattr(player, "starting_stack", 0.0) or float("inf"),
                )
            elif canonical_villains:
                chosen = min(
                    canonical_villains,
                    key=lambda player: player.stack if player.stack > 0.0 else float("inf"),
                )
                primary_villain = SimpleNamespace(
                    name=chosen.identity,
                    has_button=chosen.has_button,
                    current_stack=float(chosen.stack or 0.0),
                )

        hero_stack_candidates = [
            float(value)
            for value in (
                getattr(hero_tracker, "current_stack", 0.0) if hero_tracker else 0.0,
                getattr(hero_tracker, "starting_stack", 0.0) if hero_tracker else 0.0,
                canonical_hero.stack if canonical_hero else 0.0,
            )
            if float(value or 0.0) > 0.0
        ]
        villain_stack_candidates = [
            float(value)
            for value in (
                [getattr(player, "current_stack", 0.0) or getattr(player, "starting_stack", 0.0) for player in tracker_villains]
                + [player.stack for player in canonical_villains]
            )
            if float(value or 0.0) > 0.0
        ]
        hero_stack = max(hero_stack_candidates) if hero_stack_candidates else 0.0
        villain_stack = max(villain_stack_candidates) if villain_stack_candidates else 0.0

        if effective_stack <= 0.0:
            if hero_stack > 0.0 and villain_stack > 0.0:
                effective_stack = min(hero_stack, villain_stack)
            elif hero_stack > 0.0:
                effective_stack = hero_stack
            elif villain_stack > 0.0:
                effective_stack = villain_stack

        actionable_preflop = (
            canonical_state.street == "PREFLOP"
            and len(canonical_state.hero_cards) == 2
            and bool(canonical_state.legal_actions)
        )
        if actionable_preflop:
            hero_has_button = bool(
                canonical_hero.has_button if canonical_hero is not None else getattr(hero_tracker, "has_button", False)
            )
            if primary_villain is None:
                fallback_villain_name = (
                    next(
                        (
                            str(getattr(player, "name", "") or "").strip()
                            for player in tracker_villains
                            if str(getattr(player, "name", "") or "").strip()
                        ),
                        "",
                    )
                    or next((str(player.name or "").strip() for player in canonical_villains if str(player.name or "").strip()), "")
                    or "live_villain"
                )
                primary_villain = SimpleNamespace(
                    name=fallback_villain_name,
                    has_button=not hero_has_button,
                    current_stack=float(villain_stack or effective_stack or hero_stack or canonical_state.pot or 1.0),
                )
            if effective_stack <= 0.0:
                effective_stack = max(hero_stack, villain_stack, float(canonical_state.pot or 0.0), 1.0)

        return primary_villain, max(0.0, float(effective_stack or 0.0))

    def _record_decision_trace(self, canonical_state: CanonicalTableState, decision: dict, gate_result: GateResult) -> None:
        warnings = list(decision.get("warnings", []))
        incidents = self._normalize_incidents(list(decision.get("incidents", [])))
        ab_decision = decision.get("ab_decision") if isinstance(decision.get("ab_decision"), dict) else None
        metadata = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
        solver_metadata = _compact_solver_payload(metadata.get("solver", {}) or {})
        trace_metadata = dict(metadata)
        trace_metadata["solver"] = solver_metadata
        session_id = self._get_runtime_session_id()
        if not gate_result.allowed:
            incidents.append("gate_blocked")

        trace = {
            "timestamp": self._utc_now(),
            "session_id": session_id,
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "board": list(canonical_state.board),
            "hero_cards": list(canonical_state.hero_cards),
            "pot": canonical_state.pot,
            "legal_actions": list(canonical_state.legal_actions),
            "action_history": list(self.tracker.current_hand_actions),
            "chosen_action": decision.get("action", ""),
            "source": decision.get("source", "unknown"),
            "confidence": float(decision.get("confidence", 0.0) or 0.0),
            "latency_ms": float(decision.get("elapsed_ms", 0) or 0),
            "ev": float(decision.get("ev", 0.0) or 0.0),
            "warnings": warnings,
            "incidents": list(dict.fromkeys(incidents)),
            "backend": decision.get("backend", "unknown"),
            "cache_hit": bool(decision.get("cache_hit", solver_metadata.get("cache_hit", False))),
            "chosen_action_raw": solver_metadata.get("chosen_action_raw"),
            "gto_action": solver_metadata.get("gto_action"),
            "final_action": solver_metadata.get("final_action", decision.get("action", "")),
            "ev_by_action": dict(solver_metadata.get("ev_by_action", {}) or {}),
            "freq_by_action": dict(solver_metadata.get("freq_by_action", {}) or {}),
            "action_metadata": dict(solver_metadata.get("action_metadata", {}) or {}),
            "solver_warnings": list(solver_metadata.get("warnings", []) or []),
            "solver_warning_details": list(solver_metadata.get("warning_details", []) or []),
            "backend_details": dict(solver_metadata.get("backend_details", {}) or {}),
            "cache_details": dict(solver_metadata.get("cache_details", {}) or {}),
            "node_count": solver_metadata.get("node_count", (solver_metadata.get("backend_details", {}) or {}).get("node_count")),
            "exploitability": solver_metadata.get("exploitability"),
            "solver_elapsed_ms": solver_metadata.get("elapsed_ms"),
            "solver_id": solver_metadata.get("solver_id"),
            "preset_id": solver_metadata.get("preset_id"),
            "action_buckets": list(solver_metadata.get("action_buckets", []) or []),
            "ab_decision": dict(ab_decision) if ab_decision else None,
            "metadata": trace_metadata,
            "gate_result": gate_result.to_dict(),
            "explanation": (
                f"Decision {decision.get('action', 'pending')} on {canonical_state.street.lower()} "
                f"from {decision.get('source', 'unknown')} with state_confidence={canonical_state.state_confidence:.2f}."
            ),
        }
        self.decision_trace_history.appendleft(trace)
        self.runtime_history_store.append("decisions", trace)

    async def _wait_for_action_settle(self) -> dict:
        camera = getattr(self, "camera", None)
        detector = getattr(self, "detector", None)
        refresh_capture_region = getattr(self, "_refresh_capture_region", None)
        if (
            camera is None
            or detector is None
            or not callable(getattr(camera, "get_latest_frame", None))
            or not callable(getattr(detector, "analyze_frame", None))
        ):
            return {"settled": True, "elapsed_ms": 0.0, "buttons": []}

        timeout_s = max(0.1, float(getattr(self, "_post_action_settle_timeout_s", 0.9) or 0.9))
        poll_interval_s = max(0.01, float(getattr(self, "_post_action_settle_poll_interval_s", 0.03) or 0.03))
        started_at = time.monotonic()
        actionable_buttons: tuple[str, ...] = ()

        while (time.monotonic() - started_at) <= timeout_s:
            await asyncio.sleep(poll_interval_s)
            if callable(refresh_capture_region):
                refresh_capture_region()
            frame = camera.get_latest_frame()
            if frame is None:
                continue

            state = await asyncio.to_thread(detector.analyze_frame, frame)
            state = self._label_generic_action_buttons(state, frame)
            actionable_buttons = self._extract_actionable_runtime_buttons(
                [button.class_name for button in state.action_buttons]
            )
            if not actionable_buttons:
                return {
                    "settled": True,
                    "elapsed_ms": round((time.monotonic() - started_at) * 1000.0, 1),
                    "buttons": [],
                }

        return {
            "settled": False,
            "elapsed_ms": round((time.monotonic() - started_at) * 1000.0, 1),
            "buttons": list(actionable_buttons),
        }

    def _clear_live_decision_summary(self, canonical_state: CanonicalTableState) -> None:
        self.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
        self.last_decision_summary = {
            "action": "",
            "source": "idle",
            "confidence": 0.0,
            "observed_hands": 0,
            "cache_hit": False,
            "fallback_used": False,
            "fallback_reason": None,
            "warnings": [],
            "incidents": [],
            "elapsed_ms": 0,
            "backend": "idle",
            "action_history": list(self.tracker.current_hand_actions),
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "hero_cards": list(canonical_state.hero_cards),
            "board": list(canonical_state.board),
            "hero_position": "",
            "effective_stack": 0.0,
            "villain_name": "",
            "ab_decision": None,
            "profile": {},
            "solver": {},
            "confidence_details": {},
            "gate_confidence": 0.0,
            "gate_reason": "idle",
            "gate_allowed": False,
            "fallback_execution_readiness": {
                "status": "idle",
                "score": 0.0,
                "recommended_action": None,
                "target_button": None,
                "reasons": ["idle"],
                "signals": {},
            },
            "assisted": {
                "enabled": bool(self._build_operator_snapshot().get("assisted_mode_enabled", False)),
                "learning_live": True,
                "auto_execute": False,
                "requires_operator_action": False,
                "status": "waiting_for_spot",
                "reason": "idle",
                "signals": {},
                "thresholds": {
                    "min_state_confidence": ASSISTED_MIN_STATE_CONFIDENCE,
                    "min_decision_confidence": ASSISTED_MIN_DECISION_CONFIDENCE,
                    "min_gate_confidence": ASSISTED_MIN_GATE_CONFIDENCE,
                    "min_profile_reliability": ASSISTED_MIN_PROFILE_RELIABILITY,
                    "min_observed_hands": ASSISTED_MIN_OBSERVED_HANDS,
                },
            },
            "trace_updated_at": self._utc_now(),
            "history": {
                "fallback": [],
                "warnings": [],
                "incidents": [],
            },
            "operator_status": self._operator_action_mode(),
            "execution": {
                "status": "idle",
                "reason": "no_live_action",
            },
        }

