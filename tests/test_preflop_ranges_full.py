"""Tests des ranges preflop GTO (src/bot/preflop_ranges.py) et du consensus numérique."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.preflop_ranges import PreflopManager
from src.vision.numeric_consensus import NumericConsensus


@pytest.fixture()
def manager():
    return PreflopManager()


def test_get_hero_range_open_by_position(manager):
    assert manager.get_hero_range("utg") == manager.rfi_ranges["UTG"]
    assert manager.get_hero_range("BTN") == manager.rfi_ranges["BTN"]
    # position inconnue -> range BTN large par défaut
    assert manager.get_hero_range("middle") == manager.rfi_ranges["BTN"]


def test_get_hero_range_facing_raise(manager):
    assert manager.get_hero_range("CO", facing_raise=True) == "TT+, AQs+, AKo"
    # big blind : défense large
    assert manager.get_hero_range("BB", facing_raise=True) == manager.defense_ranges["BB"]


def test_get_villain_range_actions(manager):
    assert manager.get_villain_range("HJ", action="OPEN") == manager.rfi_ranges["HJ"]
    assert manager.get_villain_range("UTG", action="3BET") == "JJ+, AQs+, AKo"
    assert manager.get_villain_range("UTG", action="donk") == manager.rfi_ranges["BTN"]


def test_numeric_consensus_confirms_repeated_value():
    consensus = NumericConsensus(history_size=3)
    first = consensus.update(120.0)
    assert first.state == "tentative"
    second = consensus.update(120.5)  # dans la tolérance
    assert second.state == "confirmed"
    assert second.support == 2
    third = consensus.update(None)
    assert third.state == "stale"
    assert third.value == pytest.approx(120.5)


def test_numeric_consensus_empty_history_returns_empty_state():
    consensus = NumericConsensus()
    result = consensus.update(None)
    assert result.state == "empty"
    assert result.value is None

    # reset vide l'historique
    consensus.update(50.0)
    consensus.reset()
    assert consensus.update(None).state == "empty"



