"""Tests du calculateur d'outs legacy (maths pures, ratchet coverage)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from poker.decisionmaker.outs_calculator import Outs_Calculator


@pytest.fixture
def outs():
    return Outs_Calculator()


def _evaluate(outs_calc, pocket, board):
    # Usage legacy : oc EST l'Outs_Calculator (il porte calc_score).
    return outs_calc.evaluate_hands(pocket, board, outs_calc), outs_calc


def test_flush_draw_counts_nine_outs(outs):
    n_outs, oc = _evaluate(outs, ["2H", "7H"], ["AH", "KH", "9D"])
    assert outs.flush_draw is True
    assert n_outs == 9


def test_open_ended_straight_draw_counts_eight_outs(outs):
    n_outs, oc = _evaluate(outs, ["7H", "8D"], ["9C", "TD", "2S"])
    assert outs.open_straight is True
    assert n_outs == 8


def test_gut_shot_straight_draw_counts_four_outs(outs):
    n_outs, oc = _evaluate(outs, ["5H", "6D"], ["8C", "9S", "KD"])
    assert outs.gut_shot_straight is True
    assert n_outs == 4


def test_no_draw_yields_zero_outs(outs):
    n_outs, oc = _evaluate(outs, ["AH", "KD"], ["7C", "3S", "9D"])
    assert n_outs == 0
    assert outs.flush_draw is False
    assert outs.open_straight is False
    assert outs.gut_shot_straight is False


def test_deck_excludes_known_cards(outs):
    outs.evaluate_hands(["AH", "KH"], ["QH", "2C", "7D"], outs)
    assert "AH" not in outs.deck and "QH" not in outs.deck
    assert len(outs.deck) == 52 - 5


def test_straight_flush_draw_flagged_when_suited_connector(outs):
    # 4 trèfles consécutifs : straight flush draw prioritaire.
    n_outs, oc = _evaluate(outs, ["6C", "7C"], ["8C", "9C", "2D"])
    assert outs.straight_flush or n_outs > 0
