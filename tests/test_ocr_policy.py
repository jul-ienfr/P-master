"""Politique OCR par site (spec 010, constat F-08).

La cible est « un moteur principal + un fallback maximum ». Ces tests verrouillent
la règle : au plus deux moteurs, tous supportés, un rejet explicite sinon, et une
politique déclarée par site.
"""

from __future__ import annotations

import pytest

from src.vision.ocr import SUPPORTED_OCR_ENGINES
from src.vision.ocr_policy import (
    MAX_ENGINES,
    SITE_OCR_POLICIES,
    SUPPORTED_ENGINES,
    OCREnginePolicy,
    clamp_to_policy,
    policy_for_site,
    validate_engine_selection,
)


def test_default_policy_loads_at_most_two_engines():
    policy = policy_for_site("pokerstars")

    assert policy.engines() == ["rapidocr", "tesseract"]
    assert len(policy.engines()) <= MAX_ENGINES


def test_policy_engines_are_all_supported():
    for site_key in SITE_OCR_POLICIES:
        policy = policy_for_site(site_key)
        assert all(engine in SUPPORTED_ENGINES for engine in policy.engines())


def test_unknown_site_falls_back_to_default_policy():
    policy = policy_for_site("site-inexistant")

    assert policy.engines() == ["rapidocr", "tesseract"]
    assert len(policy.engines()) <= MAX_ENGINES


def test_engine_catalog_is_aligned_with_ocr_module():
    # Deux constantes nomment le même catalogue : elles ne doivent pas diverger.
    assert tuple(SUPPORTED_ENGINES) == tuple(SUPPORTED_OCR_ENGINES)


def test_policy_rejects_unknown_primary():
    with pytest.raises(ValueError, match="inconnu"):
        OCREnginePolicy(site_key="x", primary="magicocr")


def test_policy_rejects_unknown_fallback():
    with pytest.raises(ValueError, match="inconnu"):
        OCREnginePolicy(site_key="x", primary="rapidocr", fallback="magicocr")


def test_identical_fallback_is_dropped():
    policy = OCREnginePolicy(site_key="x", primary="rapidocr", fallback="rapidocr")

    assert policy.fallback is None
    assert policy.engines() == ["rapidocr"]


def test_validate_selection_rejects_more_than_two():
    with pytest.raises(ValueError, match="maximum 2"):
        validate_engine_selection(["rapidocr", "tesseract", "doctr"])


def test_validate_selection_rejects_unknown_engine():
    with pytest.raises(ValueError, match="inconnu"):
        validate_engine_selection(["rapidocr", "notreal"])


def test_validate_selection_dedupes_and_keeps_order():
    assert validate_engine_selection(["rapidocr", "rapidocr", "tesseract"]) == [
        "rapidocr",
        "tesseract",
    ]


def test_unavailable_primary_falls_back():
    policy = policy_for_site("pokerstars")

    remaining = policy.with_unavailable({"rapidocr"})

    assert remaining == ["tesseract"]


def test_both_unavailable_yields_empty_selection():
    policy = policy_for_site("pokerstars")

    assert policy.with_unavailable({"rapidocr", "tesseract"}) == []


def test_clamp_keeps_only_policy_engines_in_policy_order():
    policy = policy_for_site("pokerstars")

    # Une sélection large est ramenée à la politique du site, dans son ordre.
    clamped = clamp_to_policy(["doctr", "tesseract", "rapidocr"], policy)

    assert clamped == ["rapidocr", "tesseract"]


def test_clamp_never_exceeds_max_engines():
    policy = OCREnginePolicy(site_key="x", primary="rapidocr", fallback="tesseract")

    clamped = clamp_to_policy(["rapidocr", "tesseract", "doctr"], policy)

    assert len(clamped) <= MAX_ENGINES
