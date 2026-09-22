"""Validation plan 6 (c)(d)(g)(i) — mode live lookup-only blueprint.

- MISS ⇒ fallback_reason="no_blueprint", aucune action (fallback_used).
- HIT ⇒ réponse convergée servie depuis le store, backend="blueprint".
- Parité de clé : le générateur et le lookup live utilisent la même clé.
- Le store n'écrit/charge jamais d'entrée non convergée (Phase 0.5.6).
- Mise hors tolérance de quantification ⇒ refus, pas d'arrondi silencieux.
"""

from __future__ import annotations

import json

import pytest

from src.solver import blueprint_store as bp_module
from src.solver.bet_quantization import quantize_observed_bet
from src.solver.blueprint_store import BlueprintStore, blueprint_key
from src.solver.provider import SolverProvider

SPOT = {
    "hero_range": "AA",
    "villain_ranges": ["QQ"],
    "board": ["2c", "7d", "Js", "4h", "9s"],
    "starting_pot": 10.0,
    "effective_stack": 20.0,
    "legal_actions": ["FOLD", "CALL", "ALL_IN"],
    "spot_id": "bp:hu:river_jam:AA_vs_QQ",
    "hero_position": "oop",
    "action_history": [],
    "rake": 0.0,
}


def _make_store(tmp_path, entries: list[dict] | None = None) -> BlueprintStore:
    path = tmp_path / "blueprints.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if entries is not None:
        store = BlueprintStore(path, miss_log_path=tmp_path / "misses.jsonl", autoload=False)
        for entry in entries:
            store.append(entry)
        store.load(force=True)
        return store
    return BlueprintStore(path, miss_log_path=tmp_path / "misses.jsonl")


def _converged_entry(store: BlueprintStore) -> dict:
    key = blueprint_key(
        hero_hand=SPOT["hero_range"],
        villain_range=SPOT["villain_ranges"][0],
        board=SPOT["board"],
        pot=SPOT["starting_pot"],
        effective_stack=SPOT["effective_stack"],
        legal_actions=SPOT["legal_actions"],
        spot_id=SPOT["spot_id"],
        hero_position=SPOT["hero_position"],
        action_history=SPOT["action_history"],
        rake=SPOT["rake"],
    )
    return {
        "key": key,
        "spot": SPOT,
        "epsilon": 0.001,
        "converged": True,
        "response": {
            "chosen_action": "ALL_IN",
            "actions": [{"action": "ALL_IN", "ev": 12.5, "is_recommended": True}],
            "hero_ev": 12.5,
            "exploitability": 0.0005,
            "converged": True,
            "epsilon_target": 0.001,
        },
    }


def _lookup_provider(store: BlueprintStore, monkeypatch) -> SolverProvider:
    def _boom_native(self, payload):  # ne doit jamais être appelé en lookup-only
        raise AssertionError("native solve called in lookup-only mode")

    def _boom_http(self, payload):
        raise AssertionError("http solve called in lookup-only mode")

    monkeypatch.setenv("POKER_LIVE_LOOKUP_ONLY", "1")
    provider = SolverProvider(blueprint_store=store)
    monkeypatch.setattr(SolverProvider, "_invoke_native", _boom_native)
    monkeypatch.setattr(SolverProvider, "_invoke_http", _boom_http)
    return provider


