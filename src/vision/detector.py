import cv2
import numpy as np
import logging
import re
from ultralytics import YOLO
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Modèle de données strict pour une détection
class DetectionResult(BaseModel):
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

class TableState(BaseModel):
    board_cards: List[DetectionResult] = []
    hero_cards: List[DetectionResult] = []
    dealer_button: Optional[DetectionResult] = None
    pots: List[DetectionResult] = []
    stacks: List[DetectionResult] = []
    player_names: List[DetectionResult] = []
    action_buttons: List[DetectionResult] = []
    metadata: Dict[str, Any] = {}


CARD_CODE_RE = re.compile(r"([2-9TJQKA][shdc])$", re.IGNORECASE)


def decode_card_token(class_name: str) -> str:
    match = CARD_CODE_RE.search(class_name or "")
    if match:
        rank = match.group(1)[0].upper()
        suit = match.group(1)[1].lower()
        return f"{rank}{suit}"
    return ""


def detection_sort_key(det: DetectionResult) -> tuple[float, float]:
    _, y = det.center
    x, _ = det.center
    return (y, x)


def board_sort_key(det: DetectionResult) -> tuple[float, float]:
    x, y = det.center
    return (x, y)


def dedupe_nearby_detections(
    detections: List[DetectionResult],
    x_tolerance: float,
    y_tolerance: float,
) -> List[DetectionResult]:
    kept: List[DetectionResult] = []
    for det in sorted(detections, key=lambda item: item.confidence, reverse=True):
        cx, cy = det.center
        duplicate = False
        for existing in kept:
            ex, ey = existing.center
            if abs(cx - ex) <= x_tolerance and abs(cy - ey) <= y_tolerance:
                duplicate = True
                break
        if not duplicate:
            kept.append(det)
    return kept

class PokerDetector:
    def __init__(self, model_path: str = "models/poker_yolo_v11.engine"):
        """
        Initialise le détecteur d'objets YOLO pour la table de poker.
        
        Args:
            model_path: Le chemin vers le modèle entraîné (.pt pour PyTorch, .engine pour TensorRT/ONNX).
                        TensorRT (.engine) est fortement recommandé en production pour l'inférence en < 5ms.
        """
        self.model_path = model_path
        try:
            # Charger le modèle YOLO (gère nativement les .pt et les formats exportés comme ONNX/TensorRT)
            self.model = YOLO(model_path)
            # Dictionnaire de mapping ID de classe -> Nom de la classe
            self.names = self.model.names
            logger.info(f"Modèle YOLO chargé avec succès depuis {model_path}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement du modèle YOLO: {e}")
            self.model = None

    def analyze_frame(self, frame: np.ndarray, conf_threshold: float = 0.6) -> TableState:
        """
        Analyse une image pour détecter tous les éléments de la table.
        
        Args:
            frame: L'image (numpy array BGR).
            conf_threshold: Le seuil de confiance minimum pour garder une détection.
            
        Returns:
            TableState: Un objet Pydantic contenant la liste catégorisée des détections.
        """
        state = TableState()
        
        if self.model is None or frame is None:
            return state

        # Inférence avec YOLO
        # imgsz=640 est un standard. half=True utilise FP16 pour doubler la vitesse sur GPU
        results = self.model.predict(source=frame, conf=conf_threshold, verbose=False, half=True)
        
        if not results:
            return state

        # YOLO retourne une liste (1 élément car on traite 1 frame)
        result = results[0]
        
        for box in result.boxes:
            # Coordonnées du rectangle englobant (x_min, y_min, x_max, y_max)
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            class_name = self.names[cls_id]

            detection = DetectionResult(
                class_name=class_name,
                confidence=conf,
                bbox=(x1, y1, x2, y2)
            )

            # --- Tri des détections par catégorie ---
            # La logique de nommage dépendra de la façon dont le dataset est annoté dans Roboflow
            if class_name.startswith("card_") or class_name == "board_card" or class_name == "hero_card":
                height = frame.shape[0]
                if class_name == "hero_card" or y1 > height * 0.65:
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

            elif class_name in {
                "fold_button",
                "call_button",
                "check_button",
                "bet_button",
                "raise_button",
                "all_in_call_button",
            }:
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

    def draw_debug_frame(self, frame: np.ndarray, state: TableState) -> np.ndarray:
        """
        Dessine les boîtes de détection sur l'image pour le débogage (HUD local).
        """
        debug_frame = frame.copy()
        
        all_detections = (
            state.board_cards + state.hero_cards + 
            state.pots + state.stacks + state.player_names + state.action_buttons
        )
        if state.dealer_button:
            all_detections.append(state.dealer_button)

        for det in all_detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{det.class_name} {det.confidence:.2f}"
            cv2.putText(debug_frame, label, (x1, max(y1 - 5, 0)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
        return debug_frame
