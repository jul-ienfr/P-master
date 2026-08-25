"""Construction des joueurs runtime : pairing stacks/noms, quarantaine OCR (extrait de src/main.py)."""
import time
from collections.abc import Iterable

import numpy as np

from src.bot.live_reconstruction import (
    infer_hero_seat_id,
    ordered_stacks_by_table_geometry,
    stable_window_value,
)
from src.bot.runtime_types import CanonicalPlayer
from src.runtime.player_name_resolver import resolve_player_name
from src.vision.models import DetectionResult, TableState
from src.vision.numeric_reader import NumericReader
from src.vision.player_name_reader import PlayerNameReader


class PlayersBuilderMixin:
    def _known_stack_fallback(self, seat_id: str, cached_player: CanonicalPlayer | None) -> float:
        if cached_player is not None and float(cached_player.stack or 0.0) > 0.0:
            return float(cached_player.stack or 0.0)

        tracked_player = getattr(getattr(self, "tracker", None), "players", {}).get(seat_id)
        if tracked_player is not None and float(getattr(tracked_player, "current_stack", 0.0) or 0.0) > 0.0:
            return float(getattr(tracked_player, "current_stack", 0.0) or 0.0)

        return 0.0

    def _build_stack_quarantine_metadata(self, seat_id: str, fallback_value: float, remaining_s: float) -> dict:
        return {
            "field": "amount",
            "mode": "quarantine",
            "parallel": False,
            "supported_engines": [],
            "requested_engines": [],
            "loaded_engines": [],
            "unavailable_engines": {},
            "selected_engine": "",
            "selected_text": "",
            "selected_variant": "",
            "selected_amount": fallback_value if fallback_value > 0.0 else None,
            "selected_confidence": 0.0,
            "engine_scores": {},
            "candidates": [],
            "agreement": "quarantined",
            "seat_id": seat_id,
            "skipped_due_to_quarantine": True,
            "quarantine_remaining_s": round(max(0.0, remaining_s), 3),
        }

    def _read_player_stack(
        self,
        stack_crop: np.ndarray | None,
        seat_id: str,
        cached_player: CanonicalPlayer | None = None,
    ) -> tuple[float | None, dict]:
        if stack_crop is None:
            return None, {}

        tracker_sanity = getattr(getattr(self, "tracker", None), "sanity", None)
        if tracker_sanity is not None and tracker_sanity.is_stack_read_quarantined(seat_id):
            fallback_value = self._known_stack_fallback(seat_id, cached_player)
            remaining_s = tracker_sanity.get_stack_read_quarantine_remaining(seat_id)
            return fallback_value, self._build_stack_quarantine_metadata(seat_id, fallback_value, remaining_s)

        numeric_reader = getattr(self, "numeric_reader", None)
        if numeric_reader is None:
            numeric_reader = NumericReader(self.amount_ocr)
            self.numeric_reader = numeric_reader

        previous_value = self._known_stack_fallback(seat_id, cached_player)
        numeric_result = numeric_reader.read_amount("stack", stack_crop, previous_value=previous_value)
        metadata = {
            **dict(self.amount_ocr.get_metadata() or {}),
            "numeric_reader": {
                "selected_value": numeric_result.selected_value,
                "evidence": numeric_result.evidence.to_dict(),
                "metadata": dict(numeric_result.metadata),
            },
        }
        return numeric_result.selected_value, metadata

    def _get_player_name_reader(self) -> PlayerNameReader:
        reader = getattr(self, "player_name_reader", None)
        if reader is None:
            reader = PlayerNameReader(self.ocr)
            self.player_name_reader = reader
        return reader

    def _pair_stack_and_name(
        self,
        stack_det: DetectionResult,
        state: TableState,
        frame: np.ndarray,
        seat_index: int,
        seat_id: str,
        is_hero: bool,
        cached_player: CanonicalPlayer | None = None,
    ) -> CanonicalPlayer:
        sx, sy = self._center(stack_det)
        nearest_name = None
        nearest_distance = float("inf")
        for name_det in state.player_names:
            nx, ny = self._center(name_det)
            distance = abs(nx - sx) + abs(ny - sy)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_name = name_det

        stack_crop = self._safe_crop(frame, stack_det.bbox)
        stack_value, stack_ocr_metadata = self._read_player_stack(
            stack_crop=stack_crop,
            seat_id=seat_id,
            cached_player=cached_player,
        )
        if stack_value is None:
            stack_value = 0.0

        player_name = ""
        name_confidence = 0.0
        raw_player_name = ""
        if nearest_name is not None:
            # Remplacement des padding pixels fixes (14, 6) par un ratio dynamique (15% en x, 25% en y)
            name_crop = self._safe_crop(frame, nearest_name.bbox, pad_ratio_x=0.15, pad_ratio_y=0.25)
            name_result = self._get_player_name_reader().read_name(seat_id, name_crop, self._last_valid_player_names_by_seat)
            raw_player_name = str(name_result.metadata.get("raw_text", "") or "")
            name_ocr_metadata = dict(name_result.metadata.get("ocr", {}) or {})
            name_confidence = nearest_name.confidence
        else:
            name_ocr_metadata = {}
            name_result = None
        if name_result is not None:
            player_name = name_result.selected_name
            name_resolution_source = name_result.resolution_source
        else:
            player_name, name_resolution_source = resolve_player_name(
                seat_id=seat_id,
                candidate_name=raw_player_name,
                seat_cache=self._last_valid_player_names_by_seat,
            )
        identity_state = self.player_identity_state.update(seat_id, player_name, name_resolution_source)

        has_button = False
        if state.dealer_button is not None:
            bx, by = self._center(state.dealer_button)
            has_button = abs(bx - sx) + abs(by - sy) < 220

        return CanonicalPlayer(
            seat_id=seat_id,
            seat_index=seat_index,
            stack=float(stack_value),
            name=player_name,
            # La simple perte d'une lecture OCR de stack ne doit pas faire "disparaÃ®tre"
            # le joueur pour le tracker live.
            is_active=True,
            has_folded=False,
            is_hero=is_hero,
            has_button=has_button,
            confidence=round((stack_det.confidence + name_confidence) / 2.0, 3),
            metadata={
                "stack_bbox": list(stack_det.bbox),
                "stack_ocr": stack_ocr_metadata,
                "name_ocr": {
                    **dict(name_ocr_metadata or {}),
                    "raw_text": raw_player_name,
                    "resolved_text": player_name,
                    "resolution_source": name_resolution_source,
                    "identity_state": identity_state,
                    "player_name_reader": name_result.evidence.to_dict() if name_result is not None else None,
                },
            },
        )

    def _pair_stack_quick(
        self,
        stack_det: DetectionResult,
        state: TableState,
        frame: np.ndarray,
        seat_index: int,
        seat_id: str,
        is_hero: bool,
        cached_player: CanonicalPlayer | None,
    ) -> CanonicalPlayer:
        stack_crop = self._safe_crop(frame, stack_det.bbox)
        stack_value, stack_ocr_metadata = self._read_player_stack(
            stack_crop=stack_crop,
            seat_id=seat_id,
            cached_player=cached_player,
        )
        if stack_value is None or float(stack_value or 0.0) <= 0.0:
            stack_value = float(cached_player.stack if cached_player else 0.0)

        player_name = ""
        if cached_player and str(cached_player.name or "").strip():
            player_name = str(cached_player.name).strip()
        elif seat_id in self._last_valid_player_names_by_seat:
            player_name = self._last_valid_player_names_by_seat[seat_id]
        else:
            player_name = seat_id

        sx, sy = self._center(stack_det)
        has_button = False
        if state.dealer_button is not None:
            bx, by = self._center(state.dealer_button)
            has_button = abs(bx - sx) + abs(by - sy) < 220

        metadata = dict((cached_player.metadata or {}) if cached_player else {})
        metadata.update(
            {
                "stack_bbox": list(stack_det.bbox),
                "stack_ocr": stack_ocr_metadata,
                "responsive_stack_seed": True,
            }
        )

        return CanonicalPlayer(
            seat_id=seat_id,
            seat_index=seat_index,
            stack=float(stack_value or 0.0),
            name=player_name,
            is_active=True,
            has_folded=False,
            is_hero=is_hero,
            has_button=has_button,
            confidence=float(cached_player.confidence if cached_player else stack_det.confidence),
            metadata=metadata,
        )

    @staticmethod
    def _runtime_players_have_meaningful_stacks(
        players: Iterable[CanonicalPlayer],
        hero_seat_id: str | None,
    ) -> bool:
        players = list(players or [])
        if not players:
            return False
        positive_stacks = [player for player in players if float(player.stack or 0.0) > 0.0]
        if len(positive_stacks) < 2:
            return False
        if hero_seat_id:
            hero_player = next((player for player in players if player.seat_id == hero_seat_id), None)
            if hero_player is not None and float(hero_player.stack or 0.0) <= 0.0:
                return False
        return True

    def _ordered_stacks_by_table_geometry(self, state: TableState, frame: np.ndarray) -> list[tuple[str, DetectionResult]]:
        ordered = ordered_stacks_by_table_geometry(
            stack_bboxes=[stack_det.bbox for stack_det in state.stacks],
            frame_shape=frame.shape[:2],
            pot_bbox=state.pots[0].bbox if state.pots else None,
        )
        stack_by_bbox = {stack_det.bbox: stack_det for stack_det in state.stacks}
        return [(seat_id, stack_by_bbox[stack_bbox]) for seat_id, stack_bbox in ordered]

    def _infer_hero_seat_id(
        self,
        ordered_stacks: list[tuple[str, DetectionResult]],
        state: TableState,
        frame: np.ndarray,
    ) -> str | None:
        best_seat_id = infer_hero_seat_id(
            ordered_stacks=[(seat_id, stack_det.bbox) for seat_id, stack_det in ordered_stacks],
            hero_card_bboxes=[card.bbox for card in state.hero_cards],
            frame_shape=frame.shape[:2],
            last_hero_seat_id=self._last_hero_seat_id,
        )
        best_seat_id = stable_window_value(
            list(self._recent_runtime_hero_seat_ids),
            best_seat_id,
            ignore_values=(None, ""),
        )
        self._last_hero_seat_id = best_seat_id
        if best_seat_id:
            self._recent_runtime_hero_seat_ids.append(best_seat_id)
        return best_seat_id

    def _player_detection_signature(
        self,
        ordered_stacks: list[tuple[str, DetectionResult]],
        state: TableState,
    ) -> tuple:
        return (
            tuple((seat_id, tuple(stack_det.bbox)) for seat_id, stack_det in ordered_stacks),
            tuple(tuple(name_det.bbox) for name_det in state.player_names),
            tuple(state.dealer_button.bbox) if state.dealer_button is not None else None,
        )

    @staticmethod
    def _refresh_cached_player_runtime_flags(
        players: tuple[CanonicalPlayer, ...],
        hero_seat_id: str | None,
        state: TableState,
    ) -> tuple[CanonicalPlayer, ...]:
        if not players:
            return ()

        dealer_center = None
        if state.dealer_button is not None:
            x1, y1, x2, y2 = state.dealer_button.bbox
            dealer_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

        refreshed_players: list[CanonicalPlayer] = []
        for player in players:
            has_button = False
            if dealer_center is not None:
                stack_bbox = (((player.metadata or {}).get("stack_bbox")) or ())
                if len(stack_bbox) == 4:
                    sx = (stack_bbox[0] + stack_bbox[2]) / 2.0
                    sy = (stack_bbox[1] + stack_bbox[3]) / 2.0
                    has_button = abs(dealer_center[0] - sx) + abs(dealer_center[1] - sy) < 220

            refreshed_players.append(
                CanonicalPlayer(
                    seat_id=player.seat_id,
                    seat_index=player.seat_index,
                    stack=player.stack,
                    name=player.name,
                    is_active=player.is_active,
                    has_folded=player.has_folded,
                    is_hero=player.seat_id == hero_seat_id,
                    has_button=has_button,
                    confidence=player.confidence,
                    metadata=dict(player.metadata or {}),
                )
            )
        return tuple(refreshed_players)

    def _build_players(self, state: TableState, frame: np.ndarray) -> list[CanonicalPlayer]:
        if not state.stacks:
            return []

        ordered_stacks = self._ordered_stacks_by_table_geometry(state, frame)
        hero_seat_id = self._infer_hero_seat_id(ordered_stacks, state, frame)
        signature = self._player_detection_signature(ordered_stacks, state)
        now = time.monotonic()
        responsive_live_path = bool(state.action_buttons)
        reused_visual_state = bool((getattr(state, "metadata", {}) or {}).get("reused_visual_state", False))
        cached_by_seat = {player.seat_id: player for player in self._cached_runtime_players}
        if (
            self._cached_runtime_players
            and len(self._cached_runtime_players) == len(ordered_stacks)
            and (
                responsive_live_path
                or reused_visual_state
                or (now - self._cached_runtime_players_at) <= self._player_ocr_refresh_interval_s
            )
        ):
            return list(self._refresh_cached_player_runtime_flags(self._cached_runtime_players, hero_seat_id, state))

        if responsive_live_path:
            if not self._runtime_players_have_meaningful_stacks(self._cached_runtime_players, hero_seat_id):
                quick_players: list[CanonicalPlayer] = []
                for index, (seat_id, stack_det) in enumerate(ordered_stacks):
                    quick_players.append(
                        self._pair_stack_quick(
                            stack_det=stack_det,
                            state=state,
                            frame=frame,
                            seat_index=index,
                            seat_id=seat_id,
                            is_hero=seat_id == hero_seat_id,
                            cached_player=cached_by_seat.get(seat_id),
                        )
                    )
                self._cached_runtime_players = tuple(quick_players)
                self._cached_runtime_players_signature = signature
                self._cached_runtime_players_at = now
                return quick_players

            dealer_center = None
            if state.dealer_button is not None:
                x1, y1, x2, y2 = state.dealer_button.bbox
                dealer_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

            placeholder_players: list[CanonicalPlayer] = []
            for index, (seat_id, stack_det) in enumerate(ordered_stacks):
                cached_player = cached_by_seat.get(seat_id)
                has_button = False
                if dealer_center is not None:
                    sx = (stack_det.bbox[0] + stack_det.bbox[2]) / 2.0
                    sy = (stack_det.bbox[1] + stack_det.bbox[3]) / 2.0
                    has_button = abs(dealer_center[0] - sx) + abs(dealer_center[1] - sy) < 220

                metadata = dict((cached_player.metadata or {}) if cached_player else {})
                metadata["stack_bbox"] = list(stack_det.bbox)
                metadata["placeholder_runtime_player"] = True
                placeholder_players.append(
                    CanonicalPlayer(
                        seat_id=seat_id,
                        seat_index=index,
                        stack=float(cached_player.stack if cached_player else 0.0),
                        name=(
                            cached_player.name
                            if cached_player and str(cached_player.name or "").strip()
                            else self._last_valid_player_names_by_seat.get(seat_id, seat_id)
                        ),
                        is_active=True,
                        has_folded=False,
                        is_hero=seat_id == hero_seat_id,
                        has_button=has_button,
                        confidence=float(cached_player.confidence if cached_player else stack_det.confidence),
                        metadata=metadata,
                    )
                )
            return placeholder_players

        players = [
            self._pair_stack_and_name(
                stack_det=stack_det,
                state=state,
                frame=frame,
                seat_index=index,
                seat_id=seat_id,
                is_hero=seat_id == hero_seat_id,
                cached_player=cached_by_seat.get(seat_id),
            )
            for index, (seat_id, stack_det) in enumerate(ordered_stacks)
        ]
        self._cached_runtime_players = tuple(players)
        self._cached_runtime_players_signature = signature
        self._cached_runtime_players_at = now
        return players

