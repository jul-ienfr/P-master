"""Tests du classifieur de boutons d'action (src/vision/button_classifier.py)."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.button_classifier import (
    ButtonClassifier,
    button_slot_overlap_ratio,
    is_resume_like_button_text,
    normalize_action_button_text,
)
from src.vision.models import DetectionResult, TableState


class StubOCR:
    def read_text(self, image):
        return ""


def make_classifier(read_text=""):
    return ButtonClassifier(
        StubOCR(),
        read_text_fn=lambda crop: read_text,
    )


def test_normalize_action_button_text_lowercases_and_strips():
    assert normalize_action_button_text("  FOLD ") == "fold"
    assert normalize_action_button_text("") == ""


def test_is_resume_like_button_text_variants():
    assert is_resume_like_button_text("reprendre la main") is True
    assert is_resume_like_button_text("continue") is True
    assert is_resume_like_button_text("fold") is False
    assert is_resume_like_button_text("") is False


def test_button_slot_overlap_ratio_full_partial_and_disjoint():
    slot = (0, 0, 100, 50)
    assert button_slot_overlap_ratio((0, 0, 100, 50), slot) == pytest.approx(1.0)
    assert button_slot_overlap_ratio((50, 0, 150, 50), slot) == pytest.approx(0.5)
    assert button_slot_overlap_ratio((200, 200, 300, 250), slot) == 0.0


def test_classify_action_button_label_ocr_keywords():
    cases = {
        "se coucher": "fold_button",
        "check": "check_button",
        "suivre": "call_button",
        "relancer": "raise_button",
        "miser": "bet_button",
        "passer vite": "fast_fold_button",
        "reprendre la main": "resume_hand",
        "i'm back": "im_back",
    }
    for text, expected in cases.items():
        classifier = make_classifier(text)
        assert classifier.classify_action_button_label(np.zeros((8, 8, 3)), 1, 3) == expected, text


def test_classify_action_button_label_geometry_fallbacks():
    classifier = make_classifier("")
    # trois boutons génériques : fold / call / raise
    assert classifier.classify_action_button_label(None, 0, 3) == "fold_button"
    assert classifier.classify_action_button_label(None, 1, 3) == "call_button"
    assert classifier.classify_action_button_label(None, 2, 3) == "raise_button"
    # deux boutons : check puis bet
    assert classifier.classify_action_button_label(None, 0, 2) == "check_button"
    assert classifier.classify_action_button_label(None, 1, 2) == "bet_button"
    # un seul bouton sans texte : resume
    assert classifier.classify_action_button_label(None, 0, 1) == "resume_hand"


def test_read_action_button_text_breaks_cycle_with_native_reader(monkeypatch):
    classifier = ButtonClassifier(StubOCR(), read_text_fn=None)
    sentinel_calls = []

    def fake_native(crop):
        sentinel_calls.append(crop)
        return "check"

    monkeypatch.setattr(classifier, "native_read_action_button_text", fake_native)
    assert classifier.read_action_button_text("crop") == "check"
    assert sentinel_calls == ["crop"]


def test_promote_fast_fold_outliers_keeps_single_generic_button():
    generic = DetectionResult(
        class_name="action_button_generic", confidence=0.95, bbox=(0, 0, 80, 40)
    )
    fast = DetectionResult(class_name="fast_fold_button", confidence=0.5, bbox=(200, 0, 280, 40))
    promoted = ButtonClassifier.promote_fast_fold_outliers([generic])
    assert [b.class_name for b in promoted] == ["action_button_generic"]
    untouched = ButtonClassifier.promote_fast_fold_outliers([fast])
    assert [b.class_name for b in untouched] == ["fast_fold_button"]


def test_label_generic_action_buttons_relabels_and_sorts_left_to_right():
    classifier = ButtonClassifier(
        StubOCR(),
        read_text_fn=lambda crop: "",
    )
    state_buttons = [
        DetectionResult(
            class_name="action_button_generic", confidence=0.9, bbox=(500, 700, 600, 760)
        ),
        DetectionResult(
            class_name="action_button_generic", confidence=0.9, bbox=(100, 700, 200, 760)
        ),
        DetectionResult(
            class_name="action_button_generic", confidence=0.9, bbox=(300, 700, 400, 760)
        ),
    ]
    labeled = classifier.label_generic_action_buttons(
        TableState(action_buttons=state_buttons), None, safe_crop_stub
    )
    names = [button.class_name for button in labeled.action_buttons]
    bboxes = [button.bbox for button in labeled.action_buttons]
    # les labels suivent l'ordre d'entrée (index générique), puis tri gauche->droite
    assert names == ["call_button", "raise_button", "fold_button"]
    assert bboxes == sorted(bboxes, key=lambda bbox: bbox[0])


def safe_crop_stub(frame, bbox, pad_x=0, pad_y=0, pad_ratio_x=0.0, pad_ratio_y=0.0):
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_slot_key_for_button_requires_minimum_overlap():
    slots = {"FOLD": (0, 0, 100, 50), "CALL": (500, 0, 600, 50)}
    button = DetectionResult(
        class_name="action_button_generic", confidence=0.9, bbox=(10, 5, 90, 45)
    )
    far = DetectionResult(
        class_name="action_button_generic", confidence=0.9, bbox=(900, 900, 990, 950)
    )
    assert ButtonClassifier.slot_key_for_button(button, slots) == "FOLD"
    assert ButtonClassifier.slot_key_for_button(far, slots) == ""
    assert ButtonClassifier.slot_key_for_button(far, {"BAD": (1, 2, 3)}) == ""
