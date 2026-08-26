# -*- coding: utf-8 -*-
"""Tests du validateur numérique (src/vision/numeric_validator.py) : routage et gardes."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.numeric_validator import NumericValidator


@pytest.fixture()
def validator():
    return NumericValidator()


def test_validate_routes_by_field_name(validator):
    assert validator.validate("POT_AREA", 100.0, 150.0).valid
    assert validator.validate("player_stack", 100.0, 150.0).valid
    assert validator.validate("bet_size", 100.0, 150.0).valid
    assert validator.validate("mise_adverse", 100.0, 150.0).valid
    # champ inconnu -> validate_amount
    result = validator.validate("unknown_field", 100.0, -1.0)
    assert result.reject_reason == "invalid_numeric_value"


def test_validate_pot_rejects_suspicious_zero_regression(validator):
    result = validator.validate_pot(500.0, 0.0)
    assert result.valid is False
    assert result.reject_reason == "suspicious_zero_regression"
    assert result.accepted_value == 500.0


def test_validate_pot_accepts_zero_from_zero(validator):
    result = validator.validate_pot(0.0, 0.0)
    assert result.valid is True and result.accepted_value == 0.0


def test_validate_pot_rejects_implausible_drop(validator):
    result = validator.validate_pot(1000.0, 200.0)
    assert result.reject_reason == "implausible_pot_drop"
    # chute plausible (> 50%) acceptée (nouvelle main)
    ok = validator.validate_pot(1000.0, 600.0)
    assert ok.valid is True


def test_validate_pot_rejects_oversized_values(validator):
    result = validator.validate_pot(0.0, 300000.0)
    assert result.reject_reason == "pot_too_large"


def test_validate_pot_handles_missing_and_invalid_candidates(validator):
    missing = validator.validate_pot(100.0, None)
    assert missing.reject_reason == "missing_candidate"
    invalid = validator.validate_pot("garbage", object())
    assert invalid.reject_reason == "invalid_numeric_value"
    negative = validator.validate_pot(100.0, -5.0)
    assert negative.reject_reason == "invalid_numeric_value"


def test_validate_stack_is_previous_agnostic(validator):
    assert validator.validate_stack(99999.0, 50.0).valid is True
    too_big = validator.validate_stack(0.0, 500000.0)
    assert too_big.reject_reason == "stack_too_large"
    assert validator.validate_stack(0.0, None).reject_reason == "missing_candidate"


def test_validate_bet_rejects_negative_and_oversized(validator):
    assert validator.validate_bet(0.0, -1.0).reject_reason == "invalid_numeric_value"
    assert validator.validate_bet(0.0, 999999.0).reject_reason == "bet_too_large"
    assert validator.validate_bet(0.0, 75.0).accepted_value == 75.0


def test_validate_amount_generic_rules(validator):
    assert validator.validate_amount(0.0, 42.0).valid is True
    assert validator.validate_amount(0.0, -3.0).reject_reason == "invalid_numeric_value"
    assert validator.validate_amount(0.0, 250000.0).reject_reason == "amount_too_large"
    assert validator.validate_amount(0.0, None).reject_reason == "missing_candidate"
