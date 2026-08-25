"""Classification des boutons d'action — Phase 2.7 (extraction de src/main.py)

Logique déplacée à l'identique : OCR texte des boutons, classification
générique/par slot, promotion fast-fold, labeling complet d'un état table.
Aucun changement comportemental — les tests existants font office de garde-fou.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable

import cv2
import numpy as np

from src.vision.models import (
    DetectionResult,
    TableState,
    dedupe_nearby_detections,
    detection_sort_key,
)

logger = logging.getLogger(__name__)

STANDARD_ACTION_LABELS = {
    "fold_button",
    "call_button",
    "check_button",
    "bet_button",
    "raise_button",
    "all_in_call_button",
}

SPECIALIZED_LABELS = {"resume_hand", "im_back", "fast_fold_button"}

_KEYWORD_TOKENS = (
    "check",
    "call",
    "fold",
    "bet",
    "raise",
    "miser",
    "suivre",
    "passer",
    "payer",
    "relancer",
    "reprendre",
    "rejoindre",
    "jouer",
    "resume",
    "play",
    "join",
    "back",
    "vite",
    "time",
    "temps",
    "bank",
    "banque",
    "more",
    "give",
)


def normalize_action_button_text(raw_text: str) -> str:
    if not raw_text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(raw_text))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = "".join(
        char if char.isalnum() or char.isspace() else " " for char in normalized.lower()
    )
    return " ".join(cleaned.split())


def is_resume_like_button_text(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    compact_text = normalized_text.replace(" ", "")
    if any(
        token in normalized_text
        for token in (
            "reprendre",
            "rejoindre",
            "jouer",
            "joue",
            "resume",
            "continuer",
            "play",
            "join",
        )
    ):
        return True
    return (
        compact_text in {"jouer", "joue", "resume", "play", "join", "continue"}
        or compact_text.startswith("jou")
        or compact_text.startswith("rejo")
        or compact_text.endswith("ouer")
    )


def button_slot_overlap_ratio(
    bbox: tuple[int, int, int, int],
    slot_bbox: tuple[int, int, int, int],
) -> float:
    x1 = max(bbox[0], slot_bbox[0])
    y1 = max(bbox[1], slot_bbox[1])
    x2 = min(bbox[2], slot_bbox[2])
    y2 = min(bbox[3], slot_bbox[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = float((x2 - x1) * (y2 - y1))
    area = float(max(1, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
    return intersection / area


class ButtonClassifier:
    def __init__(self, ocr, read_text_fn: Callable[[np.ndarray | None], str] | None = None):
        self.ocr = ocr
        self._text_cache: dict[bytes, str] = {}
        # Lecteur de texte injecté par l'hôte (cache hôte, stubs de test).
        # None => lecture OCR native ci-dessous.
        self._read_text_fn = read_text_fn

    def read_action_button_text(self, image_crop: np.ndarray | None) -> str:
        if self._read_text_fn is not None:
            return self._read_text_fn(image_crop)
        return self.native_read_action_button_text(image_crop)

    def native_read_action_button_text(self, image_crop: np.ndarray | None) -> str:
        if image_crop is None or image_crop.size == 0:
            return ""

        cache_key = None
        cache = self._text_cache

        try:
            preview = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
            preview = cv2.resize(preview, (48, 20), interpolation=cv2.INTER_AREA)
            cache_key = preview.tobytes()
            cached_text = cache.get(cache_key)
            if cached_text is not None:
                return cached_text
        except Exception:
            cache_key = None

        variants: list[np.ndarray] = [image_crop]
        try:
            gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
            upscaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            variants.append(cv2.cvtColor(upscaled, cv2.COLOR_GRAY2BGR))

            _, threshold = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(cv2.cvtColor(threshold, cv2.COLOR_GRAY2BGR))

            inverse = 255 - threshold
            variants.append(cv2.cvtColor(inverse, cv2.COLOR_GRAY2BGR))
        except Exception:
            pass

        best_text = ""
        best_score = -1
        for variant in variants:
            try:
                candidate = normalize_action_button_text(self.ocr.read_text(variant))
            except Exception:
                continue
            if not candidate:
                continue

            keyword_score = sum(1 for token in _KEYWORD_TOKENS if token in candidate)
            score = keyword_score * 100 + len(candidate)
            if score > best_score:
                best_text = candidate
                best_score = score
            if keyword_score > 0:
                break

        if cache_key is not None:
            if len(cache) >= 96:
                cache.clear()
            cache[cache_key] = best_text
        return best_text

    def classify_action_button_label(
        self,
        image_crop: np.ndarray | None,
        button_index: int,
        button_count: int,
    ) -> str:
        normalized_text = self.read_action_button_text(image_crop)
        if normalized_text:
            compact_text = normalized_text.replace(" ", "")
            if is_resume_like_button_text(normalized_text):
                return "resume_hand"
            if (
                "im back" in normalized_text
                or compact_text == "imback"
                or compact_text.endswith("back")
            ):
                return "im_back"
            if (
                "passer vite" in normalized_text
                or "fast fold" in normalized_text
                or (
                    button_count == 1
                    and any(token in normalized_text for token in ("passer", "fold", "coucher"))
                )
            ):
                return "fast_fold_button"
            if any(token in normalized_text for token in ("fold", "passer", "coucher")):
                return "fold_button"
            if "check" in normalized_text:
                return "check_button"
            if any(token in normalized_text for token in ("call", "suivre", "payer")):
                return "call_button"
            if any(token in normalized_text for token in ("raise", "relancer")):
                return "raise_button"
            if any(token in normalized_text for token in ("bet", "miser")):
                return "bet_button"

            if any(char.isdigit() for char in normalized_text):
                if button_count <= 1:
                    return "resume_hand"
                return "raise_button" if button_index == max(button_count - 1, 0) else "call_button"

        if button_count >= 3:
            if button_index == 0:
                return "fold_button"
            if button_index == button_count - 1:
                return "raise_button"
            return "call_button"
        if button_count == 2:
            return "check_button" if button_index == 0 else "bet_button"
        return "resume_hand"

    @staticmethod
    def slot_key_for_button(
        button: DetectionResult,
        slot_boxes: dict[str, object],
    ) -> str:
        best_slot = ""
        best_ratio = 0.0
        for slot_key, raw_bbox in dict(slot_boxes or {}).items():
            if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
                continue
            slot_bbox = tuple(int(value) for value in raw_bbox)
            overlap_ratio = button_slot_overlap_ratio(button.bbox, slot_bbox)
            if overlap_ratio > best_ratio:
                best_ratio = overlap_ratio
                best_slot = str(slot_key)
        return best_slot if best_ratio >= 0.2 else ""

    def classify_slot_button_label(
        self,
        image_crop: np.ndarray | None,
        slot_key: str,
        visible_slot_keys: set[str],
        fallback_label: str,
    ) -> str:
        has_fold_slot = "FOLD" in visible_slot_keys
        has_call_slot = "CALL" in visible_slot_keys
        has_bet_slot = "BET_BTN" in visible_slot_keys
        normalized_text = ""
        compact_text = ""

        if slot_key == "FOLD":
            if (has_call_slot or has_bet_slot) and fallback_label != "fast_fold_button":
                return "fold_button"
            normalized_text = self.read_action_button_text(image_crop)
            compact_text = normalized_text.replace(" ", "")
            if (
                "passer vite" in normalized_text
                or "fast fold" in normalized_text
                or compact_text == "passervite"
            ):
                return "fast_fold_button"
            return "fold_button"

        if any(token in normalized_text for token in ("time", "temps", "bank", "banque")):
            return "time_bank_button"

        if slot_key == "CALL":
            if has_fold_slot:
                return (
                    fallback_label
                    if fallback_label in {"call_button", "all_in_call_button"}
                    else "call_button"
                )
            if has_bet_slot:
                return (
                    fallback_label
                    if fallback_label in {"check_button", "call_button", "all_in_call_button"}
                    else "check_button"
                )
            normalized_text = self.read_action_button_text(image_crop)
            compact_text = normalized_text.replace(" ", "")
            if (
                "im back" in normalized_text
                or compact_text == "imback"
                or compact_text.endswith("back")
            ):
                return "im_back"
            if is_resume_like_button_text(normalized_text):
                return "resume_hand"
            if "check" in normalized_text:
                return "check_button"
            if any(token in normalized_text for token in ("call", "suivre", "payer")):
                return "call_button"
            if fallback_label in {"resume_hand", "im_back"}:
                return fallback_label
            return "resume_hand"

        if slot_key == "BET_BTN":
            if has_call_slot and has_fold_slot:
                return (
                    fallback_label
                    if fallback_label in {"bet_button", "raise_button"}
                    else "raise_button"
                )
            if has_call_slot:
                return (
                    fallback_label
                    if fallback_label in {"bet_button", "raise_button"}
                    else "bet_button"
                )
            normalized_text = self.read_action_button_text(image_crop)
            compact_text = normalized_text.replace(" ", "")
            if any(token in normalized_text for token in ("raise", "relancer")):
                return "raise_button"
            if "all in" in normalized_text or compact_text == "allin":
                return "raise_button"
            if any(char.isdigit() for char in normalized_text):
                return "raise_button" if has_call_slot else "bet_button"
            if any(token in normalized_text for token in ("bet", "miser")):
                return "bet_button"
            if fallback_label in {"bet_button", "raise_button"}:
                return fallback_label
            return "bet_button"

        return fallback_label

    @staticmethod
    def promote_fast_fold_outliers(buttons: list[DetectionResult]) -> list[DetectionResult]:
        if len(buttons) < 3:
            return buttons

        reference_buttons = [
            button
            for button in buttons
            if button.class_name
            in {"check_button", "call_button", "bet_button", "raise_button", "all_in_call_button"}
        ]
        fold_candidates = [button for button in buttons if button.class_name == "fold_button"]
        if len(reference_buttons) < 2 or not fold_candidates:
            return buttons

        reference_ys = sorted(button.center[1] for button in reference_buttons)
        median_reference_y = reference_ys[len(reference_ys) // 2]
        reference_height = max(
            1.0,
            float(
                sum((button.bbox[3] - button.bbox[1]) for button in reference_buttons)
                / len(reference_buttons)
            ),
        )
        y_threshold = max(28.0, reference_height * 0.55)

        normalized: list[DetectionResult] = []
        for button in buttons:
            if button.class_name != "fold_button":
                normalized.append(button)
                continue

            center_x, center_y = button.center
            if center_y >= (median_reference_y + y_threshold):
                normalized.append(
                    DetectionResult(
                        class_name="fast_fold_button",
                        confidence=button.confidence,
                        bbox=button.bbox,
                    )
                )
                continue

            normalized.append(button)

        return normalized

    def label_generic_action_buttons(
        self,
        state: TableState,
        frame: np.ndarray,
        safe_crop: Callable[..., np.ndarray | None],
    ) -> TableState:
        if not state.action_buttons:
            return state

        ordered_buttons = sorted(state.action_buttons, key=lambda button: button.center[0])
        standard_labels = set(STANDARD_ACTION_LABELS)
        slot_boxes = (
            state.metadata.get("button_slot_boxes", {}) if isinstance(state.metadata, dict) else {}
        )
        visible_slot_keys = {
            slot_key
            for button in state.action_buttons
            for slot_key in [self.slot_key_for_button(button, slot_boxes)]
            if slot_key
        }
        relabeled_buttons: list[DetectionResult] = []
        button_count = len(state.action_buttons)
        for generic_index, button in enumerate(state.action_buttons):
            slot_key = self.slot_key_for_button(button, slot_boxes)
            if button.class_name in standard_labels and not slot_key:
                relabeled_buttons.append(button)
                continue

            # Remplacement des crop buttons absolus par le ratio dynamique (10% x, 15% y)
            crop = safe_crop(frame, button.bbox, pad_ratio_x=0.10, pad_ratio_y=0.15)
            if slot_key:
                classified = self.classify_slot_button_label(
                    image_crop=crop,
                    slot_key=slot_key,
                    visible_slot_keys=visible_slot_keys,
                    fallback_label=button.class_name,
                )
            else:
                classified = self.classify_action_button_label(crop, generic_index, button_count)
            specialized_labels = set(SPECIALIZED_LABELS)
            if (
                slot_key
                or button.class_name == "action_button_generic"
                or classified in specialized_labels
            ):
                relabeled_buttons.append(
                    DetectionResult(
                        class_name=classified,
                        confidence=button.confidence,
                        bbox=button.bbox,
                    )
                )
            else:
                relabeled_buttons.append(button)

        relabeled_buttons = dedupe_nearby_detections(
            relabeled_buttons, x_tolerance=36.0, y_tolerance=24.0
        )
        relabeled_buttons = self.promote_fast_fold_outliers(relabeled_buttons)
        if any(button.class_name in standard_labels for button in relabeled_buttons):
            relabeled_buttons = [
                button
                for button in relabeled_buttons
                if button.class_name not in {"resume_hand", "im_back"}
            ]
        state.action_buttons = sorted(relabeled_buttons, key=detection_sort_key)
        return state
