# -*- coding: utf-8 -*-
"""Chargement des presets templates (extrait de src/vision/detector.py)."""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.vision.models import ACTION_BUTTON_LABELS, decode_card_token

logger = logging.getLogger(__name__)

BUILTIN_PRESET_MANIFESTS = (
    "poker/pokerstars-7-fr-6-max/draft/manifest.json",
    "poker/official-party-poker/draft/manifest.json",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]



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




def load_presets(preset_manifests: List[Path]) -> List[TemplatePreset]:
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
