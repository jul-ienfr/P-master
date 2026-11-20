"""Puissance statistique et verdict de winrate — spec 011.

Un winrate nu n'est pas une preuve : ce module exige un effectif déclaré à
l'avance et un verdict explicite.
"""

from __future__ import annotations

import pytest

from research.sample_size import (
    VERDICT_NOT_SIGNIFICANT,
    VERDICT_SIGNIFICANT_NEGATIVE,
    VERDICT_SIGNIFICANT_POSITIVE,
    VERDICT_UNDERPOWERED,
    VERDICT_UNMEASURED,
    classify_winrate,
    required_hands,
)


def test_required_hands_matches_formula():
    # (1.96 * 90 / 10)^2 = 311.17... → 312
    assert required_hands(90.0, 10.0) == 312


def test_required_hands_is_monotonic_in_target_width():
    coarse = required_hands(90.0, 20.0)
    fine = required_hands(90.0, 5.0)
    assert fine > coarse


def test_required_hands_zero_sigma_needs_no_hands():
    assert required_hands(0.0, 10.0) == 0


def test_required_hands_rejects_non_positive_target():
    with pytest.raises(ValueError):
        required_hands(90.0, 0.0)


def test_verdict_significant_positive():
    verdict = classify_winrate(5.0, (2.0, 8.0), 4000, 3112)
    assert verdict.verdict == VERDICT_SIGNIFICANT_POSITIVE
    assert verdict.significant is True
    assert verdict.protocol_complete is True


def test_verdict_significant_negative():
    verdict = classify_winrate(-6.0, (-9.0, -3.0), 4000, 3112)
    assert verdict.verdict == VERDICT_SIGNIFICANT_NEGATIVE
    assert verdict.significant is True


def test_verdict_not_significant_containing_zero():
    verdict = classify_winrate(0.1, (-50.0, 50.0), 4000, 3112)
    assert verdict.verdict == VERDICT_NOT_SIGNIFICANT
    assert verdict.significant is False


def test_verdict_underpowered_when_below_required():
    verdict = classify_winrate(1.0, (-40.0, 42.0), 100, 3112)
    assert verdict.verdict == VERDICT_UNDERPOWERED
    assert verdict.protocol_complete is False
    assert "sample_below_required" in verdict.reasons


def test_verdict_unmeasured_without_hands():
    verdict = classify_winrate(None, None, 0, 0)
    assert verdict.verdict == VERDICT_UNMEASURED
    assert verdict.protocol_complete is False
    assert "no_evaluable_hands" in verdict.reasons


def test_protocol_incomplete_when_policy_is_not_production():
    verdict = classify_winrate(5.0, (2.0, 8.0), 4000, 3112, is_production_policy=False)
    assert verdict.protocol_complete is False
    assert "policy_not_production" in verdict.reasons


def test_protocol_complete_requires_sufficient_sample_and_ci():
    assert classify_winrate(3.0, (1.0, 5.0), 3112, 3112).protocol_complete is True
    assert classify_winrate(3.0, (1.0, 5.0), 3111, 3112).protocol_complete is False


def test_ci_bounds_are_normalized_when_reversed():
    verdict = classify_winrate(5.0, (8.0, 2.0), 4000, 3112)
    assert verdict.verdict == VERDICT_SIGNIFICANT_POSITIVE
