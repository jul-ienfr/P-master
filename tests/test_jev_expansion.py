"""Tests unitaires Jev expansion — 100 % mockés, aucun appel réseau.

Couvre les 6 usages : autolabel incidents, juge sessions, attention
multi-tables, budget solveur piloté par tier, drift temporel + wrapper
observer. Le live proxy est validé séparément (coût 0).
"""

import io
import json
from unittest import mock

from scripts.jev_autolabel_incidents import build_autolabel_questions, autolabel
from scripts.jev_judge_sessions import (
    build_judge_questions,
    build_judge_state,
    judge,
    summarize,
)
from src.bot.jev_attention import (
    build_attention_questions,
    suggest_attention_order,
)
from src.bot.jev_drift import (
    DriftSignal,
    confirm_with_jev,
    detect_drift,
    observer_drift_check,
)
from src.bot.jev_gate import JevGateConfig


def _payload(answers: dict) -> dict:
    return {"model": "jev-1.13-free", "answers": answers, "usage": {}, "cost": "0"}


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
    return mock.patch("urllib.request.urlopen", return_value=_FakeResp(payload))


CFG = JevGateConfig(mode="observer", model="jev-1.13-free", timeout_s=0.8)


# --- autolabel ---------------------------------------------------------


def test_autolabel_parses_cause_and_severity():
    payload = _payload(
        {
            "cause": {"type": "choice", "choice": "stale_frame", "confidence": 0.8},
            "severity": {"type": "score", "score": 1.5, "confidence": 0.6},
        }
    )
    with _mock_urlopen(payload):
        out = autolabel("some incident state", build_autolabel_questions(), config=CFG)
    assert out["cause"] == "stale_frame"
    assert out["cause_confidence"] == 0.8
    assert out["severity"] == 1.5
    assert out["reason"] == "parsed"


def test_autolabel_rejects_unknown_cause():
    payload = _payload(
        {
            "cause": {"type": "choice", "choice": "hallucinated", "confidence": 0.9},
            "severity": {"type": "score", "score": 2.0, "confidence": 0.5},
        }
    )
    with _mock_urlopen(payload):
        out = autolabel("state", build_autolabel_questions(), config=CFG)
    assert out["cause"] == "unknown"


def test_autolabel_fail_open_on_timeout():
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()):
        out = autolabel("state", build_autolabel_questions(), config=CFG)
    assert out["cause"] == "unknown"
    assert "fail-open" in out["reason"]


def test_autolabel_fail_open_on_malformed():
    with _mock_urlopen({"no": "answers"}):
        out = autolabel("state", build_autolabel_questions(), config=CFG)
    assert out["cause"] == "unknown"


# --- juge --------------------------------------------------------------


def test_judge_parses_verdict():
    payload = _payload(
        {
            "verdict": {"type": "choice", "choice": "tie", "confidence": 1.0},
            "b_healthier": {"type": "noul", "noul": 0.09},
        }
    )
    with _mock_urlopen(payload):
        out = judge("state", build_judge_questions(), config=CFG)
    assert out["verdict"] == "tie"
    assert out["b_healthier"] == 0.09


def test_judge_fail_open():
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError()):
        out = judge("state", build_judge_questions(), config=CFG)
    assert out["verdict"] == "unknown"


def test_judge_summarize_and_state():
    recs = [
        {"stream": "events"},
        {"stream": "events"},
        {"stream": "incidents", "id": "stale_frame"},
        {"stream": "metrics"},
    ]
    summ = summarize(recs)
    assert summ["total"] == 4
    assert summ["incidents"] == {"stale_frame": 1}
    state = build_judge_state("A", summ, "B", summ)
    assert isinstance(state, str) and "corpus A" in state and "corpus B" in state


# --- attention ---------------------------------------------------------


class _Sess:
    def __init__(self, sid, tracker=None, readiness=None):
        self.session_id = sid
        self._snap = {
            "session_id": sid,
            "tracker_state": tracker or {},
            "readiness": readiness or {},
        }

    def snapshot(self):
        return self._snap


def _signals(*pairs):
    from src.runtime.multi_table_loop import SessionTurnSignal

    return {sid: SessionTurnSignal(**kwargs) for sid, kwargs in pairs}


def test_attention_keeps_rule_order_when_no_tie():
    s1 = _Sess("a")
    s2 = _Sess("b")
    sig = _signals(
        ("a", {"is_our_turn": True}),
        ("b", {"is_our_turn": False}),
    )
    with mock.patch("src.bot.jev_attention.query") as q:
        order = suggest_attention_order([s1, s2], sig, config=CFG)
    q.assert_not_called()  # pas d'ex-aequo -> zéro appel
    assert order == ["a", "b"]


def test_attention_off_never_queries():
    off = JevGateConfig(mode="off")
    s1 = _Sess("a")
    s2 = _Sess("b")
    sig = _signals(
        ("a", {"is_our_turn": True}),
        ("b", {"is_our_turn": True}),
    )
    with mock.patch("src.bot.jev_attention.query") as q:
        order = suggest_attention_order([s1, s2], sig, config=off)
    q.assert_not_called()
    assert order == ["a", "b"]  # tri stable des règles


