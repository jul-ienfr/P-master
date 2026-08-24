from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import json

import cv2
import numpy as np


@dataclass(frozen=True)
class TableGeometry:
    regions: dict[str, tuple[float, float, float, float]]
    source: str = "default"
    table_size: tuple[int, int] = (0, 0)


DEFAULT_RUNTIME_GEOMETRY = TableGeometry(
    regions={
        "table": (0.08, 0.10, 0.92, 0.88),
        "board": (0.22, 0.25, 0.78, 0.60),
        "pot": (0.38, 0.28, 0.62, 0.48),
        "hero": (0.33, 0.62, 0.67, 0.90),
        "actions": (0.42, 0.70, 0.99, 0.99),
    }
)


def _is_area(value: Any) -> bool:
    return isinstance(value, dict) and {"x1", "y1", "x2", "y2"}.issubset(value.keys())


def _normalize_area(value: Dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(value["x1"]),
        int(value["y1"]),
        int(value["x2"]),
        int(value["y2"]),
    )


def _estimate_table_bounds(table_data: Dict[str, Any]) -> tuple[int, int]:
    max_x = 0
    max_y = 0

    def visit(node: Any) -> None:
        nonlocal max_x, max_y
        if _is_area(node):
            x1, y1, x2, y2 = _normalize_area(node)
            max_x = max(max_x, x1, x2)
            max_y = max(max_y, y1, y2)
            return
        if isinstance(node, dict):
            for child in node.values():
                visit(child)

    visit(table_data)
    return max_x + 48, max_y + 48


def _normalize_region(area: Optional[Dict[str, Any]], table_size: tuple[int, int]) -> tuple[float, float, float, float] | None:
    if not _is_area(area):
        return None
    table_width, table_height = table_size
    if table_width <= 0 or table_height <= 0:
        return None
    x1, y1, x2, y2 = _normalize_area(area)
    return (
        max(0.0, min(x1 / table_width, 1.0)),
        max(0.0, min(y1 / table_height, 1.0)),
        max(0.0, min(x2 / table_width, 1.0)),
        max(0.0, min(y2 / table_height, 1.0)),
    )


def geometry_from_manifest(manifest: dict[str, Any], *, source: str = "manifest") -> TableGeometry:
    table_data = dict(manifest.get("table_data", {}) or {})
    table_size = _estimate_table_bounds(table_data)
    regions: dict[str, tuple[float, float, float, float]] = {"table": (0.0, 0.0, 1.0, 1.0)}
    area_mapping = {
        "board": table_data.get("table_cards_area"),
        "pot": table_data.get("total_pot_area"),
        "hero": table_data.get("my_cards_area"),
        "actions": table_data.get("buttons_search_area"),
    }
    for name, area in area_mapping.items():
        normalized = _normalize_region(area, table_size)
        if normalized is not None:
            regions[name] = normalized
    return TableGeometry(regions=regions, source=source, table_size=table_size)


def geometry_from_manifest_path(manifest_path: Path) -> TableGeometry:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return geometry_from_manifest(manifest, source=str(manifest_path))


def geometry_to_pixel_regions(
    frame: np.ndarray,
    geometry: TableGeometry = DEFAULT_RUNTIME_GEOMETRY,
    *,
    table_bbox: tuple[int, int, int, int] | None = None,
) -> Dict[str, tuple[int, int, int, int]]:
    height, width = frame.shape[:2]
    if table_bbox is not None:
        tx1, ty1, tx2, ty2 = table_bbox
        base_x = int(tx1)
        base_y = int(ty1)
        base_width = max(1, int(tx2) - int(tx1))
        base_height = max(1, int(ty2) - int(ty1))
    else:
        base_x = 0
        base_y = 0
        base_width = width
        base_height = height
    pixel_regions: Dict[str, tuple[int, int, int, int]] = {}
    for name, (x1, y1, x2, y2) in geometry.regions.items():
        pixel_regions[name] = (
            int(base_x + (base_width * x1)),
            int(base_y + (base_height * y1)),
            int(base_x + (base_width * x2)),
            int(base_y + (base_height * y2)),
        )
    return pixel_regions


# --- Phase 2.7 : helpers de géométrie déplacés depuis src/main.py ---
from typing import Tuple  # noqa: E402

from src.vision.detector import DetectionResult, TableState  # noqa: E402


