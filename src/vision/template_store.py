"""Chargement des presets templates (extrait de src/vision/detector.py)."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.vision.models import (
    ACTION_BUTTON_LABELS,
    BUILTIN_PRESET_MANIFESTS,
    decode_card_token,
)
from src.vision.table_geometry import TableGeometry, geometry_from_manifest

logger = logging.getLogger(__name__)


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


def _normalize_area(value: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(value["x1"]),
        int(value["y1"]),
        int(value["x2"]),
        int(value["y2"]),
    )


def _estimate_table_bounds(table_data: dict[str, Any]) -> tuple[int, int]:
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
    table_data: dict[str, Any]
    anchor_templates: dict[str, np.ndarray]
    anchor_offsets: dict[str, tuple[int, int]]
    anchor_match_bounds: dict[str, tuple[int, int]]
    action_templates: dict[str, np.ndarray]
    card_templates: dict[str, np.ndarray]
    dealer_template: np.ndarray | None
    table_width: int
    table_height: int
    preset_hash: str = ""
    hash_verified: bool = True
    hash_mismatches: list[str] = field(default_factory=list)
    geometry: TableGeometry | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_preset_assets(manifest_path: Path) -> tuple[bool, list[str], str]:
    """Vérifie les sha256 des assets du preset contre `fingerprint.asset_hashes`.

    Retourne (verified, mismatched_asset_names, manifest_hash). Un preset sans
    section fingerprint est considéré non vérifiable (verified=True, hash vide).
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error(
            "PRESET_HASH_MISMATCH | preset=%s error=manifest_unreadable detail=%s",
            manifest_path,
            exc,
        )
        return False, ["<manifest>"], ""

    fingerprint = dict(manifest.get("fingerprint", {}) or {})
    asset_hashes = dict(fingerprint.get("asset_hashes", {}) or {})
    manifest_hash = str(fingerprint.get("hash", "") or "")
    if not asset_hashes:
        return True, [], manifest_hash

    asset_root = manifest_path.parent
    mismatches: list[str] = []
    for asset_name, expected_hash in sorted(asset_hashes.items()):
        relative_path = (manifest.get("assets", {}) or {}).get(asset_name)
        if not relative_path:
            mismatches.append(str(asset_name))
            continue
        asset_path = asset_root / str(relative_path)
        if not asset_path.is_file():
            mismatches.append(str(asset_name))
            continue
        actual_hash = _sha256_file(asset_path)
        if actual_hash.lower() != str(expected_hash).lower():
            mismatches.append(str(asset_name))
    return (not mismatches), mismatches, manifest_hash


def load_presets(preset_manifests: list[Path]) -> list[TemplatePreset]:
    manifests = preset_manifests or [
        _repo_root() / relative_path for relative_path in BUILTIN_PRESET_MANIFESTS
    ]
    presets: list[TemplatePreset] = []

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
            anchor_offsets = dict.fromkeys(anchor_templates, default_anchor_offset)
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
            hash_verified, hash_mismatches, preset_hash = verify_preset_assets(manifest_path)
            if not hash_verified:
                logger.error(
                    "PRESET_HASH_MISMATCH | preset=%s assets=%s — recalibrer ou restaurer "
                    "les assets (client mis à jour ?).",
                    manifest_path,
                    ",".join(hash_mismatches),
                )
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
                    preset_hash=preset_hash,
                    hash_verified=hash_verified,
                    hash_mismatches=hash_mismatches,
                    geometry=geometry_from_manifest(manifest, source=str(manifest_path)),
                )
            )
        except Exception as exc:  # pragma: no cover - depends on local asset integrity
            logger.warning("Impossible de charger le preset %s: %s", manifest_path, exc)

    return presets
