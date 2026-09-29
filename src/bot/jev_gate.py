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
(POKER_JEV_MODE, POKER_JEV_MODEL, POKER_JEV_TIMEOUT_S, POKER_JEV_BASE_URL,
POKER_JEV_DEPLOYMENT, POKER_JEV_BACKEND, POKER_JEV_MIN_UPGRADE,
POKER_JEV_MIN_DOWNGRADE, POKER_JEV_RISKY, POKER_JEV_LAN_URL,
POKER_JEV_LAN_MODEL, POKER_JEV_LAN_TIMEOUT_TEXT_S,
POKER_JEV_LAN_TIMEOUT_IMAGE_S, POKER_JEV_LAN_KEY_ENV, POKER_JEV_MULTIMODAL),
puis ``overrides`` explicites (ex. CLI). Précédence : overrides > env > base.
Étendue options (étape 1, parsing seul — zéro appel réseau ajouté) :
``deployment`` single|dual, ``backend`` cloud|local|auto, ``lan`` (SRV-LINUX),
``multimodal`` (text_only par défaut, crops_live verrouillé), ``usages``
(6 usages existants : autolabel/judge/report/attention/tier_budget/drift).
Jamais de clé en dur (le free n'en demande pas ; clé LAN via nom de var
d'env ``lan.api_key_env``, jamais la valeur).
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

# Déploiement 1 / 2 machines (options, étape 1 — parsing seul, zéro réseau).
# single = tout sur TABLE-WIN (comportement historique).
# dual = TABLE-WIN -> SRV-LINUX en LAN (bloc ``lan`` ci-dessous).
DEPLOYMENT_SINGLE = "single"
DEPLOYMENT_DUAL = "dual"
BACKEND_CLOUD = "cloud"
BACKEND_LOCAL = "local"
BACKEND_AUTO = "auto"

DEFAULT_LAN_MODEL = "qwen2.5-vl-3b"
DEFAULT_LAN_TIMEOUT_TEXT_S = 1.0
DEFAULT_LAN_TIMEOUT_IMAGE_S = 15.0
DEFAULT_LAN_API_KEY_ENV = "POKER_JEV_LAN_KEY"

MULTIMODAL_TEXT_ONLY = "text_only"
MULTIMODAL_CROPS_OFFLINE = "crops_offline"
MULTIMODAL_CROPS_LIVE = "crops_live"  # verrouillé tant que Phase 3 non validée

DEFAULT_MAX_IMAGES = 3
DEFAULT_CROP_SIZE_PX = 160
DEFAULT_JPEG_QUALITY = 80

DEFAULT_USAGES = ("autolabel", "judge", "report", "attention", "tier_budget", "drift")
DEFAULT_USAGE_TIMEOUT_S = 15.0

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
class JevLanConfig:
    """Serveur SRV-LINUX (JUG) en LAN — étape 1 : parsing seul, jamais appelé en live."""

    base_url: str = ""
    model: str = DEFAULT_LAN_MODEL
    timeout_text_s: float = DEFAULT_LAN_TIMEOUT_TEXT_S
    timeout_image_s: float = DEFAULT_LAN_TIMEOUT_IMAGE_S
    api_key_env: str = DEFAULT_LAN_API_KEY_ENV


@dataclass
class JevMultimodalConfig:
    """Cadrage image — étape 1 : parsing seul. crops_live reste verrouillé."""

    enabled: bool = False
    mode: str = MULTIMODAL_TEXT_ONLY  # text_only | crops_offline | crops_live
    max_images: int = DEFAULT_MAX_IMAGES
    crop_size_px: int = DEFAULT_CROP_SIZE_PX
    jpeg_quality: int = DEFAULT_JPEG_QUALITY


@dataclass
class JevGateConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: float = DEFAULT_TIMEOUT_S
    mode: str = "observer"  # observer | enforcing | off
    min_upgrade_confidence: float = MIN_UPGRADE_CONFIDENCE
    min_downgrade_confidence: float = MIN_DOWNGRADE_CONFIDENCE
    risky_threshold: float = RISKY_THRESHOLD
    deployment: str = DEPLOYMENT_SINGLE  # single | dual
    backend: str = BACKEND_CLOUD  # cloud | local | auto
    offline_mode: bool = False  # POKER_OFFLINE_MODE : loopback uniquement, jamais de WAN
    lan: JevLanConfig = field(default_factory=JevLanConfig)
    multimodal: JevMultimodalConfig = field(default_factory=JevMultimodalConfig)
    usages: dict[str, dict[str, Any]] = field(default_factory=dict)

    def usage_enabled(self, name: str) -> bool:
        """Un usage listé dans DEFAULT_USAGES est actif sauf ``enabled: false`` explicite."""
        if name not in DEFAULT_USAGES:
            return False
        entry = self.usages.get(name)
        if not isinstance(entry, dict):
            return True
        return bool(entry.get("enabled", True))

    def usage_timeout_s(self, name: str) -> float:
        entry = self.usages.get(name)
        if isinstance(entry, dict) and entry.get("timeout_s") not in (None, ""):
            try:
                return float(entry["timeout_s"])
            except (TypeError, ValueError):
                pass
        return DEFAULT_USAGE_TIMEOUT_S

    @classmethod
    def from_env(
        cls,
        overrides: dict[str, Any] | None = None,
        base: dict[str, Any] | None = None,
    ) -> "JevGateConfig":
        """Construit la config : fichier (``base``) < env < ``overrides``.

        Bloc fichier attendu (tout optionnel, défauts = comportement actuel) :
        ``{"mode","model","timeout_s","base_url","deployment","backend",
        "min_upgrade_confidence","min_downgrade_confidence","risky_threshold",
        "lan": {"base_url","model","timeout_text_s","timeout_image_s","api_key_env"},
        "multimodal": {"enabled","mode","max_images","crop_size_px","jpeg_quality"},
        "usages": {"autolabel": {"enabled","timeout_s"}, ...}}``
        """
        cfg = cls()
        if base:
            for key in ("mode", "model", "timeout_s", "base_url",
                        "deployment", "backend", "offline_mode",
                        "min_upgrade_confidence", "min_downgrade_confidence",
                        "risky_threshold"):
                if base.get(key) not in (None, "") and hasattr(cfg, key):
                    setattr(cfg, key, base[key])
            lan_base = base.get("lan")
            if isinstance(lan_base, dict):
                for key in ("base_url", "model", "timeout_text_s",
                            "timeout_image_s", "api_key_env"):
                    if lan_base.get(key) not in (None, "") and hasattr(cfg.lan, key):
                        setattr(cfg.lan, key, lan_base[key])
            mm_base = base.get("multimodal")
            if isinstance(mm_base, dict):
                for key in ("enabled", "mode", "max_images",
                            "crop_size_px", "jpeg_quality"):
                    if mm_base.get(key) not in (None, "") and hasattr(cfg.multimodal, key):
                        setattr(cfg.multimodal, key, mm_base[key])
            usages_base = base.get("usages")
            if isinstance(usages_base, dict):
                for name in DEFAULT_USAGES:
                    entry = usages_base.get(name)
                    if isinstance(entry, dict):
                        cfg.usages[name] = {
                            k: v for k, v in entry.items()
                            if k in ("enabled", "timeout_s")
                        }
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
        base_url = env.get("POKER_JEV_BASE_URL")
        if base_url:
            cfg.base_url = str(base_url).rstrip("/")
        if env.get("POKER_JEV_DEPLOYMENT"):
            cfg.deployment = str(env["POKER_JEV_DEPLOYMENT"]).strip().lower()
        if env.get("POKER_JEV_BACKEND"):
            cfg.backend = str(env["POKER_JEV_BACKEND"]).strip().lower()
        if env.get("POKER_JEV_MIN_UPGRADE"):
            try:
                cfg.min_upgrade_confidence = float(env["POKER_JEV_MIN_UPGRADE"])
            except ValueError:
                pass
        if env.get("POKER_JEV_MIN_DOWNGRADE"):
            try:
                cfg.min_downgrade_confidence = float(env["POKER_JEV_MIN_DOWNGRADE"])
            except ValueError:
                pass
        if env.get("POKER_JEV_RISKY"):
            try:
                cfg.risky_threshold = float(env["POKER_JEV_RISKY"])
            except ValueError:
                pass
        if env.get("POKER_JEV_LAN_URL"):
            cfg.lan.base_url = str(env["POKER_JEV_LAN_URL"]).rstrip("/")
        if env.get("POKER_JEV_LAN_MODEL"):
            cfg.lan.model = str(env["POKER_JEV_LAN_MODEL"]).strip()
        if env.get("POKER_JEV_LAN_TIMEOUT_TEXT_S"):
            try:
                cfg.lan.timeout_text_s = float(env["POKER_JEV_LAN_TIMEOUT_TEXT_S"])
            except ValueError:
                pass
        if env.get("POKER_JEV_LAN_TIMEOUT_IMAGE_S"):
            try:
                cfg.lan.timeout_image_s = float(env["POKER_JEV_LAN_TIMEOUT_IMAGE_S"])
            except ValueError:
                pass
        if env.get("POKER_JEV_LAN_KEY_ENV"):
            cfg.lan.api_key_env = str(env["POKER_JEV_LAN_KEY_ENV"]).strip()
        if env.get("POKER_JEV_MULTIMODAL"):
            cfg.multimodal.mode = str(env["POKER_JEV_MULTIMODAL"]).strip().lower()
            cfg.multimodal.enabled = cfg.multimodal.mode != MULTIMODAL_TEXT_ONLY
        if env.get("POKER_OFFLINE_MODE"):
            # Ajout offline : parse seul, aucun comportement existant modifie.
            cfg.offline_mode = str(env["POKER_OFFLINE_MODE"]).strip().lower() in (
                "1", "true", "yes", "on")
        if overrides:
            for key, value in overrides.items():
                if key == "lan" and isinstance(value, dict):
                    for sub, val in value.items():
                        if hasattr(cfg.lan, sub):
                            setattr(cfg.lan, sub, val)
                elif key == "multimodal" and isinstance(value, dict):
                    for sub, val in value.items():
                        if hasattr(cfg.multimodal, sub):
                            setattr(cfg.multimodal, sub, val)
                elif key == "usages" and isinstance(value, dict):
                    for name, entry in value.items():
                        if name in DEFAULT_USAGES and isinstance(entry, dict):
                            cfg.usages[name] = {
                                k: v for k, v in entry.items()
                                if k in ("enabled", "timeout_s")
                            }
                elif hasattr(cfg, key):
                    setattr(cfg, key, value)
        if cfg.mode not in ("observer", "enforcing", "off"):
            logger.warning("JEV | unknown mode %r, falling back to observer", cfg.mode)
            cfg.mode = "observer"
        if cfg.deployment not in (DEPLOYMENT_SINGLE, DEPLOYMENT_DUAL):
            logger.warning("JEV | unknown deployment %r, falling back to single",
                           cfg.deployment)
            cfg.deployment = DEPLOYMENT_SINGLE
        if cfg.backend not in (BACKEND_CLOUD, BACKEND_LOCAL, BACKEND_AUTO):
            logger.warning("JEV | unknown backend %r, falling back to cloud",
                           cfg.backend)
            cfg.backend = BACKEND_CLOUD
        if cfg.multimodal.mode not in (MULTIMODAL_TEXT_ONLY,
                                       MULTIMODAL_CROPS_OFFLINE,
                                       MULTIMODAL_CROPS_LIVE):
            logger.warning("JEV | unknown multimodal mode %r, falling back to text_only",
                           cfg.multimodal.mode)
            cfg.multimodal.mode = MULTIMODAL_TEXT_ONLY
            cfg.multimodal.enabled = False
        if cfg.multimodal.mode == MULTIMODAL_TEXT_ONLY:
            cfg.multimodal.enabled = False
        else:
            cfg.multimodal.enabled = True
        if cfg.multimodal.mode == MULTIMODAL_CROPS_LIVE:
            # Verrou Phase 3 : crops_live parsé mais jamais actif en étape 1.
            logger.warning("JEV | crops_live locked (Phase 3 not validated), "
                           "falling back to text_only")
            cfg.multimodal.mode = MULTIMODAL_TEXT_ONLY
            cfg.multimodal.enabled = False
        if cfg.deployment == DEPLOYMENT_DUAL and not cfg.lan.base_url:
            logger.warning("JEV | dual without lan.base_url, falling back to single")
            cfg.deployment = DEPLOYMENT_SINGLE
        if cfg.offline_mode:
            # Ajout offline : WAN interdite -> repli loopback sur le proxy.
            try:
                from urllib.parse import urlparse as _urlparse
                _host = (_urlparse(cfg.base_url).hostname or "").strip().lower()
            except Exception:
                _host = ""
            if _host not in ("127.0.0.1", "localhost", "::1"):
                logger.warning("JEV | offline_mode: non-loopback base_url %r, "
                               "falling back to %s", cfg.base_url, DEFAULT_BASE_URL)
                cfg.base_url = DEFAULT_BASE_URL
        try:
            cfg.multimodal.max_images = max(1, min(int(cfg.multimodal.max_images),
                                                  8))
        except (TypeError, ValueError):
            cfg.multimodal.max_images = DEFAULT_MAX_IMAGES
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
