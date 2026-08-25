"""Tests du parseur numérique (src/vision/numeric_parser.py)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.numeric_parser import NumericParser


def test_parse_accepts_space_thousands_and_decimals():
    parser = NumericParser()
    result = parser.parse("1 250,50")
    assert result.valid is True
    assert result.value == pytest.approx(1250.5)
    assert result.sanitized_text == "1 250,50"


def test_parse_rejects_empty_and_garbage():
    empty = NumericParser().parse("")
    assert empty.valid is False
    assert empty.reject_reason == "empty_text"
    assert empty.sanitized_text == ""

    garbage = NumericParser().parse("no digits here")
    assert garbage.valid is False
    assert garbage.reject_reason == "parse_rejected"


def test_parse_without_decimal_amounts_rejects_fraction():
    # PokerStars play money : les séparateurs décimaux sont interdits
    parser = NumericParser(allow_decimal_amounts=False)
    result = parser.parse("12,50")
    assert result.valid is False
    assert result.reject_reason == "parse_rejected"

    ok = parser.parse("1250")
    assert ok.valid is True and ok.value == pytest.approx(1250.0)


def test_fallback_parse_handles_nbsp_and_multiple_tokens():
    parser = NumericParser()
    assert parser._fallback_parse_amount("Pot 2 500") == 2500.0
    assert parser._fallback_parse_amount("$1,234.56") == pytest.approx(1234.56)
    assert parser._fallback_parse_amount("") is None
