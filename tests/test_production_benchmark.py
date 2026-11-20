"""Harnais de benchmark du chemin de production — spec 011 (constat F-03).

Le harnais doit mesurer une politique fournie, enregistrer honnêtement laquelle,
et refuser de présenter une mesure d'heuristique comme une mesure du produit.
"""

from __future__ import annotations

import json
from pathlib import Path
from random import Random

from research.monte_carlo_sim import View, make_heuristic_hero_policy
from research.production_benchmark import (
    ProductionBenchmarkReport,
    preflop_equity_control,
    run_production_benchmark,
    write_report,
)


def _always_check_call(view: View) -> tuple[str, float | None]:
    """Politique déterministe : appelle toujours (rapide, sans solveur)."""
    return "check_call", None


def _control(hole_cards: str, rng: Random) -> float:
    """Contrôle synthétique corrélé au hasard, de moyenne connue nulle."""
    return rng.gauss(0.0, 1.0)


def test_benchmark_produces_winrate_ci_and_required_hands():
    report = run_production_benchmark(
        _always_check_call,
        policy_label="test_policy",
        is_production=True,
        opponents=("tag",),
        hands=40,
        seed=5,
        target_half_width_bb100=10.0,
        control_fn=_control,
    )
    assert report.hands == 40
    assert report.winrate_bb100 is not None
    assert report.ci95_low_bb100 is not None
    assert report.ci95_high_bb100 is not None
    assert report.required_hands > 0
    assert report.std_per_hand_bb is not None


def test_benchmark_marks_non_production_policy():
    report = run_production_benchmark(
        _always_check_call,
        policy_label="hero_heuristic",
        is_production=False,
        opponents=("tag",),
        hands=30,
        seed=6,
        control_fn=_control,
    )
    assert report.hero_policy_is_production is False
    assert report.verdict["protocol_complete"] is False
    assert "policy_not_production" in report.verdict["reasons"]


def test_benchmark_unmeasured_without_hands():
    report = run_production_benchmark(
        _always_check_call,
        policy_label="test_policy",
        is_production=True,
        opponents=("tag",),
        hands=0,
        seed=7,
        control_fn=_control,
    )
    assert report.status == "unmeasured"
    assert report.winrate_bb100 is None
    assert report.ci95_low_bb100 is None
    assert report.std_per_hand_bb is None
    assert report.variance_reduction is None


def test_benchmark_reports_measured_variance_reduction_not_assumed():
    report = run_production_benchmark(
        _always_check_call,
        policy_label="test_policy",
        is_production=True,
        opponents=("tag",),
        hands=50,
        seed=8,
        control_fn=_control,
    )
    # Le contrôle synthétique est décorrélé du résultat : la réduction mesurée
    # est proche de zéro et n'est jamais forcée à une valeur supposée.
    assert report.variance_reduction is not None
    assert abs(report.variance_reduction) < 0.5


def test_write_report_writes_dated_json_artifact(tmp_path: Path):
    report = run_production_benchmark(
        _always_check_call,
        policy_label="test_policy",
        is_production=True,
        opponents=("tag",),
        hands=20,
        seed=9,
        control_fn=_control,
    )
    target = tmp_path / "production_winrate.json"
    written = write_report(report, target)
    assert written == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["kind"] == "production_winrate_benchmark"
    assert payload["generated_at"].endswith("Z")
    assert payload["hero_policy_is_production"] is True
    assert payload["hands"] == 20


def test_preflop_equity_control_is_centered_on_half():
    rng = Random(20261120)
    samples = [preflop_equity_control("AsKd", rng) for _ in range(200)]
    mean = sum(samples) / len(samples)
    # Moyenne exactement nulle par construction : l'échantillon doit rester
    # proche de zéro (le contrôle vaut équité − 0,5).
    assert abs(mean) < 0.15


def test_report_dict_is_json_serializable():
    report = ProductionBenchmarkReport(
        hero_policy="p",
        hero_policy_is_production=False,
        opponents=["tag"],
        hands=0,
        required_hands=0,
        status="unmeasured",
        winrate_bb100=None,
        ci95_low_bb100=None,
        ci95_high_bb100=None,
        std_per_hand_bb=None,
        variance_reduction=None,
        reduced_winrate_bb100=None,
        reduced_ci95_bb100=None,
        verdict={"verdict": "unmeasured"},
        generated_at="2026-11-20T00:00:00Z",
        seed=1,
        target_half_width_bb100=10.0,
    )
    assert json.loads(json.dumps(report.to_dict()))["status"] == "unmeasured"


def test_heuristic_policy_runs_through_harness():
    """La politique de recherche passe le harnais et reste étiquetée non-production."""
    report = run_production_benchmark(
        make_heuristic_hero_policy(),
        policy_label="hero_heuristic",
        is_production=False,
        opponents=("nit",),
        hands=6,
        seed=10,
    )
    assert report.hero_policy_is_production is False
    assert report.hero_policy == "hero_heuristic"
