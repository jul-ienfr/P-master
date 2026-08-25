"""Tests de l'ICMCalculator (Malmuth-Harville) et du risk premium tournoi."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.icm_calculator import ICMCalculator


@pytest.fixture()
def icm():
    return ICMCalculator()


def test_calculate_icm_empty_inputs(icm):
    assert icm.calculate_icm([], []) == []
    assert icm.calculate_icm([1000], []) == []


def test_calculate_icm_single_payout_is_proportional(icm):
    equities = icm.calculate_icm([750, 250], [1000.0])
    assert equities == [750.0, 250.0]


def test_calculate_icm_zero_total_chips_returns_zeros(icm):
    assert icm.calculate_icm([0, 0], [100.0, 50.0]) == [0, 0]


def test_calculate_icm_sums_to_total_prize_pool(icm):
    stacks = [5000, 3000, 2000]
    payouts = [1000.0, 600.0, 400.0]
    equities = icm.calculate_icm(stacks, payouts)
    assert len(equities) == 3
    assert sum(equities) == pytest.approx(2000.0, abs=1e-6)
    # le plus gros tapis a la plus grande équité
    assert equities[0] > equities[1] > equities[2]


def test_calculate_icm_pads_missing_paid_places_with_zero(icm):
    equities = icm.calculate_icm([5000, 3000, 2000], [1000.0])
    assert sum(equities) == pytest.approx(1000.0, abs=1e-6)


def test_get_icm_risk_premium_requires_multiple_payouts(icm):
    assert icm.get_icm_risk_premium(5000, 5000, [5000, 5000], []) == 0.0
    assert icm.get_icm_risk_premium(5000, 5000, [5000, 5000], [100.0]) == 0.0


def test_get_icm_risk_premium_positive_on_the_bubble(icm):
    all_stacks = [10000.0, 5000.0, 1000.0]
    payouts = [1000.0, 500.0, 200.0]
    premium = icm.get_icm_risk_premium(10000.0, 5000.0, all_stacks, payouts)
    assert premium > 0.0


def test_get_icm_risk_premium_infinite_when_no_gain(icm):
    # hero possède déjà tous les jetons engagés : gagner ne rapporte rien -> risque infini
    premium = icm.get_icm_risk_premium(5000.0, 0.0, [5000.0, 0.0], [100.0, 50.0])
    assert premium == 1.0


def test_adjust_gto_for_tournament_ignores_non_committing_actions(icm):
    assert icm.adjust_gto_for_tournament("FOLD", 5000, 5000, [5000, 5000], [100.0, 50.0], 100.0) == "FOLD"
    assert icm.adjust_gto_for_tournament("CHECK", 5000, 5000, [5000, 5000], [100.0, 50.0], 100.0) == "CHECK"


def test_adjust_gto_for_tournament_folds_under_extreme_pressure(icm):
    all_stacks = [8000.0, 6000.0, 4000.0, 2000.0]
    payouts = [1000.0, 400.0, 200.0]
    action = icm.adjust_gto_for_tournament(
        "CALL",
        hero_stack=6000.0,
        villain_stack=8000.0,
        all_stacks=all_stacks,
        payouts=payouts,
        pot_size=5900.0,
    )
    assert action == "FOLD"


def test_adjust_gto_for_tournament_keeps_call_when_pot_small(icm):
    all_stacks = [8000.0, 6000.0, 4000.0, 2000.0]
    payouts = [1000.0, 400.0, 200.0]
    action = icm.adjust_gto_for_tournament(
        "CALL",
        hero_stack=6000.0,
        villain_stack=8000.0,
        all_stacks=all_stacks,
        payouts=payouts,
        pot_size=100.0,
    )
    assert action == "CALL"
