"""Registre de versions, schémas lisibles et résumé par étage (spec 008, US1/US3).

Trois garanties, chacune vérifiée ici :

- chaque enregistrement porte un bloc ``versions`` (une source indisponible vaut
  ``None``, jamais une valeur inventée) ;
- un journal écrit sous un schéma **connu** reste lisible — un schéma antérieur
  est signalé, pas rejeté en bloc ; un schéma inconnu reste une erreur ;
- le résumé d'un journal calcule des percentiles **par étage** sans inventer
  d'étage absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.runtime import decision_log as decision_log_module
from src.runtime.decision_log import (
    KNOWN_SCHEMA_VERSIONS,
    SCHEMA_STATUS_CURRENT,
    SCHEMA_STATUS_LEGACY,
    SCHEMA_STATUS_UNKNOWN,
    SCHEMA_VERSION,
    build_decision_record,
    decision_versions,
    record_from_runtime_trace,
    schema_status,
    summarize_decision_records,
    validate_decision_record,
    versions_from_decision_maker,
)
from src.solver.blueprint_store import BLUEPRINT_FORMAT_VERSION

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture(name: str = "decision_replay_validated_rl.json") -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _record(**kwargs) -> dict:
    fixture = _fixture()
    return build_decision_record(fixture["request"], fixture["expected"], **kwargs)


def _valid_trace(**overrides) -> dict:
    trace = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": "2026-11-20T10:00:00+00:00",
        "board": ["2c", "7d", "Jh"],
        "hero_cards": ["Ah", "Kd"],
        "pot": 12.5,
        "legal_actions": ["FOLD", "CALL", "BET"],
        "chosen_action": "BET",
        "source": "GTO_RUST",
        "backend": "native",
        "latency_ms": 120.0,
        "metadata": {"effective_stack": 100.0, "hero_position": "ip"},
    }
    trace.update(overrides)
    return trace


# --- Registre de versions (FR-007) ------------------------------------------


def test_record_carries_a_non_empty_versions_block():
    versions = _record()["versions"]
    assert versions["schema_version"] == SCHEMA_VERSION
    assert versions["range_model_version"]  # résolue depuis les contrats V2
    assert versions["blueprint_version"] == BLUEPRINT_FORMAT_VERSION


def test_versions_block_is_part_of_a_valid_record():
    record = _record()
    assert validate_decision_record(record) == []
    assert set(record["versions"]) >= {
        "schema_version",
        "blueprint_version",
        "range_model_version",
        "solver_bet_sizes",
        "solver_raise_sizes",
    }


def test_unavailable_source_is_none_never_invented(monkeypatch):
    # Une source qui ne rend pas un entier exploitable ne doit pas produire une
    # version devinée : le champ vaut ``None``.
    monkeypatch.setattr(decision_log_module, "_resolve_blueprint_version", lambda: None)
    versions = decision_versions()
    assert versions["blueprint_version"] is None
    assert versions["schema_version"] == SCHEMA_VERSION  # le schéma, lui, est toujours connu


def test_blank_bet_sizes_are_none_never_an_empty_string():
    versions = decision_versions(solver_bet_sizes="   ", solver_raise_sizes="2.5x")
    assert versions["solver_bet_sizes"] is None
    assert versions["solver_raise_sizes"] == "2.5x"


def test_different_bet_sizes_produce_different_versions():
    class Maker:
        solver_bet_sizes = "50%"
        solver_raise_sizes = "2.5x"

    other = Maker()
    other.solver_bet_sizes = "33%,75%"
    first = versions_from_decision_maker(Maker())
    second = versions_from_decision_maker(other)
    assert first["solver_bet_sizes"] != second["solver_bet_sizes"]
    assert first != second


def test_versions_from_decision_maker_tolerates_a_missing_maker():
    versions = versions_from_decision_maker(None)
    assert versions["solver_bet_sizes"] is None
    assert versions["solver_raise_sizes"] is None


def test_runtime_trace_versions_are_merged_into_the_record():
    record = record_from_runtime_trace(
        _valid_trace(versions={"solver_bet_sizes": "60%", "range_model_version": "heuristic_v1"})
    )
    assert record["versions"]["solver_bet_sizes"] == "60%"
    assert record["versions"]["range_model_version"] == "heuristic_v1"
    # Les champs non fournis par la trace restent résolus, jamais perdus.
    assert record["versions"]["schema_version"] == SCHEMA_VERSION


# --- Schémas lisibles (FR-008) ----------------------------------------------


def test_current_schema_is_accepted_and_named_current():
    record = _record()
    assert schema_status(record) == SCHEMA_STATUS_CURRENT
    assert validate_decision_record(record) == []


def test_known_older_schema_is_read_and_signalled_never_rejected(monkeypatch):
    monkeypatch.setattr(decision_log_module, "KNOWN_SCHEMA_VERSIONS", (0, SCHEMA_VERSION))
    record = _record()
    record["schema_version"] = 0
    assert schema_status(record) == SCHEMA_STATUS_LEGACY
    # Un journal antérieur reste lisible : aucune erreur de validation.
    assert validate_decision_record(record) == []


def test_unknown_schema_is_signalled_and_stays_an_error():
    record = _record()
    record["schema_version"] = 99
    assert schema_status(record) == SCHEMA_STATUS_UNKNOWN
    errors = validate_decision_record(record)
    assert any("schema_version" in error for error in errors)


def test_non_numeric_schema_is_unknown_never_silently_current():
    assert schema_status({"schema_version": "un"}) == SCHEMA_STATUS_UNKNOWN
    assert schema_status({}) == SCHEMA_STATUS_UNKNOWN
    assert schema_status("pas un enregistrement") == SCHEMA_STATUS_UNKNOWN


def test_known_schemas_include_the_current_one():
    assert SCHEMA_VERSION in KNOWN_SCHEMA_VERSIONS


def test_trace_schema_version_is_preserved_by_coercion():
    record = record_from_runtime_trace(_valid_trace())
    assert record["schema_version"] == SCHEMA_VERSION
    assert validate_decision_record(record) == []


# --- Résumé par étage (FR-003) ----------------------------------------------


def test_runtime_trace_stages_land_in_the_canonical_record():
    record = record_from_runtime_trace(
        _valid_trace(metadata={"stages_ms": {"solver": 80.0, "profile": 4.0}})
    )
    assert record["decision"]["stages_ms"] == {"solver": 80.0, "profile": 4.0}


def test_record_without_stages_does_not_gain_a_null_key():
    record = record_from_runtime_trace(_valid_trace())
    assert "stages_ms" not in record["decision"]


def test_summary_reports_percentiles_per_stage():
    records = [
        _record(),
        _record(),
    ]
    for index, record in enumerate(records):
        record["decision"]["stages_ms"] = {"solver": 100.0 * (index + 1), "profile": 2.0}
    summary = summarize_decision_records(records)
    assert summary["stages_ms"]["records_with_stages"] == 2
    solver = summary["stages_ms"]["stages"]["solver"]
    assert solver["count"] == 2
    assert solver["max"] == 200.0


def test_summary_without_stages_is_valid_and_invents_no_stage():
    summary = summarize_decision_records([_record(), _record()])
    assert summary["stages_ms"] == {"records_with_stages": 0, "stage_count": 0, "stages": {}}


def test_summary_counts_schema_statuses():
    current = _record()
    unknown = _record()
    unknown["schema_version"] = 99
    summary = summarize_decision_records([current, unknown])
    assert summary["schema_versions"][SCHEMA_STATUS_CURRENT] == 1
    assert summary["schema_versions"][SCHEMA_STATUS_UNKNOWN] == 1
    assert summary["invalid"] == 1  # un schéma inconnu reste compté invalide


@pytest.mark.parametrize("ratio", [0.0, 0.5, 1.0])
def test_percentile_is_bounded_on_an_empty_or_single_sample(ratio):
    from src.runtime.stage_timing import percentile

    assert percentile([], ratio) == 0.0
    assert percentile([7.0], ratio) == 7.0
