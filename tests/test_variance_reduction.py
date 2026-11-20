"""Estimateurs à variance réduite (AIVAT C11 / MIVAT C27) — spec 011.

Vérifie les deux propriétés qui font la valeur d'un estimateur : il est **sans
biais** (son espérance égale celle de la moyenne brute) et il **réduit la
variance** quand la variable de contrôle est corrélée au résultat.
"""

from __future__ import annotations

import math
from random import Random

import pytest

from research.variance_reduction import (
    aivat_estimate,
    control_variate_estimate,
    mivat_estimate,
)


def _synthetic(rng: Random, n: int, *, noise: float = 1.0) -> tuple[list[float], list[float]]:
    """Résultat et contrôle corrélés, de moyenne de contrôle connue (0)."""
    payoffs: list[float] = []
    controls: list[float] = []
    for _ in range(n):
        control = rng.gauss(0.0, 1.0)
        payoff = 0.7 * control + rng.gauss(0.0, noise)
        controls.append(control)
        payoffs.append(payoff)
    return payoffs, controls


def test_estimator_is_unbiased_on_known_truth():
    """L'IC de l'estimateur couvre la vérité au taux nominal (sans biais)."""
    rng = Random(20261120)
    truth = 0.42
    covered = 0
    trials = 400
    for _ in range(trials):
        payoffs = [truth + rng.gauss(0.0, 1.0) for _ in range(200)]
        controls = [rng.gauss(0.0, 1.0) for _ in range(200)]
        estimate = control_variate_estimate(payoffs, controls, mean_control=0.0)
        low = estimate.reduced_bb100 - estimate.reduced_ci95_bb100
        high = estimate.reduced_bb100 + estimate.reduced_ci95_bb100
        if low <= truth * 50.0 <= high:
            covered += 1
    # Couverture nominale 95 % : large bande pour éviter un test instable.
    assert covered / trials >= 0.90


def test_estimator_reduces_variance_on_correlated_control():
    rng = Random(7)
    payoffs, controls = _synthetic(rng, 4000)
    estimate = control_variate_estimate(payoffs, controls, mean_control=0.0)
    assert estimate.variance_reduction > 0.0
    assert estimate.reduced_std_bb < estimate.raw_std_bb
    assert estimate.reduced_ci95_bb100 < estimate.raw_ci95_bb100


def test_constant_control_gives_raw_mean():
    """Contrôle constant : aucune réduction inventée, estimation = moyenne brute."""
    payoffs = [1.0, -2.0, 3.0, 0.5, -1.0]
    controls = [5.0] * len(payoffs)
    estimate = control_variate_estimate(payoffs, controls, mean_control=5.0)
    assert estimate.beta == pytest.approx(0.0)
    assert estimate.reduced_bb100 == pytest.approx(estimate.raw_bb100)
    assert estimate.variance_reduction == pytest.approx(0.0)


def test_perfect_control_gives_zero_variance():
    """Contrôle parfait (centré) : variance nulle, estimation = moyenne brute."""
    payoffs = [1.0, -2.0, 3.0, 0.5, -1.0]
    mean = sum(payoffs) / len(payoffs)
    controls = [payoff - mean for payoff in payoffs]
    estimate = control_variate_estimate(payoffs, controls, mean_control=0.0)
    assert estimate.reduced_std_bb == pytest.approx(0.0, abs=1e-12)
    assert estimate.variance_reduction == pytest.approx(1.0)
    assert estimate.reduced_bb100 == pytest.approx(estimate.raw_bb100)


def test_optimal_beta_beats_unit_beta():
    rng = Random(99)
    payoffs, controls = _synthetic(rng, 3000, noise=0.5)
    optimal = control_variate_estimate(payoffs, controls, mean_control=0.0, beta="optimal")
    unit = control_variate_estimate(payoffs, controls, mean_control=0.0, beta=1.0)
    assert optimal.reduced_std_bb <= unit.reduced_std_bb + 1e-9


def test_estimated_control_mean_is_flagged_not_unbiased():
    rng = Random(11)
    payoffs, controls = _synthetic(rng, 100)
    flagged = control_variate_estimate(payoffs, controls, mean_control=None)
    assert flagged.unbiased_inputs is False
    known = control_variate_estimate(payoffs, controls, mean_control=0.0)
    assert known.unbiased_inputs is True


def test_aivat_uses_centered_control():
    rng = Random(3)
    payoffs, controls = _synthetic(rng, 500)
    aivat = aivat_estimate(payoffs, controls)
    assert aivat.mean_control == 0.0
    assert aivat.beta == pytest.approx(1.0)
    assert aivat.unbiased_inputs is True


def test_mivat_gives_one_unbiased_estimate_per_player():
    rng = Random(2026)
    players = [0, 1, 2]
    payoffs: dict[int, list[float]] = {player: [] for player in players}
    controls: dict[int, list[float]] = {player: [] for player in players}
    for _ in range(800):
        draws = {player: rng.gauss(0.0, 1.0) for player in players}
        for player in players:
            controls[player].append(draws[player])
            payoffs[player].append(0.5 * draws[player] + rng.gauss(0.0, 0.8))

    estimates = mivat_estimate(payoffs, controls, mean_controls={0: 0.0, 1: 0.0, 2: 0.0})
    assert set(estimates) == set(players)
    for _player, estimate in estimates.items():
        assert estimate.unbiased_inputs is True
        assert estimate.variance_reduction > 0.0
        assert estimate.n == 800


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        control_variate_estimate([1.0, 2.0], [1.0], mean_control=0.0)


def test_unknown_beta_raises():
    with pytest.raises(ValueError):
        control_variate_estimate([1.0, 2.0], [1.0, 2.0], mean_control=0.0, beta="bogus")


def test_empty_inputs_return_zeroed_estimate():
    estimate = control_variate_estimate([], [], mean_control=0.0)
    assert estimate.n == 0
    assert estimate.raw_bb100 == 0.0
    assert estimate.reduced_ci95_bb100 == 0.0
    assert not math.isnan(estimate.variance_reduction)
