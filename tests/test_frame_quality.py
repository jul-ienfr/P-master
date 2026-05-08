import time

import numpy as np

from src.vision.crop_quality import analyze_crop_quality
from src.vision.frame_quality import analyze_frame_quality


def test_analyze_frame_quality_rejects_stale_frame():
    frame = np.full((40, 40, 3), 127, dtype=np.uint8)
    report = analyze_frame_quality(frame, captured_at=time.monotonic() - 1.0, max_age_ms=300.0)

    assert report.rejected is True
    assert report.reject_reason == "stale_frame"


def test_analyze_frame_quality_scores_sharp_frame_higher_than_uniform_frame():
    sharp = np.zeros((60, 60, 3), dtype=np.uint8)
    sharp[:, ::2] = 255
    flat = np.full((60, 60, 3), 127, dtype=np.uint8)

    sharp_report = analyze_frame_quality(sharp)
    flat_report = analyze_frame_quality(flat)

    assert sharp_report.quality_score > flat_report.quality_score


def test_analyze_crop_quality_rejects_tiny_crop():
    crop = np.zeros((4, 4, 3), dtype=np.uint8)
    report = analyze_crop_quality("pot", crop)

    assert report.rejected is True
    assert report.reject_reason == "crop_too_small"


def test_analyze_crop_quality_returns_field_name_and_scores():
    crop = np.zeros((24, 80, 3), dtype=np.uint8)
    crop[:, ::2] = 255
    report = analyze_crop_quality("button", crop)

    assert report.field_name == "button"
    assert 0.0 <= report.quality_score <= 1.0
    assert report.metadata["edge_density"] >= 0.0
