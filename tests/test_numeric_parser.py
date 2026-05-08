from src.vision.numeric_parser import NumericParser
from src.vision.numeric_validator import NumericValidator


def test_numeric_parser_accepts_space_thousands_and_decimals():
    parser = NumericParser()

    parsed = parser.parse("Pot : 1 250.25")

    assert parsed.valid is True
    assert parsed.value == 1250.25


def test_numeric_parser_rejects_non_numeric_text():
    parser = NumericParser()

    parsed = parser.parse("All In")

    assert parsed.valid is False
    assert parsed.reject_reason == "parse_rejected"


def test_numeric_validator_blocks_implausible_pot_drop():
    validator = NumericValidator()

    result = validator.validate_pot(2500.0, 200.0)

    assert result.valid is False
    assert result.accepted_value == 2500.0
    assert result.reject_reason == "implausible_pot_drop"
