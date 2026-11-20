"""Tests de la logique du gate de performance F-09 (sans exécuter le banc).

Le gate compare la latence froide du runtime à une baseline versionnée. Sa
logique a deux propriétés à ne pas perdre de vue, apprises d'un échec de CI
reproductible :

- un spot qui **sature** le délai de garde du solveur mesure ce délai, pas le
  coût du solveur : le compter comme une régression de latence est un faux
  positif (le remède est le budget, pas le solveur) ;
- un **fallback produit** et un **backend multiway absent** sont des
  invariants durs : ils doivent échouer partout, sur n'importe quelle machine.

Ces tests portent sur ``check()`` avec des charges synthétiques, donc ils ne
dépendent ni du solveur ni du matériel.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_perf_gate as gate


def _payload(
    *,
    calibration_ms: float,
    hu_cold: dict[str, float],
    hu_timeouts: dict[str, bool],
    mw_cold: dict[str, float],
    hu_fallbacks: int = 0,
    mw_backends: list[str] | None = None,
) -> dict:
    return {
        "kind": "perf_baseline",
        "repeat": 3,
        "calibration_ms": calibration_ms,
        "heads_up": {
            "cold_ms": hu_cold,
            "timeouts": hu_timeouts,
            "fallbacks": hu_fallbacks,
            "timeout_count": sum(1 for v in hu_timeouts.values() if v),
            "backends": ["native_solver", "preflop_precomputed"],
        },
        "multiway": {
            "cold_ms": mw_cold,
            "timeouts": dict.fromkeys(mw_cold, False),
            "fallbacks": 0,
            "timeout_count": 0,
            "backends": mw_backends if mw_backends is not None else ["multiway_mccfr"],
        },
    }


def _reference() -> dict:
    return {
        "kind": "perf_baseline",
        "repeat": 5,
        "calibration_ms": 10.0,
        "heads_up": {
            "cold_ms": {
                "flop_3bp_qq": 648.0,
                "flop_srp_akhk": 887.0,
                "preflop_btn_aa": 194.0,
                "turn_ts9s": 94.0,
            },
            "fallbacks": 0,
            "backends": ["native_solver", "preflop_precomputed"],
        },
        "multiway": {
            "cold_ms": {"n=3": 680.0, "n=6": 88.0},
            "fallbacks": 0,
            "backends": ["multiway_mccfr"],
        },
    }


def _ci_like() -> dict:
    """Charge reconstruite depuis un run CI réel (runner lent, 2 saturations)."""
    return _payload(
        calibration_ms=10.0,
        hu_cold={
            "flop_3bp_qq": 900.0,  # ~+39 % : au-delà du seuil, mais machine lente
            "flop_srp_akhk": 3327.0,  # saturé (budget 800 + garde 2000)
            "preflop_btn_aa": 270.0,
            "turn_ts9s": 313.0,  # saturé aussi
        },
        hu_timeouts={
            "flop_3bp_qq": False,
            "flop_srp_akhk": True,
            "preflop_btn_aa": False,
            "turn_ts9s": True,
        },
        mw_cold={"n=3": 928.0, "n=6": 124.0},
    )


def test_ci_like_payload_passes_by_default():
    """La latence est informative : une machine lente ne casse pas le gate."""
    failures = gate.check(_ci_like(), _reference())
    assert failures == []


def test_saturated_spots_are_not_reported_as_regression():
    failures = gate.check(_ci_like(), _reference())
    assert not any("flop_srp_akhk" in f for f in failures)
    assert not any("turn_ts9s" in f for f in failures)


def test_product_fallback_fails_the_gate():
    payload = _ci_like()
    payload["heads_up"]["fallbacks"] = 2
    failures = gate.check(payload, _reference())
    assert any("fallback" in f for f in failures)


def test_missing_multiway_backend_fails_the_gate():
    payload = _ci_like()
    payload["multiway"]["backends"] = []
    failures = gate.check(payload, _reference())
    assert any("backend multiway absent" in f for f in failures)


def test_strict_latency_makes_regression_blocking():
    """Sur la machine de référence, la latence redevient bloquante."""
    payload = _payload(
        calibration_ms=10.0,
        hu_cold={
            "flop_3bp_qq": 1300.0,  # +100 % sans saturation
            "flop_srp_akhk": 887.0,
            "preflop_btn_aa": 194.0,
            "turn_ts9s": 94.0,
        },
        hu_timeouts=dict.fromkeys(
            ["flop_3bp_qq", "flop_srp_akhk", "preflop_btn_aa", "turn_ts9s"], False
        ),
        mw_cold={"n=3": 680.0, "n=6": 88.0},
    )
    assert gate.check(payload, _reference()) == []  # informatif : aucun échec
    strict = gate.check(payload, _reference(), strict_latency=True)
    assert any("flop_3bp_qq" in f for f in strict)


def test_timeout_reason_is_detected_from_bench_rows():
    """Un `fallback_reason=solver_timeout` est classé comme saturation, pas fallback."""
    payload = {
        "results": [
            {
                "pass": "cold",
                "spot_id": "a",
                "elapsed_ms": 2800.0,
                "fallback_used": True,
                "fallback_reason": "solver_timeout",
            },
            {
                "pass": "cold",
                "spot_id": "b",
                "elapsed_ms": 100.0,
                "fallback_used": False,
                "fallback_reason": None,
            },
        ]
    }
    cold = gate._cold_by_spot(payload)
    assert cold["a"]["timeout"] is True
    assert cold["b"]["timeout"] is False


def test_solve_budget_mirrors_runtime():
    """Les budgets utilisés pour détecter la saturation suivent le runtime."""
    assert gate._solve_budget_ms("heads_up", "flop_srp_akhk") == 800.0
    assert gate._solve_budget_ms("multiway", "n=3") == 700.0
    assert gate._solve_budget_ms("multiway", "n=6") == 500.0
