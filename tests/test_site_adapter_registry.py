"""Registre d'adaptateurs de site, conformité et fixtures (spec 005, constat F-06).

Ces tests verrouillent ce que le constat F-06 demandait :

- deux sites livrés (PokerStars, Winamax) résolus par un registre ;
- une clé inconnue lève, jamais de repli silencieux ;
- le format de montants est déclaré **une fois** (adaptateur) et consommé par le
  parseur, vérifié par des fixtures par site ;
- les limites d'action bornent une taille de mise ;
- la résolution de site depuis un titre est déterministe.

La falsification est incluse : un adaptateur dont le format contredit ses
fixtures doit faire échouer le test de conformité.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.vision.action_limits import ActionLimits, validate_bet_amount
from src.vision.site_adapter import (
    SITE_ADAPTERS,
    WinamaxAdapter,
    available_site_keys,
    get_active_adapter,
    resolve_site_from_title,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "site_amounts"


# --- Registre -----------------------------------------------------------------


def test_both_sites_are_delivered():
    assert set(available_site_keys()) >= {"pokerstars", "winamax"}


def test_get_active_adapter_resolves_winamax():
    adapter = get_active_adapter("winamax")

    assert adapter.site_key == "winamax"
    assert adapter.display_name == "Winamax"
    assert isinstance(adapter, WinamaxAdapter)


def test_get_active_adapter_unknown_key_raises():
    with pytest.raises(ValueError, match="Unsupported site adapter"):
        get_active_adapter("partypoker")


def test_get_active_adapter_empty_key_falls_back_to_default():
    adapter = get_active_adapter("")

    assert adapter.site_key == "pokerstars"


def test_winamax_window_metadata_is_not_invented():
    """Classe et process Winamax non observés : None explicite, pas une valeur inventée."""
    profile = get_active_adapter("winamax").window_profile

    assert profile.window_class is None
    assert profile.process_name is None
    assert profile.matches_title("Winamax - Table 1")


# --- Résolution de site depuis un titre --------------------------------------


def test_resolve_site_from_title_is_deterministic():
    assert resolve_site_from_title("PokerStars - NLHE 6-max") == "pokerstars"
    assert resolve_site_from_title("Winamax - Table Expresso") == "winamax"


def test_resolve_site_from_title_unknown_returns_default():
    assert resolve_site_from_title("Some Other Room", default=None) is None
    assert resolve_site_from_title("", default="pokerstars") == "pokerstars"


# --- Conformité du contrat ----------------------------------------------------


@pytest.mark.parametrize("site_key", sorted(SITE_ADAPTERS))
def test_every_adapter_satisfies_the_contract(site_key):
    adapter = get_active_adapter(site_key)

    assert adapter.site_key == site_key
    assert adapter.display_name
    assert adapter.theme.site_key == site_key
    assert isinstance(adapter.amount_format.thousands_separators, tuple)
    assert adapter.action_limits.min_bet_bb >= 0
    assert isinstance(adapter.preset_manifests(), tuple)
    assert adapter.amount_parser() is not None


@pytest.mark.parametrize("site_key", sorted(SITE_ADAPTERS))
def test_manifests_are_empty_without_raising_when_absent(site_key):
    """Un site sans manifeste calibré retourne un tuple vide, sans lever."""
    adapter = get_active_adapter(site_key)

    assert all(isinstance(path, Path) for path in adapter.preset_manifests())


# --- Fixtures de montants -----------------------------------------------------


def _load_cases(site_key: str) -> list[dict]:
    payload = json.loads((FIXTURES_DIR / f"{site_key}.json").read_text(encoding="utf-8"))
    assert payload["site_key"] == site_key
    return payload["cases"]


@pytest.mark.parametrize("site_key", sorted(SITE_ADAPTERS))
def test_fixture_amounts_parse_as_expected(site_key):
    parser = get_active_adapter(site_key).amount_parser()

    for case in _load_cases(site_key):
        result = parser.parse(case["text"])
        expected = case["expected"]
        if expected is None:
            assert result.valid is False, f"{site_key}: {case['text']!r} aurait dû être rejeté"
        else:
            assert result.valid is True, f"{site_key}: {case['text']!r} aurait dû être accepté"
            assert result.value == pytest.approx(expected), f"{site_key}: {case['text']!r}"


def test_format_contradicting_fixtures_fails_conformance():
    """Falsification : un format décimal face à des fixtures entières échoue."""
    # PokerStars play money interdit les décimales ; un parseur qui les accepte
    # ne reproduit plus la fixture « 12,5 » (attendue rejetée).
    from src.vision.numeric_parser import NumericParser

    wrong = NumericParser(
        allow_decimal_amounts=True, thousands_separators=(" ",), decimal_separators=(",", ".")
    )
    assert wrong.parse("12,5").valid is True  # le mauvais format accepte
    correct = get_active_adapter("pokerstars", real_money=False).amount_parser()
    assert correct.parse("12,5").valid is False  # le bon rejette


# --- Limites d'action ---------------------------------------------------------


def test_validate_bet_amount_rejects_below_minimum():
    limits = ActionLimits(min_bet_bb=2.0, allow_decimals=True)

    verdict = validate_bet_amount(1.0, limits)

    assert verdict.accepted is False
    assert verdict.reason == "below_min_bet"


def test_validate_bet_amount_accepts_minimum():
    limits = ActionLimits(min_bet_bb=2.0, allow_decimals=True)

    verdict = validate_bet_amount(2.0, limits)

    assert verdict.accepted is True
    assert verdict.value == 2.0
    assert verdict.adjusted is False


def test_validate_bet_amount_accepts_all_in():
    limits = ActionLimits(min_bet_bb=2.0, allow_decimals=False)

    verdict = validate_bet_amount(0.5, limits, is_all_in=True)

    assert verdict.accepted is True
    assert verdict.value == 0.5


def test_validate_bet_amount_adjusts_decimals():
    limits = ActionLimits(min_bet_bb=1.0, allow_decimals=False)

    verdict = validate_bet_amount(3.7, limits)

    assert verdict.accepted is True
    assert verdict.adjusted is True
    assert verdict.value == 4.0


def test_validate_bet_amount_rejects_invalid():
    limits = ActionLimits()

    assert validate_bet_amount(None, limits).reason == "invalid_amount"
    assert validate_bet_amount(float("nan"), limits).reason == "invalid_amount"
    assert validate_bet_amount(-1.0, limits).reason == "invalid_amount"


# --- Non-régression PokerStars ------------------------------------------------


def test_pokerstars_default_behaviour_unchanged():
    adapter = get_active_adapter("pokerstars", theme_key="dark-fr", real_money=True)

    assert adapter.site_key == "pokerstars"
    assert adapter.amount_format.allow_decimals is True
    assert adapter.amount_format.thousands_separators == (" ",)
    assert all("pokerstars" in str(p).lower() for p in adapter.preset_manifests())


def test_pokerstars_play_money_has_no_decimals():
    adapter = get_active_adapter("pokerstars", real_money=False)

    assert adapter.amount_format.allow_decimals is False
    assert adapter.amount_format.decimal_separators == ()
