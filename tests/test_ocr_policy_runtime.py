"""Câblage runtime de la politique OCR (spec 010, constat F-08).

FR-010 : le runtime charge au plus deux moteurs issus de la politique active,
jamais le catalogue entier.
FR-011 : les moteurs indisponibles sont signalés dans les métadonnées, sans lever.

Note de contrat : le normaliseur bas niveau (`_normalize_engines`) écarte depuis
toujours un moteur inconnu au lieu de lever — comportement verrouillé par
`tests/test_ocr_engine_defaults.py` et conservé ici (non-régression). Le rejet
strict d'un moteur inconnu appartient à la **déclaration de politique**
(`OCREnginePolicy`, `validate_engine_selection`), pas à une liste de config.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from src.vision.ocr import PokerOCR


def _fake_load_engines(self) -> None:
    """Rejoue le chargement sans charger de modèle : garde les métadonnées réelles."""
    self.engines = []
    self.last_metadata = {
        **self._empty_metadata(),
        "requested_engines": list(self.enabled_engines),
        "loaded_engines": [],
        "unavailable_engines": {},
        "ocr_policy": dict(self.ocr_policy) if self.ocr_policy else None,
        "policy_notes": list(self.policy_notes),
    }


@pytest.fixture(autouse=True)
def _no_real_engine_load(monkeypatch):
    # La politique est appliquée avant le chargement : on neutralise le
    # chargement réel des modèles (lent, dépendant de la machine).
    monkeypatch.setattr(PokerOCR, "_load_engines", _fake_load_engines)


def test_runtime_clamps_engines_beyond_the_site_policy():
    ocr = PokerOCR(
        enabled_engines=["rapidocr", "tesseract", "doctr"],
        mode="fallback",
        site_key="pokerstars",
    )

    assert ocr.enabled_engines == ["rapidocr", "tesseract"]
    assert len(ocr.enabled_engines) <= 2
    assert ocr.policy_notes  # la restriction est tracée, jamais silencieuse


def test_runtime_keeps_an_explicit_two_engine_override():
    ocr = PokerOCR(enabled_engines=["doctr", "rapidocr"], mode="fallback", site_key="winamax")

    # Une surcharge explicite à deux moteurs valides est honorée telle quelle.
    assert ocr.enabled_engines == ["doctr", "rapidocr"]
    assert ocr.policy_notes == []


def test_config_path_keeps_its_historical_normalization_contract():
    ocr = PokerOCR(enabled_engines=["rapidocr", "magicocr"], site_key="pokerstars")

    # Non-régression : un moteur inconnu est écarté par le normaliseur existant,
    # il ne fait pas lever le runtime (contrat inchangé de `_normalize_engines`).
    assert ocr.enabled_engines == ["rapidocr"]


def test_legacy_surya_in_a_config_is_dropped_without_raising():
    # Un config.json hérité peut encore nommer `surya` (moteur retiré, F-18) :
    # il est écarté par le normaliseur, sans lever — même contrat.
    ocr = PokerOCR(enabled_engines=["rapidocr", "surya"], site_key="pokerstars")

    assert ocr.enabled_engines == ["rapidocr"]


def test_policy_is_exposed_in_metadata():
    ocr = PokerOCR(enabled_engines=["rapidocr"], site_key="pokerstars")

    metadata = ocr.get_metadata()

    assert metadata["ocr_policy"]["site_key"] == "pokerstars"
    assert metadata["ocr_policy"]["primary"] == "rapidocr"


def test_from_config_forwards_site_key():
    ocr = PokerOCR.from_config(
        {"enabled_engines": ["rapidocr", "tesseract", "doctr"]},
        site_key="winamax",
    )

    assert ocr.enabled_engines == ["rapidocr", "tesseract"]
    assert ocr.get_metadata()["ocr_policy"]["site_key"] == "winamax"


def test_without_site_key_the_low_level_contract_is_unchanged():
    ocr = PokerOCR(enabled_engines=["rapidocr", "tesseract", "doctr"], mode="priority")

    # Hors runtime (sonde, tests), le normaliseur garde son comportement.
    assert ocr.enabled_engines == ["rapidocr", "tesseract", "doctr"]
    assert ocr.get_metadata()["ocr_policy"] is None


def test_unavailable_engines_are_reported_without_raising(monkeypatch):
    def _load_with_failure(self) -> None:
        self.engines = []
        self.last_metadata = {
            **self._empty_metadata(),
            "requested_engines": list(self.enabled_engines),
            "loaded_engines": [],
            "unavailable_engines": {"rapidocr": "model not installed"},
            "ocr_policy": dict(self.ocr_policy) if self.ocr_policy else None,
            "policy_notes": list(self.policy_notes),
        }

    monkeypatch.setattr(PokerOCR, "_load_engines", _load_with_failure)

    ocr = PokerOCR(enabled_engines=["rapidocr"], site_key="pokerstars")
    metadata = ocr.get_metadata()

    # Un moteur indisponible est signalé, jamais levé (FR-011).
    assert metadata["unavailable_engines"] == {"rapidocr": "model not installed"}
    assert metadata["loaded_engines"] == []
