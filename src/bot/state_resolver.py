"""Résolution de l'état runtime : rues, participation, lissage, snapshot tracker (extrait de src/main.py)."""

import logging
import time
from collections.abc import Iterable

import numpy as np

from src.bot.live_reconstruction import (
    derive_street,
    normalize_board_for_street,
    smooth_state_confidence_window,
    stable_window_value,
)
from src.bot.runtime_types import CanonicalTableState
from src.runtime.readiness import build_runtime_readiness
from src.vision.models import TableState

logger = logging.getLogger("SuperBot2026")


class StateResolverMixin:
    @staticmethod
    def _resolve_action_coord_key(action_name: str) -> str:
        normalized = str(action_name or "").strip().upper()
        if normalized == "FOLD":
            return "FOLD"
        if normalized in {"CALL", "CHECK"}:
            return "CALL"
        if normalized == "BET_BOX":
            return "BET_BOX"
        return "BET_BTN"

    def _get_action_coord_diagnostic(
        self, state: TableState, action_name: str
    ) -> dict[str, object]:
        metadata = dict(getattr(state, "metadata", {}) or {})
        diagnostics = dict(metadata.get("dynamic_coord_diagnostics", {}) or {})
        coord_key = self._resolve_action_coord_key(action_name)
        diagnostic = dict(diagnostics.get(coord_key, {}) or {})
        diagnostic.setdefault("coord_key", coord_key)
        diagnostic.setdefault("slot_boxes", dict(metadata.get("button_slot_boxes", {}) or {}))
        return diagnostic

    def _build_resolved_runtime_state(
        self, canonical_state: CanonicalTableState
    ) -> CanonicalTableState:
        tracker_snapshot = dict(
            self._build_tracker_snapshot(canonical_state.to_tracker_payload()) or {}
        )
        fast_pot_snapshot = self._get_recent_fast_pot_snapshot()
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        tracker_street = str(
            tracker_snapshot.get("street", canonical_state.street) or canonical_state.street
        )
        tracker_board = tuple(tracker_snapshot.get("board", []) or [])
        tracker_hero_cards = tuple(tracker_snapshot.get("hero_cards", []) or [])
        tracker_legal_actions = tuple(
            str(action).upper() for action in (tracker_snapshot.get("legal_actions", []) or [])
        )
        tracker_pot = float(
            tracker_snapshot.get("pot", canonical_state.pot) or canonical_state.pot or 0.0
        )
        fast_pot_value = float(fast_pot_snapshot.get("value", 0.0) or 0.0)
        tracker_confidence = float(
            tracker_snapshot.get("state_confidence", canonical_state.state_confidence)
            or canonical_state.state_confidence
            or 0.0
        )
        hero_participation = str(metadata.get("hero_participation", "") or "idle")
        observation_mode = bool(metadata.get("observation_mode", False))
        use_tracker_street = (
            not observation_mode
            and bool(tracker_street)
            and tracker_street != canonical_state.street
        )
        resolved_state = CanonicalTableState(
            spot_id=str(
                canonical_state.spot_id
                if observation_mode
                else (
                    tracker_snapshot.get("spot_id", canonical_state.spot_id)
                    or canonical_state.spot_id
                )
            ),
            street=tracker_street if use_tracker_street else canonical_state.street,
            pot=(
                fast_pot_value
                if fast_pot_value > 0.0
                else (
                    tracker_pot
                    if tracker_pot > 0.0 or canonical_state.pot <= 0.0
                    else canonical_state.pot
                )
            )
            if not observation_mode
            else canonical_state.pot,
            board=(tracker_board if tracker_board else canonical_state.board)
            if not observation_mode
            else canonical_state.board,
            hero_cards=(
                tracker_hero_cards if len(tracker_hero_cards) == 2 else canonical_state.hero_cards
            )
            if not observation_mode
            else canonical_state.hero_cards,
            players=canonical_state.players,
            legal_actions=(tracker_legal_actions or canonical_state.legal_actions)
            if not observation_mode
            else canonical_state.legal_actions,
            action_buttons=canonical_state.action_buttons,
            state_confidence=(
                tracker_confidence if tracker_confidence > 0.0 else canonical_state.state_confidence
            )
            if not observation_mode
            else canonical_state.state_confidence,
            metadata={
                **metadata,
                "observed_street": canonical_state.street,
                "tracker_street": tracker_street,
                "resolved_street": tracker_street if use_tracker_street else canonical_state.street,
                "raw_board": list(canonical_state.board),
                "validated_board": list(tracker_board or canonical_state.board),
                "pending_street_promotion": str(
                    getattr(self.tracker, "pending_street_promotion", "") or ""
                ),
                "hero_participation": hero_participation,
                "observation_mode": observation_mode,
                "fast_pot_snapshot": fast_pot_snapshot,
            },
        )
        validation = self.poker_state_validator.validate(resolved_state)
        readiness = build_runtime_readiness(resolved_state, validation)
        resolved_metadata = dict(resolved_state.metadata or {})
        resolved_metadata["poker_state_validation"] = validation.to_dict()
        resolved_metadata["runtime_readiness"] = readiness.to_dict()
        resolved_state = CanonicalTableState(
            spot_id=resolved_state.spot_id,
            street=resolved_state.street,
            pot=resolved_state.pot,
            board=resolved_state.board,
            hero_cards=resolved_state.hero_cards,
            players=resolved_state.players,
            legal_actions=resolved_state.legal_actions,
            action_buttons=resolved_state.action_buttons,
            state_confidence=resolved_state.state_confidence,
            metadata=resolved_metadata,
        )
        self.last_decision_summary["runtime_readiness"] = readiness.to_dict()
        if validation.state != "fully_valid" and self._should_record_runtime_readiness_failure(
            resolved_state,
            validation,
            readiness,
        ):
            self._record_shadow_mode_failure(
                issue_type="runtime_state_desync",
                reason="runtime_readiness_not_fully_valid",
                spot_id=resolved_state.spot_id,
                validation=validation.to_dict(),
                readiness=readiness.to_dict(),
            )
            self._record_runtime_failure(
                category="near_miss",
                incident_id="runtime_readiness_not_fully_valid",
                severity="warning" if validation.state == "degraded_valid" else "error",
                context={
                    "validation": validation.to_dict(),
                    "readiness": readiness.to_dict(),
                    "spot_id": resolved_state.spot_id,
                },
            )
        self.last_resolved_runtime_state = resolved_state.to_dict()
        if logger.isEnabledFor(logging.DEBUG):
            try:
                from src.runtime.debug import _should_throttle as _dbg_throttle
                from src.runtime.debug import set_debug_context as _set_dbg_ctx
            except ImportError:
                _dbg_throttle = None  # type: ignore[assignment]
                _set_dbg_ctx = None  # type: ignore[assignment]
            if _set_dbg_ctx is not None:
                try:
                    _set_dbg_ctx(spot_id=str(resolved_state.spot_id))
                except Exception:
                    pass
            should_emit = _dbg_throttle("state_resolver:resolved", 1.0) if _dbg_throttle else True
            if should_emit:
                logger.debug(
                    "state_resolver: spot_id=%s street=%s board=%s pot=%.1f hero=%s legal=%s conf=%.3f",
                    resolved_state.spot_id,
                    resolved_state.street,
                    resolved_state.board,
                    float(resolved_state.pot or 0.0),
                    resolved_state.hero_cards,
                    resolved_state.legal_actions,
                    float(resolved_state.state_confidence or 0.0),
                )
        return resolved_state

    @staticmethod
    def _normalize_board_for_street(board: tuple[str, ...], street: str) -> tuple[str, ...]:
        return normalize_board_for_street(board, street)

    def _derive_street(self, board: list[str], hero_cards: list[str]) -> str:
        incoming_street = derive_street(board, hero_cards)
        stable_street = stable_window_value(
            list(self._recent_runtime_streets),
            incoming_street,
            ignore_values=("IDLE",),
        )
        self._recent_runtime_streets.append(stable_street)
        return stable_street

    def _derive_hero_participation_mode(
        self,
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
        pot_value: float,
        action_buttons: Iterable[str],
    ) -> str:
        button_names = tuple(str(button_name) for button_name in action_buttons)
        actionable_buttons = self._extract_actionable_runtime_buttons(button_names)
        button_set = set(button_names)
        if len(hero_cards) == 2:
            return "active_hand"
        if "resume_hand" in button_set:
            return "waiting_next_hand"
        if "im_back" in button_set:
            return "sitting_out"
        if actionable_buttons:
            return "actionable_without_hero"
        if board or float(pot_value or 0.0) > 0.0:
            return "observing_hand"
        return "idle"

    def _derive_runtime_street(
        self,
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
        action_buttons: tuple[str, ...],
    ) -> str:
        actionable_buttons = self._extract_actionable_runtime_buttons(action_buttons)
        if not board and len(hero_cards) != 2 and not actionable_buttons:
            self._recent_runtime_streets.clear()
            return "IDLE"

        incoming_street = derive_street(board, hero_cards)
        stable_street = stable_window_value(
            list(self._recent_runtime_streets),
            incoming_street,
            ignore_values=("IDLE",) if actionable_buttons else (),
        )
        self._recent_runtime_streets.append(stable_street)
        return stable_street

    @staticmethod
    def _normalize_auxiliary_action_state(
        legal_actions: tuple[str, ...],
        action_buttons: tuple[str, ...],
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        button_names = tuple(str(button_name) for button_name in action_buttons)
        button_set = set(button_names)
        if "fast_fold_button" in button_set and not board:
            if not button_set.intersection({"check_button", "bet_button", "raise_button"}):
                return (
                    (),
                    tuple(
                        button_name
                        for button_name in button_names
                        if button_name in {"fast_fold_button", "resume_hand", "im_back"}
                    ),
                )

        return legal_actions, action_buttons

    def _smooth_legal_actions(
        self,
        legal_actions: tuple[str, ...],
        action_buttons: tuple[str, ...],
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        actionable_button_labels = {
            "fold_button",
            "check_button",
            "call_button",
            "all_in_call_button",
            "bet_button",
            "raise_button",
        }
        actionable_buttons = tuple(
            button_name for button_name in action_buttons if button_name in actionable_button_labels
        )
        if not actionable_buttons:
            self._recent_runtime_legal_actions.clear()
            return (), action_buttons

        same_runtime_context = bool(hero_cards) and (
            not self.last_canonical_spot_snapshot
            or (
                list(board) == list(self.last_canonical_spot_snapshot.get("board", []))
                and list(hero_cards)
                == list(self.last_canonical_spot_snapshot.get("hero_cards", []))
            )
        )
        if not same_runtime_context:
            self._recent_runtime_legal_actions.clear()
            if legal_actions:
                self._recent_runtime_legal_actions.append(legal_actions)
            return legal_actions, action_buttons

        stable_actions = stable_window_value(
            list(self._recent_runtime_legal_actions),
            legal_actions,
            ignore_values=((),),
        )
        if stable_actions:
            self._recent_runtime_legal_actions.append(stable_actions)
            if not legal_actions:
                return stable_actions, action_buttons
        return legal_actions, action_buttons

    def _smooth_runtime_state_confidence(
        self,
        state_confidence: float,
        street: str,
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> float:
        same_runtime_context = not self.last_canonical_spot_snapshot or (
            street == self.last_canonical_spot_snapshot.get("street")
            and list(board) == list(self.last_canonical_spot_snapshot.get("board", []))
            and list(hero_cards) == list(self.last_canonical_spot_snapshot.get("hero_cards", []))
        )
        if not same_runtime_context:
            self._recent_runtime_state_confidences.clear()
            smoothed = round(float(state_confidence or 0.0), 3)
        else:
            smoothed = smooth_state_confidence_window(
                list(self._recent_runtime_state_confidences),
                state_confidence,
            )
        self._recent_runtime_state_confidences.append(smoothed)
        return smoothed

    def _stabilize_runtime_hero_cards(
        self,
        hero_cards: tuple[str, ...],
        board: tuple[str, ...],
        state: TableState,
    ) -> tuple[str, ...]:
        now = time.monotonic()
        previous_hero_cards = tuple(self._last_good_runtime_hero_cards)

        def _split_card(card: str) -> tuple[str, str]:
            card_text = str(card or "")
            if len(card_text) < 2:
                return "", ""
            return card_text[0].upper(), card_text[1].lower()

        def _is_suspicious_rank_flip(
            previous_cards: tuple[str, ...], candidate_cards: tuple[str, ...]
        ) -> bool:
            if len(previous_cards) != 2 or len(candidate_cards) != 2:
                return False
            if previous_cards == candidate_cards:
                return False
            changed_indexes = [
                index
                for index, (previous_card, candidate_card) in enumerate(
                    zip(previous_cards, candidate_cards, strict=False)
                )
                if previous_card != candidate_card
            ]
            if len(changed_indexes) != 1:
                return False
            changed_index = changed_indexes[0]
            previous_rank, previous_suit = _split_card(previous_cards[changed_index])
            candidate_rank, candidate_suit = _split_card(candidate_cards[changed_index])
            if not previous_rank or not candidate_rank:
                return False
            if previous_suit != candidate_suit:
                return False
            return True

        if (
            len(hero_cards) == 2
            and len(previous_hero_cards) == 2
            and (now - self._last_good_runtime_hero_cards_at)
            <= float(getattr(self, "_runtime_hero_cards_rank_flip_ttl_s", 1.0) or 1.0)
            and _is_suspicious_rank_flip(previous_hero_cards, hero_cards)
        ):
            logger.info(
                "HERO_CARDS | suspicious_rank_flip previous=%s candidate=%s reused=%s",
                self._format_log_cards(previous_hero_cards),
                self._format_log_cards(hero_cards),
                self._format_log_cards(previous_hero_cards),
            )
            return previous_hero_cards

        if len(hero_cards) == 2:
            self._last_good_runtime_hero_cards = tuple(hero_cards)
            self._last_good_runtime_hero_cards_at = now
            return hero_cards

        pot_value = float(getattr(state.pots[0], "confidence", 0.0) or 0.0) if state.pots else 0.0
        has_live_context = bool(board) or pot_value > 0.0
        if (
            has_live_context
            and len(self._last_good_runtime_hero_cards) == 2
            and (now - self._last_good_runtime_hero_cards_at) <= self._runtime_hero_cards_ttl_s
        ):
            return tuple(self._last_good_runtime_hero_cards)

        if not has_live_context:
            self._last_good_runtime_hero_cards = ()
            self._last_good_runtime_hero_cards_at = 0.0
        return hero_cards

    def _convert_state_for_tracker(
        self, state: TableState, frame: np.ndarray
    ) -> CanonicalTableState:
        return self._get_frame_pipeline()._convert_state_for_tracker(state, frame)

    def _build_tracker_snapshot(self, tracker_data: dict) -> dict:
        fallback_street = str((tracker_data or {}).get("street", "IDLE") or "IDLE")
        fallback_board = list((tracker_data or {}).get("board", []) or [])
        fallback_pot = float((tracker_data or {}).get("pot", 0.0) or 0.0)
        fallback_hero_cards = list((tracker_data or {}).get("hero_cards", []) or [])
        fallback_legal_actions = [
            str(action).upper() for action in ((tracker_data or {}).get("legal_actions", []) or [])
        ]
        fallback_state_confidence = float((tracker_data or {}).get("state_confidence", 0.0) or 0.0)
        fallback_hero_seat_id = str(
            ((tracker_data or {}).get("metadata", {}) or {}).get("hero_seat_id", "") or ""
        )

        hero_seat_id = next(
            (seat_id for seat_id, player in self.tracker.players.items() if player.is_hero),
            fallback_hero_seat_id,
        )
        ocr_metadata = {}
        turn_probe_metadata = {}
        if isinstance(tracker_data, dict):
            metadata = tracker_data.get("metadata", {}) or {}
            ocr_metadata = dict(metadata.get("ocr", {}) or {})
            vision_metadata = dict(metadata.get("vision", {}) or {})
            observed_pot_metadata = dict(metadata.get("observed_pot", {}) or {})
            observed_pot_fast_metadata = dict(metadata.get("observed_pot_fast", {}) or {})
            turn_probe_metadata = dict(metadata.get("turn_probe", {}) or {})
            raw_board_count = int(vision_metadata.get("raw_board_count", 0) or 0)
        else:
            vision_metadata = {}
            observed_pot_metadata = {}
            observed_pot_fast_metadata = {}
            turn_probe_metadata = {}
            raw_board_count = 0

        tracker_street = (
            str(self.tracker.state or "") if getattr(self, "tracker", None) is not None else ""
        )
        tracker_board = list(getattr(self.tracker, "current_board", []) or [])
        tracker_pot = float(getattr(self.tracker, "pot_total", 0.0) or 0.0)
        tracker_hero_cards = list(getattr(self.tracker, "hero_cards", []) or [])
        tracker_legal_actions = [
            str(action).upper() for action in (getattr(self.tracker, "legal_actions", []) or [])
        ]
        tracker_state_confidence = float(getattr(self.tracker, "state_confidence", 0.0) or 0.0)
        fast_pot_snapshot = self._get_recent_fast_pot_snapshot()
        fast_pot_value = float(fast_pot_snapshot.get("value", 0.0) or 0.0)
        fast_pot_age_s = float(fast_pot_snapshot.get("age_s", 999.0) or 999.0)
        observed_pot_fast_value = float(observed_pot_fast_metadata.get("value", 0.0) or 0.0)
        observed_pot_fast_age_s = max(
            0.0,
            time.monotonic()
            - float(observed_pot_fast_metadata.get("observed_at_monotonic", 0.0) or 0.0),
        )
        prefer_fast_pot_snapshot = fast_pot_value > 0.0 and fast_pot_age_s <= float(
            getattr(self, "_fast_pot_stale_after_s", 0.35) or 0.35
        )
        observed_pot_value = float(observed_pot_metadata.get("value", 0.0) or 0.0)
        observed_pot_age_s = max(
            0.0,
            time.monotonic()
            - float(observed_pot_metadata.get("observed_at_monotonic", 0.0) or 0.0),
        )
        prefer_observed_pot_fast = (
            observed_pot_fast_value > 0.0
            and observed_pot_fast_age_s <= 0.20
            and str(observed_pot_fast_metadata.get("ocr_focus", "") or "") == "top_label"
            and str(observed_pot_fast_metadata.get("source_region", "") or "")
            == "fast_lane_geometry"
        )
        observed_pot_ocr_focus = str(observed_pot_metadata.get("ocr_focus", "") or "")
        observed_pot_source_region = str(observed_pot_metadata.get("source_region", "") or "")
        prefer_observed_pot = (
            observed_pot_value > 0.0
            and observed_pot_age_s <= 0.45
            and observed_pot_ocr_focus == "top_label"
            and observed_pot_source_region in {"preset_geometry", "detector_pot"}
        )

        force_idle_snapshot = (
            fallback_street == "IDLE"
            and not fallback_board
            and raw_board_count < 3
            and not fallback_hero_cards
            and not fallback_legal_actions
        )
        if force_idle_snapshot:
            street = "IDLE"
            board = []
            pot = fallback_pot
            hero_cards = []
            legal_actions = []
            state_confidence = fallback_state_confidence
        else:
            street = tracker_street or fallback_street
            board = tracker_board or fallback_board
            if prefer_fast_pot_snapshot:
                pot = fast_pot_value
            elif prefer_observed_pot_fast:
                pot = observed_pot_fast_value
            elif prefer_observed_pot:
                pot = observed_pot_value
            else:
                pot = tracker_pot if tracker_pot > 0.0 else fallback_pot
            hero_cards = tracker_hero_cards if len(tracker_hero_cards) == 2 else fallback_hero_cards
            legal_actions = tracker_legal_actions or fallback_legal_actions
            state_confidence = (
                tracker_state_confidence
                if tracker_state_confidence > 0.0
                else fallback_state_confidence
            )

        return {
            "street": street,
            "board": board,
            "pot": pot,
            "hero_cards": hero_cards,
            "action_history": list(self.tracker.current_hand_actions),
            "in_hand": len(hero_cards) == 2 and street != "IDLE",
            "legal_actions": legal_actions,
            "hero_seat_id": str(hero_seat_id or ""),
            "state_confidence": state_confidence,
            "ocr_metadata": ocr_metadata,
            "vision_metadata": {
                **vision_metadata,
                "fast_pot_snapshot": fast_pot_snapshot,
                "prefer_fast_pot_snapshot": prefer_fast_pot_snapshot,
                "observed_pot_fast": observed_pot_fast_metadata,
                "prefer_observed_pot_fast": prefer_observed_pot_fast,
                "observed_pot_fast_age_s": round(observed_pot_fast_age_s, 3),
                "observed_pot": observed_pot_metadata,
                "prefer_observed_pot": prefer_observed_pot,
                "observed_pot_age_s": round(observed_pot_age_s, 3),
                "turn_probe": turn_probe_metadata,
            },
            "spot_id": str((tracker_data or {}).get("spot_id", "") or ""),
        }
