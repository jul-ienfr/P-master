"""Gate de second avis via Djev officiel (TypeSafe System One, cloud + LAN).

Miroir strict de ``src/bot/jev_gate.py`` (mêmes questions go/tier/risky/effort,
mêmes seuils 0.3/0.6/0.7, même parse tolérant, même fail-open) adapté au cloud
officiel ``https://api.typesafe.ai/v1/systemone``.

Écarts proxy :4000 vs officiel, TOUS isolés ici (jamais dans gate_flow.py) :
  - ``base_url`` : proxy = ``http://127.0.0.1:4000`` (+ ``/v1/systemone``
    ajouté) ; officiel = URL complète incluant ``/v1/systemone`` (reconnue et
    utilisée telle quelle). Modèle officiel piné ``jev-1.13.0``.
  - auth : proxy = aucune ; officiel = ``Authorization: Bearer`` lu depuis
    ``os.environ[api_key_env]`` (nom de var, JAMAIS la valeur en dur). Clé
    absente + URL non-loopback -> fail-open SANS appel réseau.
  - ``state`` string-only (comme le proxy) : restriction conservatrice, le
    cloud accepterait un objet mais on garde la comparabilité Jev/Djev.
  - erreurs : 401/422 -> fail-open direct ; 429/529 -> 1 retry avec backoff +
    ``retry-after`` respecté (borné par ``timeout_s``).
  - ``offline_mode=true`` -> URL non-loopback = fail-open SANS appel
    (``fail-open: offline_mode, WAN refused``), jamais d'egress WAN.

Config : fichier (bloc ``bot.ai_gate.djev`` via ``base``) puis env
(POKER_DJEV_BASE_URL, POKER_DJEV_MODEL, POKER_DJEV_TIMEOUT_S, POKER_DJEV_MODE,
POKER_DJEV_API_KEY_ENV, POKER_DJEV_LAN_URL, POKER_DJEV_CLOUD_URL,
POKER_DJEV_CLOUD_FALLBACK, POKER_OFFLINE_MODE, POKER_DJEV_MIN_UPGRADE,
POKER_DJEV_MIN_DOWNGRADE, POKER_DJEV_RISKY), puis ``overrides`` explicites.
Précédence : overrides > env > base. Jamais de clé en dur.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.bot.jev_gate import (
    MIN_DOWNGRADE_CONFIDENCE,
    MIN_UPGRADE_CONFIDENCE,
    RISKY_THRESHOLD,
    JevDecision,
    apply_policy,
    build_questions,
    build_state,
)

logger = logging.getLogger("SuperBot2026")

# Réexport : mêmes briques de jugement que Jev (comparabilité A/B).
__all__ = [
    "DjevGateConfig",
    "DjevDecision",
    "build_state",
    "build_questions",
    "apply_policy",
    "query",
    "decide",
]

DEFAULT_BASE_URL = "http://127.0.0.1:4000"  # lock LAN : proxy local gratuit sans cle (cloud desactive par choix)
DEFAULT_MODEL = "jev-1.13.0"  # pin stable ; jev-latest/jev-preview = alias mouvants
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_API_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_LAN_URL = "http://127.0.0.1:4000"
DEFAULT_CLOUD_URL = "https://api.typesafe.ai/v1/systemone"

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_TRUE_VALUES = ("1", "true", "yes", "on")
_RETRYABLE_STATUS = (429, 529)
_MAX_ATTEMPTS = 2

# Alias sémantique : une décision Djev a exactement la forme d'une JevDecision
# (ai_router loggue les deux via le même formateur).
DjevDecision = JevDecision


def _is_loopback(url: Any) -> bool:
    try:
        s = str(url or "").strip()
        if not s:
            return False
        if "://" not in s:
            s = "//" + s
        host = (urlparse(s).hostname or "").strip().lower()
    except Exception:
        return False
    return host in _LOOPBACK_HOSTS


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _fmt(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.2f}"


@dataclass
class DjevGateConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_s: float = DEFAULT_TIMEOUT_S
    mode: str = "observer"  # observer | enforcing | off
    lan_url: str = DEFAULT_LAN_URL
    cloud_url: str = DEFAULT_CLOUD_URL
    cloud_fallback: bool = False  # cloud desactive par choix (force false si offline)
    offline_mode: bool = True  # lock Offline strict : loopback uniquement, JAMAIS de WAN
    min_upgrade_confidence: float = MIN_UPGRADE_CONFIDENCE
    min_downgrade_confidence: float = MIN_DOWNGRADE_CONFIDENCE
    risky_threshold: float = RISKY_THRESHOLD

    @classmethod
    def from_env(
        cls,
        overrides: dict[str, Any] | None = None,
        base: dict[str, Any] | None = None,
    ) -> "DjevGateConfig":
        """Construit la config : fichier (``base``) < env < ``overrides``.

        Bloc fichier attendu (tout optionnel) : ``{"mode","model","timeout_s",
        "base_url","api_key_env","lan_url","cloud_url","cloud_fallback",
        "offline_mode","min_upgrade_confidence","min_downgrade_confidence",
        "risky_threshold"}``.
        """
        cfg = cls()
        if base:
            for key in ("mode", "model", "timeout_s", "base_url",
                        "api_key_env", "lan_url", "cloud_url",
                        "cloud_fallback", "offline_mode",
                        "min_upgrade_confidence", "min_downgrade_confidence",
                        "risky_threshold"):
                if base.get(key) not in (None, "") and hasattr(cfg, key):
                    setattr(cfg, key, base[key])
        env = os.environ
        if env.get("POKER_DJEV_MODE"):
            cfg.mode = str(env["POKER_DJEV_MODE"]).strip().lower()
        if env.get("POKER_DJEV_MODEL"):
            cfg.model = str(env["POKER_DJEV_MODEL"]).strip()
        if env.get("POKER_DJEV_TIMEOUT_S"):
            try:
                cfg.timeout_s = float(env["POKER_DJEV_TIMEOUT_S"])
            except ValueError:
                pass
        if env.get("POKER_DJEV_BASE_URL"):
            cfg.base_url = str(env["POKER_DJEV_BASE_URL"]).rstrip("/")
        if env.get("POKER_DJEV_API_KEY_ENV"):
            cfg.api_key_env = str(env["POKER_DJEV_API_KEY_ENV"]).strip()
        if env.get("POKER_DJEV_LAN_URL"):
            cfg.lan_url = str(env["POKER_DJEV_LAN_URL"]).rstrip("/")
        if env.get("POKER_DJEV_CLOUD_URL"):
            cfg.cloud_url = str(env["POKER_DJEV_CLOUD_URL"]).rstrip("/")
        if env.get("POKER_DJEV_CLOUD_FALLBACK"):
            cfg.cloud_fallback = (
                str(env["POKER_DJEV_CLOUD_FALLBACK"]).strip().lower()
                in _TRUE_VALUES
            )
        if env.get("POKER_DJEV_MIN_UPGRADE"):
            try:
                cfg.min_upgrade_confidence = float(env["POKER_DJEV_MIN_UPGRADE"])
            except ValueError:
                pass
        if env.get("POKER_DJEV_MIN_DOWNGRADE"):
            try:
                cfg.min_downgrade_confidence = float(
                    env["POKER_DJEV_MIN_DOWNGRADE"]
                )
            except ValueError:
                pass
        if env.get("POKER_DJEV_RISKY"):
            try:
                cfg.risky_threshold = float(env["POKER_DJEV_RISKY"])
            except ValueError:
                pass
        if env.get("POKER_OFFLINE_MODE"):
            cfg.offline_mode = (
                str(env["POKER_OFFLINE_MODE"]).strip().lower() in _TRUE_VALUES
            )
        if overrides:
            for key, value in overrides.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        if cfg.mode not in ("observer", "enforcing", "off"):
            logger.warning(
                "DJEV | unknown mode %r, falling back to observer", cfg.mode
            )
            cfg.mode = "observer"
        if cfg.offline_mode:
            # Offline strict : aucun egress WAN (fallbacks cloud tombés,
            # miroir TS normalizeAiGateConfig / Rust normalize_ai_gate_config).
            cfg.cloud_fallback = False
        if cfg.offline_mode and not _is_loopback(cfg.base_url):
            # WAN interdite : on garde l'URL telle quelle et c'est query()
            # qui refuse SANS appel (fail-open: offline_mode, WAN refused).
            # Pas de repli silencieux ici : un repli changerait l'URL appelee
            # et masquerait le refus WAN (cf. docs/djev_spike.md).
            logger.warning(
                "DJEV | offline_mode: non-loopback base_url %r, "
                "WAN calls will be refused without network",
                cfg.base_url,
            )
        return cfg


def _endpoint(base_url: str) -> str:
    """Normalise l'endpoint : accepte base nue ou URL complète /v1/systemone."""
    clean = str(base_url or "").strip().rstrip("/")
    if clean.lower().endswith("/v1/systemone"):
        return clean
    return f"{clean}/v1/systemone"


