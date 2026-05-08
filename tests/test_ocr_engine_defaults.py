import numpy as np

from src.vision import ocr as ocr_module
from src.vision.temporal_ocr import TemporalOCRFilter


def test_default_requested_engines_prioritize_rapidocr(monkeypatch):
    monkeypatch.setattr(ocr_module, "RAPIDOCR_AVAILABLE", True)
    monkeypatch.setattr(ocr_module, "SURYA_AVAILABLE", True)
    monkeypatch.setattr(ocr_module, "EASYOCR_AVAILABLE", True)
    monkeypatch.setattr(ocr_module, "TESSERACT_AVAILABLE", True)
    monkeypatch.setattr(ocr_module, "DOCTR_AVAILABLE", False)

    assert ocr_module.PokerOCR._default_requested_engines() == [
        "rapidocr",
        "easyocr",
        "tesseract",
    ]


def test_engine_normalization_keeps_supported_order():
    ocr = ocr_module.PokerOCR(
        enabled_engines=["rapidocr", "rapidocr", "easyocr", "unknown", "tesseract"],
        mode="priority",
        parallel=False,
    )

    assert ocr.enabled_engines == ["rapidocr", "easyocr", "tesseract"]


def test_temporal_filter_defaults_include_rapidocr(monkeypatch):
    monkeypatch.setattr(ocr_module, "RAPIDOCR_AVAILABLE", True)
    monkeypatch.setattr(ocr_module, "EASYOCR_AVAILABLE", True)
    filter_engine = TemporalOCRFilter()
    assert filter_engine.ocr_engine.enabled_engines[:2] == [
        "rapidocr",
        "easyocr",
    ]


def test_parse_amount_ignores_text_prefixes():
    assert ocr_module.PokerOCR.parse_amount("Pot : 39 690") == 39690.0
    assert ocr_module.PokerOCR.parse_amount("Pot 850") == 850.0


def test_parse_amount_play_money_rejects_decimal_separators():
    assert ocr_module.PokerOCR.parse_amount("Pot : 39 690", thousands_separators=[" "]) == 39690.0
    assert ocr_module.PokerOCR.parse_amount("Pot : 39,690", thousands_separators=[" "]) is None
    assert ocr_module.PokerOCR.parse_amount("Pot : 39.690", thousands_separators=[" "]) is None
    assert ocr_module.PokerOCR.parse_amount("Pot : 12,5", thousands_separators=[" "]) is None


def test_parse_amount_real_money_supports_space_thousands_and_decimals():
    assert (
        ocr_module.PokerOCR.parse_amount(
            "Pot : 1 250,25",
            allow_decimal_amounts=True,
            thousands_separators=[" "],
            decimal_separators=[","],
        )
        == 1250.25
    )
    assert (
        ocr_module.PokerOCR.parse_amount(
            "Pot : 1 250.25",
            allow_decimal_amounts=True,
            thousands_separators=[" "],
            decimal_separators=["."],
        )
        == 1250.25
    )
    assert (
        ocr_module.PokerOCR.parse_amount(
            "Pot : 1 250,25",
            allow_decimal_amounts=True,
            thousands_separators=[" "],
            decimal_separators=["."],
        )
        is None
    )


def test_from_config_auto_accepts_integer_and_decimal_amounts(monkeypatch):
    monkeypatch.setattr(ocr_module.PokerOCR, "_load_engines", lambda self: None)

    ocr = ocr_module.PokerOCR.from_config(
        {
            "amount_format": {
                "allow_decimals": True,
                "thousands_separators": ["space"],
                "decimal_separators": [",", "."],
            }
        }
    )

    assert ocr._parse_amount_with_current_format("Pot : 39 690") == 39690.0
    assert ocr._parse_amount_with_current_format("Pot : 1 250,25") == 1250.25
    assert ocr._parse_amount_with_current_format("Pot : 1 250.25") == 1250.25


def test_parse_amount_rejects_non_numeric_words():
    assert ocr_module.PokerOCR.parse_amount("All Ir") is None
    assert ocr_module.PokerOCR.parse_amount("Nick Deb01") is None


def test_read_and_parse_amount_stops_after_first_valid_engine(monkeypatch):
    monkeypatch.setattr(ocr_module.PokerOCR, "_load_engines", lambda self: None)

    class FakeAmountEngine:
        def __init__(self, name, response):
            self.name = name
            self.response = response
            self.calls = 0

        def read_text(self, image_crop):
            del image_crop
            self.calls += 1
            return self.response

    ocr = ocr_module.PokerOCR(enabled_engines=["rapidocr", "easyocr"], mode="fallback", parallel=True)
    first = FakeAmountEngine("rapidocr", "$42")
    second = FakeAmountEngine("easyocr", "$99")
    ocr.engines = [first, second]

    assert ocr.read_and_parse_amount(np.zeros((2, 2, 3), dtype=np.uint8)) == 42.0
    assert first.calls == 1
    assert second.calls == 0
