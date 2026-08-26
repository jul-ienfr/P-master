"""Tests du lecteur OCR natif et du classifieur par slots (button_classifier)."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.button_classifier import ButtonClassifier


class ScriptedOCR:
    """OCR qui renvoie les textes fournis dans l'ordre des appels."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    def read_text(self, image):
        self.calls += 1
        return self.texts.pop(0) if self.texts else ""


FRAME = np.full((30, 80, 3), 100, dtype=np.uint8)


def make_classifier(texts):
    return ButtonClassifier(ScriptedOCR(texts), read_text_fn=None)


def test_native_reader_prefers_keyword_variant():
    # la première variante produit du bruit, une variante prétraitée trouve le mot-clé
    classifier = ButtonClassifier(
        ScriptedOCR(["###", "se coucher"]), read_text_fn=None
    )
    assert classifier.native_read_action_button_text(FRAME) == "se coucher"


def test_native_reader_uses_cache_on_second_call(monkeypatch):
    ocr = ScriptedOCR(["check"])
    classifier = ButtonClassifier(ocr, read_text_fn=None)
    first = classifier.native_read_action_button_text(FRAME)
    assert first == "check"
    before = ocr.calls
    second = classifier.native_read_action_button_text(FRAME)
    assert second == "check"
    assert ocr.calls == before  # servi depuis le cache


def test_native_reader_empty_crop_returns_empty():
    classifier = ButtonClassifier(ScriptedOCR([]), read_text_fn=None)
    assert classifier.native_read_action_button_text(None) == ""
    empty = np.zeros((0,), dtype=np.uint8)
    assert classifier.native_read_action_button_text(empty) == ""


def test_classify_slot_fold_with_other_slots_is_direct():
    classifier = make_classifier([])
    assert (
        classifier.classify_slot_button_label(None, "FOLD", {"CALL", "BET_BTN"}, "x")
        == "fold_button"
    )


def test_classify_slot_fold_fast_fold_detection():
    # sans slot CALL/BET visible, le lecteur natif est consulté sur le crop
    classifier = ButtonClassifier(
        ScriptedOCR(["passer vite"]), read_text_fn=None
    )
    assert (
        classifier.classify_slot_button_label(FRAME, "FOLD", set(), "x")
        == "fast_fold_button"
    )


def test_classify_slot_call_with_fold_visible_keeps_fallback():
    classifier = make_classifier([])
    assert (
        classifier.classify_slot_button_label(
            None, "CALL", {"FOLD", "BET_BTN"}, "all_in_call_button"
        )
        == "all_in_call_button"
    )
    assert (
        classifier.classify_slot_button_label(None, "CALL", {"FOLD", "BET_BTN"}, "weird")
        == "call_button"
    )


def test_classify_slot_call_without_fold_reads_text():
    classifier = make_classifier(["check"])
    assert classifier.classify_slot_button_label(None, "CALL", {"BET_BTN"}, "") == "check_button"

    resume = make_classifier(["reprendre"])
    assert resume.classify_slot_button_label(None, "CALL", set(), "") == "resume_hand"


def test_classify_slot_bet_btn_defaults_by_context():
    classifier = make_classifier([])
    # fold + call visibles -> fallback raise
    assert (
        classifier.classify_slot_button_label(None, "BET_BTN", {"FOLD", "CALL"}, "bet_button")
        == "bet_button"
    )
    assert classifier.classify_slot_button_label(None, "BET_BTN", {"FOLD", "CALL"}, "?") == "raise_button"
    # call seul visible -> bet
    assert classifier.classify_slot_button_label(None, "BET_BTN", {"CALL"}, "?") == "bet_button"


def test_classify_slot_unknown_key_time_bank_guard():
    classifier = make_classifier([])
    # slot inconnu : passe dans la branche time bank avant tout traitement texte
    assert (
        classifier.classify_slot_button_label(None, "OTHER", set(), "resume_hand")
        == "resume_hand"
    )
