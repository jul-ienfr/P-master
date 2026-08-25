"""Modèles pydantic et helpers de détection (extrait de src/vision/detector.py)."""
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class DetectionResult(BaseModel):
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


class TableState(BaseModel):
    board_cards: list[DetectionResult] = Field(default_factory=list)
    hero_cards: list[DetectionResult] = Field(default_factory=list)
    dealer_button: DetectionResult | None = None
    pots: list[DetectionResult] = Field(default_factory=list)
    stacks: list[DetectionResult] = Field(default_factory=list)
    player_names: list[DetectionResult] = Field(default_factory=list)
    action_buttons: list[DetectionResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


CARD_CODE_RE = re.compile(r"([2-9TJQKA][shdc])$", re.IGNORECASE)
ACTION_BUTTON_LABELS = (
    "fold_button",
    "call_button",
    "check_button",
    "bet_button",
    "raise_button",
    "all_in_call_button",
    "fast_fold_button",
    "resume_hand",
    "im_back",
    "action_button_generic",
)
MODEL_PATH_CANDIDATE_SUFFIXES = (".engine", ".onnx", ".pt")
FALLBACK_SCALE_FACTORS = (0.75, 0.85, 0.95, 1.0, 1.1, 1.2, 1.35)
BUILTIN_PRESET_MANIFESTS = (
    "poker/pokerstars-7-fr-6-max/draft/manifest.json",
    "poker/official-party-poker/draft/manifest.json",
)


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
    detections: list[DetectionResult],
    x_tolerance: float,
    y_tolerance: float,
) -> list[DetectionResult]:
    kept: list[DetectionResult] = []
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

