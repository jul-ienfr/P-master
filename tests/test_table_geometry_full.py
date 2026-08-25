"""Tests de la géométrie de table (src/vision/table_geometry.py)."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.models import DetectionResult, TableState
from src.vision.table_geometry import (
    detection_center,
    geometry_to_pixel_regions,
    is_image_changed,
    safe_crop,
)


def det(cls, x1, y1, x2, y2, confidence=0.9):
    return DetectionResult(class_name=cls, confidence=confidence, bbox=(x1, y1, x2, y2))


def sample_state():
    return TableState(
        board_cards=[det("card", 300, 200, 340, 260)],
        hero_cards=[det("card", 250, 400, 290, 460)],
        dealer_button=det("dealer_button", 500, 300, 520, 320),
        pots=[det("pot", 380, 240, 450, 270)],
        stacks=[det("stack", 100, 350, 160, 400)],
        player_names=[det("player_name", 90, 410, 180, 430)],
        action_buttons=[
            det("fold_button", 550, 480, 640, 520),
            det("call_button", 660, 480, 750, 520),
        ],
        metadata={},
    )


def test_detection_center_returns_midpoint():
    assert detection_center(det("x", 10, 20, 30, 60)) == (20.0, 40.0)


def test_safe_crop_clamps_and_pads():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    crop = safe_crop(frame, (10, 10, 50, 50))
    assert crop.shape == (40, 40, 3)
    # bbox hors cadre -> clamp
    clamped = safe_crop(frame, (-20, -20, 500, 500))
    assert clamped.shape == (100, 100, 3)
    # bbox dégénérée -> None
    assert safe_crop(frame, (30, 30, 30, 30)) is None


def test_safe_crop_supports_ratio_padding():
    frame = np.full((200, 200, 3), 255, dtype=np.uint8)
    crop = safe_crop(frame, (50, 50, 100, 100), pad_ratio_x=0.5, pad_ratio_y=0.5)
    assert crop.shape[0] > 50 and crop.shape[1] > 50


def test_is_image_changed_detects_difference_and_similarity():
    base = np.zeros((50, 50, 3), dtype=np.uint8)
    same = base.copy()
    changed = base.copy()
    changed[10:40, 10:40] = 255
    assert is_image_changed(base, changed) == True  # noqa: E712
    assert is_image_changed(base, same) == False  # noqa: E712
    # image manquante -> considérée comme changée
    assert is_image_changed(base, None) == True  # noqa: E712


def test_geometry_to_pixel_regions_covers_expected_named_regions():
    regions = geometry_to_pixel_regions(np.zeros((600, 900, 3), dtype=np.uint8))
    for name in ("board", "hero", "pot", "table", "actions"):
        assert name in regions
        bbox = regions[name]
        assert len(bbox) == 4
        assert bbox[0] < bbox[2] and bbox[1] < bbox[3]


def test_geometry_to_pixel_regions_scales_with_frame_size():
    small = geometry_to_pixel_regions(np.zeros((300, 450, 3), dtype=np.uint8))
    large = geometry_to_pixel_regions(np.zeros((1200, 1800, 3), dtype=np.uint8))
    assert large["actions"][2] > small["actions"][2]
