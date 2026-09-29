"""Tests unitaires du DjevGate officiel — 100 % mockés, aucun appel réseau.

Miroir de tests/test_jev_gate.py adapté aux écarts proxy :4000 vs officiel
(isolés dans src/bot/djev_gate.py) : auth Bearer via nom de var env, endpoint
complet /v1/systemone, modèle piné jev-1.13.0, retry 429/529, fail-open
401/422, offline_mode WAN refused, clé absente sans appel.
"""

import io
import json
import urllib.error
from unittest import mock

from src.bot.djev_gate import (
    DEFAULT_MODEL,
    DjevGateConfig,
    _endpoint,
    apply_policy,
    build_questions,
    build_state,
    decide,
    query,
)
from src.bot.jev_gate import JevDecision


def _payload(go=0.83, tier="fast", tier_conf=0.95, risky=0.64, effort=0.43):
    return {
        "model": "jev-1.13.0",
        "answers": {
            "go": {"type": "noul", "noul": go},
            "tier": {"type": "choice", "choice": tier, "confidence": tier_conf},
            "risky": {"type": "noul", "noul": risky},
            "effort": {"type": "score", "score": effort, "confidence": 0.57},
        },
        "usage": {"input_tokens": 100, "output_tokens": 5},
    }


class _FakeResp:
    def __init__(self, payload):
        self._buf = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._buf.read()


def _mock_urlopen(payload):
    return mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen", return_value=_FakeResp(payload)
    )


SNAPSHOT = {
    "street": "FLOP",
    "hero_cards": ["As", "Kd"],
    "board": ["Ah", "7c", "2d"],
    "pot": 150.0,
    "legal_actions": ["FOLD", "CALL", "RAISE"],
    "state_confidence": 0.92,
}


def _lan_cfg(**kw):
    base = {"mode": "observer", "base_url": "http://127.0.0.1:4000"}
    base.update(kw)
    return DjevGateConfig.from_env(base=base)


def test_default_model_pinned():
    assert DEFAULT_MODEL == "jev-1.13.0"
    assert DjevGateConfig.from_env().model == "jev-1.13.0"


def test_endpoint_accepts_naked_or_full_base():
    assert _endpoint("http://127.0.0.1:4000") == "http://127.0.0.1:4000/v1/systemone"
    assert _endpoint("https://api.typesafe.ai/v1/systemone") == (
        "https://api.typesafe.ai/v1/systemone"
    )


def test_build_state_and_questions_shared_with_jev():
    state = build_state(SNAPSHOT)
    assert isinstance(state, str) and "As Kd" in state
    q = build_questions()
    assert q["go"]["type"] == "noul"
    assert isinstance(q["tier"]["criteria"], dict)
    assert isinstance(q["effort"]["criteria"], list)


def test_query_parses_mocked_response_lan():
    cfg = _lan_cfg()
    with _mock_urlopen(_payload()):
        d = query("some state", build_questions(), config=cfg)
    assert d.go == 0.83
    assert d.tier == "fast"
    assert d.tier_confidence == 0.95
    assert d.reason == "parsed"


def test_query_sends_bearer_when_key_present(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-xyz")
    cfg = DjevGateConfig.from_env(
        base={"mode": "observer", "base_url": "https://api.typesafe.ai/v1/systemone"},
        overrides={"offline_mode": False},  # voie cloud explicite (lock: offline True par defaut)
    )
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.get_header("Authorization")
        return _FakeResp(_payload())

    with mock.patch("src.bot.djev_gate.urllib.request.urlopen", side_effect=fake_urlopen):
        d = query("some state", build_questions(), config=cfg)
    assert seen["auth"] == "Bearer secret-xyz"
    assert d.go == 0.83


def test_query_missing_key_cloud_makes_no_call(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    cfg = DjevGateConfig.from_env(
        base={"mode": "observer", "base_url": "https://api.typesafe.ai/v1/systemone"},
        overrides={"offline_mode": False},  # voie cloud explicite (lock: offline True par defaut)
    )
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=AssertionError("must not call"),
    ):
        d = query("some state", build_questions(), config=cfg)
    assert d.verdict is None and d.go is None
    assert d.reason == "fail-open: missing api key"


def test_query_offline_mode_wan_refused_makes_no_call(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-xyz")
    cfg = DjevGateConfig.from_env(
        base={"mode": "observer", "base_url": "https://api.typesafe.ai/v1/systemone"},
        overrides={"offline_mode": True},
    )
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=AssertionError("must not call"),
    ):
        d = query("some state", build_questions(), config=cfg)
    assert d.reason == "fail-open: offline_mode, WAN refused"


def test_query_offline_mode_lan_still_calls():
    cfg = _lan_cfg(offline_mode=True)
    with _mock_urlopen(_payload()):
        d = query("some state", build_questions(), config=cfg)
    assert d.go == 0.83


def test_query_401_422_fail_open_direct():
    cfg = _lan_cfg()
    for code in (401, 422):
        err = urllib.error.HTTPError(
            "http://127.0.0.1:4000/v1/systemone", code, "err", {}, None
        )
        with mock.patch(
            "src.bot.djev_gate.urllib.request.urlopen", side_effect=err
        ):
            d = query("some state", build_questions(), config=cfg)
        assert d.verdict is None and d.reason == f"fail-open: HTTPError {code}"


def test_query_429_529_retry_once_then_parse():
    cfg = _lan_cfg()
    err = urllib.error.HTTPError(
        "http://127.0.0.1:4000/v1/systemone", 429, "rate", {}, None
    )
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=[err, _FakeResp(_payload())],
    ), mock.patch("src.bot.djev_gate.time.sleep", return_value=None):
        d = query("some state", build_questions(), config=cfg)
    assert d.go == 0.83


