"""Rejeu offline du DjevGate officiel sur les crops runtime_failures.

Clone de scripts/eval_jev_gate.py sur src/bot/djev_gate.py : mêmes états
texte + mêmes questions go/tier/risky/effort, métriques accord/p50/p95/
fail-open/coût + colonnes source (lan/cloud) + model + tier_confidence.
Mode A/B : --lan-url compare cloud officiel vs LAN loopback ; la preuve
câble débranché (URL morte -> fail-open, zéro exception) est intégrée.

Usage:
    python scripts/eval_djev_gate.py [--mode observer] [--limit N]
        [--no-network] [--lan-url http://127.0.0.1:4000] [--out rapport.json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot.djev_gate import (  # noqa: E402
    DjevGateConfig,
    apply_policy,
    build_questions,
    build_state,
    query,
)

ROOT = Path(__file__).resolve().parents[1]
INCIDENTS = ROOT / "dataset" / "runtime_failures" / "incidents.jsonl"


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
    with_crops = [r for r in rows if (r.get("timestamp") or "")[:19]]
    rest = [r for r in rows if r not in with_crops]
    ordered = with_crops + rest
    return ordered[:limit] if limit > 0 else ordered


def state_from_incident(incident: dict) -> tuple[str, bool]:
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
    return build_state(snapshot), bool(readiness.get("actionable", False))


def _is_loopback(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="observer",
                    choices=["observer", "enforcing", "off"])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--lan-url", default="",
                    help="URL LAN loopback Djev (ou env POKER_DJEV_LAN_URL). "
                         "Si vide : cloud officiel seul.")
    ap.add_argument("--lan-timeout-s", type=float, default=5.0)
    ap.add_argument("--out", default="",
                    help="Chemin JSON du rapport A/B (optionnel).")
    args = ap.parse_args()

    lan_url = (args.lan_url or os.environ.get("POKER_DJEV_LAN_URL", "")).strip()
    ab_mode = bool(lan_url)

    incidents = load_incidents(args.limit)
    print(f"incidents: {len(incidents)} (mode={args.mode}"
          f"{', A/B cloud vs lan' if ab_mode else ''})")
    if args.no_network:
        print("no-network: construction des états uniquement (aucun appel)")
    base = None
    config_path = os.environ.get("POKER_CONFIG", "config.json")
    try:
        with open(config_path, encoding="utf-8") as fh:
            config_data = json.load(fh)
        base = (((config_data.get("bot", {}) or {}).get("ai_gate", {}) or {})
                .get("djev", {}) or {}) or None
    except (OSError, ValueError):
        pass
    cfg = DjevGateConfig.from_env({"mode": args.mode}, base=base)
    lan_cfg = None
    if ab_mode:
        lan_cfg = DjevGateConfig(mode="observer", base_url=lan_url,
                                 timeout_s=args.lan_timeout_s)
    questions = build_questions()
    lat: list[float] = []
    lan_lat: list[float] = []
    agree = 0
    decided = 0
    fail_open = 0
    lan_fail_open = 0
    ab_agree = 0
    ab_compared = 0
    ab_false_go = 0
    models: set[str] = set()
    ab_rows: list[dict] = []
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
        models.add(str((decision.raw or {}).get("model", cfg.model)))
        cloud_ok = not (decision.go is None and decision.tier is None)
        djev_go: bool | None = None
        if not cloud_ok:
            fail_open += 1
            print(f"    DJEV fail-open ({decision.reason}) {decision.latency_ms:.0f}ms")
            if not ab_mode:
                continue
        else:
            decided += 1
            allowed, reason = apply_policy(heuristic, decision, config=cfg)
            djev_go = (decision.go or 0) >= 0.5
            if djev_go == heuristic:
                agree += 1
            print(
                f"    DJEV go={decision.go} tier={decision.tier} "
                f"({decision.tier_confidence}) risky={decision.risky} "
                f"effort={decision.effort} model={cfg.model} "
                f"{decision.latency_ms:.0f}ms -> enforcing={allowed} ({reason})"
            )
        if ab_mode and lan_cfg is not None and not args.no_network:
            lan_decision = query(state, questions, config=lan_cfg)
            lan_lat.append(lan_decision.latency_ms)
            if lan_decision.go is None and lan_decision.tier is None:
                lan_fail_open += 1
                print(f"    LAN fail-open ({lan_decision.reason}) "
                      f"{lan_decision.latency_ms:.0f}ms")
            else:
                lan_go = (lan_decision.go or 0) >= 0.5
                ab_rows.append({
                    "timestamp": ts,
                    "category": inc.get("category"),
                    "heuristic_go": heuristic,
                    "cloud_go": djev_go,
                    "lan_go": lan_go,
                    "cloud_model": cfg.model,
                    "lan_model": lan_cfg.model,
                    "cloud_tier_confidence": decision.tier_confidence,
                    "lan_tier_confidence": lan_decision.tier_confidence,
                    "cloud_latency_ms": round(decision.latency_ms, 1),
                    "lan_latency_ms": round(lan_decision.latency_ms, 1),
                })
                if djev_go is None:
                    print(f"    LAN seul a decide (cloud fail-open) : "
                          f"lan_go={lan_go} {lan_decision.latency_ms:.0f}ms")
                else:
                    ab_compared += 1
                    if lan_go == djev_go:
                        ab_agree += 1
                    if lan_go and not djev_go:
                        ab_false_go += 1
                        print("    LAN FAUX-DEBLOCAGE : lan go alors que cloud no-go")
                print(f"    LAN go={lan_decision.go} tier={lan_decision.tier} "
                      f"({lan_decision.tier_confidence}) "
                      f"{lan_decision.latency_ms:.0f}ms")
    print("\n===== metrics =====")
    print(f"queried={decided + fail_open} decided={decided} fail_open={fail_open}")
    if decided:
        print(f"agreement heuristic/djev: {agree}/{decided} = {agree / decided:.2f}")
    if lat:
        print(f"latency p50={statistics.median(lat):.0f}ms p95={_p95(lat):.0f}ms "
              f"max={max(lat):.0f}ms")
    print(f"models seen: {sorted(models) or ['n/a']} (attendu jev-1.13.0 piné)")
    print(f"offline_mode={cfg.offline_mode} (WAN refusée si true)")
    if ab_mode:
        print("\n===== A/B cloud vs lan =====")
        if ab_compared:
            print(f"accord cloud/lan: {ab_agree}/{ab_compared} = "
                  f"{ab_agree / ab_compared:.2f}  [cible >= 0.90]")
        else:
            print("accord cloud/lan: n/a (aucun cas compare)")
        print(f"faux-deblocage lan: {ab_false_go}  [cible 0]")
        print(f"fail-open lan: {lan_fail_open}")
        if lan_lat:
            print(f"latency lan p50={statistics.median(lan_lat):.0f}ms "
                  f"p95={_p95(lan_lat):.0f}ms max={max(lan_lat):.0f}ms")
        dead = query("street flop. hero As Kd. board Qh 7s 2c. pot 125. "
                     "buttons fold/call/raise. state confidence 0.82",
                     questions,
                     config=DjevGateConfig(mode="observer",
                                           base_url="http://127.0.0.1:9",
                                           timeout_s=2.0))
        dead_ok = dead.go is None and dead.tier is None
        print(f"fail-open cable debranche: {'OK' if dead_ok else 'KO'} "
              f"({dead.reason})")
        go_phase3 = (ab_compared > 0
                     and ab_agree / ab_compared >= 0.90
                     and ab_false_go == 0 and dead_ok)
        print(f"GO phase 3 (observer texte live): {'OUI' if go_phase3 else 'NON'}")
        if args.out:
            report = {
                "cloud_url": cfg.base_url,
                "lan_url": lan_url,
                "model": cfg.model,
                "limit": args.limit,
                "accord_cloud_lan": [ab_agree, ab_compared],
                "faux_deblocage": ab_false_go,
                "fail_open_cloud": fail_open,
                "fail_open_lan": lan_fail_open,
                "failopen_cable_debranche": dead_ok,
                "go_phase3": go_phase3,
                "cases": ab_rows,
            }
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            print(f"rapport ecrit : {out_path}")
        return 0 if go_phase3 else 1
    return 0


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    idx = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[idx]


if __name__ == "__main__":
    raise SystemExit(main())
