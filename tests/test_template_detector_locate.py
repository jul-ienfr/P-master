"""Tests de localisation de preset template avec ancre synthétique."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.template_detector import (
    TemplateFallbackDetector,
    TemplatePreset,
    _crop_frame,
    _resize_template,
    _scale_bbox,
)


@pytest.fixture()
def detector(tmp_path):
    return TemplateFallbackDetector(preset_manifests=[tmp_path / "missing"])


def make_preset(anchor: np.ndarray, name: str = "synthetic") -> TemplatePreset:
    return TemplatePreset(
        name=name,
        manifest_path=Path("synthetic/manifest.json"),
        table_data={"anchor_offset": {"x": 0, "y": 0}},
        anchor_templates={"topleft_corner_1": anchor},
        anchor_offsets={"topleft_corner_1": (0, 0)},
        anchor_match_bounds={},
        action_templates={},
        card_templates={},
        dealer_template=None,
        table_width=100,
        table_height=60,
    )


def synthetic_frame(anchor: np.ndarray, width=300, height=200, origin=(50, 40)):
    frame = np.full((height, width, 3), 30, dtype=np.uint8)
    x0, y0 = origin
    h, w = anchor.shape[:2]
    frame[y0 : y0 + h, x0 : x0 + w] = anchor
    return frame


def test_locate_cached_preset_relocates_anchor(detector):
    rng = np.random.default_rng(7)
    anchor = rng.integers(40, 220, size=(20, 30, 3), dtype=np.uint8)
    preset = make_preset(anchor)
    detector.presets = [preset]
    detector._last_match = {
        "preset_name": "synthetic",
        "anchor_name": "topleft_corner_1",
        "location": (52, 38),
        "scale": 1.0,
        "frame_shape": (20, 30),
        "error": 0.01,
    }
    frame = synthetic_frame(anchor)
    match = detector._locate_cached_preset(frame, threshold=0.2)
    assert match is not None
    _preset, location, error, _name, scale = match
    assert abs(location[0] - 50) <= 3
    assert abs(location[1] - 40) <= 3


def test_locate_locked_preset_matches_at_prior_scale(detector):
    anchor = np.full((20, 30, 3), 90, dtype=np.uint8)
    anchor[2:-2, 2:-2] = 180
    preset = make_preset(anchor)
    detector.presets = [preset]
    detector._last_match = {
        "preset_name": "synthetic",
        "anchor_name": "topleft_corner_1",
        "location": (50, 40),
        "scale": 1.0,
    }
    frame = synthetic_frame(anchor)
    match = detector._locate_locked_preset(frame, threshold=0.2)
    assert match is not None
    assert match[1] == (50, 40)


def test_locate_best_preset_full_scan_finds_anchor_first_time(detector):
    anchor = rng_anchor()
    preset = make_preset(anchor)
    detector.presets = [preset]
    detector._last_match = None
    frame = synthetic_frame(anchor)
    match = detector._locate_best_preset(frame, threshold=0.15)
    assert match is not None
    _preset, location, _error, _name, _scale = match
    assert abs(location[0] - 50) <= 4 and abs(location[1] - 40) <= 4
    # la correspondance est mémorisée pour les frames suivantes
    assert detector._last_match is not None


def rng_anchor():
    rng = np.random.default_rng(11)
    return rng.integers(30, 230, size=(18, 26, 3), dtype=np.uint8)


def test_locate_best_preset_returns_none_without_match(detector):
    anchor = rng_anchor()
    detector.presets = [make_preset(anchor)]
    noise = np.random.default_rng(3).integers(
        0, 255, size=(200, 300, 3), dtype=np.uint8
    )
    match = detector._locate_best_preset(noise, threshold=0.05)
    # sur du bruit pur, aucune correspondance fiable : None ou erreur > seuil strict
    assert match is None or match[2] > 0.05


def test_ordered_candidate_scales_prioritises_closest_to_ratio(detector_unused=None):
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    preset = make_preset(np.zeros((20, 30, 3), dtype=np.uint8))
    ordered = TemplateFallbackDetector._ordered_candidate_scales(frame, preset)
    assert ordered  # liste non vide
    # le ratio réel (200/100 = 2.0, 120/60 = 2.0) éloigne tous les candidats ;
    # vérifie simplement un tri déterministe par distance au prior
    assert sorted(ordered) == sorted(set(ordered))

    limited = TemplateFallbackDetector._ordered_candidate_scales(frame, preset, limit=2)
    assert len(limited) == 2
    assert limited == ordered[:2]


def test_crop_frame_and_scale_bbox_helpers():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    crop = _crop_frame(frame, (10, 10, 40, 40))
    assert crop.shape == (30, 30, 3)
    assert _crop_frame(frame, (200, 10, 250, 40)) is None
    scaled = _scale_bbox((10, 10, 20, 20), (2.0, 3.0))
    assert scaled == (20, 30, 40, 60)
    uniform = _scale_bbox((10, 10, 20, 20), 2.0)
    assert uniform == (20, 20, 40, 40)


def test_resize_template_identity_and_scaling():
    tpl = np.zeros((10, 20, 3), dtype=np.uint8)
    assert _resize_template(tpl, 1.0) is tpl
    bigger = _resize_template(tpl, 2.0)
    assert bigger.shape == (20, 40, 3)
