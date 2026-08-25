"""Tests unitaires des helpers purs du detector (ratchet coverage 43%)."""
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.vision.detector import resolve_model_path
from src.vision.models import (
    DetectionResult,
    decode_card_token,
    dedupe_nearby_detections,
    detection_sort_key,
)
from src.vision.template_detector import (
    _bbox_overlap_ratio,
    _clip_bbox,
    _find_template_candidates,
    _find_template_sqdiff,
)


def _make_frame(width=200, height=150) -> np.ndarray:
    return np.full((height, width, 3), 40, dtype=np.uint8)


def test_find_template_sqdiff_handles_invalid_inputs():
    score, loc = _find_template_sqdiff(None, None)
    assert (score, loc) == (1.0, (0, 0))

    frame = _make_frame()
    huge_template = np.zeros((500, 500, 3), dtype=np.uint8)
    assert _find_template_sqdiff(frame, huge_template) == (1.0, (0, 0))


def test_find_template_sqdiff_locates_exact_match():
    frame = _make_frame()
    template = np.full((20, 30, 3), 200, dtype=np.uint8)
    frame[50:70, 80:110] = template

    score, (x, y) = _find_template_sqdiff(frame, template)
    assert score == pytest.approx(0.0, abs=1e-6)
    assert (x, y) == (80, 50)


def test_find_template_candidates_suppresses_neighbours():
    frame = _make_frame(300, 200)
    template = np.full((10, 10, 3), 220, dtype=np.uint8)
    # Deux occurrences éloignées.
    frame[40:50, 30:40] = template
    frame[120:130, 220:230] = template

    candidates = _find_template_candidates(frame, template, threshold=1e-4, max_candidates=4)

    locations = sorted(loc for _, loc in candidates)
    assert len(candidates) >= 2
    assert (30, 40) in locations
    assert (220, 120) in locations


def test_find_template_candidates_empty_on_mismatch():
    frame = _make_frame()
    template = np.full((10, 10, 3), 250, dtype=np.uint8)  # absent du frame
    assert _find_template_candidates(frame, template, threshold=0.01, max_candidates=2) == []


def test_clip_bbox_clamps_to_frame():
    assert _clip_bbox((-5, -5, 500, 400), (100, 200)) == (0, 0, 200, 100)
    assert _clip_bbox((10, 10, 50, 60), (100, 200)) == (10, 10, 50, 60)


def test_bbox_overlap_ratio_zero_when_disjoint_or_degenerate():
    assert _bbox_overlap_ratio((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    # bbox dégénérée (aire nulle) : ratio 0 sans division par zéro.
    assert _bbox_overlap_ratio((5, 5, 5, 5), (0, 0, 10, 10)) == 0.0


def test_dedupe_nearby_detections_keeps_best_confidence_per_cluster():
    detections = [
        DetectionResult(class_name="a", confidence=0.6, bbox=(100, 100, 160, 140)),
        DetectionResult(class_name="a", confidence=0.9, bbox=(104, 102, 164, 142)),
        DetectionResult(class_name="b", confidence=0.5, bbox=(600, 600, 700, 660)),
    ]
    kept = dedupe_nearby_detections(detections, x_tolerance=36.0, y_tolerance=24.0)
    assert len(kept) == 2
    best = [d for d in kept if d.bbox[0] < 300][0]
    assert best.confidence == pytest.approx(0.9)


def test_detection_sort_key_reads_top_left_first():
    top_left = DetectionResult(class_name="a", confidence=0.5, bbox=(0, 0, 20, 20))
    bottom_right = DetectionResult(class_name="a", confidence=0.9, bbox=(100, 100, 140, 140))
    assert detection_sort_key(top_left) < detection_sort_key(bottom_right)


def test_decode_card_token_normalizes_rank_suit():
    for raw, expected in (("Ah", "Ah"), ("KD", "Kd"), ("Td", "Td"), ("as", "As")):
        assert decode_card_token(raw) == expected, raw
    # "10" n'est pas un rang valide (le dix s'écrit T) : rejeté.
    assert decode_card_token("10c") == ""


def test_resolve_model_path_finds_existing_file_and_none_otherwise():
    hit = resolve_model_path("README.md")
    assert hit is not None and hit.is_file()

    miss = resolve_model_path("modele_absoluement_inexistant.onnx")
    assert miss is None
