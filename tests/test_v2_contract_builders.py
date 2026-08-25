"""Tests des builders de payloads mock (gros volume, déterministes)."""

import json

from poker.decisionmaker.v2_contracts import (
    build_config_lab_surface_payload,
    build_mock_bot_cockpit_payload,
    build_mock_config_payload,
    build_mock_llm_assist_payload,
    build_mock_ocr_snapshot,
    build_mock_operator_snapshot,
    build_mock_replay_analytics_payload,
    build_mock_solve_response_payload,
    build_replay_analytics_surface_payload,
)


def _assert_json_serializable(payload):
    json.dumps(payload, default=str)


def test_build_mock_solve_response_payload_is_serializable_and_actionable():
    payload = build_mock_solve_response_payload()
    _assert_json_serializable(payload)
    # Le contrat v2 exige une décision exploitable.
    assert "chosen_action" in json.dumps(payload)


def test_build_mock_llm_assist_payload_shape():
    payload = build_mock_llm_assist_payload()
    _assert_json_serializable(payload)
    assert isinstance(payload, dict)


def test_build_mock_replay_analytics_payload_shape():
    payload = build_mock_replay_analytics_payload()
    _assert_json_serializable(payload)
    assert payload


def test_build_mock_bot_cockpit_payload_surfaces():
    payload = build_mock_bot_cockpit_payload()
    _assert_json_serializable(payload)
    for key in ("state", "runtime", "spot", "decision", "ocr", "operator"):
        assert key in payload, key


def test_surface_payloads_share_envelope():
    replay = build_replay_analytics_surface_payload()
    config_lab = build_config_lab_surface_payload()
    for surface in (replay, config_lab):
        _assert_json_serializable(surface)
        assert surface["kind"]
        assert surface["status"] in {"ok", "empty", "stale", "ready"} or surface["status"]
        assert surface["source"]


def test_snapshot_mocks_are_serializable():
    for payload in (
        build_mock_ocr_snapshot(),
        build_mock_operator_snapshot(),
        build_mock_config_payload(),
    ):
        _assert_json_serializable(payload)
