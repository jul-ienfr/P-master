"""SLO et alertes (spec 008, US2/US4) : statuts, effectif, vacuité, indépendance."""

from __future__ import annotations

import inspect

from src.runtime import slo as slo_module
from src.runtime.go_live_gate import evaluate_go_live_gate
from src.runtime.slo import (
    DEFAULT_SLO_OBJECTIVES,
    STATUS_BREACHED,
    STATUS_IGNORED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    SloObjective,
    SloTracker,
    breached_names,
    evaluate_slo,
    parse_slo_objectives,
    slo_metrics_from_history,
    slo_objectives_from_config,
)

EVALUATED_AT = "2026-11-20T10:00:00Z"

OBJECTIVES = (
    SloObjective(name="fallback_rate", metric="fallback_rate", operator="<=", target=0.1),
    SloObjective(
        name="latency_p95_ms",
        metric="latency_p95_ms",
        operator="<=",
        target=500.0,
        severity="critical",
    ),
)


def _evaluate(metrics: dict, objectives=OBJECTIVES):
    return evaluate_slo(metrics, objectives, evaluated_at=EVALUATED_AT)


def _by_name(evaluation) -> dict:
    return {item["name"]: item for item in evaluation.objectives}


def test_objective_held_is_ok_and_produces_no_alert():
    evaluation = _evaluate(
        {"decision_count": 40, "fallback_rate": 0.05, "latency_p95_ms": 220.0}
    )
    statuses = {item["status"] for item in evaluation.objectives}
    assert statuses == {STATUS_OK}
    assert evaluation.alerts == ()
    assert evaluation.breached == ()
    assert evaluation.evaluated_at == EVALUATED_AT


def test_breached_objective_produces_a_named_alert_with_value_target_and_severity():
    evaluation = _evaluate(
        {"decision_count": 40, "fallback_rate": 0.4, "latency_p95_ms": 900.0}
    )
    entries = _by_name(evaluation)

    assert entries["fallback_rate"]["status"] == STATUS_BREACHED
    assert entries["fallback_rate"]["value"] == 0.4
    assert entries["fallback_rate"]["target"] == 0.1
    assert entries["latency_p95_ms"]["status"] == STATUS_BREACHED

    assert evaluation.breached == ("fallback_rate", "latency_p95_ms")
    assert len(evaluation.alerts) == 2
    alert = next(item for item in evaluation.alerts if item["name"] == "latency_p95_ms")
    assert alert["metric"] == "latency_p95_ms"
    assert alert["value"] == 900.0
    assert alert["target"] == 500.0
    assert alert["severity"] == "critical"
    assert alert["operator"] == "<="
    assert alert["reason"]


def test_breach_reason_names_the_metric_and_the_direction():
    evaluation = _evaluate({"decision_count": 40, "fallback_rate": 0.9, "latency_p95_ms": 1.0})
    entry = _by_name(evaluation)["fallback_rate"]
    assert entry["reason"] == "fallback_rate<_target"


def test_insufficient_sample_is_insufficient_data_never_ok():
    for count in (0, 1, 4):
        evaluation = _evaluate(
            {"decision_count": count, "fallback_rate": 0.0, "latency_p95_ms": 10.0}
        )
        for entry in evaluation.objectives:
            assert entry["status"] == STATUS_INSUFFICIENT_DATA, (count, entry["name"])
            assert entry["reason"] == "insufficient_samples"
            assert entry["value"] is None
        assert evaluation.alerts == ()


def test_sample_metric_absent_is_insufficient_data_never_ok():
    evaluation = _evaluate({"fallback_rate": 0.0, "latency_p95_ms": 10.0})
    assert {item["status"] for item in evaluation.objectives} == {STATUS_INSUFFICIENT_DATA}


def test_min_samples_is_honoured_per_objective():
    objectives = (
        SloObjective(
            name="strict",
            metric="fallback_rate",
            operator="<=",
            target=0.1,
            min_samples=10,
        ),
        SloObjective(name="souple", metric="fallback_rate", operator="<=", target=0.1, min_samples=2),
    )
    entries = _by_name(_evaluate({"decision_count": 5, "fallback_rate": 0.0}, objectives))
    assert entries["strict"]["status"] == STATUS_INSUFFICIENT_DATA
    assert entries["souple"]["status"] == STATUS_OK