def test_lookup_only_miss_returns_no_blueprint(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    provider = _lookup_provider(store, monkeypatch)
    response = provider.solve_spot_v2(**SPOT)
    assert response["fallback_used"] is True
    assert response["fallback_reason"] == "no_blueprint"
    assert response["chosen_action"] == ""
    assert not response["actions"]


def test_lookup_only_hit_serves_blueprint(monkeypatch, tmp_path):
    store = _make_store(tmp_path)
    store.append(_converged_entry(store))
    provider = _lookup_provider(store, monkeypatch)
    response = provider.solve_spot_v2(**SPOT)
    assert response["fallback_used"] is False
    assert response["chosen_action"] == "ALL_IN"
    assert response["backend"] == "blueprint"
    assert response["converged"] is True


def test_key_parity_generator_vs_live_lookup(tmp_path):
    """Le générateur écrit avec blueprint_key(spot) ; le live interroge avec
    le payload — les deux doivent produire la même clé (Phase 0.6.4 / 6g)."""
    store = _make_store(tmp_path, entries=[])
    gen_key = blueprint_key(
        hero_hand=SPOT["hero_range"],
        villain_range=SPOT["villain_ranges"][0],
        board=SPOT["board"],
        pot=SPOT["starting_pot"],
        effective_stack=SPOT["effective_stack"],
        legal_actions=SPOT["legal_actions"],
        spot_id=SPOT["spot_id"],
        hero_position=SPOT["hero_position"],
        action_history=SPOT["action_history"],
        rake=SPOT["rake"],
    )
    live_key = SolverProvider._blueprint_key(dict(SPOT))
    assert gen_key == live_key


def test_store_never_persists_non_converged(tmp_path):
    store = _make_store(tmp_path)
    entry = _converged_entry(store)
    entry["converged"] = False
    assert store.append(entry) is False
    assert store.path.exists() is False or entry["key"] not in {
        json.loads(line)["key"]
        for line in store.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def test_store_skips_non_converged_lines_at_load(tmp_path):
    path = tmp_path / "blueprints.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    bad = {"key": "k1", "converged": False, "response": {"chosen_action": "X"}}
    good = {"key": "k2", "converged": True, "response": {"chosen_action": "Y", "actions": []}}
    path.write_text(json.dumps(bad) + "\n" + json.dumps(good) + "\n", encoding="utf-8")
    store = BlueprintStore(path, miss_log_path=tmp_path / "misses.jsonl")
    assert store.lookup("k1") is None
    assert store.lookup("k2") is not None


def test_bet_out_of_tolerance_is_refused(monkeypatch, tmp_path):
    """60% pot avec menu {25,33,50,66,75,100,150} et tol ±2% ⇒ refus
    (plus proche nœud 0.66, delta 6% ≫ tolérance)."""
    store = _make_store(tmp_path)
    provider = _lookup_provider(store, monkeypatch)
    payload = dict(SPOT, action_history=["villain:bet:6.0"])
    response = provider.solve_spot_v2(**payload)
    assert response["fallback_reason"] == "no_blueprint"
    assert response["metadata"]["native_reason"] == "bet_out_of_quantization_tolerance"


def test_bet_within_tolerance_passes_quantization(monkeypatch, tmp_path):
    """33% pot (dans le menu) ne déclenche pas le refus de quantification."""
    store = _make_store(tmp_path)
    provider = _lookup_provider(store, monkeypatch)
    payload = dict(SPOT, action_history=["villain:bet:3.3"])
    response = provider.solve_spot_v2(**payload)
    assert response["fallback_reason"] == "no_blueprint"  # spot non couvert
    assert response["metadata"]["native_reason"] != "bet_out_of_quantization_tolerance"


def test_quantize_observed_bet_semantics():
    assert quantize_observed_bet(7.0, 10.0) is None  # 70% hors tolérance (Δ 4% au nœud 0.66)
    assert quantize_observed_bet(3.3, 10.0) == pytest.approx(0.33)
    assert quantize_observed_bet(0.0, 10.0) is None
    assert quantize_observed_bet(1.0, 0.0) is None  # pot invalide


def test_miss_telemetry_written(tmp_path):
    store = _make_store(tmp_path)
    store.record_miss("clef-test", {"spot_id": "x"}, reason="miss")
    store.record_miss("clef-test", {"spot_id": "x"}, reason="miss")  # dédup
    lines = store.miss_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["key"] == "clef-test"
    assert record["reason"] == "miss"


def test_default_store_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom" / "bp.jsonl"
    monkeypatch.setenv("POKER_BLUEPRINT_PATH", str(custom))
    bp_module._default_store = None
    try:
        store = bp_module.default_blueprint_store()
        assert store.path == custom
    finally:
        monkeypatch.delenv("POKER_BLUEPRINT_PATH", raising=False)
        bp_module._default_store = None
