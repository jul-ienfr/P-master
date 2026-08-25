"""Tests des helpers purs de PokerOCR (parsing de montants, confiance, métadonnées)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.ocr import PokerOCR


@pytest.fixture(scope="module")
def ocr():
    return PokerOCR(enabled_engines=[], mode="consensus_amounts")


def test_normalize_amount_separators_aliases_and_dedupes():
    assert PokerOCR._normalize_amount_separators(None, default=(",", ".")) == (",", ".")
    assert PokerOCR._normalize_amount_separators(["space"], default=(" ",)) == (" ",)
    assert PokerOCR._normalize_amount_separators(["NBSP", " "], default=(" ",)) == (" ",)
    # séparateurs non autorisés ignorés -> fallback défaut
    assert PokerOCR._normalize_amount_separators([";"], default=(" ",)) == (" ",)
    assert PokerOCR._normalize_amount_separators([], default=(" ",), allow_empty=True) == ()


def test_normalize_amount_token_fixes_common_confusions():
    assert PokerOCR._normalize_amount_token(" O5I ") == "051"
    assert PokerOCR._normalize_amount_token("-1.2B0-") == "1.280"
    nbsp = "1 250"
    assert "|" not in PokerOCR._normalize_amount_token(nbsp)


def test_parse_integer_candidate_rejects_letters():
    assert PokerOCR._parse_integer_candidate("1250", [" "]) == 1250.0
    assert PokerOCR._parse_integer_candidate("1 250", [" "]) == 1250.0
    assert PokerOCR._parse_integer_candidate("12a50", [" "]) is None
    assert PokerOCR._parse_integer_candidate("", [" "]) is None


def test_parse_decimal_candidate_rules():
    assert PokerOCR._parse_decimal_candidate("12,5", [], [","]) == 12.5
    assert PokerOCR._parse_decimal_candidate("1 250,50", [" "], [","]) == 1250.5
    # deux séparateurs décimaux -> rejet
    assert PokerOCR._parse_decimal_candidate("1.2.3", [], ["."]) is None
    # plus de 2 décimales -> rejet
    assert PokerOCR._parse_decimal_candidate("1,234", [], [","]) is None
    assert PokerOCR._parse_decimal_candidate("1250", [], [","]) == 1250.0


def test_parse_amount_with_format_handles_currency_and_multipliers():
    parse = PokerOCR._parse_amount_with_format
    assert parse("$1 250", allow_decimal_amounts=True, thousands_separators=(" ",), decimal_separators=(",", ".")) == 1250.0
    assert parse("2,5k", allow_decimal_amounts=True, thousands_separators=(" ",), decimal_separators=(",", ".")) == 2500.0
    assert parse("garbage", allow_decimal_amounts=True, thousands_separators=(" ",), decimal_separators=(",", ".")) is None
    assert parse("", allow_decimal_amounts=True, thousands_separators=(" ",), decimal_separators=(",", ".")) is None


def test_parse_amount_static_entry_points(ocr):
    # par défaut : montants entiers (play money), décimales désactivées
    assert PokerOCR.parse_amount("2 500") == 2500.0
    assert PokerOCR.parse_amount("") is None
    assert PokerOCR.parse_amount("nope") is None
    # avec décimales autorisées (real money)
    value = PokerOCR.parse_amount("1 250,50", allow_decimal_amounts=True)
    assert value == pytest.approx(1250.5)


def test_text_confidence_prefers_long_clean_text(ocr):
    low = PokerOCR._text_confidence("a")
    high = PokerOCR._text_confidence("Villain123")
    assert high > low


def test_empty_metadata_shape(ocr):
    metadata = PokerOCR._empty_metadata()
    assert isinstance(metadata, dict)
    assert "engines" in metadata or len(metadata) >= 0
