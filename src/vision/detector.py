import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from pydantic import BaseModel, Field

from src.vision.preset_registry import PresetRegistry

try:
    from ultralytics import YOLO
except Exception:  # pragma: no cover - depends on optional local runtime packages
    YOLO = None

logger = logging.getLogger(__name__)


class DetectionResult(BaseModel):
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


class TableState(BaseModel):
    board_cards: List[DetectionResult] = Field(default_factory=list)
    hero_cards: List[DetectionResult] = Field(default_factory=list)
    dealer_button: Optional[DetectionResult] = None
    pots: List[DetectionResult] = Field(default_factory=list)
    stacks: List[DetectionResult] = Field(default_factory=list)
    player_names: List[DetectionResult] = Field(default_factory=list)
    action_buttons: List[DetectionResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_model_path(model_path: str) -> Optional[Path]:
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


def _load_cv2_image(path: Path) -> np.ndarray:
    payload = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(payload, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unable to decode image at {path}")
    return image


def _is_area(value: Any) -> bool:
    return isinstance(value, dict) and {"x1", "y1", "x2", "y2"}.issubset(value.keys())


def _normalize_area(value: Dict[str, Any]) -> Tuple[int, int, int, int]:
    return (
        int(value["x1"]),
        int(value["y1"]),
        int(value["x2"]),
        int(value["y2"]),
    )


def _estimate_table_bounds(table_data: Dict[str, Any]) -> Tuple[int, int]:
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


def _find_template_sqdiff(haystack: np.ndarray, template: np.ndarray) -> Tuple[float, Tuple[int, int]]:
    if haystack is None or template is None:
        return 1.0, (0, 0)
    if haystack.shape[0] < template.shape[0] or haystack.shape[1] < template.shape[1]:
        return 1.0, (0, 0)
    result = cv2.matchTemplate(haystack, template, cv2.TM_SQDIFF_NORMED)
    min_val, _, min_loc, _ = cv2.minMaxLoc(result)
    return float(min_val), (int(min_loc[0]), int(min_loc[1]))


def _find_template_candidates(
    haystack: np.ndarray,
    template: np.ndarray,
    threshold: float,
    max_candidates: int,
) -> List[Tuple[float, Tuple[int, int]]]:
    if haystack is None or template is None:
        return []
    if haystack.shape[0] < template.shape[0] or haystack.shape[1] < template.shape[1]:
        return []

    result = cv2.matchTemplate(haystack, template, cv2.TM_SQDIFF_NORMED)
    working = result.copy()
    suppression_x = max(3, template.shape[1] // 2)
    suppression_y = max(3, template.shape[0] // 2)
    candidates: List[Tuple[float, Tuple[int, int]]] = []

    for _ in range(max_candidates):
        min_val, _, min_loc, _ = cv2.minMaxLoc(working)
        if float(min_val) > threshold:
            break

        x, y = int(min_loc[0]), int(min_loc[1])
        candidates.append((float(min_val), (x, y)))

        x1 = max(0, x - suppression_x)
        y1 = max(0, y - suppression_y)
        x2 = min(working.shape[1], x + suppression_x + 1)
        y2 = min(working.shape[0], y + suppression_y + 1)
        working[y1:y2, x1:x2] = 1.0

    return candidates


def _clip_bbox(bbox: Tuple[int, int, int, int], frame_shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = bbox
    return (
        max(0, min(int(x1), width)),
        max(0, min(int(y1), height)),
        max(0, min(int(x2), width)),
        max(0, min(int(y2), height)),
    )


def _bbox_overlap_ratio(
    bbox: Tuple[int, int, int, int],
    region: Tuple[int, int, int, int],
) -> float:
    x1 = max(int(bbox[0]), int(region[0]))
    y1 = max(int(bbox[1]), int(region[1]))
    x2 = min(int(bbox[2]), int(region[2]))
    y2 = min(int(bbox[3]), int(region[3]))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = float((x2 - x1) * (y2 - y1))
    area = float(max(1, (int(bbox[2]) - int(bbox[0])) * (int(bbox[3]) - int(bbox[1]))))
    return max(0.0, min(intersection / area, 1.0))


def _center_inside_region(center: Tuple[float, float], region: Tuple[int, int, int, int]) -> bool:
    return float(region[0]) <= center[0] <= float(region[2]) and float(region[1]) <= center[1] <= float(region[3])


def _distance_score(center: Tuple[float, float], region: Tuple[int, int, int, int]) -> float:
    rx = (float(region[0]) + float(region[2])) / 2.0
    ry = (float(region[1]) + float(region[3])) / 2.0
    half_w = max(1.0, (float(region[2]) - float(region[0])) / 2.0)
    half_h = max(1.0, (float(region[3]) - float(region[1])) / 2.0)
    normalized_distance = (((center[0] - rx) / half_w) ** 2 + ((center[1] - ry) / half_h) ** 2) ** 0.5
    return max(0.0, min(1.0, 1.0 - (normalized_distance / 1.6)))


def _card_shape_score(detection: DetectionResult, region: Tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = detection.bbox
    width = max(1.0, float(x2 - x1))
    height = max(1.0, float(y2 - y1))
    aspect = width / height
    aspect_score = max(0.0, 1.0 - (abs(aspect - 0.72) / 0.45))
    region_area = max(1.0, float((region[2] - region[0]) * (region[3] - region[1])))
    area_ratio = (width * height) / region_area
    size_score = max(0.0, min(1.0, area_ratio / 0.12))
    return round((aspect_score * 0.7) + (size_score * 0.3), 4)


def score_detection_geometry(
    detection: DetectionResult,
    region: Tuple[int, int, int, int],
    *,
    visual_kind: str = "",
) -> Dict[str, Any]:
    center = detection.center
    center_score = 1.0 if _center_inside_region(center, region) else 0.0
    overlap_score = _bbox_overlap_ratio(detection.bbox, region)
    distance_score = _distance_score(center, region)
    geometry_score = (center_score * 0.45) + (overlap_score * 0.35) + (distance_score * 0.20)
    result: Dict[str, Any] = {
        "class_name": detection.class_name,
        "bbox": [int(value) for value in detection.bbox],
        "center_in_region": bool(center_score),
        "overlap_score": round(overlap_score, 4),
        "distance_score": round(distance_score, 4),
        "geometry_score": round(max(0.0, min(geometry_score, 1.0)), 4),
    }
    if visual_kind == "card":
        result["visual_score"] = _card_shape_score(detection, region)
        result["score"] = round((result["geometry_score"] * 0.8) + (result["visual_score"] * 0.2), 4)
    else:
        result["score"] = result["geometry_score"]
    return result


def build_detection_quality_metadata(
    state: TableState,
    pixel_regions: Dict[str, Tuple[int, int, int, int]],
) -> Dict[str, Any]:
    region_map = {
        "board_cards": "board",
        "hero_cards": "hero",
        "pots": "pot",
        "dealer_button": "table",
        "action_buttons": "actions",
    }
    quality: Dict[str, Any] = {}
    for field_name, region_name in region_map.items():
        region = pixel_regions.get(region_name)
        raw_detections = getattr(state, field_name, None)
        detections = raw_detections if isinstance(raw_detections, list) else ([raw_detections] if raw_detections is not None else [])
        items = [
            score_detection_geometry(
                detection,
                region,
                visual_kind="card" if field_name in {"board_cards", "hero_cards"} else "",
            )
            for detection in detections
            if region is not None
        ]
        quality[field_name] = {
            "region": region_name,
            "count": len(detections),
            "average_score": round(sum(item["score"] for item in items) / len(items), 4) if items else 0.0,
            "detections": items,
        }
    return quality


def _crop_frame(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = _clip_bbox(bbox, frame.shape[:2])
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size > 0 else None


def _resize_template(template: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-6:
        return template
    width = max(4, int(round(template.shape[1] * scale)))
    height = max(4, int(round(template.shape[0] * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(template, (width, height), interpolation=interpolation)


def _scale_bbox(
    bbox: Tuple[int, int, int, int],
    scale: float | Tuple[float, float],
) -> Tuple[int, int, int, int]:
    if isinstance(scale, tuple):
        scale_x, scale_y = scale
        x1, y1, x2, y2 = bbox
        return (
            int(round(x1 * scale_x)),
            int(round(y1 * scale_y)),
            int(round(x2 * scale_x)),
            int(round(y2 * scale_y)),
        )
    return tuple(int(round(value * scale)) for value in bbox)


def _expand_bbox(
    bbox: Tuple[int, int, int, int],
    pad_x: int,
    pad_y: int,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return (x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y)


def _card_template_scale_candidates(base_scale: float) -> List[float]:
    candidates = []
    for factor in (0.82, 0.9, 0.96, 1.0, 1.06):
        candidate = round(base_scale * factor, 3)
        if 0.55 <= candidate <= 1.75:
            candidates.append(candidate)
    return sorted(dict.fromkeys(candidates))


def _extract_card_corner(image: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if image is None or image.size == 0:
        return None
    height, width = image.shape[:2]
    corner_width = max(8, int(round(width * 0.48)))
    corner_height = max(10, int(round(height * 0.58)))
    return image[:corner_height, :corner_width]


def _has_visible_card_signal(crop: Optional[np.ndarray]) -> bool:
    if crop is None or crop.size == 0:
        return False

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    bright_ratio = float((gray > 140).mean())
    high_bright_ratio = float((gray > 180).mean())
    gray_std = float(gray.std())
    green_ratio = float(
        (
            (hsv[:, :, 0] > 35)
            & (hsv[:, :, 0] < 95)
            & (hsv[:, :, 1] > 40)
        ).mean()
    )

    if bright_ratio >= 0.12 or high_bright_ratio >= 0.08:
        return True
    if gray_std >= 45.0 and green_ratio < 0.75:
        return True
    return False


def _location_adjusted_error(
    raw_error: float,
    location: Tuple[int, int],
    search_shape: Tuple[int, int],
    template_shape: Tuple[int, int],
) -> float:
    search_height, search_width = search_shape
    _template_height, _template_width = template_shape

    # Penalize only candidates that land materially away from the slot origin.
    # Using the search area size keeps the bias stable across template widths.
    x_ratio = float(location[0]) / max(float(search_width), 1.0)
    y_ratio = float(location[1]) / max(float(search_height), 1.0)
    x_penalty = max(0.0, x_ratio - 0.08)
    y_penalty = max(0.0, y_ratio - 0.05)
    return float(raw_error) + (0.08 * x_penalty) + (0.1 * y_penalty)


def _dedupe_card_detections(detections: List[DetectionResult], sort_key) -> List[DetectionResult]:
    best_by_label: Dict[str, DetectionResult] = {}
    for detection in detections:
        existing = best_by_label.get(detection.class_name)
        if existing is None or detection.confidence > existing.confidence:
            best_by_label[detection.class_name] = detection
    unique = list(best_by_label.values())
    unique.sort(key=sort_key)
    return unique


def _resolved_card_detections(detections: List[DetectionResult]) -> List[DetectionResult]:
    return [detection for detection in detections if decode_card_token(detection.class_name)]


@dataclass
class TemplatePreset:
    name: str
    manifest_path: Path
    table_data: Dict[str, Any]
    anchor_templates: Dict[str, np.ndarray]
    anchor_offsets: Dict[str, Tuple[int, int]]
    anchor_match_bounds: Dict[str, Tuple[int, int]]
    action_templates: Dict[str, np.ndarray]
    card_templates: Dict[str, np.ndarray]
    dealer_template: Optional[np.ndarray]
    table_width: int
    table_height: int


class TemplateFallbackDetector:
    """Template detector used as a first-class vision backend for calibrated table themes."""

    def __init__(self, preset_manifests: Optional[List[Path]] = None):
        manifests = preset_manifests or []
        if manifests:
            manifests = list(PresetRegistry.from_paths(manifests).existing())
        self.presets = self._load_presets(manifests)
        self._last_match: Optional[Dict[str, Any]] = None

    def available(self) -> bool:
        return bool(self.presets)

    @staticmethod
    def _heuristic_action_area(table_shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
        height, width = table_shape[:2]
        return (
            int(round(width * 0.38)),
            int(round(height * 0.74)),
            int(round(width * 0.995)),
            int(round(height * 0.995)),
        )

    @staticmethod
    def _heuristic_hero_area(table_shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
        height, width = table_shape[:2]
        return (
            int(round(width * 0.40)),
            int(round(height * 0.60)),
            int(round(width * 0.64)),
            int(round(height * 0.93)),
        )

    def analyze_frame(self, frame: np.ndarray) -> TableState:
        state = TableState(metadata={"detector_mode": "template", "table_detected": False})
        preset_match = self._locate_best_preset(frame)
        if preset_match is None:
            state.metadata["fallback_reason"] = "no_preset_anchor_matched"
            return state

        preset, top_left, anchor_error, anchor_name, template_scale = preset_match
        anchor_offset = preset.anchor_offsets.get(anchor_name, (0, 0))
        scaled_anchor_offset = (
            int(round(anchor_offset[0] * template_scale)),
            int(round(anchor_offset[1] * template_scale)),
        )
        origin_x = top_left[0] - scaled_anchor_offset[0]
        origin_y = top_left[1] - scaled_anchor_offset[1]
        table_bbox = (
            origin_x,
            origin_y,
            origin_x + int(round(preset.table_width * template_scale)),
            origin_y + int(round(preset.table_height * template_scale)),
        )
        table_origin = (origin_x, origin_y)
        table_frame = _crop_frame(frame, table_bbox)
        if table_frame is None:
            state.metadata["fallback_reason"] = "cropped_table_empty"
            return state

        clipped_table_bbox = _clip_bbox(table_bbox, frame.shape[:2])
        effective_width = max(1, int(clipped_table_bbox[2] - clipped_table_bbox[0]))
        effective_height = max(1, int(clipped_table_bbox[3] - clipped_table_bbox[1]))
        region_scale_x = effective_width / max(float(preset.table_width), 1.0)
        region_scale_y = effective_height / max(float(preset.table_height), 1.0)
        region_scale = (region_scale_x, region_scale_y)
        content_scale = max(0.55, min(float(template_scale), (region_scale_x + region_scale_y) / 2.0))

        state.metadata.update(
            {
                "table_detected": True,
                "fallback_preset": preset.name,
                "topleft_anchor_asset": anchor_name,
                "topleft_anchor_offset": [int(value) for value in scaled_anchor_offset],
                "topleft_match_error": round(anchor_error, 4),
                "topleft_match_score": round(max(0.0, 1.0 - anchor_error), 4),
                "topleft_match_scale": round(float(template_scale), 3),
                "content_match_scale": round(float(content_scale), 3),
                "content_region_scale": [round(float(region_scale_x), 3), round(float(region_scale_y), 3)],
                "table_bbox": [int(value) for value in clipped_table_bbox],
                "button_slot_boxes": {
                    key: [int(value) for value in bbox]
                    for key, bbox in self._collect_preset_slot_boxes(
                        preset=preset,
                        region_scale=region_scale,
                        top_left=table_origin,
                        frame_shape=frame.shape[:2],
                    ).items()
                },
            }
        )

        state.action_buttons = self._detect_action_buttons(frame, table_frame, preset, table_origin, content_scale, region_scale)
        state.dealer_button = self._detect_dealer_button(frame, table_frame, preset, table_origin, content_scale, region_scale)
        state.hero_cards = self._detect_hero_cards(frame, table_frame, preset, table_origin, content_scale, region_scale)
        state.board_cards = self._detect_board_cards(frame, table_frame, preset, table_origin, content_scale, region_scale)
        if state.hero_cards or state.board_cards:
            best_board_by_label = {card.class_name: card for card in state.board_cards}
            best_hero_by_label = {card.class_name: card for card in state.hero_cards}
            duplicate_labels = set(best_board_by_label).intersection(best_hero_by_label)
            for label in duplicate_labels:
                board_card = best_board_by_label[label]
                hero_card = best_hero_by_label[label]
                if board_card.confidence >= hero_card.confidence:
                    state.hero_cards = [card for card in state.hero_cards if card.class_name != label]
                else:
                    state.board_cards = [card for card in state.board_cards if card.class_name != label]
            state.hero_cards = _dedupe_card_detections(state.hero_cards, detection_sort_key)
            state.board_cards = _dedupe_card_detections(state.board_cards, board_sort_key)
            if len(state.hero_cards) == 0:
                state.hero_cards = []
        state.stacks = self._build_static_area_detections(
            full_frame=frame,
            preset=preset,
            top_left=table_origin,
            area_name="player_funds_area",
            class_name="stack_area",
            region_scale=region_scale,
        )
        state.player_names = self._build_static_area_detections(
            full_frame=frame,
            preset=preset,
            top_left=table_origin,
            area_name="player_name_area",
            class_name="player_name_area",
            region_scale=region_scale,
        )

        total_pot_area = preset.table_data.get("total_pot_area")
        if _is_area(total_pot_area):
            x1, y1, x2, y2 = _scale_bbox(_normalize_area(total_pot_area), region_scale)
            state.pots = [
                DetectionResult(
                    class_name="pot_area",
                    confidence=1.0,
                    bbox=(origin_x + x1, origin_y + y1, origin_x + x2, origin_y + y2),
                )
            ]

        state.metadata["static_stack_area_count"] = len(state.stacks)
        state.metadata["static_name_area_count"] = len(state.player_names)
        return state

    @staticmethod
    def _load_presets(preset_manifests: List[Path]) -> List[TemplatePreset]:
        manifests = preset_manifests or [
            _repo_root() / relative_path for relative_path in BUILTIN_PRESET_MANIFESTS
        ]
        presets: List[TemplatePreset] = []

        for manifest_path in manifests:
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                asset_root = manifest_path.parent
                assets = manifest.get("assets", {})
                table_data = manifest.get("table_data", {})
                anchor_templates = {}
                for asset_name, relative_path in assets.items():
                    if asset_name.startswith("topleft_corner"):
                        anchor_templates[asset_name] = _load_cv2_image(asset_root / relative_path)

                if not anchor_templates:
                    continue

                card_templates = {}
                for asset_name, relative_path in assets.items():
                    if decode_card_token(asset_name):
                        card_templates[asset_name.lower()] = _load_cv2_image(asset_root / relative_path)

                action_templates = {}
                for asset_name in ACTION_BUTTON_LABELS:
                    relative_path = assets.get(asset_name)
                    if relative_path:
                        action_templates[asset_name] = _load_cv2_image(asset_root / relative_path)

                dealer_template = None
                if assets.get("dealer_button"):
                    dealer_template = _load_cv2_image(asset_root / assets["dealer_button"])

                default_anchor_offset_data = table_data.get("anchor_offset", {})
                default_anchor_offset = (
                    int(default_anchor_offset_data.get("x", 0)),
                    int(default_anchor_offset_data.get("y", 0)),
                )
                anchor_offsets = {
                    anchor_name: default_anchor_offset for anchor_name in anchor_templates
                }
                anchor_offsets_data = table_data.get("anchor_offsets", {})
                if isinstance(anchor_offsets_data, dict):
                    for anchor_name, offset_data in anchor_offsets_data.items():
                        if not isinstance(offset_data, dict):
                            continue
                        anchor_offsets[anchor_name] = (
                            int(offset_data.get("x", default_anchor_offset[0])),
                            int(offset_data.get("y", default_anchor_offset[1])),
                        )
                anchor_match_bounds = {}
                anchor_match_bounds_data = table_data.get("anchor_match_bounds", {})
                if isinstance(anchor_match_bounds_data, dict):
                    for anchor_name, bounds_data in anchor_match_bounds_data.items():
                        if not isinstance(bounds_data, dict):
                            continue
                        anchor_match_bounds[anchor_name] = (
                            int(bounds_data.get("max_x", 0)),
                            int(bounds_data.get("max_y", 0)),
                        )
                table_width, table_height = _estimate_table_bounds(table_data)
                presets.append(
                    TemplatePreset(
                        name=str(manifest.get("display_name") or manifest_path.parent.parent.name),
                        manifest_path=manifest_path,
                        table_data=table_data,
                        anchor_templates=anchor_templates,
                        anchor_offsets=anchor_offsets,
                        anchor_match_bounds=anchor_match_bounds,
                        action_templates=action_templates,
                        card_templates=card_templates,
                        dealer_template=dealer_template,
                        table_width=table_width,
                        table_height=table_height,
                    )
                )
            except Exception as exc:  # pragma: no cover - depends on local asset integrity
                logger.warning("Impossible de charger le preset %s: %s", manifest_path, exc)

        return presets

    @staticmethod
    def _find_template_sqdiff_in_region(
        frame: np.ndarray,
        template: np.ndarray,
        region: Tuple[int, int, int, int],
    ) -> Optional[Tuple[float, Tuple[int, int]]]:
        search_crop = _crop_frame(frame, region)
        if search_crop is None:
            return None
        if search_crop.shape[0] < template.shape[0] or search_crop.shape[1] < template.shape[1]:
            return None
        error, location = _find_template_sqdiff(search_crop, template)
        return error, (region[0] + location[0], region[1] + location[1])

    @staticmethod
    def _clip_region_to_frame(
        region: Tuple[int, int, int, int],
        frame_shape: Tuple[int, int],
    ) -> Optional[Tuple[int, int, int, int]]:
        frame_height, frame_width = frame_shape[:2]
        x1, y1, x2, y2 = region
        clipped = (
            max(0, min(int(x1), frame_width)),
            max(0, min(int(y1), frame_height)),
            max(0, min(int(x2), frame_width)),
            max(0, min(int(y2), frame_height)),
        )
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            return None
        return clipped

    def _build_fast_anchor_regions(
        self,
        frame: np.ndarray,
        preset: TemplatePreset,
        anchor_name: str,
        template_shape: Tuple[int, int],
        expected_location: Optional[Tuple[int, int]] = None,
    ) -> List[Tuple[int, int, int, int]]:
        frame_height, frame_width = frame.shape[:2]
        template_height, template_width = template_shape[:2]
        regions: List[Tuple[int, int, int, int]] = []

        if expected_location is not None:
            margin_x = max(56, int(template_width * 2.5))
            margin_y = max(56, int(template_height * 2.5))
            clipped = self._clip_region_to_frame(
                (
                    expected_location[0] - margin_x,
                    expected_location[1] - margin_y,
                    expected_location[0] + template_width + margin_x,
                    expected_location[1] + template_height + margin_y,
                ),
                frame.shape[:2],
            )
            if clipped is not None:
                regions.append(clipped)

        bounds = preset.anchor_match_bounds.get(anchor_name)
        if bounds is not None:
            max_x, max_y = bounds
            clipped = self._clip_region_to_frame(
                (
                    0,
                    0,
                    max_x + template_width + 48,
                    max_y + template_height + 48,
                ),
                frame.shape[:2],
            )
            if clipped is not None:
                regions.append(clipped)
        elif anchor_name.startswith("topleft_corner"):
            heuristic_width = min(
                frame_width,
                max(180, int(frame_width * 0.22), int(template_width * 5)),
            )
            heuristic_height = min(
                frame_height,
                max(180, int(frame_height * 0.22), int(template_height * 5)),
            )
            clipped = self._clip_region_to_frame(
                (0, 0, heuristic_width, heuristic_height),
                frame.shape[:2],
            )
            if clipped is not None:
                regions.append(clipped)

        deduped: List[Tuple[int, int, int, int]] = []
        seen = set()
        for region in regions:
            if region not in seen:
                deduped.append(region)
                seen.add(region)
        return deduped

    @staticmethod
    def _ordered_candidate_scales(
        frame: np.ndarray,
        preset: TemplatePreset,
        prior_scale: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> List[float]:
        candidates = TemplateFallbackDetector._candidate_scales(frame, preset)
        width_ratio = frame.shape[1] / max(float(preset.table_width), 1.0)
        height_ratio = frame.shape[0] / max(float(preset.table_height), 1.0)
        priors = [width_ratio, height_ratio, (width_ratio + height_ratio) / 2.0]
        if prior_scale is not None and 0.5 <= float(prior_scale) <= 1.9:
            priors.insert(0, float(prior_scale))

        def sort_key(scale: float) -> Tuple[float, float]:
            distance = min(abs(float(scale) - prior) for prior in priors)
            return (distance, abs(float(scale) - 1.0))

        ordered = sorted(candidates, key=sort_key)
        if limit is not None:
            return ordered[:limit]
        return ordered

    def _remember_match(
        self,
        match: Tuple[TemplatePreset, Tuple[int, int], float, str, float],
    ) -> Tuple[TemplatePreset, Tuple[int, int], float, str, float]:
        preset, location, error, anchor_name, scale = match
        self._last_match = {
            "preset_name": preset.name,
            "anchor_name": anchor_name,
            "location": (int(location[0]), int(location[1])),
            "scale": float(scale),
            "frame_shape": tuple(int(value) for value in preset.anchor_templates[anchor_name].shape[:2]),
            "error": float(error),
        }
        return match

    def _locate_cached_preset(
        self,
        frame: np.ndarray,
        threshold: float,
    ) -> Optional[Tuple[TemplatePreset, Tuple[int, int], float, str, float]]:
        cached = dict(self._last_match or {})
        if not cached:
            return None

        preset_name = str(cached.get("preset_name", "") or "")
        anchor_name = str(cached.get("anchor_name", "") or "")
        expected_location = cached.get("location")
        prior_scale = cached.get("scale")
        if not preset_name or not anchor_name or expected_location is None:
            return None

        preset = next((item for item in self.presets if item.name == preset_name), None)
        if preset is None:
            return None

        anchor_template = preset.anchor_templates.get(anchor_name)
        if anchor_template is None:
            return None

        best_match: Optional[Tuple[TemplatePreset, Tuple[int, int], float, str, float]] = None
        for scale in self._ordered_candidate_scales(frame, preset, prior_scale=prior_scale, limit=5):
            scaled_template = _resize_template(anchor_template, scale)
            if (
                scaled_template.shape[1] >= frame.shape[1]
                or scaled_template.shape[0] >= frame.shape[0]
            ):
                continue
            for region in self._build_fast_anchor_regions(
                frame,
                preset,
                anchor_name,
                scaled_template.shape[:2],
                expected_location=expected_location,
            ):
                candidate = self._find_template_sqdiff_in_region(frame, scaled_template, region)
                if candidate is None:
                    continue
                error, location = candidate
                if best_match is None or error < best_match[2]:
                    best_match = (preset, location, error, anchor_name, scale)

        if best_match is None or best_match[2] > threshold:
            return None
        return self._remember_match(best_match)

    def _locate_locked_preset(
        self,
        frame: np.ndarray,
        threshold: float,
    ) -> Optional[Tuple[TemplatePreset, Tuple[int, int], float, str, float]]:
        cached = dict(self._last_match or {})
        if not cached:
            return None

        preset_name = str(cached.get("preset_name", "") or "")
        anchor_name = str(cached.get("anchor_name", "") or "")
        location = cached.get("location")
        prior_scale = float(cached.get("scale", 1.0) or 1.0)
        if not preset_name or not anchor_name or location is None:
            return None

        preset = next((item for item in self.presets if item.name == preset_name), None)
        if preset is None:
            return None

        anchor_template = preset.anchor_templates.get(anchor_name)
        if anchor_template is None:
            return None

        scaled_template = _resize_template(anchor_template, prior_scale)
        h, w = scaled_template.shape[:2]
        x, y = int(location[0]), int(location[1])
        if w <= 0 or h <= 0:
            return None

        margin_x = max(18, int(round(w * 0.35)))
        margin_y = max(18, int(round(h * 0.35)))
        search_region = self._clip_region_to_frame(
            (
                x - margin_x,
                y - margin_y,
                x + w + margin_x,
                y + h + margin_y,
            ),
            frame.shape[:2],
        )
        if search_region is None:
            return None

        candidate = self._find_template_sqdiff_in_region(frame, scaled_template, search_region)
        if candidate is None:
            return None
        error, location = candidate

        relaxed_threshold = min(max(float(threshold), 0.24), 0.32)
        if error > relaxed_threshold:
            return None

        locked_match = (preset, location, float(error), anchor_name, prior_scale)
        return self._remember_match(locked_match)

    def _locate_best_preset(
        self,
        frame: np.ndarray,
        threshold: float = 0.2,
    ) -> Optional[Tuple[TemplatePreset, Tuple[int, int], float, str, float]]:
        locked_match = self._locate_locked_preset(frame, threshold=threshold)
        if locked_match is not None:
            return locked_match

        cached_match = self._locate_cached_preset(frame, threshold=threshold)
        if cached_match is not None:
            return cached_match

        fast_match: Optional[Tuple[TemplatePreset, Tuple[int, int], float, str, float]] = None
        for preset in self.presets:
            prior_scale = None
            if self._last_match and self._last_match.get("preset_name") == preset.name:
                prior_scale = self._last_match.get("scale")
            scale_candidates = self._ordered_candidate_scales(frame, preset, prior_scale=prior_scale, limit=6)
            for anchor_name, anchor_template in preset.anchor_templates.items():
                expected_location = None
                if (
                    self._last_match
                    and self._last_match.get("preset_name") == preset.name
                    and self._last_match.get("anchor_name") == anchor_name
                ):
                    expected_location = self._last_match.get("location")
                for scale in scale_candidates:
                    scaled_template = _resize_template(anchor_template, scale)
                    if (
                        scaled_template.shape[1] >= frame.shape[1]
                        or scaled_template.shape[0] >= frame.shape[0]
                    ):
                        continue
                    for region in self._build_fast_anchor_regions(
                        frame,
                        preset,
                        anchor_name,
                        scaled_template.shape[:2],
                        expected_location=expected_location,
                    ):
                        candidate = self._find_template_sqdiff_in_region(frame, scaled_template, region)
                        if candidate is None:
                            continue
                        error, location = candidate
                        if fast_match is None or error < fast_match[2]:
                            fast_match = (preset, location, error, anchor_name, scale)

        if fast_match is not None and fast_match[2] <= threshold:
            return self._remember_match(fast_match)

        best_match: Optional[Tuple[TemplatePreset, Tuple[int, int], float, str, float]] = None

        for preset in self.presets:
            prior_scale = None
            if self._last_match and self._last_match.get("preset_name") == preset.name:
                prior_scale = self._last_match.get("scale")
            scale_candidates = self._ordered_candidate_scales(frame, preset, prior_scale=prior_scale)
            for anchor_name, anchor_template in preset.anchor_templates.items():
                for scale in scale_candidates:
                    scaled_template = _resize_template(anchor_template, scale)
                    if (
                        scaled_template.shape[1] >= frame.shape[1]
                        or scaled_template.shape[0] >= frame.shape[0]
                    ):
                        continue
                    error, location = _find_template_sqdiff(frame, scaled_template)
                    if anchor_name in preset.anchor_match_bounds:
                        max_x, max_y = preset.anchor_match_bounds[anchor_name]
                        # Compact anchors were originally calibrated on pre-cropped table captures,
                        # but the live runtime searches inside window and multi-screen frames.
                        strong_global_match = (
                            error <= 0.02
                            and (
                                frame.shape[1] > preset.table_width + 80
                                or frame.shape[0] > preset.table_height + 80
                            )
                        )
                        if (location[0] > max_x or location[1] > max_y) and not strong_global_match:
                            continue
                    if best_match is None or error < best_match[2]:
                        best_match = (preset, location, error, anchor_name, scale)

        if best_match is None or best_match[2] > threshold:
            self._last_match = None
            return None
        return self._remember_match(best_match)

    @staticmethod
    def _sorted_area_items(area_map: Dict[str, Any]) -> List[Tuple[str, Any]]:
        def area_sort_key(item: Tuple[str, Any]) -> tuple[int, str]:
            key = str(item[0])
            return (0, f"{int(key):04d}") if key.isdigit() else (1, key)

        return sorted(area_map.items(), key=area_sort_key)

    @staticmethod
    def _candidate_scales(frame: np.ndarray, preset: TemplatePreset) -> List[float]:
        candidates = set(float(scale) for scale in FALLBACK_SCALE_FACTORS)
        width_ratio = frame.shape[1] / max(float(preset.table_width), 1.0)
        height_ratio = frame.shape[0] / max(float(preset.table_height), 1.0)

        # When we analyze a direct window capture, the frame dimensions are a useful prior
        # for the table scale. Search around that prior with a finer local neighborhood.
        priors = [width_ratio, height_ratio, (width_ratio + height_ratio) / 2.0]
        for prior in priors:
            if 0.55 <= prior <= 1.75:
                for delta in (-0.12, -0.08, -0.05, -0.03, 0.0, 0.03, 0.05, 0.08, 0.12):
                    candidate = round(prior + delta, 3)
                    if 0.55 <= candidate <= 1.8:
                        candidates.add(candidate)

        return sorted(candidates)

    def _detect_action_buttons(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
    ) -> List[DetectionResult]:
        buttons_area = preset.table_data.get("buttons_search_area")
        if not _is_area(buttons_area):
            return []

        area_bbox = _scale_bbox(_normalize_area(buttons_area), region_scale)
        search_crop = _crop_frame(table_frame, area_bbox)
        if search_crop is None:
            return []

        origin_x, origin_y = top_left
        detections: List[DetectionResult] = []
        for label, template in preset.action_templates.items():
            scaled_template = _resize_template(template, template_scale)
            if (
                scaled_template.shape[1] >= search_crop.shape[1]
                or scaled_template.shape[0] >= search_crop.shape[0]
            ):
                continue
            error, location = _find_template_sqdiff(search_crop, scaled_template)
            if error > (0.18 if abs(template_scale - 1.0) > 0.05 else 0.14):
                continue
            local_x, local_y = location
            x1 = origin_x + area_bbox[0] + local_x
            y1 = origin_y + area_bbox[1] + local_y
            x2 = x1 + scaled_template.shape[1]
            y2 = y1 + scaled_template.shape[0]
            detections.append(
                DetectionResult(
                    class_name=label,
                    confidence=max(0.0, 1.0 - error),
                    bbox=_clip_bbox((x1, y1, x2, y2), full_frame.shape[:2]),
                )
            )

        detections = dedupe_nearby_detections(
            detections,
            x_tolerance=max(24.0, 24.0 * template_scale),
            y_tolerance=max(24.0, 24.0 * template_scale),
        )

        if len(detections) < 2:
            generic_buttons = self._detect_generic_action_buttons(
                full_frame=full_frame,
                table_frame=table_frame,
                top_left=top_left,
                scaled_search_area=area_bbox,
                template_scale=template_scale,
                existing=detections,
            )
            if generic_buttons:
                detections.extend(generic_buttons)
                detections = dedupe_nearby_detections(
                    detections,
                    x_tolerance=max(24.0, 24.0 * template_scale),
                    y_tolerance=max(24.0, 24.0 * template_scale),
                )

        if len(detections) < 2:
            slot_buttons = self._detect_slot_action_buttons(
                full_frame=full_frame,
                table_frame=table_frame,
                top_left=top_left,
                scaled_search_area=area_bbox,
                template_scale=template_scale,
                existing=detections,
            )
            if slot_buttons:
                detections.extend(slot_buttons)
                detections = dedupe_nearby_detections(
                    detections,
                    x_tolerance=max(24.0, 24.0 * template_scale),
                    y_tolerance=max(24.0, 24.0 * template_scale),
                )

        if len(detections) < 2:
            preset_slot_buttons = self._detect_preset_slot_action_buttons(
                full_frame=full_frame,
                table_frame=table_frame,
                preset=preset,
                top_left=top_left,
                template_scale=template_scale,
                region_scale=region_scale,
                existing=detections,
            )
            if preset_slot_buttons:
                detections.extend(preset_slot_buttons)
                detections = dedupe_nearby_detections(
                    detections,
                    x_tolerance=max(24.0, 24.0 * template_scale),
                    y_tolerance=max(24.0, 24.0 * template_scale),
                )

        detections = self._normalize_preset_slot_action_buttons(
            full_frame=full_frame,
            table_frame=table_frame,
            preset=preset,
            top_left=top_left,
            template_scale=template_scale,
            region_scale=region_scale,
            detections=detections,
        )

        if len(detections) < 2:
            heuristic_area = self._heuristic_action_area(table_frame.shape[:2])
            heuristic_buttons = self._detect_generic_action_buttons(
                full_frame=full_frame,
                table_frame=table_frame,
                top_left=top_left,
                scaled_search_area=heuristic_area,
                template_scale=template_scale,
                existing=detections,
            )
            if len(heuristic_buttons) < 2:
                heuristic_buttons.extend(
                    self._detect_slot_action_buttons(
                        full_frame=full_frame,
                        table_frame=table_frame,
                        top_left=top_left,
                        scaled_search_area=heuristic_area,
                        template_scale=template_scale,
                        existing=detections + heuristic_buttons,
                    )
                )
            if heuristic_buttons:
                detections.extend(heuristic_buttons)
                detections = dedupe_nearby_detections(
                    detections,
                    x_tolerance=max(24.0, 24.0 * template_scale),
                    y_tolerance=max(24.0, 24.0 * template_scale),
                )

        detections.sort(key=detection_sort_key)
        return detections

    @staticmethod
    def _bbox_slot_overlap_ratio(
        bbox: Tuple[int, int, int, int],
        slot_bbox: Tuple[int, int, int, int],
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

    def _normalize_preset_slot_action_buttons(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
        detections: List[DetectionResult],
    ) -> List[DetectionResult]:
        slot_boxes = self._collect_preset_slot_boxes(
            preset=preset,
            region_scale=region_scale,
            top_left=top_left,
            frame_shape=full_frame.shape[:2],
        )
        if not slot_boxes:
            return detections

        slot_visibility: Dict[str, bool] = {}
        for slot_key, slot_bbox in slot_boxes.items():
            slot_crop = _crop_frame(full_frame, slot_bbox)
            slot_visibility[slot_key] = self._has_generic_button_signal(slot_crop)

        visible_slots = {
            slot_key
            for slot_key, visible in slot_visibility.items()
            if visible
        }
        if not visible_slots:
            return detections

        normalized: List[DetectionResult] = []
        duplicate_margin = max(18, int(round(18 * template_scale)))

        slot_priorities = {
            "FOLD": ("fold_button", "fast_fold_button", "action_button_generic"),
            "CALL": ("check_button", "call_button", "all_in_call_button", "action_button_generic"),
            "BET_BTN": ("bet_button", "raise_button", "action_button_generic"),
        }

        for slot_key in ("FOLD", "CALL", "BET_BTN"):
            slot_bbox = slot_boxes.get(slot_key)
            if slot_bbox is None:
                continue

            slot_candidates = [
                detection
                for detection in detections
                if self._bbox_slot_overlap_ratio(detection.bbox, slot_bbox) >= 0.2
            ]
            slot_visible = slot_key in visible_slots or bool(slot_candidates)
            if not slot_visible:
                continue

            best_detection: Optional[DetectionResult] = None
            priorities = slot_priorities.get(slot_key, ())
            for label in priorities:
                labeled_candidates = [candidate for candidate in slot_candidates if candidate.class_name == label]
                if labeled_candidates:
                    best_detection = max(labeled_candidates, key=lambda candidate: candidate.confidence)
                    break

            if best_detection is None and slot_candidates:
                best_detection = max(slot_candidates, key=lambda candidate: candidate.confidence)

            class_name: str
            confidence: float
            bbox: Tuple[int, int, int, int]
            if best_detection is not None:
                class_name = best_detection.class_name
                confidence = best_detection.confidence
                bbox = best_detection.bbox
            else:
                class_name = "action_button_generic"
                confidence = 0.4
                bbox = slot_bbox

            if slot_key == "FOLD":
                class_name = "fold_button"
            elif slot_key == "CALL":
                if class_name == "all_in_call_button":
                    pass
                elif "FOLD" not in visible_slots and "BET_BTN" in visible_slots:
                    class_name = "check_button"
                elif class_name not in {"check_button", "call_button"}:
                    class_name = "call_button"
            elif slot_key == "BET_BTN":
                if class_name not in {"bet_button", "raise_button"}:
                    class_name = "bet_button"

            candidate = DetectionResult(
                class_name=class_name,
                confidence=confidence,
                bbox=bbox,
            )
            duplicate = False
            for existing in normalized:
                if (
                    abs(candidate.bbox[0] - existing.bbox[0]) <= duplicate_margin
                    and abs(candidate.bbox[1] - existing.bbox[1]) <= duplicate_margin
                    and abs(candidate.bbox[2] - existing.bbox[2]) <= duplicate_margin
                    and abs(candidate.bbox[3] - existing.bbox[3]) <= duplicate_margin
                ):
                    duplicate = True
                    if candidate.confidence > existing.confidence:
                        normalized.remove(existing)
                        normalized.append(candidate)
                    break
            if not duplicate:
                normalized.append(candidate)

        if normalized:
            return normalized
        return detections

    @staticmethod
    def _has_generic_button_signal(crop: Optional[np.ndarray]) -> bool:
        if crop is None or crop.size == 0:
            return False

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        bright_ratio = float((gray > 135).mean())
        dark_ratio = float((gray < 105).mean())
        red_ratio = float(
            (
                (((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 168)))
                & (hsv[:, :, 1] > 70)
                & (hsv[:, :, 2] > 75)
            ).mean()
        )
        edge_ratio = float((cv2.Canny(gray, 40, 120) > 0).mean())
        contrast = float(gray.std())

        if red_ratio >= 0.035 and bright_ratio >= 0.01:
            return True
        if bright_ratio >= 0.018 and dark_ratio >= 0.18 and contrast >= 18.0 and edge_ratio >= 0.018:
            return True
        return False

    @staticmethod
    def _find_card_candidate_boxes(
        search_crop: Optional[np.ndarray],
        limit: int,
    ) -> List[Tuple[int, int, int, int]]:
        if search_crop is None or search_crop.size == 0:
            return []

        gray = cv2.cvtColor(search_crop, cv2.COLOR_BGR2GRAY)
        white_mask = (gray > 140).astype(np.uint8) * 255
        component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(white_mask, 8)
        if component_count <= 1:
            return []

        candidates: List[Tuple[int, int, int, int, int]] = []
        for index in range(1, component_count):
            x, y, w, h, area = [int(value) for value in stats[index]]
            segments = [(x, y, w, h, area)]
            aspect = float(w) / max(float(h), 1.0)
            if w >= 110:
                region_mask = white_mask[y : y + h, x : x + w]
                split_index: Optional[int] = None
                if region_mask.size > 0:
                    column_strength = (region_mask > 0).sum(axis=0).astype(np.float32)
                    if column_strength.size >= 12:
                        smoothed = cv2.GaussianBlur(column_strength.reshape(1, -1), (1, 9), 0).reshape(-1)
                        search_start = int(round(w * 0.22))
                        search_end = int(round(w * 0.78))
                        if search_end > search_start:
                            valley_offset = int(np.argmin(smoothed[search_start:search_end]))
                            valley_index = search_start + valley_offset
                            max_strength = float(smoothed.max()) if smoothed.size else 0.0
                            valley_strength = float(smoothed[valley_index]) if smoothed.size else max_strength
                            if max_strength > 0.0 and valley_strength <= (max_strength * 0.45):
                                split_index = valley_index

                if split_index is not None:
                    left_width = max(24, split_index)
                    right_width = max(24, w - split_index)
                    segments = [
                        (x, y, left_width, h, left_width * h),
                        (x + split_index, y, right_width, h, right_width * h),
                    ]
                elif aspect > 2.1:
                    left_width = max(24, int(round(w / 2.0)))
                    right_width = max(24, w - left_width)
                    segments = [
                        (x, y, left_width, h, left_width * h),
                        (x + w - right_width, y, right_width, h, right_width * h),
                    ]

            for seg_x, seg_y, seg_w, seg_h, seg_area in segments:
                if seg_area < 320 or seg_w < 18 or seg_h < 24:
                    continue

                seg_aspect = float(seg_w) / max(float(seg_h), 1.0)
                if seg_aspect < 0.32 or seg_aspect > 1.65:
                    continue

                crop = search_crop[seg_y : seg_y + seg_h, seg_x : seg_x + seg_w]
                if crop.size == 0:
                    continue

                crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                bright_ratio = float((crop_gray > 160).mean())
                if bright_ratio < 0.28:
                    continue

                candidates.append((seg_area, seg_x, seg_y, seg_w, seg_h))

        if not candidates:
            return []

        candidates.sort(key=lambda item: (-item[0], item[2], item[1]))
        boxes: List[Tuple[int, int, int, int]] = []
        for _, x, y, w, h in candidates:
            duplicate = False
            for existing in boxes:
                ex, ey, ew, eh = existing
                if (
                    abs(x - ex) <= max(10, ew // 3)
                    and abs(y - ey) <= max(10, eh // 3)
                    and abs((x + w) - (ex + ew)) <= max(12, ew // 3)
                    and abs((y + h) - (ey + eh)) <= max(12, eh // 3)
                ):
                    duplicate = True
                    break
            if not duplicate:
                boxes.append((x, y, w, h))

        boxes.sort(key=lambda item: (item[1], item[0]))
        return boxes[: max(limit * 2, limit)]

    @staticmethod
    def _normalize_card_candidate_bbox(
        bbox: Tuple[int, int, int, int],
        crop_shape: Tuple[int, int],
        template_scale: float,
    ) -> Tuple[int, int, int, int]:
        x, y, w, h = bbox
        crop_height, crop_width = crop_shape[:2]
        aspect_ratio = 0.72
        target_w = max(w, int(round(h * aspect_ratio)), int(round(36 * template_scale)))
        target_h = max(h, int(round(w / aspect_ratio)), int(round(54 * template_scale)))

        center_x = x + (w / 2.0)
        center_y = y + (h / 2.0)
        if h < target_h * 0.72:
            center_y += (target_h - h) * 0.24

        x1 = int(round(center_x - (target_w / 2.0) - 4))
        y1 = int(round(center_y - (target_h / 2.0) - 4))
        x2 = int(round(center_x + (target_w / 2.0) + 4))
        y2 = int(round(center_y + (target_h / 2.0) + 4))
        return _clip_bbox((x1, y1, x2, y2), (crop_height, crop_width))

    def _classify_card_crop(
        self,
        crop: Optional[np.ndarray],
        preset: TemplatePreset,
        template_scale: float,
        corner_weight: float,
    ) -> Optional[Tuple[str, float, Tuple[int, int, int, int]]]:
        if crop is None or crop.size == 0 or not _has_visible_card_signal(crop):
            return None

        crop_corner = _extract_card_corner(crop)
        best_label: Optional[str] = None
        best_location = (0, 0)
        best_error: Optional[float] = None
        best_raw_error: Optional[float] = None
        best_template_shape = (0, 0)

        for label, template in preset.card_templates.items():
            for scale_candidate in _card_template_scale_candidates(template_scale):
                scaled_template = _resize_template(template, scale_candidate)
                if (
                    scaled_template.shape[1] >= crop.shape[1]
                    or scaled_template.shape[0] >= crop.shape[0]
                ):
                    continue

                raw_error, location = _find_template_sqdiff(crop, scaled_template)
                adjusted_error = _location_adjusted_error(
                    raw_error,
                    location,
                    crop.shape[:2],
                    scaled_template.shape[:2],
                )
                combined_error = adjusted_error
                template_corner = _extract_card_corner(scaled_template)
                if (
                    corner_weight > 0.0
                    and crop_corner is not None
                    and template_corner is not None
                    and template_corner.size > 0
                ):
                    interpolation = cv2.INTER_AREA if crop_corner.shape[0] >= template_corner.shape[0] else cv2.INTER_CUBIC
                    resized_corner = cv2.resize(
                        crop_corner,
                        (template_corner.shape[1], template_corner.shape[0]),
                        interpolation=interpolation,
                    )
                    corner_error = float(
                        np.mean(
                            (
                                resized_corner.astype(np.float32)
                                - template_corner.astype(np.float32)
                            )
                            ** 2
                        )
                    ) / (255.0 ** 2)
                    combined_error = (adjusted_error * (1.0 - corner_weight)) + (corner_error * corner_weight)

                if best_error is None or combined_error < best_error:
                    best_error = combined_error
                    best_raw_error = raw_error
                    best_label = label
                    best_location = location
                    best_template_shape = (
                        int(scaled_template.shape[1]),
                        int(scaled_template.shape[0]),
                    )

        if best_label is None or best_error is None:
            return None

        threshold = 0.24 if abs(template_scale - 1.0) > 0.05 else 0.19
        if best_error > threshold:
            return None

        local_x, local_y = best_location
        width, height = best_template_shape
        return (
            best_label,
            max(0.0, 1.0 - float(best_raw_error if best_raw_error is not None else best_error)),
            (local_x, local_y, local_x + width, local_y + height),
        )

    def _detect_cards_from_search_area(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        area_bbox: Tuple[int, int, int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
        limit: int,
        sort_key,
        pad_ratio_x: float,
        pad_ratio_y: float,
        corner_weight: float,
    ) -> List[DetectionResult]:
        scaled_area_bbox = _scale_bbox(area_bbox, region_scale)
        area_width = max(1, scaled_area_bbox[2] - scaled_area_bbox[0])
        area_height = max(1, scaled_area_bbox[3] - scaled_area_bbox[1])
        pad_x = max(12, int(round(area_width * pad_ratio_x)))
        pad_y = max(12, int(round(area_height * pad_ratio_y)))
        scaled_area_bbox = _expand_bbox(scaled_area_bbox, pad_x, pad_y)
        search_crop = _crop_frame(table_frame, scaled_area_bbox)
        if search_crop is None:
            return []

        origin_x, origin_y = top_left
        detections: List[DetectionResult] = []
        candidate_boxes = self._find_card_candidate_boxes(search_crop, limit=limit)
        for candidate_bbox in candidate_boxes:
            normalized_bbox = self._normalize_card_candidate_bbox(
                candidate_bbox,
                search_crop.shape[:2],
                template_scale,
            )
            candidate_crop = _crop_frame(search_crop, normalized_bbox)
            classified = self._classify_card_crop(candidate_crop, preset, template_scale, corner_weight=corner_weight)
            if classified is None:
                continue

            label, confidence, local_match_bbox = classified
            nx1, ny1, _, _ = normalized_bbox
            mx1, my1, mx2, my2 = local_match_bbox
            detections.append(
                DetectionResult(
                    class_name=label,
                    confidence=confidence,
                    bbox=_clip_bbox(
                        (
                            origin_x + scaled_area_bbox[0] + nx1 + mx1,
                            origin_y + scaled_area_bbox[1] + ny1 + my1,
                            origin_x + scaled_area_bbox[0] + nx1 + mx2,
                            origin_y + scaled_area_bbox[1] + ny1 + my2,
                        ),
                        full_frame.shape[:2],
                    ),
                )
            )

        detections = _dedupe_card_detections(dedupe_nearby_detections(detections, 18.0, 18.0), sort_key)
        return detections[:limit]

    def _detect_generic_action_buttons(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        top_left: Tuple[int, int],
        scaled_search_area: Tuple[int, int, int, int],
        template_scale: float,
        existing: List[DetectionResult],
    ) -> List[DetectionResult]:
        search_crop = _crop_frame(table_frame, scaled_search_area)
        if search_crop is None or search_crop.size == 0:
            return []

        hsv = cv2.cvtColor(search_crop, cv2.COLOR_BGR2HSV)
        lower_red_1 = np.array([0, 70, 80], dtype=np.uint8)
        upper_red_1 = np.array([12, 255, 255], dtype=np.uint8)
        lower_red_2 = np.array([168, 70, 80], dtype=np.uint8)
        upper_red_2 = np.array([180, 255, 255], dtype=np.uint8)
        red_mask = cv2.inRange(hsv, lower_red_1, upper_red_1) | cv2.inRange(hsv, lower_red_2, upper_red_2)
        kernel = np.ones((5, 5), dtype=np.uint8)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []

        origin_x, origin_y = top_left
        min_height = max(36, int(round(52 * template_scale)))
        min_width = max(72, int(round(110 * template_scale)))
        min_area = max(5000, int(round(7000 * template_scale * template_scale)))
        max_area = int(round(search_crop.shape[0] * search_crop.shape[1] * 0.45))

        generic_detections: List[DetectionResult] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = int(w * h)
            if h < min_height or w < min_width or area < min_area or area > max_area:
                continue
            if w < (h * 1.2):
                continue

            contour_mask = np.zeros_like(red_mask)
            cv2.drawContours(contour_mask, [contour], -1, 255, thickness=-1)
            crop_mask = contour_mask[y : y + h, x : x + w]
            red_ratio = float((crop_mask > 0).mean()) if crop_mask.size else 0.0
            if red_ratio < 0.45:
                continue

            bbox = _clip_bbox(
                (
                    origin_x + scaled_search_area[0] + x,
                    origin_y + scaled_search_area[1] + y,
                    origin_x + scaled_search_area[0] + x + w,
                    origin_y + scaled_search_area[1] + y + h,
                ),
                full_frame.shape[:2],
            )

            duplicate = False
            for existing_detection in existing:
                ex1, ey1, ex2, ey2 = existing_detection.bbox
                if (
                    abs(bbox[0] - ex1) <= max(18, int(18 * template_scale))
                    and abs(bbox[1] - ey1) <= max(18, int(18 * template_scale))
                    and abs(bbox[2] - ex2) <= max(18, int(18 * template_scale))
                    and abs(bbox[3] - ey2) <= max(18, int(18 * template_scale))
                ):
                    duplicate = True
                    break
            if duplicate:
                continue

            generic_detections.append(
                DetectionResult(
                    class_name="action_button_generic",
                    confidence=round(min(0.99, 0.45 + red_ratio), 3),
                    bbox=bbox,
                )
            )

        generic_detections.sort(key=lambda det: (det.center[1], det.center[0]))
        return generic_detections[:3]

    def _detect_slot_action_buttons(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        top_left: Tuple[int, int],
        scaled_search_area: Tuple[int, int, int, int],
        template_scale: float,
        existing: List[DetectionResult],
    ) -> List[DetectionResult]:
        search_crop = _crop_frame(table_frame, scaled_search_area)
        if search_crop is None or search_crop.size == 0:
            return []

        crop_height, crop_width = search_crop.shape[:2]
        vertical_bounds = [
            (
                max(0, int(round(crop_height * 0.12))),
                min(crop_height, int(round(crop_height * 0.92))),
            ),
            (
                max(0, int(round(crop_height * 0.18))),
                min(crop_height, int(round(crop_height * 0.88))),
            ),
        ]
        horizontal_layouts = (
            ((0.00, 0.31), (0.345, 0.655), (0.69, 1.00)),
            ((0.18, 0.56), (0.60, 0.98)),
        )

        origin_x, origin_y = top_left
        slot_detections: List[DetectionResult] = []
        duplicate_margin = max(18, int(round(18 * template_scale)))

        for y1, y2 in vertical_bounds:
            for layout in horizontal_layouts:
                for start_ratio, end_ratio in layout:
                    x1 = max(0, min(crop_width, int(round(crop_width * start_ratio))))
                    x2 = max(0, min(crop_width, int(round(crop_width * end_ratio))))
                    if x2 <= x1 or y2 <= y1:
                        continue
                    slot_crop = search_crop[y1:y2, x1:x2]
                    if not self._has_generic_button_signal(slot_crop):
                        continue

                    bbox = _clip_bbox(
                        (
                            origin_x + scaled_search_area[0] + x1,
                            origin_y + scaled_search_area[1] + y1,
                            origin_x + scaled_search_area[0] + x2,
                            origin_y + scaled_search_area[1] + y2,
                        ),
                        full_frame.shape[:2],
                    )

                    duplicate = False
                    for existing_detection in existing + slot_detections:
                        ex1, ey1, ex2, ey2 = existing_detection.bbox
                        if (
                            abs(bbox[0] - ex1) <= duplicate_margin
                            and abs(bbox[1] - ey1) <= duplicate_margin
                            and abs(bbox[2] - ex2) <= duplicate_margin
                            and abs(bbox[3] - ey2) <= duplicate_margin
                        ):
                            duplicate = True
                            break
                    if duplicate:
                        continue

                    slot_detections.append(
                        DetectionResult(
                            class_name="action_button_generic",
                            confidence=0.42,
                            bbox=bbox,
                        )
                    )

        slot_detections.sort(key=lambda det: (det.center[1], det.center[0]))
        return slot_detections[:3]

    @staticmethod
    def _collect_preset_slot_boxes(
        preset: TemplatePreset,
        region_scale: Tuple[float, float],
        top_left: Tuple[int, int],
        frame_shape: Tuple[int, int],
    ) -> Dict[str, Tuple[int, int, int, int]]:
        slot_map = {
            "FOLD": preset.table_data.get("mouse_fold"),
            "CALL": preset.table_data.get("mouse_check") or preset.table_data.get("mouse_call"),
            "BET_BTN": preset.table_data.get("mouse_raise"),
            "BET_BOX": preset.table_data.get("raise_value"),
        }
        boxes: Dict[str, Tuple[int, int, int, int]] = {}
        origin_x, origin_y = top_left
        for key, area in slot_map.items():
            if not _is_area(area):
                continue
            x1, y1, x2, y2 = _scale_bbox(_normalize_area(area), region_scale)
            boxes[key] = _clip_bbox(
                (origin_x + x1, origin_y + y1, origin_x + x2, origin_y + y2),
                frame_shape,
            )
        return boxes

    def _detect_preset_slot_action_buttons(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
        existing: List[DetectionResult],
    ) -> List[DetectionResult]:
        slot_boxes = self._collect_preset_slot_boxes(
            preset=preset,
            region_scale=region_scale,
            top_left=top_left,
            frame_shape=full_frame.shape[:2],
        )
        if not slot_boxes:
            return []

        detections: List[DetectionResult] = []
        duplicate_margin = max(18, int(round(18 * template_scale)))
        ordered_slots = ("FOLD", "CALL", "BET_BTN")

        for slot_key in ordered_slots:
            bbox = slot_boxes.get(slot_key)
            if not bbox:
                continue

            duplicate = False
            for existing_detection in existing + detections:
                ex1, ey1, ex2, ey2 = existing_detection.bbox
                if (
                    abs(bbox[0] - ex1) <= duplicate_margin
                    and abs(bbox[1] - ey1) <= duplicate_margin
                    and abs(bbox[2] - ex2) <= duplicate_margin
                    and abs(bbox[3] - ey2) <= duplicate_margin
                ):
                    duplicate = True
                    break
            if duplicate:
                continue

            crop = _crop_frame(full_frame, bbox)
            if not self._has_generic_button_signal(crop):
                continue

            detections.append(
                DetectionResult(
                    class_name="action_button_generic",
                    confidence=0.44,
                    bbox=bbox,
                )
            )

        detections.sort(key=lambda det: (det.center[1], det.center[0]))
        return detections[:3]

    def _detect_dealer_button(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
    ) -> Optional[DetectionResult]:
        if preset.dealer_template is None:
            return None

        button_area = preset.table_data.get("button_search_area")
        if not isinstance(button_area, dict):
            return None

        origin_x, origin_y = top_left
        best_detection = None
        best_error = None
        scaled_template = _resize_template(preset.dealer_template, template_scale)
        for candidate in button_area.values():
            if not _is_area(candidate):
                continue
            area_bbox = _scale_bbox(_normalize_area(candidate), region_scale)
            search_crop = _crop_frame(table_frame, area_bbox)
            if search_crop is None:
                continue
            if (
                scaled_template.shape[1] >= search_crop.shape[1]
                or scaled_template.shape[0] >= search_crop.shape[0]
            ):
                continue
            error, location = _find_template_sqdiff(search_crop, scaled_template)
            if error > (0.2 if abs(template_scale - 1.0) > 0.05 else 0.16):
                continue
            if best_error is None or error < best_error:
                local_x, local_y = location
                x1 = origin_x + area_bbox[0] + local_x
                y1 = origin_y + area_bbox[1] + local_y
                x2 = x1 + scaled_template.shape[1]
                y2 = y1 + scaled_template.shape[0]
                best_detection = DetectionResult(
                    class_name="dealer_button",
                    confidence=max(0.0, 1.0 - error),
                    bbox=_clip_bbox((x1, y1, x2, y2), full_frame.shape[:2]),
                )
                best_error = error

        return best_detection

    def _detect_hero_cards(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
    ) -> List[DetectionResult]:
        hero_area = preset.table_data.get("my_cards_area")
        if _is_area(hero_area):
            detections = self._detect_cards_from_search_area(
                full_frame=full_frame,
                table_frame=table_frame,
                preset=preset,
                top_left=top_left,
                area_bbox=_normalize_area(hero_area),
                template_scale=template_scale,
                region_scale=region_scale,
                limit=2,
                sort_key=detection_sort_key,
                pad_ratio_x=0.18,
                pad_ratio_y=1.0,
                corner_weight=0.0,
            )
            detections = _dedupe_card_detections(detections, detection_sort_key)
            if len(detections) == 2:
                return detections

        detections: List[DetectionResult] = []
        for area_name in ("left_card_area", "right_card_area"):
            area_data = preset.table_data.get(area_name)
            if not _is_area(area_data):
                continue
            best = self._detect_single_best_card(
                full_frame=full_frame,
                table_frame=table_frame,
                preset=preset,
                top_left=top_left,
                area_bbox=_normalize_area(area_data),
                template_scale=template_scale,
                region_scale=region_scale,
            )
            if best is not None:
                detections.append(best)

        if detections:
            detections = _dedupe_card_detections(detections, detection_sort_key)
            return detections

        heuristic_area = self._heuristic_hero_area(table_frame.shape[:2])
        detections = self._detect_cards_from_search_area(
            full_frame=full_frame,
            table_frame=table_frame,
            preset=preset,
            top_left=top_left,
            area_bbox=heuristic_area,
            template_scale=template_scale,
            region_scale=(1.0, 1.0),
            limit=2,
            sort_key=detection_sort_key,
            pad_ratio_x=0.12,
            pad_ratio_y=0.20,
            corner_weight=0.0,
        )
        detections = _dedupe_card_detections(detections, detection_sort_key)
        if len(detections) == 2:
            return detections

        if _is_area(hero_area):
            detections = self._detect_cards_in_area(
                full_frame=full_frame,
                table_frame=table_frame,
                preset=preset,
                top_left=top_left,
                area_bbox=_normalize_area(hero_area),
                threshold=0.14,
                x_tolerance=18.0,
                y_tolerance=18.0,
                limit=2,
                template_scale=template_scale,
                region_scale=region_scale,
            )

        detections = _dedupe_card_detections(detections, detection_sort_key)
        return detections

    def _build_static_area_detections(
        self,
        full_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        area_name: str,
        class_name: str,
        region_scale: Tuple[float, float],
    ) -> List[DetectionResult]:
        area_map = preset.table_data.get(area_name)
        if not isinstance(area_map, dict):
            return []

        origin_x, origin_y = top_left
        detections: List[DetectionResult] = []
        pad_x = 0
        pad_y = 0
        if class_name == "player_name_area":
            pad_x = max(14, int(round(20 * max(region_scale[0], 1.0))))
            pad_y = max(6, int(round(8 * max(region_scale[1], 1.0))))
        elif class_name == "stack_area":
            pad_x = max(12, int(round(16 * max(region_scale[0], 1.0))))
            pad_y = max(6, int(round(8 * max(region_scale[1], 1.0))))

        for _, candidate in self._sorted_area_items(area_map):
            if not _is_area(candidate):
                continue
            x1, y1, x2, y2 = _scale_bbox(_normalize_area(candidate), region_scale)
            x1, y1, x2, y2 = _expand_bbox((x1, y1, x2, y2), pad_x, pad_y)
            detections.append(
                DetectionResult(
                    class_name=class_name,
                    confidence=1.0,
                    bbox=_clip_bbox((origin_x + x1, origin_y + y1, origin_x + x2, origin_y + y2), full_frame.shape[:2]),
                )
            )

        return detections

    def _detect_board_cards(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
    ) -> List[DetectionResult]:
        board_slot_map = preset.table_data.get("board_card_areas") or preset.table_data.get("table_card_areas")
        if isinstance(board_slot_map, dict):
            detections: List[DetectionResult] = []
            for _, candidate in self._sorted_area_items(board_slot_map):
                if not _is_area(candidate):
                    continue
                best = self._detect_single_best_board_card(
                    full_frame=full_frame,
                    table_frame=table_frame,
                    preset=preset,
                    top_left=top_left,
                    area_bbox=_normalize_area(candidate),
                    template_scale=template_scale,
                    region_scale=region_scale,
                )
                if best is not None:
                    detections.append(best)
            return _dedupe_card_detections(detections, board_sort_key)

        area_data = preset.table_data.get("table_cards_area")
        if not _is_area(area_data):
            return []

        detections = self._detect_cards_in_area(
            full_frame=full_frame,
            table_frame=table_frame,
            preset=preset,
            top_left=top_left,
            area_bbox=_normalize_area(area_data),
            threshold=0.13,
            x_tolerance=18.0,
            y_tolerance=22.0,
            limit=5,
            template_scale=template_scale,
            region_scale=region_scale,
        )
        return _dedupe_card_detections(detections, board_sort_key)

    def _detect_single_best_board_card(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        area_bbox: Tuple[int, int, int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
    ) -> Optional[DetectionResult]:
        scaled_area_bbox = _scale_bbox(area_bbox, region_scale)
        pad_x = max(16, int(round(18 * max(region_scale[0], 1.0))))
        pad_y = max(12, int(round(14 * max(region_scale[1], 1.0))))
        search_bbox = _expand_bbox(scaled_area_bbox, pad_x, pad_y)
        search_crop = _crop_frame(table_frame, search_bbox)
        if search_crop is None or not _has_visible_card_signal(search_crop):
            return None

        best_label: Optional[str] = None
        best_error: Optional[float] = None
        best_location = (0, 0)
        best_scale = template_scale

        for label, template in preset.card_templates.items():
            for scale_candidate in _card_template_scale_candidates(template_scale):
                scaled_template = _resize_template(template, scale_candidate)
                template_corner = _extract_card_corner(scaled_template)
                if template_corner is None:
                    continue
                if (
                    template_corner.shape[1] >= search_crop.shape[1]
                    or template_corner.shape[0] >= search_crop.shape[0]
                ):
                    continue

                raw_error, location = _find_template_sqdiff(search_crop, template_corner)
                if best_error is None or raw_error < best_error:
                    best_error = raw_error
                    best_label = label
                    best_location = location
                    best_scale = scale_candidate

        if best_label is None or best_error is None or best_error > 0.14:
            return None

        matched_template = _resize_template(preset.card_templates[best_label], best_scale)
        origin_x, origin_y = top_left
        local_x, local_y = best_location
        x1 = origin_x + search_bbox[0] + local_x
        y1 = origin_y + search_bbox[1] + local_y
        x2 = x1 + matched_template.shape[1]
        y2 = y1 + matched_template.shape[0]
        return DetectionResult(
            class_name=best_label,
            confidence=max(0.0, 1.0 - float(best_error)),
            bbox=_clip_bbox((x1, y1, x2, y2), full_frame.shape[:2]),
        )

    def _detect_single_best_card(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        area_bbox: Tuple[int, int, int, int],
        template_scale: float,
        region_scale: Tuple[float, float],
        corner_weight: float = 0.0,
        apply_location_bias: bool = True,
    ) -> Optional[DetectionResult]:
        scaled_area_bbox = _scale_bbox(area_bbox, region_scale)
        pad_x = max(8, int(round(10 * max(region_scale[0], 1.0))))
        pad_y = max(10, int(round(16 * max(region_scale[1], 1.0))))
        scaled_area_bbox = _expand_bbox(scaled_area_bbox, pad_x, pad_y)
        search_crop = _crop_frame(table_frame, scaled_area_bbox)
        if search_crop is None or not _has_visible_card_signal(search_crop):
            return None

        best_label = None
        best_location = (0, 0)
        best_error = None
        best_raw_error = None
        best_scale = template_scale
        for label, template in preset.card_templates.items():
            for scale_candidate in _card_template_scale_candidates(template_scale):
                scaled_template = _resize_template(template, scale_candidate)
                if (
                    scaled_template.shape[1] >= search_crop.shape[1]
                    or scaled_template.shape[0] >= search_crop.shape[0]
                ):
                    continue
                raw_error, location = _find_template_sqdiff(search_crop, scaled_template)
                adjusted_error = (
                    _location_adjusted_error(
                        raw_error,
                        location,
                        search_crop.shape[:2],
                        scaled_template.shape[:2],
                    )
                    if apply_location_bias
                    else float(raw_error)
                )
                combined_error = adjusted_error
                if corner_weight > 0.0:
                    local_x, local_y = location
                    matched_crop = search_crop[
                        local_y : local_y + scaled_template.shape[0],
                        local_x : local_x + scaled_template.shape[1],
                    ]
                    crop_corner = _extract_card_corner(matched_crop)
                    template_corner = _extract_card_corner(scaled_template)
                    if crop_corner is not None and template_corner is not None and crop_corner.size and template_corner.size:
                        if crop_corner.shape[:2] != template_corner.shape[:2]:
                            crop_corner = cv2.resize(
                                crop_corner,
                                (template_corner.shape[1], template_corner.shape[0]),
                                interpolation=cv2.INTER_AREA,
                            )
                        corner_error = float(
                            np.mean(
                                (crop_corner.astype(np.float32) - template_corner.astype(np.float32)) ** 2
                            )
                        ) / (255.0 ** 2)
                        combined_error = (adjusted_error * (1.0 - corner_weight)) + (corner_error * corner_weight)

                if best_error is None or combined_error < best_error:
                    best_error = combined_error
                    best_raw_error = raw_error
                    best_label = label
                    best_location = location
                    best_scale = scale_candidate

        if best_label is None or best_error is None or best_error > (0.24 if abs(template_scale - 1.0) > 0.05 else 0.18):
            return None

        template = _resize_template(preset.card_templates[best_label], best_scale)
        origin_x, origin_y = top_left
        local_x, local_y = best_location
        x1 = origin_x + scaled_area_bbox[0] + local_x
        y1 = origin_y + scaled_area_bbox[1] + local_y
        x2 = x1 + template.shape[1]
        y2 = y1 + template.shape[0]
        return DetectionResult(
            class_name=best_label,
            confidence=max(0.0, 1.0 - float(best_raw_error if best_raw_error is not None else best_error)),
            bbox=_clip_bbox((x1, y1, x2, y2), full_frame.shape[:2]),
        )

    def _detect_cards_in_area(
        self,
        full_frame: np.ndarray,
        table_frame: np.ndarray,
        preset: TemplatePreset,
        top_left: Tuple[int, int],
        area_bbox: Tuple[int, int, int, int],
        threshold: float,
        x_tolerance: float,
        y_tolerance: float,
        limit: int,
        template_scale: float,
        region_scale: Tuple[float, float],
    ) -> List[DetectionResult]:
        scaled_area_bbox = _scale_bbox(area_bbox, region_scale)
        pad_x = max(8, int(round(10 * max(region_scale[0], 1.0))))
        pad_y = max(10, int(round(14 * max(region_scale[1], 1.0))))
        scaled_area_bbox = _expand_bbox(scaled_area_bbox, pad_x, pad_y)
        search_crop = _crop_frame(table_frame, scaled_area_bbox)
        if search_crop is None or not _has_visible_card_signal(search_crop):
            return []

        origin_x, origin_y = top_left
        detections: List[DetectionResult] = []
        for label, template in preset.card_templates.items():
            for scale_candidate in _card_template_scale_candidates(template_scale):
                scaled_template = _resize_template(template, scale_candidate)
                if (
                    scaled_template.shape[1] >= search_crop.shape[1]
                    or scaled_template.shape[0] >= search_crop.shape[0]
                ):
                    continue
                for error, location in _find_template_candidates(
                    search_crop,
                    scaled_template,
                    threshold=max(threshold, 0.18 if abs(scale_candidate - 1.0) > 0.05 else threshold),
                    max_candidates=max(2, limit),
                ):
                    adjusted_error = _location_adjusted_error(
                        error,
                        location,
                        search_crop.shape[:2],
                        scaled_template.shape[:2],
                    )
                    local_x, local_y = location
                    x1 = origin_x + scaled_area_bbox[0] + local_x
                    y1 = origin_y + scaled_area_bbox[1] + local_y
                    x2 = x1 + scaled_template.shape[1]
                    y2 = y1 + scaled_template.shape[0]
                    detections.append(
                        DetectionResult(
                            class_name=label,
                            confidence=max(0.0, 1.0 - adjusted_error),
                            bbox=_clip_bbox((x1, y1, x2, y2), full_frame.shape[:2]),
                        )
                    )

        detections = dedupe_nearby_detections(
            detections,
            x_tolerance=max(x_tolerance, x_tolerance * template_scale),
            y_tolerance=max(y_tolerance, y_tolerance * template_scale),
        )
        detections.sort(key=board_sort_key)
        return detections[:limit]


class PokerDetector:
    def __init__(self, model_path: str = "models/poker_yolo_v11.engine", pipeline: list = None):
        self.model_path = model_path
        self.pipeline = pipeline or ["yolo", "llm", "opencv"]
        self.model = None
        self.names = {}
        self.fallback_detector = TemplateFallbackDetector()
        self._last_fallback_preset_name: Optional[str] = None

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
    def _has_actionable_button_layout(action_buttons: List[DetectionResult]) -> bool:
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
                        import cv2
                        from datetime import datetime
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
                        llm_hero: List[DetectionResult] = []
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
