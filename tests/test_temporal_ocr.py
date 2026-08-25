# -*- coding: utf-8 -*-
"""Tests du filtre OCR temporel anti-hallucination (src/vision/temporal_ocr.py)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.temporal_ocr import TemporalOCRFilter


def make_filter(history_size=3, amounts=None, texts=None):
    f = TemporalOCRFilter.__new__(TemporalOCRFilter)
    f.history_size = history_size
    f._amount_history = __import__("collections").deque(maxlen=history_size)
    f._text_history = __import__("collections").deque(maxlen=history_size)
    f.ocr_engine = SimpleNamespace(
        read_and_parse_amount=lambda crop: (amounts.pop(0) if amounts else None),
        read_text=lambda crop: (texts.pop(0) if texts else ""),
    )
    return f


FRAME = np.zeros((10, 20, 3), dtype=np.uint8)


def test_read_stable_amount_returns_raw_until_history_full():
    f = make_filter(history_size=3, amounts=[100.0, 100.0])
    assert f.read_stable_amount(FRAME) == 100.0
    assert f.read_stable_amount(FRAME) == 100.0
    # historique plein et stable -> consensus
    f.read_stable_amount(FRAME)
    assert f._get_consensus_amount() == 100.0


def test_read_stable_amount_missing_reading_falls_back_to_consensus():
    f = make_filter(history_size=2, amounts=[None])
    f._amount_history.append(50.0)
    assert f.read_stable_amount(FRAME) == 50.0


def test_read_stable_amount_unstable_history_returns_none():
    f = make_filter(history_size=4)
    for value in [10.0, 500.0, 900.0]:
        f._amount_history.append(value)
    assert f._get_consensus_amount() is None


def test_chip_count_zero_warning_does_not_alter_value():
    f = make_filter(history_size=2, amounts=[80.0])
    assert f.read_stable_amount(FRAME, chip_count=0) == 80.0


def test_read_stable_text_requires_majority():
    f = make_filter(history_size=2, texts=["Villain"])
    assert f.read_stable_text(FRAME) == "Villain"
    f.read_stable_text(FRAME)
    assert f.read_stable_text(FRAME) == "Villain"


def test_reset_history_clears_both_caches():
    f = make_filter()
    f._amount_history.append(1.0)
    f._text_history.append("a")
    f.reset_history()
    assert len(f._amount_history) == 0
    assert len(f._text_history) == 0
    assert f._get_consensus_amount() is None
    assert f._get_consensus_text() == ""


def test_get_consensus_text_empty_history():
    assert TemporalOCRFilter._get_consensus_text(make_filter()) == ""
