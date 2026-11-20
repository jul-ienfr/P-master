"""Mesure par étage (spec 008, US1) : timer, imbrication, percentiles, coût."""

from __future__ import annotations

import time

from src.runtime.stage_timing import (
    StageTimer,
    extract_stages_ms,
    percentile,
    summarize_stage_timings,
)


class ManualClock:
    """Horloge contrôlée : aucune dépendance au temps réel dans les assertions."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_timer_reports_non_negative_stages_in_traversal_order():
    clock = ManualClock()
    timer = StageTimer(clock=clock)

    with timer.stage("profile"):
        clock.value += 0.012
    with timer.stage("solver"):
        clock.value += 0.250

    stages = timer.as_dict()
    assert list(stages) == ["profile", "solver"]
    assert stages["profile"] == 12.0
    assert stages["solver"] == 250.0
    assert all(value >= 0.0 for value in stages.values())
    assert timer.total_ms == 262.0


def test_nested_stages_are_reported_as_is_never_clamped_to_total():
    clock = ManualClock()
    timer = StageTimer(clock=clock)

    with timer.stage("outer"):
        clock.value += 0.100
        with timer.stage("inner"):
            clock.value += 0.200

    stages = timer.as_dict()
    assert stages["outer"] == 300.0
    assert stages["inner"] == 200.0
    # La somme dépasse la latence totale : elle est rapportée telle quelle.
    assert sum(stages.values()) > timer.total_ms


def test_repeated_stage_accumulates_and_reuses_the_same_key():
    clock = ManualClock()
    timer = StageTimer(clock=clock)

    with timer.stage("solver"):
        clock.value += 0.010
    with timer.stage("solver"):
        clock.value += 0.020

    assert timer.as_dict() == {"solver": 30.0}
    assert len(timer) == 1


def test_timer_ignores_unmatched_stop_and_non_monotonic_clock():
    clock = ManualClock(10.0)
    timer = StageTimer(clock=clock)

    timer.stop("jamais_commence")  # aucune exception, aucun étage inventé
    assert timer.as_dict() == {}

    timer.start("x")
    clock.value -= 5.0  # horloge non monotone
    timer.stop("x")
    assert timer.as_dict() == {"x": 0.0}


def test_empty_stage_name_is_ignored():
    timer = StageTimer(clock=ManualClock())
    timer.start("")
    timer.stop("")
    assert timer.as_dict() == {}


def test_percentile_of_empty_list_is_zero_never_an_exception():
    assert percentile([], 0.95) == 0.0
    assert percentile([], 0.0) == 0.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([7.0], 0.99) == 7.0


def test_extract_stages_reads_canonical_record_and_runtime_trace():
    assert extract_stages_ms({"decision": {"stages_ms": {"solver": 12.5}}}) == {"solver": 12.5}
    assert extract_stages_ms({"metadata": {"stages_ms": {"rl": 3}}}) == {"rl": 3.0}
    assert extract_stages_ms({"stages_ms": {"a": 1}}) == {"a": 1.0}
    # Non numérique : l'étage est écarté, jamais converti en zéro.
    assert extract_stages_ms({"stages_ms": {"a": 1, "b": "lent", "c": True}}) == {"a": 1.0}
    assert extract_stages_ms({"decision": {}}) == {}
    assert extract_stages_ms("pas un enregistrement") == {}


def test_summary_computes_percentiles_per_stage():
    records = [
        {"decision": {"stages_ms": {"profile": 1.0, "solver": 100.0}}},
        {"decision": {"stages_ms": {"profile": 3.0, "solver": 200.0}}},
        {"decision": {"stages_ms": {"profile": 5.0, "solver": 300.0}}},
        {"decision": {"stages_ms": {"profile": 7.0, "solver": 400.0}}},
    ]

    summary = summarize_stage_timings(records)
    assert summary["records_with_stages"] == 4
    assert summary["stage_count"] == 2
    solver = summary["stages"]["solver"]
    assert solver["count"] == 4
    assert solver["p50"] == 200.0
    assert solver["p95"] == 400.0
    assert solver["max"] == 400.0
    assert solver["mean"] == 250.0


def test_summary_never_invents_a_stage_absent_from_a_record():
    records = [
        {"decision": {"stages_ms": {"solver": 10.0, "rl": 2.0}}},
        {"decision": {"stages_ms": {"solver": 20.0}}},
        {"decision": {}},  # schéma antérieur : aucun étage
    ]

    summary = summarize_stage_timings(records)
    assert summary["records_with_stages"] == 2
    assert summary["stages"]["solver"]["count"] == 2
    # `rl` n'est compté que sur le seul enregistrement qui le porte.
    assert summary["stages"]["rl"]["count"] == 1
    assert "profile" not in summary["stages"]


def test_summary_of_a_journal_without_stages_is_empty_and_valid():
    summary = summarize_stage_timings([{"decision": {}}, {"decision": {}}])
    assert summary == {"records_with_stages": 0, "stage_count": 0, "stages": {}}


def test_timer_overhead_is_measured_not_assumed():
    """Le surcoût est mesuré : la borne du test garde une marge de mesure (CI
    lente) tout en interdisant un coût d'un ordre de grandeur au-dessus."""
    iterations = 20_000
    timer = StageTimer()

    baseline_start = time.perf_counter()
    for _ in range(iterations):
        time.perf_counter()
        time.perf_counter()
    baseline_us = (time.perf_counter() - baseline_start) / iterations * 1e6

    measured_start = time.perf_counter()
    for _ in range(iterations):
        timer.start("solver")
        timer.stop("solver")
    measured_us = (time.perf_counter() - measured_start) / iterations * 1e6

    assert measured_us < 5.0, f"coût mesuré {measured_us:.3f} µs par étage"
    # L'accumulateur n'ajoute qu'une comptabilité, pas un ordre de grandeur.
    assert measured_us <= baseline_us * 5 + 1.0
    assert len(timer) == 1
