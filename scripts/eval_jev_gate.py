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
    ap.add_argument("--lan-url", default="",
                    help="URL backend local JUG (ou env POKER_JEV_LAN_URL, "
                         "jamais en dur). Si vide : comportement historique "
                         "(un seul backend).")
    ap.add_argument("--lan-timeout-s", type=float, default=5.0,
                    help="Timeout par requete LAN (defaut 5s : on mesure, "
                         "on ne gate pas).")
    ap.add_argument("--out", default="",
                    help="Chemin JSON du rapport A/B (optionnel).")
    args = ap.parse_args()

    lan_url = (args.lan_url or os.environ.get("POKER_JEV_LAN_URL", "")).strip()
    ab_mode = bool(lan_url)

    incidents = load_incidents(args.limit)
    print(f"incidents: {len(incidents)} (mode={args.mode}"
          f"{', A/B cloud vs lan' if ab_mode else ''})")
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
    lan_cfg = None
    if ab_mode:
        # Second avis local : config isolee, observer, jamais d'enforcing,
        # jamais de cle (le shim/JUG local n'en demande pas).
        lan_cfg = JevGateConfig(mode="observer", base_url=lan_url,
                                timeout_s=args.lan_timeout_s)
    questions = build_questions()
    lat: list[float] = []
    lan_lat: list[float] = []
    agree = 0
    decided = 0
    fail_open = 0
    lan_fail_open = 0
    # A/B : accord go/no-go cloud vs lan + faux-deblocage (lan go la ou
    # cloud dit no-go). Cible Phase 3 : accord >= 90 %, faux-deblocage 0.
    ab_agree = 0
    ab_compared = 0
    ab_false_go = 0
    costs: set[str] = set()
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
        if ab_mode and lan_cfg is not None and not args.no_network:
            # Requete isolee vers JUG avec le MEME state/questions.
            # Jamais decide()/apply_policy cote lan : on compare les avis
            # bruts, on ne gate rien.
            lan_decision = query(state, questions, config=lan_cfg)
            lan_lat.append(lan_decision.latency_ms)
            if lan_decision.go is None and lan_decision.tier is None:
                lan_fail_open += 1
                print(f"    LAN fail-open ({lan_decision.reason}) "
                      f"{lan_decision.latency_ms:.0f}ms")
            else:
                cloud_go = jev_go
                lan_go = (lan_decision.go or 0) >= 0.5
                ab_compared += 1
                if lan_go == cloud_go:
                    ab_agree += 1
                if lan_go and not cloud_go:
                    ab_false_go += 1
                    print("    LAN FAUX-DEBLOCAGE : lan go alors que cloud no-go")
                ab_rows.append({
                    "timestamp": ts,
                    "category": inc.get("category"),
                    "heuristic_go": heuristic,
                    "cloud_go": cloud_go,
                    "lan_go": lan_go,
                    "cloud_latency_ms": round(decision.latency_ms, 1),
                    "lan_latency_ms": round(lan_decision.latency_ms, 1),
                })
                print(f"    LAN go={lan_decision.go} tier={lan_decision.tier} "
                      f"risky={lan_decision.risky} "
                      f"{lan_decision.latency_ms:.0f}ms")
    print("\n===== metrics =====")
    print(f"queried={decided + fail_open} decided={decided} fail_open={fail_open}")
    if decided:
        print(f"agreement heuristic/jev: {agree}/{decided} = {agree / decided:.2f}")
    if lat:
        print(f"latency p50={statistics.median(lat):.0f}ms p95={_p95(lat):.0f}ms max={max(lat):.0f}ms")
        print(f"budget 800ms: {'OK' if _p95(lat) < 800 else 'OVER (fail-open covers it)'}")
    print(f"costs seen: {sorted(costs) or ['n/a']} (attendu '0' en free)")
    if ab_mode:
        print("\n===== A/B cloud vs lan =====")
        if ab_compared:
            print(f"accord cloud/lan: {ab_agree}/{ab_compared} = "
                  f"{ab_agree / ab_compared:.2f}  [cible >= 0.90]")
        else:
            print("accord cloud/lan: n/a (aucun cas compare, fail-open des "
                  "deux cotes)")
        print(f"faux-deblocage lan: {ab_false_go}  [cible 0]")
        print(f"fail-open lan: {lan_fail_open}")
        if lan_lat:
            print(f"latency lan p50={statistics.median(lan_lat):.0f}ms "
                  f"p95={_p95(lan_lat):.0f}ms max={max(lan_lat):.0f}ms")
        # Preuve cable debranche : URL morte -> fail-open, zero exception.
        dead = query("street flop. hero As Kd. board Qh 7s 2c. pot 125. "
                     "buttons fold/call/raise. state confidence 0.82",
                     questions,
                     config=JevGateConfig(mode="observer",
                                          base_url="http://127.0.0.1:9",
                                          timeout_s=2.0))
        dead_ok = dead.go is None and dead.tier is None
        print(f"fail-open cable debranche: {'OK' if dead_ok else 'KO'} "
              f"({dead.reason})")
        go_phase3 = (ab_compared > 0
                     and ab_agree / ab_compared >= 0.90
                     and ab_false_go == 0 and dead_ok)
        print(f"GO phase 3 (observer texte live): "
              f"{'OUI' if go_phase3 else 'NON'}")
        if args.out:
            report = {
                "cloud_url": cfg.base_url,
                "lan_url": lan_url,
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
            out_path.write_text(json.dumps(report, indent=2,
                                           ensure_ascii=False),
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
