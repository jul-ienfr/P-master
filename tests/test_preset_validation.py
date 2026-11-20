"""Statut de validation d'un preset — un vert exige une mesure (spec 010, F-08).

Constat : les manifestes livrés portaient ``status = "green"`` avec
``evaluated_samples = 0`` et des taux à ``1.0``. Ces tests verrouillent la règle :
un preset non mesuré est ``unmeasured`` avec des taux ``None``, jamais ``green``
ni un taux inventé.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.preset_validation import (
    GREEN,
    RED,
    UNMEASURED,
    YELLOW,
    compute_validation_status,
)

SHIPPED_MANIFESTS = (
    ROOT / "poker" / "pokerstars-7-fr-6-max" / "stable" / "manifest.json",
    ROOT / "poker" / "official-party-poker" / "stable" / "manifest.json",
)


# --- Un vert exige une mesure -------------------------------------------------


def test_no_evaluated_sample_is_unmeasured_not_green():
    outcome = compute_validation_status(golden_scores=[], live_scores=[])

    assert outcome.status == UNMEASURED
    assert outcome.status != GREEN
    assert outcome.evaluated_samples == 0


def test_unmeasured_rates_are_none_not_invented():
    outcome = compute_validation_status()

    # Ni 0.0 (« tout faux ») ni 1.0 (« tout juste ») : non mesuré.
    assert outcome.golden_pass_rate is None
    assert outcome.live_pass_rate is None
    assert outcome.critical_anchor_score is None
    assert outcome.measured is False


def test_all_samples_pass_is_green():
    outcome = compute_validation_status(
        golden_scores=[1.0], live_scores=[1.0, 1.0], critical_anchor_score=1.0
    )

    assert outcome.status == GREEN
    assert outcome.evaluated_samples == 3
    assert outcome.measured is True


def test_a_failing_sample_among_passing_ones_is_never_green():
    # Un échantillon réellement en échec (0.0) fait chuter le taux moyen.
    outcome = compute_validation_status(
        golden_scores=[1.0], live_scores=[1.0, 0.0], critical_anchor_score=1.0
    )

    assert outcome.status in {YELLOW, RED}
    assert outcome.status != GREEN


def test_a_golden_failure_blocks_green_even_with_perfect_live():
    outcome = compute_validation_status(
        golden_scores=[1.0, 0.0], live_scores=[1.0, 1.0], critical_anchor_score=1.0
    )

    assert outcome.status != GREEN


def test_mean_live_rate_at_the_threshold_stays_green():
    # Non-régression du seuil historique : 0.95 (moyenne) est encore vert.
    outcome = compute_validation_status(
        golden_scores=[1.0], live_scores=[1.0, 0.9], critical_anchor_score=1.0
    )

    assert outcome.status == GREEN
    assert outcome.live_pass_rate == pytest.approx(0.95)


def test_all_samples_fail_is_red_not_unmeasured():
    outcome = compute_validation_status(
        golden_scores=[0.0], live_scores=[0.0], critical_anchor_score=0.0
    )

    assert outcome.status == RED
    assert outcome.evaluated_samples == 2


def test_issues_force_red_even_with_a_passing_sample():
    outcome = compute_validation_status(
        golden_scores=[1.0], live_scores=[1.0], issues=["Missing mandatory asset: fold_button"]
    )

    assert outcome.status == RED


def test_golden_only_validation_is_measured():
    outcome = compute_validation_status(golden_scores=[1.0], live_scores=[])

    assert outcome.status == GREEN
    assert outcome.evaluated_samples == 1
    assert outcome.measured is True


def test_as_dict_serializes_none_rates_without_rounding():
    payload = compute_validation_status().as_dict()

    assert payload["status"] == UNMEASURED
    assert payload["golden_pass_rate"] is None
    assert payload["live_pass_rate"] is None
    assert payload["evaluated_samples"] == 0


# --- Non-régression sur les manifestes livrés ---------------------------------


def test_shipped_manifests_are_not_green_without_measure():
    for path in SHIPPED_MANIFESTS:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        validation = manifest["validation"]

        assert validation["evaluated_samples"] == 0, path
        assert validation["status"] == UNMEASURED, path
        assert validation["status"] != GREEN, path
        assert validation["golden_pass_rate"] is None, path
        assert validation["live_pass_rate"] is None, path
