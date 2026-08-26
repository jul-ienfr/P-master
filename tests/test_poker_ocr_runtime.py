# -*- coding: utf-8 -*-
"""Tests du runtime PokerOCR avec moteurs factices (aucune dépendance OCR réelle)."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.ocr import PokerOCR

FRAME = np.zeros((20, 60, 3), dtype=np.uint8)


class FakeEngine:
    def __init__(self, name, texts):
        self.name = name
        self._texts = list(texts)

    def read_text(self, image_crop):
        return self._texts.pop(0) if self._texts else ""


def make_ocr(mode="consensus_amounts", engine_texts=None, **kwargs):
    ocr = PokerOCR(enabled_engines=[], mode=mode, **kwargs)
    if engine_texts is None:
        engine_texts = []
    ocr.engines = [
        FakeEngine(name, texts) for name, texts in zip(("engine_a", "engine_b"), engine_texts)
    ]
    return ocr


def test_read_text_returns_first_non_empty_in_consensus_mode():
    ocr = make_ocr(engine_texts=[["Villain"], [""]])
    assert ocr.read_text(FRAME) == "Villain"
    assert ocr.last_metadata["selected_engine"] == "engine_a"
    # un seul texte non vide -> accord complet
    assert ocr.last_metadata["agreement"] == "full"


def test_read_text_priority_mode_takes_first_candidate_even_if_empty():
    ocr = make_ocr(mode="priority", engine_texts=[[""], ["second"]])
    assert ocr.read_text(FRAME) == ""
    assert ocr.last_metadata["selected_engine"] == "engine_a"


def test_read_text_without_engines_or_frame_is_empty():
    ocr = make_ocr()
    ocr.engines = []
    assert ocr.read_text(None) == ""
    assert ocr.read_text(np.zeros((0,), dtype=np.uint8)) == ""
    assert ocr.last_metadata["agreement"] == "none"


def test_read_and_parse_amount_consensus_between_engines():
    ocr = make_ocr(engine_texts=[["1 250"], ["1250"]])
    value = ocr.read_and_parse_amount(FRAME)
    assert value == 1250.0
    assert ocr.last_metadata["agreement"] == "consensus"
    assert ocr.last_metadata["selected_confidence"] > 0.5


def test_read_and_parse_amount_fallback_when_no_consensus():
    ocr = make_ocr(engine_texts=[["300"], ["700"]])
    value = ocr.read_and_parse_amount(FRAME)
    assert value == 300.0  # premier candidat valide
    assert ocr.last_metadata["agreement"] == "fallback"


def test_read_and_parse_amount_none_when_all_engines_fail():
    ocr = make_ocr(engine_texts=[["garbage"], ["..."]])
    assert ocr.read_and_parse_amount(FRAME) is None
    assert ocr.last_metadata["agreement"] == "none"


def test_read_and_parse_amount_priority_mode_stops_at_first_valid():
    ocr = make_ocr(mode="priority", engine_texts=[["500"], ["900"]])
    assert ocr.read_and_parse_amount(FRAME) == 500.0
    assert ocr.last_metadata["agreement"] == "priority"


def test_read_and_parse_amount_without_engines_returns_none():
    ocr = make_ocr()
    ocr.engines = []
    assert ocr.read_and_parse_amount(None) is None


def test_read_player_name_selects_usable_candidate():
    ocr = make_ocr(engine_texts=[["Villain42"], ["Villain42"]])
    name = ocr.read_player_name(FRAME)
    assert isinstance(name, str)
    assert ocr.last_metadata["field"] == "player_name"


def test_read_player_name_without_signal_returns_empty():
    ocr = make_ocr()
    ocr.engines = []
    assert ocr.read_player_name(np.zeros((4, 4, 3), dtype=np.uint8)) == ""
    assert ocr.last_metadata["field"] == "player_name"


def test_build_player_name_variants_generates_preprocessed_images():
    variants = PokerOCR._build_player_name_variants(FRAME)
    names = [name for name, _img in variants]
    assert names == ["original", "upscaled_contrast", "threshold"]
    empty = PokerOCR._build_player_name_variants(np.zeros((0,), dtype=np.uint8))
    assert len(empty) == 1


def test_player_name_candidate_score_penalizes_placeholders():
    good = PokerOCR._player_name_candidate_score("Villain42", "original", support_count=2)
    ui_label = PokerOCR._player_name_candidate_score("Seat 1", "original")
    assert good == 1.0
    # les labels UI (Seat N) sont quasi éliminés par le score
    assert ui_label < 0.1
    assert PokerOCR._player_name_candidate_score("", "original") == 0.0


def test_preprocess_for_amount_returns_binary_image():
    frame = np.full((30, 90, 3), 40, dtype=np.uint8)
    processed = PokerOCR._preprocess_for_amount(frame)
    assert processed is not None
    assert processed.shape[:2] == (90, 270)  # upscale x3
    # entrée dégénérée renvoyée telle quelle
    tiny = np.zeros((0,), dtype=np.uint8)
    assert PokerOCR._preprocess_for_amount(tiny) is tiny


def test_from_config_reads_amount_format_block():
    ocr = PokerOCR.from_config(
        {
            "use_gpu": False,
            "parallel": False,
            "mode": "priority",
            "amount_format": {"allow_decimals": True, "thousands_separators": ["space"]},
        }
    )
    assert ocr.mode == "priority"
    assert ocr.parallel is False
    assert ocr.allow_decimal_amounts is True
    assert ocr.amount_thousands_separators == (" ",)
    assert PokerOCR.from_config(None).mode == "consensus_amounts"
    # amount_format non-dict -> ignoré proprement
    assert PokerOCR.from_config({"amount_format": "bad"}).allow_decimal_amounts is False


def test_normalize_engines_dedupes_and_falls_back():
    ocr = PokerOCR(enabled_engines=["rapidocr", "RAPIDOCR", "unknown_engine"])
    normalized = ocr.enabled_engines
    assert normalized.count("rapidocr") == 1
    assert "unknown_engine" not in normalized


def test_get_metadata_reflects_load_state():
    ocr = make_ocr()
    metadata = ocr.get_metadata()
    # la liste vide retombe sur les moteurs par défaut demandés
    assert isinstance(metadata["requested_engines"], list)
    assert isinstance(metadata["loaded_engines"], list)
    assert metadata["mode"] == "consensus_amounts"
