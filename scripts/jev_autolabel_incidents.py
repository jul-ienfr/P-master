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

from scripts.eval_jev_gate import load_incidents  # noqa: E402
from src.bot.jev_gate import JevGateConfig, build_state  # noqa: E402

CAUSE_CRITERIA = {
    "vision_degraded": "OCR/crop illisible ou partiel : cartes, pot ou boutons manquants.",
    "state_incoherent": "Divergence STRUCTURELLE spot vs tracker (heros present/absent d'un cote, ou street differente avec heros visible). Un simple 'confidence drift' mineur n'est PAS incoherent.",
    "stale_frame": "Frame trop vieille ou figee, etat perime.",
    "loop_error": "Erreur logicielle de la boucle (exception, timeout interne).",
    "conservative_block": "Gate conservateur sur etat coherent : spot et tracker d'accord (meme street, meme visibilite heros), confiance basse mais pas de vrai probleme - ex. IDLE sans heros en debut/fin de main.",
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


def state_from_incident(incident: dict) -> tuple[str, str]:
    """État texte riche + vrai incident_id.

    Matière discriminante (le context brut est le signal le plus direct) :
    état table (canonical_spot sinon tracker : street, héros, board, pot,
    boutons, confiance), puis signaux readiness/vision/loop — en premier le
    ``context`` brut de l'incident (frame_age_ms vs max_age_ms pour stale,
    message d'erreur pour loop_error, element/consecutive_rejected/avg_score
    pour vision_quality_degraded) — puis readiness (reasons, degraded_fields),
    crop quality pot (quality_score bas = flou), fallback utilisé.
    Retourne (state, vrai incident_id).
    """
    ctx = incident.get("context") or {}
    readiness = ctx.get("readiness") or {}
    validation = ctx.get("validation") or {}
    spot = incident.get("canonical_spot") or {}
    tracker = incident.get("tracker") or {}
    decision = incident.get("decision") or {}
    incident_id = str(incident.get("incident_id") or "?")

    snapshot = dict(spot) if isinstance(spot, dict) else {}
    if not snapshot:
        snapshot = dict(tracker) if isinstance(tracker, dict) else {}
    meta = dict(snapshot.get("metadata") or {})
    # build_state sérialiserait meta["ocr_confidence"] brut : ici c'est un
    # gros dict de config OCR, pas un score -> on le retire (le signal utile
    # est pot crop quality, ajouté séparément dans extras).
    meta.pop("ocr_confidence", None)
    meta.pop("ocr", None)
    meta.setdefault("readiness_state", readiness.get("state"))
    meta.setdefault("validation_state", validation.get("state"))
    snapshot["metadata"] = meta
    state = build_state(snapshot)

    extras: list[str] = []
    # 0. Divergence spot canonique <-> tracker live — le signal readiness.
    # canonical_spot = dernier état résolu (source de la décision live),
    # tracker = dernier snapshot brut. Quand ils divergent (street, héros,
    # confiance), la jambe vision/résolution est incohérente même si chaque
    # jambe prise seule semble lisible (ex. PREFLOP Ah As conf 0.333 d'un
    # côté, IDLE sans héros conf 0.25 de l'autre).
    spot_street = spot.get("street") if isinstance(spot, dict) else None
    tracker_street = tracker.get("street") if isinstance(tracker, dict) else None
    spot_hero = spot.get("hero_cards") if isinstance(spot, dict) else None
    tracker_hero = tracker.get("hero_cards") if isinstance(tracker, dict) else None
    spot_conf = spot.get("state_confidence") if isinstance(spot, dict) else None
    tracker_conf = tracker.get("state_confidence") if isinstance(tracker, dict) else None
    # Divergence structurelle (sens métier) : présence/absence du héros, ou
    # changement de street avec héros — pas les micro-écarts float de
    # confiance (bruit : 78 % des readiness, "0.333 vs 0.25" lisible).
    struct_div = (bool(spot_hero) != bool(tracker_hero)) or (
        spot_street != tracker_street and (bool(spot_hero) or bool(tracker_hero))
    )
    if spot and tracker and struct_div:
        extras.append(
            "spot vs tracker DIVERGE (structural): "
            f"spot {spot_street}/{spot_hero} "
            f"vs tracker {tracker_street}/{tracker_hero}"
        )
    elif spot and tracker and spot_conf != tracker_conf:
        extras.append(
            f"spot vs tracker confidence drift {spot_conf} vs {tracker_conf} "
            "(minor: same street, same hero visibility)"
        )
    # 1. Context brut de l'incident — le plus discriminant, en premier.
    if isinstance(ctx.get("frame_age_ms"), (int, float)):
        extras.append(
            f"frame age {ctx['frame_age_ms']:.0f} ms "
            f"(max allowed {ctx.get('max_age_ms', '?')} ms)"
        )
    if ctx.get("error"):
        extras.append(f"loop error: {ctx['error']}")
    for key in ("element", "consecutive_rejected", "avg_score"):
        if ctx.get(key) not in (None, ""):
            extras.append(f"{key} {ctx[key]}")
    # 2. Readiness (cas runtime_readiness_not_fully_valid).
    reasons = readiness.get("reasons") or []
    if reasons:
        extras.append("readiness reasons: " + "; ".join(map(str, reasons)))
    degraded = readiness.get("degraded_fields") or []
    if degraded:
        extras.append("degraded fields: " + ", ".join(map(str, degraded)))
    if incident.get("severity"):
        extras.append(f"logged severity {incident['severity']}")
    # 3. Crop quality pot (flou) depuis vision_metadata.
    vision_meta = tracker.get("vision_metadata") or {}
    crop_q = (vision_meta.get("crop_quality") or {}) if isinstance(vision_meta, dict) else {}
    pot_q = (crop_q.get("pot") or {}) if isinstance(crop_q, dict) else {}
    if isinstance(pot_q.get("quality_score"), (int, float)):
        extras.append(f"pot crop quality {pot_q['quality_score']:.2f}")
    fallback_used = decision.get("fallback_used")
    if fallback_used:
        extras.append(f"fallback used ({decision.get('fallback_reason', '?')})")
    if extras:
        state += ". " + ". ".join(extras)
    return state, incident_id


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