def test_missing_or_non_numeric_target_is_ignored_with_a_reason_never_breached():
    objectives = (
        SloObjective(name="sans_cible", metric="fallback_rate", operator="<=", target=None),
        SloObjective(name="cible_texte", metric="fallback_rate", operator="<=", target="bas"),
        SloObjective(name="operateur", metric="fallback_rate", operator="~=", target=0.1),
    )
    entries = _by_name(_evaluate({"decision_count": 40, "fallback_rate": 0.9}, objectives))

    assert entries["sans_cible"]["status"] == STATUS_IGNORED
    assert entries["sans_cible"]["reason"] == "invalid_target"
    assert entries["cible_texte"]["status"] == STATUS_IGNORED
    assert entries["operateur"]["status"] == STATUS_IGNORED
    assert entries["operateur"]["reason"] == "unknown_operator"
    assert all(item["status"] != STATUS_BREACHED for item in entries.values())


def test_metric_absent_with_enough_samples_is_ignored_never_zero():
    objectives = (SloObjective(name="p95", metric="latency_p95_ms", operator="<=", target=500.0),)
    entries = _by_name(_evaluate({"decision_count": 40}, objectives))
    assert entries["p95"]["status"] == STATUS_IGNORED
    assert entries["p95"]["reason"] == "metric_missing"
    assert entries["p95"]["value"] is None


def test_no_objective_configured_yields_an_empty_set_never_a_false_alert():
    evaluation = evaluate_slo({"decision_count": 0, "fallback_rate": 0.9}, ())
    assert evaluation.objectives == ()
    assert evaluation.alerts == ()
    assert breached_names(evaluation) == ()


def test_evaluation_is_pure_and_repeatable():
    metrics = {"decision_count": 40, "fallback_rate": 0.4, "latency_p95_ms": 900.0}
    before = dict(metrics)
    first = _evaluate(metrics).to_dict()
    second = _evaluate(metrics).to_dict()
    assert first == second
    assert metrics == before  # les métriques ne sont pas modifiées
    assert breached_names(first) == ("fallback_rate", "latency_p95_ms")


def test_breached_slo_does_not_change_the_go_live_gate_verdict():
    local_metrics = {
        "decision_count": 30,
        "block_rate": 0.1,
        "fallback_rate": 0.1,
        "rolling_latency_ms": 120.0,
    }
    snapshot = {"runtime": {"incident_count": 1}}
    kwargs = {
        "readiness": {"state": "actionable", "score": 0.9},
        "validation": {"state": "fully_valid"},
    }

    gate_before = evaluate_go_live_gate(local_metrics, snapshot, **kwargs)
    assert gate_before.passed is True
    assert gate_before.verdict == "go"

    evaluation = _evaluate(
        {"decision_count": 40, "fallback_rate": 0.4, "latency_p95_ms": 900.0}
    )
    assert evaluation.alerts  # un SLO est bien franchi

    gate_after = evaluate_go_live_gate(local_metrics, snapshot, **kwargs)
    assert gate_after.to_dict() == gate_before.to_dict()
    assert gate_after.verdict == "go"
    # Les deux verdicts sont nommés séparément : le gate dit « apte à démarrer ».
    assert gate_after.checks["fallback_rate"]["threshold"] == 0.5


def test_slo_module_does_not_reach_into_the_go_live_gate():
    source = inspect.getsource(slo_module)
    assert "go_live_gate" not in source
    assert "DEFAULT_GO_LIVE_THRESHOLDS" not in source


def test_defaults_are_declared_once_with_unique_names():
    names = [objective.name for objective in DEFAULT_SLO_OBJECTIVES]
    assert len(names) == len(set(names))
    assert names  # non vide
    # Plus stricts que les seuils d'admission : « en bonne santé » ≠ « apte ».
    fallback = next(o for o in DEFAULT_SLO_OBJECTIVES if o.name == "fallback_rate")
    assert fallback.target < 0.5
    latency = next(o for o in DEFAULT_SLO_OBJECTIVES if o.name == "latency_p95_ms")
    assert latency.target < 2500.0


