"""Auto-labeling des incidents runtime_failures par Jev (offline, jamais de live).

Pour chaque incident de ``dataset/runtime_failures/incidents.jsonl``,
construit le même état texte que le gate (via ``state_from_incident`` du
script d'eval) et demande à Jev une classification ``cause`` (choice) +
``severity`` (score). Le label proposé est écrit dans un fichier de sortie
séparé — le dataset source n'est jamais modifié. Fail-open : label
``unknown`` si le proxy ne répond pas.

Usage:
    python scripts/jev_autolabel_incidents.py [--limit N] [--out labels.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.eval_jev_gate import load_incidents, state_from_incident  # noqa: E402
from src.bot.jev_gate import JevGateConfig  # noqa: E402

CAUSE_CRITERIA = {
    "vision_degraded": "OCR/crop illisible ou partiel : cartes, pot ou boutons manquants.",
    "state_incoherent": "Champs visibles mais contradictoires entre eux.",
    "stale_frame": "Frame trop vieille ou figée, état périmé.",
    "loop_error": "Erreur logicielle de la boucle (exception, timeout interne).",
    "conservative_block": "Gate conservateur sur état lisible, pas de vrai problème.",
    "unknown": "Cause indéterminée.",
}

SEVERITY_RUBRIC = ["noise", "to review", "to fix now"]


def build_autolabel_questions() -> dict:
    return {
        "cause": {
            "type": "choice",
            "instructions": (
                "What is the most likely root cause of this poker table runtime incident?"
            ),
            "criteria": dict(CAUSE_CRITERIA),
        },
        "severity": {
            "type": "score",
            "instructions": "How urgently does this incident need a fix?",
            "criteria": list(SEVERITY_RUBRIC),
        },
    }


def autolabel(state: str, questions: dict, *, config: JevGateConfig) -> dict:
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
        return {"cause": "unknown", "cause_confidence": None,
                "severity": None, "reason": f"fail-open: {type(exc).__name__}"}
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        return {"cause": "unknown", "cause_confidence": None,
                "severity": None, "reason": "fail-open: malformed"}
    cause_a = answers.get("cause") if isinstance(answers.get("cause"), dict) else {}
    sev_a = answers.get("severity") if isinstance(answers.get("severity"), dict) else {}
    cause = cause_a.get("choice")
    return {
        "cause": cause if cause in CAUSE_CRITERIA else "unknown",
        "cause_confidence": cause_a.get("confidence")
        if isinstance(cause_a.get("confidence"), (int, float)) else None,
        "severity": sev_a.get("score")
        if isinstance(sev_a.get("score"), (int, float)) else None,
        "reason": "parsed",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="dataset/runtime_failures/jev_labels.jsonl")
    args = ap.parse_args()

    incidents = load_incidents(args.limit)
    print(f"incidents: {len(incidents)}")
    cfg = JevGateConfig.from_env()
    questions = build_autolabel_questions()
    out_path = Path(args.out)
    counts: dict[str, int] = {}
    with open(out_path, "w", encoding="utf-8") as fh:
        for inc in incidents:
            state, _ = state_from_incident(inc)
            label = autolabel(state, questions, config=cfg)
            row = {
                "timestamp": inc.get("timestamp"),
                "session_id": inc.get("session_id"),
                "incident_id": inc.get("incident_id"),
                "category": inc.get("category"),
                "jev_cause": label["cause"],
                "jev_cause_confidence": label["cause_confidence"],
                "jev_severity": label["severity"],
            }
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
            counts[label["cause"]] = counts.get(label["cause"], 0) + 1
    print(f"labels -> {out_path}")
    print("causes:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
