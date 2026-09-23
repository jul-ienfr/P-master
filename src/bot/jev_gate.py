"""Gate de second avis via Jev (TypeSafe System One) à travers le proxy local :4000.

Wire format validé le 2026-09-22 (campagne T1-T6) — NE PAS "améliorer" sans retester :
  POST http://127.0.0.1:4000/v1/systemone
  header: Content-Type: application/json uniquement (pas d'auth côté client)
  body: {"model": "jev-1.13-free", "state": <str>, "questions": {...}}
    - ``state`` DOIT être une string (objet -> 400).
    - types autorisés: ``noul`` / ``choice`` / ``score`` uniquement.
    - ``model`` requis (absent -> 404). POC = ``jev-1.13-free`` (cost "0").
    - ``choice`` exige ``criteria`` objet ; ``score`` exige ``criteria`` array.
  réponse: {"model", "answers": {go: {noul}, tier: {choice, confidence},
              risky: {noul}, effort: {score, confidence}}, "usage", "cost": "0"}

Politique transposée de .claude/skills/jev-model-router/hooks/policy.ts :
  min_upgrade_confidence=0.3 (bloquer coûte peu), min_downgrade_confidence=0.6
  (assouplir coûte cher), risky > 0.7 force l'escalade, sans confiance on ne
  peut que bloquer, jamais assouplir. Tout échec -> fail-open (verdict None).

Jev ne voit que du TEXTE (phrase d'état), jamais d'image/screenshot.
Config : fichier (bloc ``bot.jev_gate`` de config.json, via ``base``) puis env
(POKER_JEV_MODE, POKER_JEV_MODEL, POKER_JEV_TIMEOUT_S, POKER_JEV_BASE_URL),
puis ``overrides`` explicites (ex. CLI). Précédence : overrides > env > base.
Jamais de clé en dur (le free n'en demande pas).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("SuperBot2026")

DEFAULT_BASE_URL = "http://127.0.0.1:4000"
DEFAULT_MODEL = "jev-1.13-free"
DEFAULT_TIMEOUT_S = 0.8

MIN_UPGRADE_CONFIDENCE = 0.3
MIN_DOWNGRADE_CONFIDENCE = 0.6
RISKY_THRESHOLD = 0.7

TIER_CRITERIA = {
    "fast": (
        "Mechanical and local: hero cards, pot and buttons all clearly visible "
        "and readable, OCR confidence high, no contradiction between fields."
    ),
    "balanced": (
        "Ordinary analysis: street state readable but one field degraded "
        "(blur, partial OCR, missing stack), needs a careful second look."
    ),
    "deep": (
        "Hard or incoherent: hero cards missing, pot unreadable, buttons "
        "missing, or contradictions between fields (e.g. pot changed "
        "inconsistently). Needs escalation, never act on it."
    ),
}

EFFORT_RUBRIC = ["almost none", "some", "a lot", "as much as possible"]


@dataclass
class JevGateConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = DEFAULT_TIMEOUT_S
    mode: str = "observer"  # observer | enforcing | off
    min_upgrade_confidence: float = MIN_UPGRADE_CONFIDENCE
    min_downgrade_confidence: float = MIN_DOWNGRADE_CONFIDENCE
    risky_threshold: float = RISKY_THRESHOLD

    @classmethod
    def from_env(
        cls,
        overrides: dict[str, Any] | None = None,
        base: dict[str, Any] | None = None,
    ) -> "JevGateConfig":
        """Construit la config : fichier (``base``) < env < ``overrides``."""
        cfg = cls()
        if base:
            for key in ("mode", "model", "timeout_s", "base_url"):
                if base.get(key) not in (None, "") and hasattr(cfg, key):
                    setattr(cfg, key, base[key])
        env = os.environ
        if env.get("POKER_JEV_MODE"):
            cfg.mode = str(env["POKER_JEV_MODE"]).strip().lower()
        if env.get("POKER_JEV_MODEL"):
            cfg.model = str(env["POKER_JEV_MODEL"]).strip()
        if env.get("POKER_JEV_TIMEOUT_S"):
            try:
                cfg.timeout_s = float(env["POKER_JEV_TIMEOUT_S"])
            except ValueError:
                pass
        base = env.get("POKER_JEV_BASE_URL")
        if base:
            cfg.base_url = str(base).rstrip("/")
        if overrides:
            for key, value in overrides.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        if cfg.mode not in ("observer", "enforcing", "off"):
            logger.warning("JEV | unknown mode %r, falling back to observer", cfg.mode)
            cfg.mode = "observer"
        return cfg


@dataclass
class JevDecision:
    """Second avis Jev. ``verdict`` None = fail-open (ignorer, garder l'heuristique)."""

    verdict: bool | None  # True=go, False=block, None=fail-open
    reason: str = ""
    go: float | None = None
    tier: str | None = None
    tier_confidence: float | None = None
    risky: float | None = None
    effort: float | None = None
    effort_confidence: float | None = None
    latency_ms: float = 0.0
    cost: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def build_state(snapshot: Any) -> str:
    """Sérialise un SpotSnapshot/CanonicalTableState en phrase d'état textuelle."""
    if hasattr(snapshot, "to_dict"):
        data = dict(snapshot.to_dict())
    elif isinstance(snapshot, dict):
        data = dict(snapshot)
    else:
        return f"unparsable snapshot type {type(snapshot).__name__}, treat as incoherent"

    def _get(*names: str, default: Any = "") -> Any:
        for name in names:
            if data.get(name) not in (None, ""):
                return data[name]
        meta = data.get("metadata") or {}
        for name in names:
            if isinstance(meta, dict) and meta.get(name) not in (None, ""):
                return meta[name]
        return default

    hero = _get("hero_cards", default=[])
    board = _get("board", default=[])
    pot = _get("pot", default="?")
    street = _get("street", default="?")
    legal = _get("legal_actions", "action_buttons", default=[])
    conf = _get("state_confidence", "confidence", "ocr_confidence", default="?")
    parts = [
        f"street {street}",
        f"hero {' '.join(str(c) for c in hero) if hero else 'NOT visible'}",
        f"board {' '.join(str(c) for c in board) if board else 'empty'}",
        f"pot {pot}",
        f"buttons {'/'.join(str(a) for a in legal) if legal else 'missing'}",
        f"state confidence {conf}",
    ]
    meta = data.get("metadata")
    if isinstance(meta, dict):
        ocr = meta.get("ocr_confidence", meta.get("ocr"))
        if ocr is not None:
            parts.append(f"OCR {ocr}")
        if meta.get("contradiction") or meta.get("incoherent"):
            parts.append("flagged incoherent by vision")
    return ". ".join(parts)


def build_questions() -> dict[str, Any]:
    """Set complet poker validé (T5)."""
    return {
        "go": {
            "type": "noul",
            "instructions": (
                "The table state is complete and coherent: hero cards, pot and "
                "action buttons are all visible and readable, with no "
                "contradiction between fields."
            ),
        },
        "tier": {
            "type": "choice",
            "instructions": "Which tier best describes this poker table state?",
            "criteria": dict(TIER_CRITERIA),
        },
        "risky": {
            "type": "noul",
            "instructions": (
                "Clicking now would commit real money on an uncertain or "
                "incoherent table state."
            ),
        },
        "effort": {
            "type": "score",
            "instructions": "How much extra review does this table state need?",
            "criteria": list(EFFORT_RUBRIC),
        },
    }


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def query(
    state: str,
    questions: dict[str, Any] | None = None,
    *,
    config: JevGateConfig | None = None,
) -> JevDecision:
    """POST /v1/systemone, parse tolérant. Jamais d'exception vers l'appelant."""
    cfg = config or JevGateConfig.from_env()
    started = time.monotonic()
    fail = lambda reason: JevDecision(
        verdict=None,
        reason=reason,
        latency_ms=(time.monotonic() - started) * 1000.0,
    )
    if not isinstance(state, str) or not state.strip():
        return fail("fail-open: empty state")
    url = f"{cfg.base_url.rstrip('/')}/v1/systemone"
    body = json.dumps(
        {"model": cfg.model, "state": state, "questions": questions or build_questions()}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:  # timeout, connexion, proxy down -> fail-open
        return fail(f"fail-open: {type(exc).__name__}")
    latency_ms = (time.monotonic() - started) * 1000.0
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        return fail("fail-open: malformed response")
    answers = payload["answers"]
    go_a = answers.get("go") if isinstance(answers.get("go"), dict) else {}
    tier_a = answers.get("tier") if isinstance(answers.get("tier"), dict) else {}
    risky_a = answers.get("risky") if isinstance(answers.get("risky"), dict) else {}
    effort_a = answers.get("effort") if isinstance(answers.get("effort"), dict) else {}
    tier = tier_a.get("choice")
    decision = JevDecision(
        verdict=None,
        reason="parsed",
        go=_num(go_a.get("noul")),
        tier=tier if tier in ("fast", "balanced", "deep") else None,
        tier_confidence=_num(tier_a.get("confidence")),
        risky=_num(risky_a.get("noul")),
        effort=_num(effort_a.get("score")),
        effort_confidence=_num(effort_a.get("confidence")),
        latency_ms=latency_ms,
        cost=payload.get("cost"),
        raw=payload if isinstance(payload, dict) else {},
    )
    usage = payload.get("usage")
    logger.info(
        "JEV | go=%s tier=%s (%s) risky=%s effort=%s (%s) %.0fms cost=%s",
        _fmt(decision.go),
        decision.tier,
        _fmt(decision.tier_confidence),
        _fmt(decision.risky),
        _fmt(decision.effort),
        _fmt(decision.effort_confidence),
        latency_ms,
        decision.cost,
        extra={"usage": usage} if usage else None,
    )
    return decision


def _fmt(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.2f}"


def apply_policy(
    heuristic_allowed: bool,
    jev: JevDecision,
    *,
    config: JevGateConfig | None = None,
) -> tuple[bool, str]:
    """Combine l'avis Jev avec le gate heuristique. Ne lève jamais.

    Asymétrie (cf. mod) : Jev peut bloquer un "go" heuristique (bar basse),
    mais ne peut jamais forcer un "go" si l'heuristique bloque.
    Garde-fou tier (correctif 2026-09-23, sweep 3/12 faux blocs) : si Jev
    déclare lui-même l'état lisible (tier fast/balanced), le blocage exige
    la bar haute (min_downgrade) — sinon le tier contredit le blocage.
    La bar basse (min_upgrade) ne s'applique que si tier = deep ou absent.
    """
    cfg = config or JevGateConfig.from_env()
    if jev.verdict is None and jev.go is None and jev.tier is None:
        return heuristic_allowed, "jev fail-open, heuristic kept"
    # risky > seuil -> escalade forcée, quel que soit le reste.
    if jev.risky is not None and jev.risky > cfg.risky_threshold:
        if heuristic_allowed:
            return False, f"jev risky {_fmt(jev.risky)} > {cfg.risky_threshold} (forced)"
        return False, "heuristic blocked, jev risky confirms"
    if not heuristic_allowed:
        return False, "heuristic blocked (jev never unblocks)"
    # L'heuristique dit go : Jev confiant "incohérent" peut bloquer.
    conf_go = 1.0 - jev.go if jev.go is not None else None  # P(incohérent)
    conf = conf_go
    if jev.tier == "deep" and jev.tier_confidence is not None:
        # Le pire des deux signaux : incohérence = max(P(!go), conf(deep)).
        conf = max(c for c in (conf_go, jev.tier_confidence) if c is not None)
    if conf is None:
        return True, "jev no confidence, heuristic go kept"
    if conf < cfg.min_upgrade_confidence:
        return True, "jev agrees with heuristic go"
    # Garde-fou tier : Jev dit "fast/balanced" (= lisible) mais P(!go)
    # atteint la bar basse -> signaux contradictoires -> bar haute exigée.
    if jev.tier in ("fast", "balanced") and conf < cfg.min_downgrade_confidence:
        return True, f"jev tier {jev.tier} contradicts block (conf {_fmt(conf)} < {cfg.min_downgrade_confidence})"
    return False, f"jev blocks incoherent state (conf {_fmt(conf)})"


def decide(
    snapshot: Any,
    heuristic_allowed: bool,
    *,
    config: JevGateConfig | None = None,
) -> tuple[bool, JevDecision, str]:
    """Point d'entrée du gate : query + policy. Mode off = zéro appel, zéro latence."""
    cfg = config or JevGateConfig.from_env()
    if cfg.mode == "off":
        empty = JevDecision(verdict=None, reason="off")
        return heuristic_allowed, empty, "jev off"
    jev = query(build_state(snapshot), build_questions(), config=cfg)
    if jev.verdict is None and jev.reason.startswith("fail-open"):
        return heuristic_allowed, jev, "jev fail-open, heuristic kept"
    if cfg.mode == "observer":
        agree = (heuristic_allowed and (jev.go or 0) >= 0.5) or (
            not heuristic_allowed and (jev.go or 1) < 0.5
        )
        return heuristic_allowed, jev, f"observer ({'agree' if agree else 'disagree'})"
    allowed, reason = apply_policy(heuristic_allowed, jev, config=cfg)
    return allowed, jev, reason