def test_parse_objectives_from_config_falls_back_to_defaults_and_honours_empty():
    assert parse_slo_objectives(None) == DEFAULT_SLO_OBJECTIVES
    assert parse_slo_objectives("n'importe quoi") == DEFAULT_SLO_OBJECTIVES
    assert parse_slo_objectives([]) == ()  # SLO explicitement désactivés

    parsed = parse_slo_objectives(
        [
            {"name": "fallback_rate", "operator": "<=", "target": 0.05, "min_samples": 20},
            {"name": "", "target": 1},  # sans nom : écartée
            {"name": "sans_cible"},  # sans cible : écartée
            {"name": "op", "operator": "??", "target": 1},  # opérateur inconnu : écartée
            "pas un objet",
        ]
    )
    assert len(parsed) == 1
    assert parsed[0].metric == "fallback_rate"  # métrique = nom par défaut
    assert parsed[0].target == 0.05
    assert parsed[0].min_samples == 20


def test_objectives_from_config_read_the_bot_block():
    config = {"bot": {"slo": [{"name": "block_rate", "target": 0.25}]}}
    objectives = slo_objectives_from_config(config)
    assert len(objectives) == 1
    assert objectives[0].name == "block_rate"
    assert objectives[0].operator == "<="
    assert slo_objectives_from_config({}) == DEFAULT_SLO_OBJECTIVES
    assert slo_objectives_from_config(None) == DEFAULT_SLO_OBJECTIVES


def test_metrics_from_history_use_only_real_recorded_values():
    decisions = [
        {"latency_ms": 100.0, "metadata": {"stages_ms": {"solver": 40.0}}},
        {"latency_ms": 200.0, "metadata": {"stages_ms": {"solver": 80.0}}},
        {"latency_ms": 300.0, "metadata": {"stages_ms": {"solver": 120.0}}},
        {"latency_ms": 400.0, "metadata": {}},  # aucun étage enregistré
    ]
    metrics = slo_metrics_from_history(
        {"decision_count": 4, "fallback_rate": 0.25, "block_rate": 0.5, "rolling_latency_ms": 250.0},
        decisions,
    )
    assert metrics["decision_count"] == 4
    assert metrics["fallback_rate"] == 0.25
    assert metrics["latency_p95_ms"] == 400.0
    # `solver` n'est mesuré que sur les trois décisions qui le portent.
    assert metrics["solver_p95_ms"] == 120.0


def test_metrics_without_latency_report_none_never_zero():
    metrics = slo_metrics_from_history({"decision_count": 2}, [{"metadata": {}}, {}])
    assert metrics["latency_p95_ms"] is None
    assert metrics["solver_p95_ms"] is None
    # Un p95 absent rend l'objectif ignoré, jamais un succès inventé.
    objectives = (SloObjective(name="p95", metric="latency_p95_ms", operator="<=", target=500.0),)
    entries = _by_name(evaluate_slo(metrics, objectives))
    assert entries["p95"]["status"] == STATUS_IGNORED


def test_tracker_signals_only_on_change_of_the_breached_set():
    tracker = SloTracker()
    healthy = _evaluate({"decision_count": 40, "fallback_rate": 0.0, "latency_p95_ms": 10.0})
    breached = _evaluate({"decision_count": 40, "fallback_rate": 0.4, "latency_p95_ms": 10.0})

    assert tracker.observe(healthy) is None  # première observation : pas d'alerte
    assert tracker.observe(healthy) is None
    assert tracker.observe(breached) == {
        "kind": "slo_breached",
        "breached": ["fallback_rate"],
        "resolved": [],
    }
    assert tracker.observe(breached) is None  # même ensemble : pas de bruit
    assert tracker.observe(healthy) == {
        "kind": "slo_recovered",
        "breached": [],
        "resolved": ["fallback_rate"],
    }
