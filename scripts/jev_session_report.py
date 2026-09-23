"""Rapport de session papier en langage naturel via chat gratuit (offline).

Lit ``runtime_history`` via ``RuntimeHistoryStore.export_records`` (inclut les
.bak par rotation), résume avec ``summarize`` de ``jev_judge_sessions`` puis
demande au modèle gratuit ``muse-spark-1.3-contributor-free`` (endpoint
``/v1/chat/completions`` du proxy :4000) un résumé texte en français.

Offline uniquement : le prompt ne contient que des compteurs agrégés
(jamais d'image, jamais de live). Fail-open : tout échec -> raison texte,
jamais d'exception vers l'appelant. Timeout défaut 30 s (génération texte
plus lente que /v1/systemone ; prototype live ~14 s).

Usage:
    python scripts/jev_session_report.py [--store log/runtime_history.jsonl]
        [--batch 0] [--limit 0] [--out rapport.md]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.jev_judge_sessions import summarize  # noqa: E402
from src.runtime.history_store import RuntimeHistoryStore  # noqa: E402

DEFAULT_MODEL = "muse-spark-1.3-contributor-free"


def build_report_prompt(label: str, summary: dict) -> str:
    streams = ", ".join(f"{k}={v}" for k, v in summary["streams"].items()) or "none"
    incs = ", ".join(f"{k}={v}" for k, v in summary["incidents"].items()) or "none"
    return (
        "Tu es l'assistant QA d'un bot de poker (sessions papier, aucun argent "
        "réel). Voici les compteurs agrégés d'une session : "
        f"{label}: {summary['total']} records ({streams}). incidents: {incs}. "
        "Rédige en français un rapport court : 1) santé globale en une phrase, "
        "2) anomalies notables (incidents, erreurs solver), "
        "3) une recommandation concrète pour la prochaine session. "
        "Reste factuel, pas de jargon inutile."
    )


def chat(prompt: str, *, model: str, base_url: str, timeout_s: float) -> dict:
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}],
         "max_tokens": 400}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:
        return {"report": None, "reason": f"fail-open: {type(exc).__name__}"}
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"report": None, "reason": "fail-open: malformed"}
    if not isinstance(content, str) or not content.strip():
        return {"report": None, "reason": "fail-open: empty"}
    return {"report": content.strip(), "reason": "parsed"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="log/runtime_history.jsonl")
    ap.add_argument("--batch", type=int, default=None,
                    help="index de batch export_record_batches (au lieu du store entier)")
    ap.add_argument("--limit", type=int, default=0,
                    help="0 = tout le store (résumé agrégé, prompt court)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default="http://127.0.0.1:4000")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out", default=None, help="fichier texte du rapport (sinon stdout)")
    args = ap.parse_args()

    store = RuntimeHistoryStore(enabled=True, file_path=args.store)
    if args.batch is not None:
        batches = store.export_record_batches()
        if not batches:
            print("aucun batch dans le store")
            return 1
        try:
            records = batches[args.batch]["records"]
        except IndexError:
            print("index de batch invalide")
            return 1
        label = f"batch[{args.batch}]"
    else:
        records = store.export_records()
        label = args.store
    if args.limit > 0:
        records = records[-args.limit :]
    summary = summarize(records)
    print(f"{label}: {summary}")
    prompt = build_report_prompt(label, summary)
    result = chat(prompt, model=args.model, base_url=args.base_url,
                  timeout_s=args.timeout)
    if result["report"] is None:
        print("JEV rapport: indisponible (%s)" % result["reason"])
        return 1
    if args.out:
        Path(args.out).write_text(result["report"] + "\n", encoding="utf-8")
        print(f"rapport -> {args.out}")
    else:
        print("--- rapport ---")
        print(result["report"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
