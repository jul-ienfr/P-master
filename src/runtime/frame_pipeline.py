from __future__ import annotations

import asyncio
import time
from typing import Dict

import numpy as np

from src.bot.runtime_types import CanonicalTableState
from src.runtime.poker_state_validator import PokerStateValidator
from src.runtime.readiness import build_runtime_readiness
from src.vision.crop_quality import analyze_crop_quality
from src.vision.detector import DetectionResult, TableState, build_detection_quality_metadata, decode_card_token
from src.vision.frame_quality import analyze_frame_quality
from src.vision.preset_registry import PresetRegistry
from src.vision.region_proposals import build_region_proposals, resolve_region_proposals
from src.vision.numeric_reader import NumericReader
from src.vision.site_adapter import get_active_adapter
from src.vision.table_geometry import DEFAULT_RUNTIME_GEOMETRY, geometry_from_manifest, geometry_to_pixel_regions


class FramePipeline:
    def __init__(self, controller) -> None:
        object.__setattr__(self, "controller", controller)

    def __setattr__(self, name: str, value) -> None:
        if name == "controller":
            object.__setattr__(self, name, value)
            return
        setattr(self.controller, name, value)

    def __getattr__(self, name: str):
        return getattr(self.controller, name)

    def _get_poker_state_validator(self) -> PokerStateValidator:
        validator = getattr(self, "poker_state_validator", None)
        if validator is None:
            validator = PokerStateValidator()
            self.poker_state_validator = validator
        return validator

    @staticmethod
    def _runtime_visual_regions(frame: np.ndarray) -> Dict[str, tuple[int, int, int, int]]:
        try:
            return geometry_to_pixel_regions(frame, DEFAULT_RUNTIME_GEOMETRY)
        except Exception:
            return geometry_to_pixel_regions(frame, DEFAULT_RUNTIME_GEOMETRY)

    def _get_preset_registry(self) -> PresetRegistry | None:
        registry = getattr(self, "preset_registry", None)
        if registry is not None:
            return registry
        try:
            registry = PresetRegistry.from_adapter(get_active_adapter("pokerstars"))
        except Exception:
            return None
        self.preset_registry = registry
        return registry

    def _get_numeric_reader(self) -> NumericReader | None:
        reader = getattr(self, "numeric_reader", None)
        if reader is not None:
            return reader
        ocr_engine = getattr(self, "amount_ocr", None)
        if ocr_engine is None:
            return None
        reader = NumericReader(ocr_engine)
        self.numeric_reader = reader
        return reader

    def _read_live_pot_fast(self, frame: np.ndarray, pot_box: tuple[int, int, int, int]) -> dict | None:
        amount_ocr = getattr(self, "amount_ocr", None)
        if amount_ocr is None:
            return None
        pot_focus_box = self._build_pot_text_focus_bbox(pot_box)
        pot_crop = self._safe_crop(frame, pot_focus_box)
        crop_quality = analyze_crop_quality("pot", pot_crop).to_dict() if pot_crop is not None else None
        if pot_crop is None or not self._is_pot_crop_usable(crop_quality):
            pot_crop = self._safe_crop(frame, pot_box)
            crop_quality = analyze_crop_quality("pot", pot_crop).to_dict() if pot_crop is not None else None
            if pot_crop is None or not self._is_pot_crop_usable(crop_quality):
                return None
            pot_focus_box = pot_box
        value = amount_ocr.read_and_parse_amount(pot_crop)
        metadata = dict(amount_ocr.get_metadata() or {}) if hasattr(amount_ocr, "get_metadata") else {}
        confidence = float(metadata.get("selected_confidence", 0.0) or 0.0)
        if value is None or confidence < 0.9:
            return None
        return {
            "value": float(value),
            "observed_at_monotonic": time.monotonic(),
            "source_region": "fast_lane_geometry",
            "ocr_focus": "top_label",
            "ocr_bbox": list(pot_focus_box),
            "source_bbox": list(pot_box),
            "selected_text": str(metadata.get("selected_text", "") or ""),
            "selected_confidence": confidence,
        }

    def _try_update_cached_fast_pot(self, frame: np.ndarray, cached_state: TableState) -> TableState:
        metadata = dict(getattr(cached_state, "metadata", {}) or {})
        runtime_geometry = dict(metadata.get("runtime_geometry", {}) or {})
        regions = dict(runtime_geometry.get("regions", {}) or {})
        raw_pot_box = regions.get("pot")
        if not isinstance(raw_pot_box, (list, tuple)) or len(raw_pot_box) != 4:
            return cached_state
        pot_box = tuple(int(round(float(value))) for value in raw_pot_box)
        try:
            fast_lane_pot = self._read_live_pot_fast(frame, pot_box)
        except Exception:
            fast_lane_pot = None
        if fast_lane_pot is None:
            amount_ocr = getattr(self, "amount_ocr", None)
            if amount_ocr is not None:
                pot_focus_box = self._build_pot_text_focus_bbox(pot_box)
                pot_crop = self._safe_crop(frame, pot_focus_box)
                if pot_crop is not None:
                    try:
                        value = amount_ocr.read_and_parse_amount(pot_crop)
                        metadata = dict(amount_ocr.get_metadata() or {}) if hasattr(amount_ocr, "get_metadata") else {}
                        confidence = float(metadata.get("selected_confidence", 0.0) or 0.0)
                        if value is not None and confidence >= 0.9:
                            fast_lane_pot = {
                                "value": float(value),
                                "observed_at_monotonic": time.monotonic(),
                                "source_region": "fast_lane_geometry",
                                "ocr_focus": "top_label",
                                "ocr_bbox": list(pot_focus_box),
                                "source_bbox": list(pot_box),
                                "selected_text": str(metadata.get("selected_text", "") or ""),
                                "selected_confidence": confidence,
                            }
                    except Exception:
                        fast_lane_pot = None
        if fast_lane_pot is None:
            return cached_state
        cached_state.metadata = dict(metadata)
        cached_state.metadata["observed_pot_fast"] = dict(fast_lane_pot)
        if cached_state.pots:
            cached_state.pots[0].confidence = float(fast_lane_pot.get("value", 0.0) or 0.0)
        else:
            cached_state.pots.append(
                DetectionResult(
                    class_name="pot_area",
                    confidence=1.0,
                    bbox=pot_box,
                )
            )
            cached_state.pots[0].confidence = float(fast_lane_pot.get("value", 0.0) or 0.0)
        return cached_state

    def _resolve_runtime_geometry(self, state: TableState, frame: np.ndarray):
        metadata = dict(getattr(state, "metadata", {}) or {})
        table_bbox = metadata.get("table_bbox") if isinstance(metadata.get("table_bbox"), list) else None
        registry = self._get_preset_registry()
        preset_name = str(metadata.get("fallback_preset") or "")
        if registry is not None and preset_name and isinstance(table_bbox, list) and len(table_bbox) == 4:
            preset = registry.find_by_display_name(preset_name)
            if preset is not None:
                geometry = geometry_from_manifest(preset.manifest, source=preset.display_name)
                pixel_regions = geometry_to_pixel_regions(frame, geometry, table_bbox=tuple(int(value) for value in table_bbox))
                return geometry, pixel_regions
        return DEFAULT_RUNTIME_GEOMETRY, self._runtime_visual_regions(frame)

    @staticmethod
    def _safe_crop(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return None
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        x1 = max(0, min(int(x1), width))
        y1 = max(0, min(int(y1), height))
        x2 = max(0, min(int(x2), width))
        y2 = max(0, min(int(y2), height))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        return crop if crop.size else None

    @staticmethod
    def _is_pot_crop_usable(crop_quality: dict | None) -> bool:
        if not isinstance(crop_quality, dict) or not crop_quality:
            return False
        if bool(crop_quality.get("rejected", False)):
            return False
        width = int(crop_quality.get("width", 0) or 0)
        height = int(crop_quality.get("height", 0) or 0)
        quality_score = float(crop_quality.get("quality_score", 0.0) or 0.0)
        return width >= 96 and height >= 28 and quality_score >= 0.12

    @staticmethod
    def _build_pot_text_focus_bbox(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = (int(value) for value in bbox)
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        focus_x1 = x1 + int(round(width * 0.16))
        focus_x2 = x2 - int(round(width * 0.16))
        focus_y1 = y1 + int(round(height * 0.02))
        focus_y2 = y1 + int(round(height * 0.26))
        if focus_x2 <= focus_x1:
            focus_x1, focus_x2 = x1, x2
        if focus_y2 <= focus_y1:
            focus_y1, focus_y2 = y1, y2
        return (focus_x1, focus_y1, focus_x2, focus_y2)

    def _capture_live_visual_previews(self, frame: np.ndarray) -> Dict[str, np.ndarray]:
        regions = self._runtime_visual_regions(frame)
        previews: Dict[str, np.ndarray] = {}
        for key, bbox in regions.items():
            preview = self._build_visual_preview(frame, bbox)
            if preview is not None:
                previews[key] = preview
        return previews

    def _detect_relevant_visual_change(
        self,
        frame: np.ndarray,
    ) -> tuple[bool, Dict[str, np.ndarray], tuple[str, ...]]:
        controller_override = getattr(getattr(self.controller, "__dict__", {}), "get", lambda _key, _default=None: None)(
            "_detect_relevant_visual_change",
            None,
        )
        if callable(controller_override):
            return controller_override(frame)
        previews = self._capture_live_visual_previews(frame)
        if not previews:
            return True, previews, ("capture_unavailable",)

        if not self._last_visual_previews:
            return True, previews, tuple(previews.keys())

        changed_regions = tuple(
            region_name
            for region_name, preview in previews.items()
            if self._is_image_changed(
                self._last_visual_previews.get(region_name),
                preview,
                threshold=self._visual_state_change_threshold,
            )
        )
        return bool(changed_regions), previews, changed_regions

    async def _process_frame(self, frame) -> TableState:
        refresh_due = (time.monotonic() - self._last_visual_state_at) >= self._visual_state_refresh_interval_s
        visual_changed, previews, changed_regions = self._detect_relevant_visual_change(frame)
        changed_region_set = set(changed_regions)
        fast_action_refresh = bool(changed_region_set) and changed_region_set.issubset({"actions", "pot"})
        if not visual_changed and not refresh_due and self._last_visual_state is not None:
            cached_state = self._copy_table_state(self._last_visual_state)
            cached_state.metadata = dict(getattr(cached_state, "metadata", {}) or {})
            cached_state.metadata.update(
                {
                    "reused_visual_state": True,
                    "visual_changed": False,
                    "visual_changed_regions": [],
                    "visual_refresh_due": False,
                }
            )
            cached_state = self._try_update_cached_fast_pot(frame, cached_state)
            self._last_visual_previews = previews
            return cached_state

        if fast_action_refresh and not refresh_due and self._last_visual_state is not None:
            cached_state = self._copy_table_state(self._last_visual_state)
            cached_state = self._label_generic_action_buttons(cached_state, frame)
            cached_state.metadata = dict(getattr(cached_state, "metadata", {}) or {})
            cached_state.metadata.update(
                {
                    "reused_visual_state": True,
                    "visual_changed": True,
                    "visual_changed_regions": list(changed_regions),
                    "visual_refresh_due": False,
                    "fast_action_refresh": True,
                }
            )
            cached_state = self._try_update_cached_fast_pot(frame, cached_state)
            self._last_visual_previews = previews
            self._last_visual_state = self._copy_table_state(cached_state)
            self._last_visual_state_at = time.monotonic()
            return cached_state

        self._set_loop_stage("process_frame:detector", publish=True)
        state = await asyncio.to_thread(self.detector.analyze_frame, frame)
        state = self._label_generic_action_buttons(state, frame)
        state.metadata = dict(getattr(state, "metadata", {}) or {})
        frame_quality = analyze_frame_quality(frame)
        state.metadata["frame_quality"] = frame_quality.to_dict()
        runtime_geometry, pixel_regions = self._resolve_runtime_geometry(state, frame)
        state.metadata["runtime_geometry"] = {
            "source": getattr(runtime_geometry, "source", "default"),
            "table_size": list(getattr(runtime_geometry, "table_size", (0, 0))),
            "regions": {key: [float(value) for value in values] for key, values in getattr(runtime_geometry, "regions", {}).items()},
        }
        fast_lane_pot_box = pixel_regions.get("pot")
        if fast_lane_pot_box is not None:
            try:
                fast_lane_pot = self._read_live_pot_fast(frame, tuple(int(value) for value in fast_lane_pot_box))
            except Exception:
                fast_lane_pot = None
            if fast_lane_pot is not None:
                state.metadata["observed_pot_fast"] = dict(fast_lane_pot)
        region_proposals = build_region_proposals(state, pixel_regions)
        region_resolutions = resolve_region_proposals(region_proposals)
        state.metadata["region_proposals"] = {
            key: [proposal.to_dict() for proposal in values]
            for key, values in region_proposals.items()
        }
        state.metadata["region_resolutions"] = {
            key: value.to_dict()
            for key, value in region_resolutions.items()
        }
        state.metadata["detection_quality"] = build_detection_quality_metadata(state, pixel_regions)

        pot_detection_available = bool(state.pots)
        resolved_pot = region_resolutions.get("pot")
        default_pot_box = tuple(resolved_pot.selected.bbox) if resolved_pot is not None else pixel_regions.get("pot")
        if pot_detection_available or default_pot_box is not None:
            self._set_loop_stage("process_frame:pot_ocr", publish=True)
            pot_box = tuple(default_pot_box) if default_pot_box is not None else state.pots[0].bbox
            pot_focus_box = self._build_pot_text_focus_bbox(pot_box)
            pot_crop = self._safe_crop(frame, pot_focus_box)
            ocr_box = pot_focus_box
            crop_quality = analyze_crop_quality("pot", pot_crop).to_dict() if pot_crop is not None else None
            fallback_pot_box = pixel_regions.get("pot")
            fallback_pot_crop = None
            fallback_crop_quality = None
            if not self._is_pot_crop_usable(crop_quality):
                pot_crop = self._safe_crop(frame, pot_box)
                ocr_box = pot_box
                crop_quality = analyze_crop_quality("pot", pot_crop).to_dict() if pot_crop is not None else None
            if (
                fallback_pot_box is not None
                and tuple(int(value) for value in fallback_pot_box) != tuple(int(value) for value in pot_box)
                and not self._is_pot_crop_usable(crop_quality)
            ):
                fallback_pot_crop = self._safe_crop(frame, tuple(int(value) for value in fallback_pot_box))
                if fallback_pot_crop is not None:
                    fallback_crop_quality = analyze_crop_quality("pot", fallback_pot_crop).to_dict()
                    if self._is_pot_crop_usable(fallback_crop_quality):
                        pot_box = tuple(int(value) for value in fallback_pot_box)
                        pot_crop = fallback_pot_crop
                        ocr_box = pot_box
                        crop_quality = fallback_crop_quality
            if crop_quality is not None:
                state.metadata.setdefault("crop_quality", {})["pot"] = crop_quality
            if fallback_crop_quality is not None:
                state.metadata.setdefault("crop_quality", {})["pot_fallback"] = fallback_crop_quality
            pot_refresh_due = (time.monotonic() - float(getattr(self, "_last_pot_ocr_at", 0.0) or 0.0)) >= float(
                getattr(self, "_pot_ocr_refresh_interval_s", 0.12) or 0.12
            )
            pot_changed = bool(
                pot_crop is not None and self._is_image_changed(
                    self.last_pot_crop,
                    pot_crop,
                    threshold=float(getattr(self, "_pot_crop_change_threshold", 0.85) or 0.85),
                )
            )
            if pot_crop is not None and not pot_changed and not pot_refresh_due:
                if state.pots:
                    state.pots[0].confidence = self.last_pot_value
                elif self.last_pot_value > 0.0:
                    state.pots.append(DetectionResult(class_name="pot_area", confidence=1.0, bbox=tuple(int(value) for value in pot_box)))
                    state.pots[0].confidence = self.last_pot_value
            elif pot_crop is not None:
                numeric_reader = self._get_numeric_reader()
                numeric_result = (
                    await asyncio.to_thread(numeric_reader.read_amount, "pot", pot_crop, previous_value=self.last_pot_value)
                    if numeric_reader is not None
                    else None
                )
                pot_value = numeric_result.selected_value if numeric_result is not None else None
                val = pot_value if pot_value else 0.0
                if state.pots:
                    state.pots[0].confidence = val
                elif val > 0.0:
                    state.pots.append(DetectionResult(class_name="pot_area", confidence=1.0, bbox=tuple(int(value) for value in pot_box)))
                    state.pots[0].confidence = val
                state.metadata["pot_ocr"] = self.amount_ocr.get_metadata()
                if numeric_result is not None:
                    state.metadata["numeric_reader"] = state.metadata.get("numeric_reader", {}) or {}
                    state.metadata["numeric_reader"]["pot"] = {
                        "selected_value": numeric_result.selected_value,
                        "evidence": numeric_result.evidence.to_dict(),
                        "metadata": dict(numeric_result.metadata),
                        "source_bbox": list(pot_box),
                        "ocr_bbox": list(ocr_box),
                        "ocr_focus": "top_label" if tuple(int(value) for value in ocr_box) == tuple(int(value) for value in pot_focus_box) else "full_region",
                        "source_region": (
                            "preset_geometry"
                            if fallback_pot_box is not None and tuple(int(value) for value in pot_box) == tuple(int(value) for value in fallback_pot_box)
                            else (resolved_pot.selected.source if resolved_pot is not None else "detector_pot")
                        ),
                        "ocr_without_detector": not pot_detection_available,
                    }
                    state.metadata["observed_pot"] = {
                        "value": float(numeric_result.selected_value or 0.0),
                        "observed_at_monotonic": time.monotonic(),
                        "source_region": state.metadata["numeric_reader"]["pot"]["source_region"],
                        "ocr_focus": state.metadata["numeric_reader"]["pot"]["ocr_focus"],
                    }
                self.last_pot_value = val
                self.last_pot_crop = pot_crop.copy()
                self._last_pot_ocr_at = time.monotonic()
            else:
                state.metadata.setdefault("crop_quality", {})["pot"] = analyze_crop_quality("pot", np.empty((0, 0), dtype=np.uint8)).to_dict()

        if len(state.board_cards) >= 3 and not state.pots:
            self._set_loop_stage("process_frame:hitl_pot_check", publish=True)
            if not getattr(self.hitl, "is_waiting_for_human", False):
                asyncio.create_task(
                    self.hitl.request_intervention_async(
                        frame=frame,
                        issue_type="MISSING_POT",
                        reason="Le flop est distribue mais je ne detecte aucun pot.",
                    )
                )

        state.metadata["reused_visual_state"] = False
        state.metadata["visual_changed"] = bool(visual_changed)
        state.metadata["visual_changed_regions"] = list(changed_regions)
        state.metadata["visual_refresh_due"] = bool(refresh_due)
        self._last_visual_previews = previews
        self._last_visual_state = self._copy_table_state(state)
        self._last_visual_state_at = time.monotonic()

        return state

    @staticmethod
    def _derive_observation_street(
        street: str,
        board: tuple[str, ...],
        pot_value: float,
        action_buttons: tuple[str, ...],
        hero_participation: str,
    ) -> str:
        if hero_participation not in {"waiting_next_hand", "sitting_out", "observing_hand"}:
            return street
        if len(board) >= 5:
            return "RIVER"
        if len(board) == 4:
            return "TURN"
        if len(board) == 3:
            return "FLOP"
        if pot_value > 0.0 or street == "PREFLOP" or any(
            button_name in {"resume_hand", "im_back", "fast_fold_button"} for button_name in action_buttons
        ):
            return "PREFLOP"
        return "IDLE"

    def _convert_state_for_tracker(self, state: TableState, frame: np.ndarray) -> CanonicalTableState:
        state = self._label_generic_action_buttons(state, frame)
        raw_board_count = len(getattr(state, "board_cards", []) or [])
        board = tuple(card for card in (decode_card_token(c.class_name) for c in state.board_cards) if card)
        hero_cards = tuple(card for card in (decode_card_token(c.class_name) for c in state.hero_cards) if card)
        hero_cards = self._stabilize_runtime_hero_cards(hero_cards, board, state)
        pot_value = float(getattr(state.pots[0], "confidence", 0.0) or 0.0) if state.pots else 0.0
        players = tuple(self._build_players(state, frame))
        legal_actions, action_buttons = self._derive_legal_actions(state)
        legal_actions, action_buttons = self._normalize_auxiliary_action_state(
            legal_actions,
            action_buttons,
            board,
            hero_cards,
        )
        confirmed_live_context = bool(board) or raw_board_count >= 3 or len(hero_cards) == 2 or pot_value > 0.0
        if not confirmed_live_context:
            action_buttons = tuple(
                button_name
                for button_name in action_buttons
                if button_name in {"resume_hand", "im_back", "fast_fold_button"}
            )
            legal_actions = ()
        street = self._derive_runtime_street(board, hero_cards, action_buttons)
        if street == "IDLE" and raw_board_count >= 5:
            street = "RIVER"
        elif street == "IDLE" and raw_board_count == 4:
            street = "TURN"
        elif street == "IDLE" and raw_board_count >= 3:
            street = "FLOP"
        board = self._normalize_board_for_street(board, street)
        legal_actions, action_buttons = self._smooth_legal_actions(
            legal_actions,
            action_buttons,
            board,
            hero_cards,
        )
        confidence_parts = [
            1.0 if state.metadata.get("table_detected") else 0.0,
            1.0 if len(hero_cards) == 2 else 0.0,
            min(len(board) / 5.0, 1.0),
            1.0 if state.pots else 0.0,
            1.0 if players else 0.0,
            1.0 if legal_actions else 0.0,
        ]
        state_confidence = round(sum(confidence_parts) / len(confidence_parts), 3)
        state_confidence = self._smooth_runtime_state_confidence(state_confidence, street, board, hero_cards)
        normalized_pot = round(max(0.0, float(pot_value or 0.0)), 1)
        hero_participation = self._derive_hero_participation_mode(board, hero_cards, normalized_pot, action_buttons)
        observation_mode = hero_participation in {"waiting_next_hand", "sitting_out", "observing_hand"}
        observation_street = self._derive_observation_street(
            street,
            board,
            normalized_pot,
            action_buttons,
            hero_participation,
        )
        if observation_street == "IDLE" and raw_board_count >= 5:
            observation_street = "RIVER"
        elif observation_street == "IDLE" and raw_board_count == 4:
            observation_street = "TURN"
        elif observation_street == "IDLE" and raw_board_count >= 3:
            observation_street = "FLOP"
        actionable_buttons = tuple(sorted(self._extract_actionable_runtime_buttons(action_buttons)))
        spot_signature = (
            street,
            tuple(hero_cards),
            tuple(board),
            normalized_pot,
            tuple(str(action).upper() for action in legal_actions),
            tuple(actionable_buttons),
            hero_participation,
        )
        if observation_mode:
            button_part = "-".join(action_buttons) or "no_buttons"
            spot_suffix = f"{hero_participation}:pot-{normalized_pot:.1f}:{button_part}"
        elif board:
            spot_suffix = "-".join(board)
        elif street == "PREFLOP":
            legal_part = "-".join(str(action).lower() for action in legal_actions) or "none"
            button_part = "-".join(actionable_buttons) or "no_buttons"
            spot_suffix = f"pot-{normalized_pot:.1f}:{legal_part}:{button_part}"
        else:
            spot_suffix = street.lower()
        ocr_metadata = {}
        ocr_reader = getattr(self, "ocr", None)
        if ocr_reader is not None and hasattr(ocr_reader, "get_metadata"):
            try:
                ocr_metadata = dict(ocr_reader.get_metadata() or {})
            except Exception:
                ocr_metadata = {}
        frame_quality = dict((state.metadata or {}).get("frame_quality", {}) or {})
        crop_quality = dict((state.metadata or {}).get("crop_quality", {}) or {})
        runtime_geometry = dict((state.metadata or {}).get("runtime_geometry", {}) or {})
        region_proposals = dict((state.metadata or {}).get("region_proposals", {}) or {})
        region_resolutions = dict((state.metadata or {}).get("region_resolutions", {}) or {})
        detection_quality = dict((state.metadata or {}).get("detection_quality", {}) or {})
        numeric_reader = dict((state.metadata or {}).get("numeric_reader", {}) or {})

        return CanonicalTableState(
            spot_id=f"live:{street}:{spot_suffix}",
            street=street,
            pot=pot_value,
            board=board,
            hero_cards=hero_cards,
            players=players,
            legal_actions=legal_actions,
            action_buttons=action_buttons,
            state_confidence=state_confidence,
            metadata={
                "spot_signature": list(spot_signature),
                "detected_player_count": len(players),
                "has_dealer_button": state.dealer_button is not None,
                "hero_seat_id": next((player.seat_id for player in players if player.is_hero), ""),
                "ocr": {
                    "pot": state.metadata.get("pot_ocr", {}),
                    "engines": ocr_metadata.get("loaded_engines", []),
                    "requested_engines": ocr_metadata.get("requested_engines", []),
                    "mode": ocr_metadata.get("mode", "consensus_amounts"),
                    "parallel": ocr_metadata.get("parallel", True),
                },
                "vision": {
                    "detector_mode": state.metadata.get("detector_mode", ""),
                    "table_detected": bool(state.metadata.get("table_detected", False)),
                    "raw_board_count": raw_board_count,
                    "fallback_preset": state.metadata.get("fallback_preset", ""),
                    "topleft_anchor_asset": state.metadata.get("topleft_anchor_asset", ""),
                    "topleft_match_scale": state.metadata.get("topleft_match_scale"),
                    "table_bbox": state.metadata.get("table_bbox", []),
                    "static_stack_area_count": int(state.metadata.get("static_stack_area_count", 0) or 0),
                    "static_name_area_count": int(state.metadata.get("static_name_area_count", 0) or 0),
                    "frame_quality": frame_quality,
                    "crop_quality": crop_quality,
                    "runtime_geometry": runtime_geometry,
                    "region_proposals": region_proposals,
                    "region_resolutions": region_resolutions,
                    "detection_quality": detection_quality,
                    "numeric_reader": numeric_reader,
                    "visual_changed": bool(state.metadata.get("visual_changed", False)),
                    "visual_changed_regions": list(state.metadata.get("visual_changed_regions", []) or []),
                    "visual_refresh_due": bool(state.metadata.get("visual_refresh_due", False)),
                },
                "hero_participation": hero_participation,
                "observation_mode": observation_mode,
                "observation_street": observation_street,
            },
        )

    def build_runtime_readiness(self, canonical_state: CanonicalTableState):
        validator = self._get_poker_state_validator()
        validation = validator.validate(canonical_state)
        return build_runtime_readiness(canonical_state, validation)