def safe_crop(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    pad_x: int = 0,
    pad_y: int = 0,
    pad_ratio_x: float = 0.0,
    pad_ratio_y: float = 0.0,
) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = bbox
    height, width = frame.shape[:2]

    box_width = x2 - x1
    box_height = y2 - y1

    # Le padding relatif (ratio) prime sur le pixel absolu s'il est spécifié
    actual_pad_x = int(box_width * pad_ratio_x) if pad_ratio_x > 0 else pad_x
    actual_pad_y = int(box_height * pad_ratio_y) if pad_ratio_y > 0 else pad_y

    x1 = max(0, min(x1 - actual_pad_x, width))
    x2 = max(0, min(x2 + actual_pad_x, width))
    y1 = max(0, min(y1 - actual_pad_y, height))
    y2 = max(0, min(y2 + actual_pad_y, height))

    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size > 0 else None


def detection_center(det: DetectionResult) -> Tuple[float, float]:
    x1, y1, x2, y2 = det.bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def is_image_changed(
    img1: np.ndarray,
    img2: np.ndarray,
    threshold: float = 0.95,
    mask_edges: bool = True,
) -> bool:
    if img1 is None or img2 is None:
        return True
    try:
        # On redimensionne tout à 100x30 pour unifier la comparaison
        i1 = cv2.resize(img1, (100, 30))
        i2 = cv2.resize(img2, (100, 30))

        # Masque optionnel sur les bords : les animations externes débordent
        # souvent sur les crops pot/stack (avatar qui bouge, chat).
        if mask_edges:
            mask = np.zeros((30, 100), dtype=np.uint8)
            # On ne compare visuellement que la zone centrale (texte OCR)
            cv2.rectangle(mask, (15, 5), (85, 25), 255, -1)
            i1 = cv2.bitwise_and(i1, i1, mask=mask)
            i2 = cv2.bitwise_and(i2, i2, mask=mask)

        i1 = cv2.GaussianBlur(i1, (3, 3), 0)
        i2 = cv2.GaussianBlur(i2, (3, 3), 0)
        diff = cv2.absdiff(i1, i2)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        # Seuil augmenté de 15 à 25 pour tolérer les lueurs
        _, thresh = cv2.threshold(gray_diff, 25, 255, cv2.THRESH_BINARY)
        difference_ratio = np.count_nonzero(thresh) / thresh.size

        return difference_ratio > (1.0 - threshold)
    except Exception:
        return True


_BUTTON_TO_COORD_KEY = {
    "fold_button": "FOLD",
    "call_button": "CALL",
    "check_button": "CALL",
    "bet_button": "BET_BTN",
    "raise_button": "BET_BTN",
}

_COORD_KEYS = ("FOLD", "CALL", "BET_BTN", "BET_BOX")


def build_dynamic_coordinates(
    state: TableState,
    fallback_coords: Dict[str, Any],
) -> tuple[Dict[str, Tuple[int, int]], Dict[str, Dict[str, Any]]]:
    mapping: Dict[str, Tuple[int, int]] = {}
    diagnostics: Dict[str, Dict[str, Any]] = {}

    for button in state.action_buttons:
        cx, cy = detection_center(button)
        coord = (int(cx), int(cy))
        mapped = _BUTTON_TO_COORD_KEY.get(button.class_name.lower())
        if mapped:
            mapping[mapped] = coord
            diagnostics[mapped] = {
                "source": "detected_button",
                "label": str(button.class_name),
                "coord": [coord[0], coord[1]],
                "bbox": [int(value) for value in button.bbox],
                "confidence": round(float(getattr(button, "confidence", 0.0) or 0.0), 3),
            }
    slot_boxes = state.metadata.get("button_slot_boxes", {}) if isinstance(state.metadata, dict) else {}
    if isinstance(slot_boxes, dict):
        for key in _COORD_KEYS:
            bbox = slot_boxes.get(key)
            if (
                key not in mapping
                and isinstance(bbox, (list, tuple))
                and len(bbox) == 4
            ):
                x1, y1, x2, y2 = [int(value) for value in bbox]
                mapping[key] = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                diagnostics[key] = {
                    "source": "slot_box",
                    "label": key,
                    "coord": [mapping[key][0], mapping[key][1]],
                    "bbox": [x1, y1, x2, y2],
                }
    for btn in _COORD_KEYS:
        if btn not in mapping:
            fallback_coord = fallback_coords.get(btn)
            mapping.setdefault(btn, fallback_coord)
            if fallback_coord:
                diagnostics[btn] = {
                    "source": "fallback",
                    "label": btn,
                    "coord": [int(fallback_coord[0]), int(fallback_coord[1])],
                }
    return mapping, diagnostics


def copy_table_state(state: TableState) -> TableState:
    if hasattr(state, "model_copy"):
        return state.model_copy(deep=True)
    if hasattr(state, "copy"):
        return state.copy(deep=True)
    return state
