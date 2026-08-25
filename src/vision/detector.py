"""Orchestrateur de détection : YOLO + fallback template (lecture cartes/table)."""
import logging
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

try:
    from ultralytics import YOLO
except Exception:  # pragma: no cover - depends on optional local runtime packages
    YOLO = None

from src.vision.models import (
    ACTION_BUTTON_LABELS,
    DetectionResult,
    TableState,
    board_sort_key,
    decode_card_token,
    dedupe_nearby_detections,
    detection_sort_key,
)
from src.vision.template_detector import (
    TemplateFallbackDetector,
    _clip_bbox,
    _crop_frame,
    _dedupe_card_detections,
    _extract_card_corner,
    _find_template_sqdiff,
    _resolved_card_detections,
)

logger = logging.getLogger(__name__)

MODEL_PATH_CANDIDATE_SUFFIXES = (".engine", ".onnx", ".pt")

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_model_path(model_path: str) -> Path | None:
    requested = Path(model_path)
    if not requested.is_absolute():
        requested = (_repo_root() / model_path).resolve()

    if requested.is_file():
        return requested

    stem = requested.with_suffix("")
    for suffix in MODEL_PATH_CANDIDATE_SUFFIXES:
        candidate = stem.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


class PokerDetector:
    def __init__(self, model_path: str = "models/poker_yolo_v11.engine", pipeline: list = None):
        self.model_path = model_path
        self.pipeline = pipeline or ["yolo", "llm", "opencv"]
        self.model = None
        self.names = {}
        self.fallback_detector = TemplateFallbackDetector()
        self._last_fallback_preset_name: str | None = None

        resolved_model_path = resolve_model_path(model_path)

        if YOLO is None:
            logger.info(
                "ultralytics n'est pas disponible. Backend vision template actif."
            )
            return

        if resolved_model_path is None:
            logger.info(
                "Modèle YOLO introuvable pour %s. Backend vision template actif.",
                model_path,
            )
            return

        try:
            self.model = YOLO(str(resolved_model_path), task="detect")
            self.names = self.model.names
            logger.info("Modèle YOLO chargé avec succès depuis %s", resolved_model_path)
        except Exception as exc:
            logger.error("Erreur lors du chargement du modèle YOLO: %s", exc)
            self.model = None

    @staticmethod
    def _has_meaningful_signal(state: TableState) -> bool:
        return any(
            (
                state.board_cards,
                state.hero_cards,
                state.pots,
                state.stacks,
                state.player_names,
                state.action_buttons,
                state.dealer_button is not None,
            )
        )

    @staticmethod
    def _has_actionable_button_layout(action_buttons: list[DetectionResult]) -> bool:
        labels = {str(button.class_name or "").lower() for button in action_buttons}
        return "fold_button" in labels and bool(
            labels.intersection({"call_button", "check_button", "bet_button", "raise_button", "all_in_call_button"})
        )

    @staticmethod
    def _has_probable_hero_presence(state: TableState) -> bool:
        resolved_hero = _resolved_card_detections(state.hero_cards)
        return len(resolved_hero) >= 1 or len(state.hero_cards) >= 2

    def _should_query_llm_for_hero(self, state: TableState) -> bool:
        resolved_hero = _resolved_card_detections(state.hero_cards)
        has_hero_context = self._has_probable_hero_presence(state) or self._has_actionable_button_layout(state.action_buttons)
        return bool(state.metadata.get("table_detected")) and len(resolved_hero) < 2 and has_hero_context

    def _hybrid_validate_card(self, crop: np.ndarray, original_class: str) -> str:
        if not self.fallback_detector.presets or crop is None or crop.size == 0:
            return original_class
        
        best_error = 1.0
        best_label = original_class
        
        for preset in self.fallback_detector.presets:
            for label, template in preset.card_templates.items():
                crop_h, crop_w = crop.shape[:2]
                if crop_h < 10 or crop_w < 10:
                    continue
                
                corner = _extract_card_corner(crop)
                t_corner = _extract_card_corner(template)
                if corner is None or t_corner is None:
                    continue
                
                t_corner = cv2.resize(t_corner, (corner.shape[1], corner.shape[0]), interpolation=cv2.INTER_AREA)
                error, _ = _find_template_sqdiff(corner, t_corner)
                if error < best_error:
                    best_error = error
                    best_label = label
                    
        # Seuil d'erreur permissif pour accepter la correction
        if best_error < 0.18:
            return best_label
        return original_class

    def _run_yolo_detection(self, frame: np.ndarray, base_conf_threshold: float) -> TableState:
        state = TableState(metadata={"detector_mode": "yolo"})

        if self.model is None or frame is None:
            return state

        # Run YOLO with a very permissive threshold to catch cards (which are often tricky)
        internal_conf = min(0.05, base_conf_threshold)
        results = self.model.predict(source=frame, conf=internal_conf, verbose=False, half=True)
        if not results:
            return state

        result = results[0]
        for box in result.boxes:
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            class_name = self.names[cls_id]
            
            # Keep cards with >= 0.05 conf temporarily for extreme logging
            is_card_class = len(class_name) == 2 and class_name[0] in "23456789TJQKA" and class_name[1] in "shdc"
            min_required_conf = 0.05 if is_card_class else base_conf_threshold
            if conf < min_required_conf:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            
            detection = DetectionResult(
                class_name=class_name,
                confidence=conf,
                bbox=(x1, y1, x2, y2),
            )

            is_card = bool(decode_card_token(class_name)) or class_name.startswith("card_") or class_name in ("board_card", "hero_card")
            
            # HYBRID FALLBACK: Si YOLO doute d'une carte (conf < 0.82), on demande à OpenCV Templates
            if is_card and conf < 0.82 and decode_card_token(class_name):
                crop = _crop_frame(frame, (x1, y1, x2, y2))
                validated_class = self._hybrid_validate_card(crop, class_name)
                if validated_class != class_name:
                    logger.info(f"[HYBRID] YOLO uncertain ({conf:.2f}) on {class_name}. Corrected to {validated_class} via Template Matching.")
                    class_name = validated_class
            
            detection.class_name = class_name
            if is_card:
                logger.info(f"[YOLO DEBUG] Raw card candidate: cls={class_name} conf={conf:.3f} y1={y1}")
                height = frame.shape[0]
                if class_name == "hero_card" or y1 > height * 0.58:
                    state.hero_cards.append(detection)
                else:
                    state.board_cards.append(detection)
            elif class_name == "dealer_button":
                state.dealer_button = detection
            elif class_name == "pot_area":
                state.pots.append(detection)
            elif class_name == "stack_area":
                state.stacks.append(detection)
            elif class_name == "player_name_area":
                state.player_names.append(detection)
            elif class_name in ACTION_BUTTON_LABELS:
                state.action_buttons.append(detection)

        height, width = frame.shape[:2]
        state.board_cards = dedupe_nearby_detections(
            state.board_cards,
            x_tolerance=max(width * 0.03, 18.0),
            y_tolerance=max(height * 0.04, 22.0),
        )
        state.hero_cards = dedupe_nearby_detections(
            state.hero_cards,
            x_tolerance=max(width * 0.04, 24.0),
            y_tolerance=max(height * 0.05, 28.0),
        )

        state.board_cards.sort(key=board_sort_key)
        state.hero_cards.sort(key=detection_sort_key)
        state.stacks.sort(key=detection_sort_key)
        state.player_names.sort(key=detection_sort_key)
        state.pots.sort(key=detection_sort_key)
        state.action_buttons.sort(key=detection_sort_key)
        return state

    def _run_template_fallback(self, frame: np.ndarray) -> TableState:
        fallback_state = self.fallback_detector.analyze_frame(frame)
        preset_name = fallback_state.metadata.get("fallback_preset")
        if preset_name and preset_name != self._last_fallback_preset_name:
            logger.info("Backend vision template actif: table reconnue via le preset '%s'.", preset_name)
        self._last_fallback_preset_name = preset_name or self._last_fallback_preset_name
        return fallback_state

    def analyze_frame(self, frame: np.ndarray, conf_threshold: float = 0.6) -> TableState:
        if frame is None:
            return TableState(metadata={"detector_mode": "none"})

        state = TableState(metadata={"detector_mode": "none", "table_detected": False})
        
        for step in self.pipeline:
            valides_hero = _resolved_card_detections(state.hero_cards)
            valides_board = _resolved_card_detections(state.board_cards)
            
            # Si on a déjà tout trouvé aux étapes précédentes, on s'arrête là !
            if len(valides_hero) >= 2 and state.metadata.get("table_detected"):
                break
                
            if step == "yolo" and self.model is not None:
                yolo_state = self._run_yolo_detection(frame, conf_threshold)
                if self._has_meaningful_signal(yolo_state):
                    state.metadata["table_detected"] = True
                    # On comble les trous avec ce que YOLO a trouvé
                    if len(valides_hero) < 2:
                        state.hero_cards = yolo_state.hero_cards
                    if not valides_board:
                        state.board_cards = yolo_state.board_cards
                    if not state.action_buttons:
                        state.action_buttons = yolo_state.action_buttons
                    if not state.pots:
                        state.pots = yolo_state.pots
                        
            elif step == "opencv" and self.fallback_detector.available():
                fallback_state = self._run_template_fallback(frame)
                if fallback_state.metadata.get("table_detected"):
                    state.metadata["table_detected"] = True
                    state.metadata["detector_mode"] = str(fallback_state.metadata.get("detector_mode") or "template")
                    for key in (
                        "fallback_preset",
                        "topleft_anchor_asset",
                        "topleft_anchor_offset",
                        "topleft_match_error",
                        "topleft_match_score",
                        "topleft_match_scale",
                        "content_match_scale",
                        "content_region_scale",
                        "table_bbox",
                        "button_slot_boxes",
                        "static_stack_area_count",
                        "static_name_area_count",
                    ):
                        if key in fallback_state.metadata:
                            state.metadata[key] = fallback_state.metadata[key]
                if fallback_state.hero_cards and len(valides_hero) < 2:
                    logger.info(f"OpenVL a trouvé les cartes : {fallback_state.hero_cards}")
                    state.hero_cards = fallback_state.hero_cards
                    # Active Learning (Sauvegarde image pour annotation si YOLO/LLM a échoué avant)
                    try:
                        import os
                        from datetime import datetime

                        import cv2
                        os.makedirs("dataset/needs_annotation", exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                        cv2.imwrite(f"dataset/needs_annotation/al_openvl_{timestamp}.jpg", frame)
                    except: pass
                if fallback_state.board_cards and not state.board_cards:
                    state.board_cards = fallback_state.board_cards
                if fallback_state.action_buttons and not state.action_buttons:
                    state.action_buttons = fallback_state.action_buttons
                if fallback_state.pots and not state.pots:
                    state.pots = fallback_state.pots
                if fallback_state.stacks and not state.stacks:
                    state.stacks = fallback_state.stacks
                if fallback_state.player_names and not state.player_names:
                    state.player_names = fallback_state.player_names
                if fallback_state.dealer_button is not None and state.dealer_button is None:
                    state.dealer_button = fallback_state.dealer_button
                    
            elif step == "llm" and hasattr(self, "ai_fallback") and self.ai_fallback is not None:
                if self._should_query_llm_for_hero(state):
                    logger.info("Appel de l'API LLM...")
                    h, w = frame.shape[:2]
                    boxes = self.ai_fallback.ask_ai_with_fallbacks("", w, h, frame=frame)
                    if boxes:
                        llm_hero: list[DetectionResult] = []
                        for b in boxes:
                            cls_name = b.get("class", "")
                            if not decode_card_token(cls_name):
                                continue
                            ymin = float(b.get("ymin", 0) or 0)
                            if ymin <= (h / 2):
                                continue
                            try:
                                bbox = _clip_bbox(
                                    (
                                        int(float(b.get("xmin", 0) or 0)),
                                        int(float(b.get("ymin", 0) or 0)),
                                        int(float(b.get("xmax", 0) or 0)),
                                        int(float(b.get("ymax", 0) or 0)),
                                    ),
                                    frame.shape[:2],
                                )
                            except (TypeError, ValueError):
                                continue
                            llm_hero.append(
                                DetectionResult(
                                    class_name=cls_name,
                                    confidence=float(b.get("confidence", 1.0) or 1.0),
                                    bbox=bbox,
                                )
                            )
                        
                        if len(llm_hero) == 2:
                            llm_hero = _dedupe_card_detections(llm_hero, detection_sort_key)
                            if len(llm_hero) == 2:
                                logger.info("API LLM a validé les cartes: %s", [card.class_name for card in llm_hero])
                                state.hero_cards = llm_hero
                                state.metadata["table_detected"] = True
                                # Active Learning Automatique
                                try:
                                    import os
                                    from datetime import datetime

                                    import cv2
                                    yolo_txt = self.ai_fallback.convert_to_yolo_format(boxes, w, h)
                                    os.makedirs("dataset/raw_images", exist_ok=True)
                                    os.makedirs("dataset/labels", exist_ok=True)
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                                    cv2.imwrite(f"dataset/raw_images/al_llm_{timestamp}.jpg", frame)
                                    with open(f"dataset/labels/al_llm_{timestamp}.txt", "w") as f:
                                        f.write(yolo_txt)
                                except: pass

        return state

    def draw_debug_frame(self, frame: np.ndarray, state: TableState) -> np.ndarray:
        debug_frame = frame.copy()

        all_detections = (
            state.board_cards
            + state.hero_cards
            + state.pots
            + state.stacks
            + state.player_names
            + state.action_buttons
        )
        if state.dealer_button:
            all_detections.append(state.dealer_button)

        for det in all_detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{det.class_name} {det.confidence:.2f}"
            cv2.putText(
                debug_frame,
                label,
                (x1, max(y1 - 5, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2,
            )

        if state.metadata.get("fallback_preset"):
            cv2.putText(
                debug_frame,
                f"fallback: {state.metadata['fallback_preset']}",
                (12, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 200, 255),
                2,
            )

        return debug_frame
