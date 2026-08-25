"""Tests des contrats V2 (sérialisation, coercions, builders)."""
import json
from types import SimpleNamespace

import pytest

from poker.decisionmaker.v2_contracts import (
    CachePolicy,
    CacheTier,
    DecisionGateResult,
    DecisionSnapshot,
    LlmConfig,
    LlmProviderMode,
    RangeModelVersion,
    SerializableDataclass,
    SolveRequestV2,
    SpotSnapshot,
    _as_bool,
    _as_float,
    _as_int,
    _coerce_cache_policy,
    _coerce_cache_tier,
    _coerce_provider_mode,
    _coerce_range_model_version,
    build_default_llm_config,
    build_health_payload,
    build_mock_decision_snapshot,
    build_mock_gate_result,
    build_mock_spot_snapshot,
    build_runtime_snapshot,
    build_version_payload,
    build_suite_samples,
)


def test_scalar_coercions_use_safe_defaults():
    assert _as_float("3.5") == 3.5
    assert _as_float("x") == 0.0
    assert _as_float(None, default=1.5) == 1.5

    assert _as_int("7") == 7
    assert _as_int("x", default=2) == 2

    assert _as_bool(True) is True
    assert _as_bool("yes") is True
    assert _as_bool(0) is False
    # Le défaut ne s'applique qu'à None ; une string inconnue vaut False.
    assert _as_bool("junk", default=True) is False
    assert _as_bool(None, default=True) is True


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("openai_compatible_remote", LlmProviderMode.OPENAI_COMPATIBLE_REMOTE),
        ("openai_compatible_local", LlmProviderMode.OPENAI_COMPATIBLE_LOCAL),
        ("garbage", LlmProviderMode.DISABLED),
        (None, LlmProviderMode.DISABLED),
    ],
)
def test_coerce_provider_mode(raw, expected):
    # Coercion sensible à la casse : seules les valeurs exactes de l'enum passent.
    assert _coerce_provider_mode(raw) == expected


def test_coerce_cache_policies_fallback_to_defaults():
    assert _coerce_cache_policy("memory") == CachePolicy.MEMORY
    # Valeur inconnue / type invalide : repli MEMORY (défaut runtime).
    assert _coerce_cache_policy("nonsense") == CachePolicy.MEMORY
    assert _coerce_cache_policy(None) == CachePolicy.MEMORY
    assert _coerce_cache_tier("nonsense") == CacheTier.NONE
    assert _coerce_range_model_version("calibrated_v3") == RangeModelVersion.CALIBRATED_V3
    # Valeur inconnue -> version par défaut (board_aware_v2).
    assert _coerce_range_model_version(42) == RangeModelVersion.BOARD_AWARE_V2


def test_serializable_dataclass_roundtrip():
    snapshot = build_mock_spot_snapshot()
    payload = json.loads(snapshot.to_json())
    restored = SpotSnapshot.from_json(snapshot.to_json())
    assert isinstance(restored, SpotSnapshot)
    assert restored.spot_id == payload["spot_id"]


def test_build_mock_gate_result_is_blocking_or_ready_consistent():
    gate = build_mock_gate_result()
    assert isinstance(gate, DecisionGateResult)
    payload = gate.to_dict()
    assert isinstance(payload, dict)
    # Round-trip dict -> objet.
    restored = DecisionGateResult.from_dict(payload)
    assert restored.allowed == gate.allowed


def test_decision_snapshot_roundtrip_and_legacy():
    snapshot = build_mock_decision_snapshot()
    payload = snapshot.to_dict()

    from_dict_restored = DecisionSnapshot.from_dict(payload)
    assert from_dict_restored.action == snapshot.action

    # from_legacy lit l'attribut `decision` (contrat historique), pas `action`.
    fake_legacy = SimpleNamespace(
        decision="BET_75",
        confidence=0.9,
        cache_hit=False,
        fallback_used=False,
    )
    converted = DecisionSnapshot.from_legacy(fake_legacy, source="test")
    assert converted.action == "BET_75"
    assert converted.source == "test"


def test_solve_request_defaults_are_sane():
    request = SolveRequestV2()
    payload = request.to_dict()
    assert isinstance(payload, dict)

    restored = SolveRequestV2.from_dict(payload)
    assert restored.hero_range == request.hero_range


def test_llm_config_disabled_default():
    config = LlmConfig.disabled_default()
    assert config.is_enabled() is False

    rebuilt = LlmConfig.from_dict(config.to_dict())
    assert rebuilt.is_enabled() is False

    default = build_default_llm_config()
    assert isinstance(default, LlmConfig)


def test_build_suite_samples_contains_expected_sections():
    samples = build_suite_samples()
    assert isinstance(samples, dict)
    assert samples


def test_runtime_health_version_payloads():
    runtime = build_runtime_snapshot(service_name="unit-test")
    assert runtime["service"] == "unit-test"

    health = build_health_payload()
    assert health["status"] in {"ok", "degraded"}

    version = build_version_payload()
    assert isinstance(version, dict)