def _retry_after_s(exc: urllib.error.HTTPError, cap_s: float) -> float:
    try:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        delay = float(str(raw).strip().split(",")[0])
    except (TypeError, ValueError, AttributeError):
        delay = 1.0
    return max(0.0, min(delay if delay == delay else 1.0, cap_s))


def query(
    state: str,
    questions: dict[str, Any] | None = None,
    *,
    config: DjevGateConfig | None = None,
) -> JevDecision:
    """POST System One officiel (ou shim LAN loopback), parse tolérant.

    Jamais d'exception vers l'appelant : tout échec -> fail-open (verdict None).
    Zéro appel réseau si ``state`` vide, si ``offline_mode`` + WAN, ou si clé
    absente + URL cloud (fail-open ``missing api key``).
    """
    cfg = config or DjevGateConfig.from_env()
    started = time.monotonic()
    fail = lambda reason: JevDecision(  # noqa: E731
        verdict=None,
        reason=reason,
        latency_ms=(time.monotonic() - started) * 1000.0,
    )
    if not isinstance(state, str) or not state.strip():
        return fail("fail-open: empty state")
    url = _endpoint(cfg.base_url)
    if cfg.offline_mode and not _is_loopback(url):
        return fail("fail-open: offline_mode, WAN refused")
    api_key = ""
    if cfg.api_key_env:
        api_key = str(os.environ.get(cfg.api_key_env, "") or "")
    if not api_key and not _is_loopback(url):
        # Cloud sans clé : on ne tente même pas l'appel (401 garantie).
        return fail("fail-open: missing api key")
    body = json.dumps(
        {"model": cfg.model, "state": state, "questions": questions or build_questions()}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: Any = None
    attempts = 0
    while attempts < _MAX_ATTEMPTS:
        attempts += 1
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            break
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_STATUS and attempts < _MAX_ATTEMPTS:
                delay = _retry_after_s(exc, cfg.timeout_s)
                logger.info(
                    "DJEV | %s, retry in %.1fs (attempt %d/%d)",
                    exc.code,
                    delay,
                    attempts,
                    _MAX_ATTEMPTS,
                )
                time.sleep(delay)
                continue
            return fail(f"fail-open: HTTPError {exc.code}")
        except Exception as exc:  # timeout, connexion, DNS -> fail-open
            return fail(f"fail-open: {type(exc).__name__}")
    latency_ms = (time.monotonic() - started) * 1000.0
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        return fail("fail-open: malformed response")
    answers = payload["answers"]
    go_a = answers.get("go") if isinstance(answers.get("go"), dict) else {}
    tier_a = answers.get("tier") if isinstance(answers.get("tier"), dict) else {}
    risky_a = answers.get("risky") if isinstance(answers.get("risky"), dict) else {}
    effort_a = (
        answers.get("effort") if isinstance(answers.get("effort"), dict) else {}
    )
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
        "DJEV | model=%s go=%s tier=%s (%s) risky=%s effort=%s (%s) %.0fms cost=%s",
        payload.get("model", cfg.model),
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


def decide(
    snapshot: Any,
    heuristic_allowed: bool,
    *,
    config: DjevGateConfig | None = None,
) -> tuple[bool, JevDecision, str]:
    """Point d'entrée du gate : query + policy. Mode off = zéro appel."""
    cfg = config or DjevGateConfig.from_env()
    if cfg.mode == "off":
        empty = JevDecision(verdict=None, reason="off")
        return heuristic_allowed, empty, "djev off"
    djev = query(build_state(snapshot), build_questions(), config=cfg)
    if djev.verdict is None and djev.reason.startswith("fail-open"):
        return heuristic_allowed, djev, "djev fail-open, heuristic kept"
    if cfg.mode == "observer":
        agree = (heuristic_allowed and (djev.go or 0) >= 0.5) or (
            not heuristic_allowed and (djev.go or 1) < 0.5
        )
        return heuristic_allowed, djev, f"observer ({'agree' if agree else 'disagree'})"
    allowed, reason = apply_policy(heuristic_allowed, djev, config=cfg)
    return allowed, djev, reason
