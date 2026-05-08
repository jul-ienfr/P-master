from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import json

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
