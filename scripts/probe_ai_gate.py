#!/usr/bin/env python
"""Sonde manuelle du gate IA (Jev proxy ou Djev officiel).

But : rendre visible en une commande l'état réel du gate, sans jamais
afficher de secret. Le script charge la configuration par défaut
(fichier + env), envoie une requête minimale et résume la décision.

Sortie :
- code 0 : réponse parsée (``reason == "parsed"``) ;
- code 1 : fail-open (réseau, HTTP, réponse malformée, clé absente) ;
- code 2 : erreur de configuration.

Exemples :
    python scripts/probe_ai_gate.py
    python scripts/probe_ai_gate.py --provider jev --timeout 2
    python scripts/probe_ai_gate.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.djev_gate import DjevGateConfig  # noqa: E402
from src.bot.djev_gate import query as djev_query
from src.bot.jev_gate import JevGateConfig  # noqa: E402
from src.bot.jev_gate import query as jev_query

DEFAULT_STATE = "preflop NLHE, hero AKs BTN, pot 3.5bb, hero to act, no contradiction"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("djev", "jev"),
        default="djev",
        help="djev = endpoint officiel / proxy loopback ; jev = gate historique",
    )
    parser.add_argument("--state", default=DEFAULT_STATE, help="état textuel envoyé")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="timeout en secondes (override la configuration)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="sortie JSON machine (pas de texte décoratif)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.provider == "djev":
            overrides = {"timeout_s": args.timeout} if args.timeout else None
            cfg = DjevGateConfig.from_env(overrides=overrides)
            decision = djev_query(args.state, config=cfg)
        else:
            overrides = {"timeout_s": args.timeout} if args.timeout else None
            cfg = JevGateConfig.from_env(overrides=overrides)
            decision = jev_query(args.state, config=cfg)
    except Exception as exc:  # config illisible : ne jamais masquer l'erreur
        print(f"probe_ai_gate: configuration invalide: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    ok = decision.reason == "parsed"
    payload = {
        "provider": args.provider,
        "endpoint": str(cfg.base_url),
        "model": cfg.model,
        "mode": cfg.mode,
        "offline_mode": bool(cfg.offline_mode),
        "reason": decision.reason,
        "ok": ok,
        "latency_ms": round(float(decision.latency_ms or 0.0), 1),
        "go": decision.go,
        "tier": decision.tier,
        "tier_confidence": decision.tier_confidence,
        "risky": decision.risky,
        "effort": decision.effort,
        "effort_confidence": decision.effort_confidence,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{args.provider}: endpoint={payload['endpoint']} "
            f"model={payload['model']} mode={payload['mode']} "
            f"offline={payload['offline_mode']}"
        )
        print(
            f"résultat: {payload['reason']} ({payload['latency_ms']:.0f} ms) "
            f"go={payload['go']} tier={payload['tier']} "
            f"risky={payload['risky']} effort={payload['effort']}"
        )
        if not ok:
            print(
                "fail-open: l'heuristique est conservée ; "
                "vérifier le proxy/endpoint et les logs DJEV/JEV.",
                file=sys.stderr,
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