def test_attention_tiebreak_moves_pick_first():
    from src.bot.jev_gate import JevDecision

    s1 = _Sess("a")
    s2 = _Sess("b")
    sig = _signals(
        ("a", {"is_our_turn": True}),
        ("b", {"is_our_turn": True}),
    )
    fake = JevDecision(
        verdict=None,
        reason="mock",
        raw={"answers": {"pick": {"choice": "table_1"}, "risky": {"noul": 0.2}}},
    )
    with mock.patch("src.bot.jev_attention.query", return_value=fake):
        order = suggest_attention_order([s1, s2], sig, config=CFG)
    assert order == ["b", "a"]


def test_attention_fail_open_keeps_rule_order():
    s1 = _Sess("a")
    s2 = _Sess("b")
    sig = _signals(
        ("a", {"is_our_turn": True}),
        ("b", {"is_our_turn": True}),
    )
    with mock.patch("src.bot.jev_attention.query", side_effect=TimeoutError()):
        order = suggest_attention_order([s1, s2], sig, config=CFG)
    assert order == ["a", "b"]


def test_attention_questions_shape():
    qs = build_attention_questions(2)
    assert qs["pick"]["type"] == "choice"
    assert isinstance(qs["pick"]["criteria"], dict) and len(qs["pick"]["criteria"]) == 2
    assert qs["risky"]["type"] == "noul"


# --- budget solveur ----------------------------------------------------


def test_jev_tier_budgets():
    from src.bot import decision_maker as dm_mod

    dm = dm_mod.DecisionMaker.__new__(dm_mod.DecisionMaker)
    assert dm._apply_jev_tier_budget(1000, jev_tier=None) == (1000, None)
    assert dm._apply_jev_tier_budget(1000, jev_tier="fast") == (400, "fast")
    assert dm._apply_jev_tier_budget(700, jev_tier="balanced") == (700, "balanced")
    assert dm._apply_jev_tier_budget(1000, jev_tier="deep") == (2500, "deep")
    assert dm._apply_jev_tier_budget(1000, jev_tier="???") == (1000, None)


# --- drift -------------------------------------------------------------


def test_detect_street_stalled_on_board_growth():
    prev = {"street": "FLOP", "board": ["As", "Kd"], "pot": 100,
            "validation_state": "fully_valid", "frame_age_ms": 10}
    curr = {"street": "FLOP", "board": ["As", "Kd", "Qh"], "pot": 100,
            "validation_state": "fully_valid", "frame_age_ms": 12}
    sig = detect_drift(prev, curr)
    assert sig is not None and sig.kind == "street_stalled"


def test_detect_pot_frozen_on_bets():
    prev = {"street": "FLOP", "board": [], "pot": 100,
            "validation_state": "fully_valid", "frame_age_ms": 10}
    curr = {"street": "FLOP", "board": [], "pot": 100,
            "total_bets_this_frame": 25,
            "validation_state": "fully_valid", "frame_age_ms": 12}
    sig = detect_drift(prev, curr)
    assert sig is not None and sig.kind == "pot_frozen"


def test_detect_nothing_on_healthy_frames():
    prev = {"street": "FLOP", "board": ["As"], "pot": 100,
            "validation_state": "fully_valid", "frame_age_ms": 10}
    curr = {"street": "FLOP", "board": ["As"], "pot": 100,
            "validation_state": "fully_valid", "frame_age_ms": 12}
    assert detect_drift(prev, curr) is None


def test_detect_never_raises():
    assert detect_drift(None, {}) is None
    assert detect_drift({}, None) is None
    assert detect_drift("x", "y") is None


def test_confirm_with_jev_deep_pauses():
    sig = DriftSignal("street_stalled", "board 2->3")
    pause, reason = confirm_with_jev(sig, {"tier": "deep", "risky": 0.2})
    assert pause is True
    pause, _ = confirm_with_jev(sig, {"tier": "fast", "risky": 0.1})
    assert pause is False
    pause, _ = confirm_with_jev(sig, {"tier": "balanced", "risky": 0.85})
    assert pause is True  # risky > 0.7 force


def test_observer_drift_check_off():
    off = JevGateConfig(mode="off")
    prev = {"street": "FLOP", "board": ["As"], "pot": 1, "frame_age_ms": 400}
    curr = {"street": "FLOP", "board": ["As"], "pot": 1, "frame_age_ms": 410}
    sig, pause, reason = observer_drift_check(prev, curr, jev={"tier": "deep"}, config=off)
    assert (sig, pause, reason) == (None, False, "off")


def test_observer_drift_check_advisory_without_jev():
    prev = {"street": "FLOP", "board": ["As", "Kd"], "pot": 100, "frame_age_ms": 10}
    curr = {"street": "FLOP", "board": ["As", "Kd", "Qh"], "pot": 100, "frame_age_ms": 12}
    sig, pause, _ = observer_drift_check(prev, curr, config=CFG)
    assert sig is not None and pause is False  # avis seul, jamais de pause
