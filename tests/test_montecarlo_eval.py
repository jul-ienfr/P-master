"""Tests de l'évaluateur de mains MonteCarlo legacy (pur, haute valeur)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from poker.decisionmaker.montecarlo_python import MonteCarlo


@pytest.fixture
def mc():
    return MonteCarlo()


def test_create_card_deck_has_52_unique_cards(mc):
    deck = mc.create_card_deck()
    assert len(deck) == 52
    assert len(set(deck)) == 52
    assert "AH" in deck and "2C" in deck and "TD" in deck


def test_get_two_short_notation_suited_pairs_offsuit(mc):
    suited = mc.get_two_short_notation(["AH", "KH"])
    assert suited == ("AKS", "KAS")

    offsuit = mc.get_two_short_notation(["AS", "KD"])
    assert offsuit == ("AKO", "KAO")

    pair_default = mc.get_two_short_notation(["AS", "AD"])
    assert pair_default == ("AA", "AA")

    pair_flagged = mc.get_two_short_notation(["AS", "AD"], add_O_to_pairs=True)
    assert pair_flagged == ("AAO", "AAO")


def test_eval_best_hand_picks_winner_and_type(mc):
    hands = [
        ["2C", "3D", "4H", "5S", "6C"],          # suite 6-high... battue par la paire ? Non : straight > paire
        ["AC", "AD", "4H", "5S", "9C"],           # paire d'as
    ]
    winner, hand_type = mc.eval_best_hand(hands)
    assert winner == hands[0]
    assert hand_type == "Straight"


HAND_CASES = [
    (["AC", "KC", "QH", "JS", "9D"], ((1,), ), "HighCard"),
    (["AC", "AD", "KH", "QS", "9D"], ((2, 1, 1, 1),), "Pair"),
    (["AC", "AD", "KH", "KS", "9D"], ((2, 2, 1),), "TwoPair"),
    (["AC", "AD", "AH", "KS", "9D"], ((3, 1, 1),), "ThreeOfAKind"),
    (["AC", "AD", "AH", "AS", "9D"], ((4,),), "FoufOfAKind"),
    (["AC", "AD", "AH", "KD", "KS"], ((3, 2),), "FullHouse"),
    (["AC", "KC", "QC", "JC", "9C", "2H", "3D"], None, "Flush"),
    (["2H", "3D", "4C", "5S", "AD", "KH", "2C"], None, "Straight"),
    (["2C", "3C", "4C", "5C", "6C", "KH", "AD"], None, "StraightFlush"),
]


@pytest.mark.parametrize("hand,_score,expected_type", HAND_CASES)
def test_calc_score_hand_types(mc, hand, _score, expected_type):
    score, card_ranks, hand_type = mc.calc_score(hand)
    assert hand_type == expected_type, f"{hand}: obtenu {hand_type}"


def test_calc_score_straight_flush_beats_flush(mc):
    _, _, sf_type = mc.calc_score(["2C", "3C", "4C", "5C", "6C"])
    _, _, f_type = mc.calc_score(["AC", "KC", "QC", "JC", "9C"])
    assert sf_type == "StraightFlush"
    assert f_type == "Flush"


def test_calc_score_wheel_is_straight(mc):
    # A2345 : la roue doit être détectée via l'ajustement -1.
    score, _, hand_type = mc.calc_score(["AH", "2D", "3C", "4S", "5D"])
    assert hand_type == "Straight"
