import numpy as np
from pathlib import Path

from src.vision.table_geometry import DEFAULT_RUNTIME_GEOMETRY, geometry_from_manifest_path, geometry_to_pixel_regions


def test_geometry_to_pixel_regions_returns_expected_named_regions():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    regions = geometry_to_pixel_regions(frame, DEFAULT_RUNTIME_GEOMETRY)

    assert set(regions.keys()) == {"table", "board", "pot", "hero", "actions"}
    assert regions["table"] == (16, 10, 184, 88)


def test_geometry_to_pixel_regions_scales_with_frame_size():
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    regions = geometry_to_pixel_regions(frame, DEFAULT_RUNTIME_GEOMETRY)

    assert regions["pot"] == (152, 84, 248, 144)


def test_geometry_from_manifest_path_loads_preset_regions():
    manifest_path = Path(__file__).resolve().parents[1] / "poker" / "pokerstars-7-fr-6-max" / "draft" / "manifest.json"
    geometry = geometry_from_manifest_path(manifest_path)

    assert geometry.source.endswith("manifest.json")
    assert "pot" in geometry.regions
    assert geometry.table_size[0] > 0
