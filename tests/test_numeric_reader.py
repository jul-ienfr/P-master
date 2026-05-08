import numpy as np

from src.vision.numeric_preprocessing import preprocess_numeric_variants
from src.vision.numeric_reader import NumericReader
from src.vision.numeric_validator import NumericValidator


def test_numeric_preprocessing_returns_multiple_named_variants():
    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    variants = preprocess_numeric_variants(crop)

    assert len(variants) >= 5
    assert variants[0][0] == "original"
    assert all(image.size > 0 for _, image in variants)


def test_numeric_reader_keeps_best_confident_candidate():
    class FakeOCR:
        def __init__(self):
            self._call_count = 0

        def read_and_parse_amount(self, image_crop):
            del image_crop
            self._call_count += 1
            return 1250.0 if self._call_count >= 2 else None

        def get_metadata(self):
            if self._call_count >= 2:
                return {
                    "selected_engine": "rapidocr",
                    "selected_text": "1 250",
                    "selected_confidence": 0.91,
                }
            return {
                "selected_engine": "rapidocr",
                "selected_text": "",
                "selected_confidence": 0.0,
            }

    reader = NumericReader(FakeOCR())
    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    result = reader.read_amount("pot", crop)

    assert result.selected_value == 1250.0
    assert result.evidence.selected_value == 1250.0
    assert result.evidence.selected_candidate is not None
    assert result.evidence.selected_candidate.variant in {"gray_normalized", "upscaled_x2", "threshold_otsu", "threshold_adaptive", "threshold_inverted", "denoised"}


def test_numeric_reader_rejects_implausible_pot_drop_and_keeps_previous_value():
    class FakeOCR:
        def read_and_parse_amount(self, image_crop):
            del image_crop
            return 100.0

        def get_metadata(self):
            return {
                "selected_engine": "rapidocr",
                "selected_text": "100",
                "selected_confidence": 0.95,
            }

    reader = NumericReader(FakeOCR())
    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    result = reader.read_amount("pot", crop, previous_value=5000.0)

    assert result.selected_value == 5000.0
    assert result.evidence.state == "quarantined"
    assert result.evidence.rejection_reason == "implausible_pot_drop"


def test_numeric_reader_promotes_value_to_confirmed_after_repeated_reads():
    class FakeOCR:
        def read_and_parse_amount(self, image_crop):
            del image_crop
            return 1800.0

        def get_metadata(self):
            return {
                "selected_engine": "rapidocr",
                "selected_text": "1 800",
                "selected_confidence": 0.95,
            }

    reader = NumericReader(FakeOCR())
    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    first = reader.read_amount("pot", crop, previous_value=0.0)
    second = reader.read_amount("pot", crop, previous_value=first.selected_value or 0.0)

    assert first.evidence.state == "tentative"
    assert second.evidence.state == "confirmed"


def test_numeric_validator_allows_stack_to_drop_without_pot_drop_rejection():
    validator = NumericValidator()

    result = validator.validate("hero_stack", previous_value=5000.0, candidate_value=100.0)

    assert result.valid is True
    assert result.accepted_value == 100.0


def test_numeric_validator_keeps_pot_drop_rejection():
    validator = NumericValidator()

    result = validator.validate("pot", previous_value=5000.0, candidate_value=100.0)

    assert result.valid is False
    assert result.accepted_value == 5000.0
    assert result.reject_reason == "implausible_pot_drop"


def test_numeric_validator_rejects_invalid_bet_values():
    validator = NumericValidator()

    negative = validator.validate("bet", previous_value=0.0, candidate_value=-1.0)
    too_large = validator.validate("bet", previous_value=0.0, candidate_value=200001.0)

    assert negative.valid is False
    assert negative.reject_reason == "invalid_numeric_value"
    assert too_large.valid is False
    assert too_large.reject_reason == "bet_too_large"
