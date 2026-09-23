"""Juge de sessions papier via Jev (offline, jamais de live).

Compare deux batches de ``runtime_history`` (ex. session A vs session B,
ou corpus avant/après un changement de config) et demande à Jev quel
corpus reflète la session la plus saine. Généralisation de
``scripts/eval_jev_gate.py`` : même wire format ``/v1/systemone``
(state string, types noul/choice/score), lecture via
``RuntimeHistoryStore.export_records`` (inclut les .bak par rotation).

Usage:
    python scripts/jev_judge_sessions.py --a log/runtime_history.jsonl \
        --b log/other_history.jsonl [--limit 0]
    python scripts/jev_judge_sessions.py --batch-a 0 --batch-b 1
        (compare deux batches export_record_batches du même store)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot.jev_gate import JevGateConfig  # noqa: E402
from src.runtime.history_store import RuntimeHistoryStore  # noqa: E402


def load_records(path: str, limit: int) -> list[dict]:
    """Lit via RuntimeHistoryStore (inclut .bak par rotation, normalisé)."""
    store = RuntimeHistoryStore(enabled=True, file_path=path)
    records = store.export_records()
    return records[-limit:] if limit > 0 else records


def summarize(records: list[dict]) -> dict:
    counts: dict[str, int] = {}
    incidents: dict[str, int] = {}
    for rec in records:
        stream = str(rec.get("stream", "?"))
        counts[stream] = counts.get(stream, 0) + 1
        if stream == "incidents":
            code = str(rec.get("id", rec.get("incident_id", "?")))
            incidents[code] = incidents.get(code, 0) + 1
    return {"total": len(records), "streams": counts, "incidents": incidents}


def build_judge_state(name_a: str, sum_a: dict, name_b: str, sum_b: dict) -> str:
    def fmt(name: str, summ: dict) -> str:
        streams = ", ".join(f"{k}={v}" for k, v in summ["streams"].items()) or "none"
        incs = ", ".join(f"{k}={v}" for k, v in summ["incidents"].items()) or "none"
        return f"corpus {name}: {summ['total']} records ({streams}). incidents: {incs}"
    return (
        "Two poker bot paper sessions to compare. "
        + fmt(name_a, sum_a) + ". " + fmt(name_b, sum_b) + ". "
        + "Healthier means fewer errors, fewer incidents, coherent decision flow."
    )


def build_judge_questions() -> dict:
    return {
        "b_healthier": {
            "type": "noul",
            "instructions": "Corpus B reflects a healthier session than corpus A.",
        },
        "verdict": {
            "type": "choice",
            "instructions": "Which corpus reflects the healthier poker session?",
            "criteria": {
                "a": "Corpus A is healthier (fewer incidents, cleaner flow).",
                "b": "Corpus B is healthier (fewer incidents, cleaner flow).",
                "tie": "Both corpora look equally healthy or equally broken.",
            },
        },
        "review_effort": {
            "type": "score",
            "instructions": "How much manual review does the worse corpus need?",
            "criteria": ["almost none", "some", "a lot", "as much as possible"],
        },
    }


def judge(state: str, questions: dict, *, config: JevGateConfig) -> dict:
    body = json.dumps(
        {"model": config.model, "state": state, "questions": questions}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{config.base_url.rstrip('/')}/v1/systemone",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:
        return {"verdict": "unknown", "reason": f"fail-open: {type(exc).__name__}"}
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        return {"verdict": "unknown", "reason": "fail-open: malformed"}
    verdict_a = answers.get("verdict") if isinstance(answers.get("verdict"), dict) else {}
    b_a = answers.get("b_healthier") if isinstance(answers.get("b_healthier"), dict) else {}
    return {
        "verdict": verdict_a.get("choice", "unknown"),
        "verdict_confidence": verdict_a.get("confidence"),
        "b_healthier": b_a.get("noul"),
        "reason": "parsed",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="log/runtime_history.jsonl")
    ap.add_argument("--b", default="log/runtime_history.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch-a", type=int, default=None,
                    help="index de batch export_record_batches pour A (au lieu de --a)")
    ap.add_argument("--batch-b", type=int, default=None,
                    help="index de batch export_record_batches pour B (au lieu de --b)")
    ap.add_argument("--store", default="log/runtime_history.jsonl",
                    help="store source quand --batch-a/--batch-b sont utilisés")
    args = ap.parse_args()

    if args.batch_a is not None or args.batch_b is not None:
        store = RuntimeHistoryStore(enabled=True, file_path=args.store)
        batches = store.export_record_batches()
        if not batches:
            print("aucun batch dans le store")
            return 1
        print(f"batches: {len(batches)}")
        for i, b in enumerate(batches):
            print(f"  [{i}] session={b['session_id']} n={len(b['records'])} src={b['source_path']}")
        try:
            rec_a = batches[args.batch_a or 0]["records"]
            rec_b = batches[args.batch_b if args.batch_b is not None else -1]["records"]
        except IndexError:
            print("index de batch invalide")
            return 1
        name_a, name_b = f"batch[{args.batch_a or 0}]", f"batch[{args.batch_b if args.batch_b is not None else -1}]"
    else:
        rec_a = load_records(args.a, args.limit)
        rec_b = load_records(args.b, args.limit)
        name_a, name_b = f"A ({args.a})", f"B ({args.b})"
    sum_a, sum_b = summarize(rec_a), summarize(rec_b)
    print(f"{name_a}: {sum_a}")
    print(f"{name_b}: {sum_b}")
    cfg = JevGateConfig.from_env()
    state = build_judge_state("A", sum_a, "B", sum_b)
    result = judge(state, build_judge_questions(), config=cfg)
    print("JEV verdict:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