def test_query_timeout_fail_open():
    cfg = _lan_cfg(mode="enforcing")
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=TimeoutError("slow"),
    ):
        d = query("some state", build_questions(), config=cfg)
    assert d.verdict is None and d.reason.startswith("fail-open")


def test_query_empty_state_makes_no_call():
    cfg = _lan_cfg()
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=AssertionError("must not call"),
    ):
        d = query("   ", build_questions(), config=cfg)
    assert d.reason == "fail-open: empty state"


def test_policy_blocks_but_never_unblocks():
    cfg = _lan_cfg(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.01, tier="deep",
                      tier_confidence=1.0, risky=0.84, effort=2.85)
    allowed, reason = apply_policy(True, jev, config=cfg)
    assert allowed is False and "risky" in reason
    jev2 = JevDecision(verdict=None, reason="parsed", go=0.99, tier="fast",
                       tier_confidence=0.9, risky=0.1, effort=0.1)
    assert apply_policy(False, jev2, config=cfg)[0] is False


def test_decide_off_makes_no_call():
    cfg = _lan_cfg(mode="off")
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=AssertionError("must not call"),
    ):
        allowed, decision, reason = decide(SNAPSHOT, True, config=cfg)
    assert allowed is True and decision.reason == "off" and reason == "djev off"


def test_decide_observer_never_changes_heuristic():
    cfg = _lan_cfg(mode="observer")
    with _mock_urlopen(_payload(go=0.01, tier="deep", tier_conf=1.0,
                                risky=0.84, effort=2.85)):
        allowed, _, reason = decide(SNAPSHOT, True, config=cfg)
        assert allowed is True and reason.startswith("observer")
    with _mock_urlopen(_payload()):
        allowed, _, _ = decide(SNAPSHOT, False, config=cfg)
        assert allowed is False


def test_from_env_precedence_base_env_overrides(monkeypatch):
    base = {"mode": "enforcing", "model": "jev-1.13.0", "timeout_s": 2.0}
    cfg = DjevGateConfig.from_env(base=base)
    assert (cfg.mode, cfg.model, cfg.timeout_s) == ("enforcing", "jev-1.13.0", 2.0)
    monkeypatch.setenv("POKER_DJEV_MODE", "off")
    assert DjevGateConfig.from_env(base=base).mode == "off"
    cfg = DjevGateConfig.from_env(overrides={"mode": "observer"}, base=base)
    assert cfg.mode == "observer"


def test_from_env_unknown_mode_falls_back_to_observer(monkeypatch):
    monkeypatch.setenv("POKER_DJEV_MODE", "whatever")
    assert DjevGateConfig.from_env().mode == "observer"


def test_from_env_offline_keeps_url_query_refuses_wan(monkeypatch):
    # Pas de repli silencieux : l'URL WAN est conservee telle quelle dans la
    # config, et c'est query() qui refuse SANS appel reseau (fail-open).
    monkeypatch.setenv("POKER_OFFLINE_MODE", "1")
    cfg = DjevGateConfig.from_env(
        base={"base_url": "https://api.typesafe.ai/v1/systemone"}
    )
    assert cfg.base_url == "https://api.typesafe.ai/v1/systemone"
    with mock.patch(
        "src.bot.djev_gate.urllib.request.urlopen",
        side_effect=AssertionError("must not call"),
    ):
        d = query("some state", build_questions(), config=cfg)
    assert d.verdict is None
    assert d.reason == "fail-open: offline_mode, WAN refused"
