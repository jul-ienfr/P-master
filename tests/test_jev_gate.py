"""Tests unitaires du JevGate — 100 % mockés, aucun appel réseau.

Couvre le wire format (state string, types noul/choice/score, criteria),
la politique asymétrique (bloque, ne débloque jamais), le fail-open et
les modes observer/enforcing/off. Le live proxy est validé séparément
via scripts/eval_jev_gate.py (coût 0, p95 < 800 ms).
"""

import io
import json
from unittest import mock

from src.bot.jev_gate import (
    JevDecision,
    JevGateConfig,
    apply_policy,
    build_questions,
    build_state,
    decide,
    query,
)


def _payload(go=0.83, tier="fast", tier_conf=0.95, risky=0.64, effort=0.43):
    return {
        "model": "jev-1.13-free",
        "answers": {
            "go": {"type": "noul", "noul": go},
            "tier": {"type": "choice", "choice": tier, "confidence": tier_conf},
            "risky": {"type": "noul", "noul": risky},
            "effort": {"type": "score", "score": effort, "confidence": 0.57},
        },
        "usage": {"input_tokens": 100, "output_tokens": 5},
        "cost": "0",
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
        "src.bot.jev_gate.urllib.request.urlopen", return_value=_FakeResp(payload)
    )


SNAPSHOT = {
    "street": "FLOP",
    "hero_cards": ["As", "Kd"],
    "board": ["Ah", "7c", "2d"],
    "pot": 150.0,
    "legal_actions": ["FOLD", "CALL", "RAISE"],
    "state_confidence": 0.92,
}


def test_build_state_is_text_with_key_fields():
    state = build_state(SNAPSHOT)
    assert isinstance(state, str)
    assert "As Kd" in state
    assert "150" in state
    assert "FLOP" in state or "flop" in state


def test_build_questions_wire_format():
    q = build_questions()
    assert q["go"]["type"] == "noul"
    assert q["risky"]["type"] == "noul"
    assert q["tier"]["type"] == "choice"
    assert isinstance(q["tier"]["criteria"], dict)  # choice exige criteria objet
    assert q["effort"]["type"] == "score"
    assert isinstance(q["effort"]["criteria"], list)  # score exige criteria array


def test_query_parses_mocked_response():
    cfg = JevGateConfig(mode="observer")
    with _mock_urlopen(_payload()):
        d = query("some state", build_questions(), config=cfg)
    assert d.go == 0.83
    assert d.tier == "fast"
    assert d.tier_confidence == 0.95
    assert d.risky == 0.64
    assert d.effort == 0.43
    assert d.cost == "0"


def test_query_fail_open_on_timeout():
    cfg = JevGateConfig(mode="enforcing")
    with mock.patch(
        "src.bot.jev_gate.urllib.request.urlopen", side_effect=TimeoutError("slow")
    ):
        d = query("some state", build_questions(), config=cfg)
    assert d.verdict is None and d.go is None and d.tier is None
    assert d.reason.startswith("fail-open")


def test_policy_coherent_go_passes():
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.83, tier="fast",
                      tier_confidence=0.95, risky=0.5, effort=0.43)
    allowed, _ = apply_policy(True, jev, config=cfg)
    assert allowed is True


def test_policy_incoherent_go_blocked():
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.01, tier="deep",
                      tier_confidence=1.0, risky=0.84, effort=2.85)
    allowed, reason = apply_policy(True, jev, config=cfg)
    assert allowed is False
    assert "risky" in reason  # risky > 0.7 force l'escalade


def test_policy_tier_fast_contradicts_weak_block():
    """Garde-fou tier (sweep 2026-09-23 : 3/12 faux blocs) : tier fast/balanced
    (= état lisible selon Jev lui-même) + conf < bar haute -> pas de bloc."""
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.67, tier="fast",
                      tier_confidence=0.56, risky=0.61, effort=1.06)
    allowed, reason = apply_policy(True, jev, config=cfg)
    assert allowed is True
    assert "contradicts" in reason


def test_policy_tier_fast_strong_block_still_blocks():
    """Même avec tier fast, une conf >= bar haute (0.6) bloque toujours."""
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.30, tier="fast",
                      tier_confidence=0.4, risky=0.5, effort=1.0)
    allowed, _ = apply_policy(True, jev, config=cfg)
    assert allowed is False


def test_policy_tier_deep_weak_block_still_blocks():
    """tier deep (ou absent) : la bar basse 0.3 suffit, comportement inchangé."""
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.61, tier="deep",
                      tier_confidence=0.39, risky=0.5, effort=1.0)
    allowed, _ = apply_policy(True, jev, config=cfg)
    assert allowed is False


def test_policy_never_unblocks_heuristic():
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="parsed", go=0.99, tier="fast",
                      tier_confidence=0.9, risky=0.1, effort=0.1)
    allowed, _ = apply_policy(False, jev, config=cfg)
    assert allowed is False


def test_policy_fail_open_keeps_heuristic():
    cfg = JevGateConfig(mode="enforcing")
    jev = JevDecision(verdict=None, reason="fail-open: TimeoutError")
    assert apply_policy(True, jev, config=cfg)[0] is True
    assert apply_policy(False, jev, config=cfg)[0] is False


def test_decide_off_makes_no_call():
    cfg = JevGateConfig(mode="off")
    with mock.patch(
        "src.bot.jev_gate.urllib.request.urlopen",
        side_effect=AssertionError("must not call"),
    ):
        allowed, decision, reason = decide(SNAPSHOT, True, config=cfg)
    assert allowed is True
    assert decision.reason == "off"
    assert reason == "jev off"


def test_decide_observer_never_changes_heuristic():
    cfg = JevGateConfig(mode="observer")
    with _mock_urlopen(_payload(go=0.01, tier="deep", tier_conf=1.0,
                                risky=0.84, effort=2.85)):
        allowed, _, reason = decide(SNAPSHOT, True, config=cfg)
        assert allowed is True
        assert reason.startswith("observer")
    with _mock_urlopen(_payload()):
        allowed, _, _ = decide(SNAPSHOT, False, config=cfg)
        assert allowed is False


def test_from_env_unknown_mode_falls_back_to_observer(monkeypatch):
    monkeypatch.setenv("POKER_JEV_MODE", "whatever")
    assert JevGateConfig.from_env().mode == "observer"


def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("POKER_JEV_MODE", "enforcing")
    monkeypatch.setenv("POKER_JEV_MODEL", "jev-1.13-free")
    monkeypatch.setenv("POKER_JEV_TIMEOUT_S", "1.5")
    cfg = JevGateConfig.from_env()
    assert (cfg.mode, cfg.model, cfg.timeout_s) == ("enforcing", "jev-1.13-free", 1.5)


def test_from_env_base_then_env_then_overrides(monkeypatch):
    base = {"mode": "enforcing", "model": "jev-1.13", "timeout_s": 2.0}
    cfg = JevGateConfig.from_env(base=base)
    assert (cfg.mode, cfg.model, cfg.timeout_s) == ("enforcing", "jev-1.13", 2.0)
    monkeypatch.setenv("POKER_JEV_MODE", "off")
    cfg = JevGateConfig.from_env(base=base)
    assert cfg.mode == "off"  # env bat base
    cfg = JevGateConfig.from_env({"mode": "observer"}, base=base)
    assert cfg.mode == "observer"  # overrides bat env
