"""Rejeu offline du JevGate sur les crops runtime_failures (POC, jamais de live).

Pour chaque incident ``near_miss`` avec crops (hero/pot/actions), construit un
état texte + appelle POST /v1/systemone via src.bot.jev_gate, puis compare au
label d'incident. Métriques : accord, latence p50/p95, fail-open, coût.

Usage:
    python scripts/eval_jev_gate.py [--mode observer] [--limit N] [--no-network]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot.jev_gate import (  # noqa: E402
    JevGateConfig,
    apply_policy,
    build_questions,
    build_state,
    query,
)

ROOT = Path(__file__).resolve().parents[1]
INCIDENTS = ROOT / "dataset" / "runtime_failures" / "incidents.jsonl"
CROPS = ROOT / "dataset" / "runtime_failures" / "crops"


def load_incidents(limit: int = 0) -> list[dict]:
    rows: list[dict] = []
    if not INCIDENTS.exists():
        return rows
    with open(INCIDENTS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    # Incidents avec crops exploitables en priorité (ceux qui ont un timestamp).
    with_crops = [r for r in rows if (r.get("timestamp") or "")[:19]]
    rest = [r for r in rows if r not in with_crops]
    ordered = with_crops + rest
    return ordered[:limit] if limit > 0 else ordered


def state_from_incident(incident: dict) -> tuple[str, bool]:
    """État texte + heuristique (actionnable ou non) depuis le contexte incident."""
    ctx = incident.get("context") or {}
    readiness = ctx.get("readiness") or {}
    validation = ctx.get("validation") or {}
    meta = (validation.get("metadata") or {}) if isinstance(validation, dict) else {}
    snapshot = {
        "street": meta.get("street", "?"),
        "hero_cards": ["??"] * int(meta.get("hero_cards_count", 0) or 0),
        "board": ["??"] * int(meta.get("board_count", 0) or 0),
        "pot": meta.get("pot", "?"),
        "legal_actions": ["?"] * int(meta.get("legal_action_count", 0) or 0),
        "state_confidence": readiness.get("score", readiness.get("state_confidence", "?")),
        "metadata": {
            "readiness_state": readiness.get("state"),
            "validation_state": validation.get("state"),
        },
    }
    heuristic_allowed = bool(readiness.get("actionable", False))
    return build_state(snapshot), heuristic_allowed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="observer", choices=["observer", "enforcing", "off"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--no-network", action="store_true")
    args = ap.parse_args()

    incidents = load_incidents(args.limit)
    print(f"incidents: {len(incidents)} (mode={args.mode})")
    if args.no_network:
        print("no-network: construction des états uniquement (aucun appel proxy)")
    base = None
    config_path = os.environ.get("POKER_CONFIG", "config.json")
    try:
        with open(config_path, encoding="utf-8") as fh:
            config_data = json.load(fh)
        base = ((config_data.get("bot", {}) or {}).get("jev_gate", {}) or {}) or None
    except (OSError, ValueError):
        pass
    cfg = JevGateConfig.from_env({"mode": args.mode}, base=base)
    questions = build_questions()
    lat: list[float] = []
    agree = 0
    decided = 0
    fail_open = 0
    costs: set[str] = set()
    for inc in incidents:
        state, heuristic = state_from_incident(inc)
        ts = str(inc.get("timestamp", "?"))
        print(f"\n--- {ts} cat={inc.get('category')} heuristic_go={heuristic}")
        print(f"    state: {state[:160]}")
        if args.no_network or cfg.mode == "off":
            print("    skipped (no query)")
            continue
        decision = query(state, questions, config=cfg)
        lat.append(decision.latency_ms)
        if decision.cost is not None:
            costs.add(str(decision.cost))
        if decision.go is None and decision.tier is None:
            fail_open += 1
            print(f"    JEV fail-open ({decision.reason}) {decision.latency_ms:.0f}ms")
            continue
        decided += 1
        allowed, reason = apply_policy(heuristic, decision, config=cfg)
        jev_go = (decision.go or 0) >= 0.5
        if jev_go == heuristic:
            agree += 1
        print(
            f"    JEV go={decision.go} tier={decision.tier} "
            f"risky={decision.risky} effort={decision.effort} "
            f"{decision.latency_ms:.0f}ms -> enforcing={allowed} ({reason})"
        )
    print("\n===== metrics =====")
    print(f"queried={decided + fail_open} decided={decided} fail_open={fail_open}")
    if decided:
        print(f"agreement heuristic/jev: {agree}/{decided} = {agree / decided:.2f}")
    if lat:
        print(f"latency p50={statistics.median(lat):.0f}ms p95={_p95(lat):.0f}ms max={max(lat):.0f}ms")
        print(f"budget 800ms: {'OK' if _p95(lat) < 800 else 'OVER (fail-open covers it)'}")
    print(f"costs seen: {sorted(costs) or ['n/a']} (attendu '0' en free)")
    return 0


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    idx = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[idx]


if __name__ == "__main__":
    raise SystemExit(main())
