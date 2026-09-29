"""Protocole de provider IA + adaptateurs Jev / Djev (socle unifié).

Phase 1 du plan : un seul contrat pour tous les avis IA, deux transports :
  - ``JevProvider`` : proxy local ``http://127.0.0.1:4000`` via
    ``src/bot/jev_gate.py`` (legacy, fail-open, timeout court 0.8s).
  - ``DjevProvider`` : officiel TypeSafe System One via
    ``src/bot/djev_gate.py`` (LAN prioritaire, cloud fallback autorisé,
    clé lue depuis ``os.environ[api_key_env]`` — nom de var, JAMAIS la valeur
    en dur ; clé absente + URL cloud -> fail-open SANS appel).

Le routeur ``src/bot/ai_router.py`` reste le point d'entrée du live
(``decide(provider=auto)`` + log source+modèle). Ce module expose le contrat
``AiProvider`` et les adaptateurs utilisés par les futurs remplacements natifs
(Phase 2 : parseViaDjev, vision, openaiCompatible) : ``query()`` retourne une
``AiAnswer`` typée au lieu de lever, ``health()`` ne fait jamais d'appel
réseau (ping loopback uniquement quand l'URL est loopback, sinon unknown).

``AiAnswer.source`` : ``lan`` | ``cloud`` | ``fallback`` (fail-open /
heuristique). ``raw`` conserve le payload brut (+ ``usage`` quand présent)
pour les logs A/B (source+modèle+probabilities+confidence).
"""

from __future__ import annotations

import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

logger = logging.getLogger("SuperBot2026")

__all__ = [
    "AiAnswer",
    "AiProvider",
    "JevProvider",
    "DjevProvider",
    "get_provider",
]

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_TRUE_VALUES = ("1", "true", "yes", "on")


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


@dataclass
class AiAnswer:
    """Réponse IA typée : jamais d'exception, ``data`` vide si fail-open."""

    data: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    latency_ms: float = 0.0
    source: str = "fallback"  # lan | cloud | fallback
    model: str = "?"
    probabilities: dict[str, float] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.data) and self.source in ("lan", "cloud")


@runtime_checkable
class AiProvider(Protocol):
    """Contrat unique pour tout avis IA (Jev legacy + Djev officiel)."""

    name: str

    def query(
        self, state: str, questions: dict[str, Any]
    ) -> AiAnswer: ...  # pragma: no cover - contrat

    def health(self) -> dict[str, Any]: ...  # pragma: no cover - contrat


def _answer_from_decision(
    dec: Any, *, source: str, model: Any, latency_ms: float
) -> AiAnswer:
    data: dict[str, Any] = {}
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    raw: dict[str, Any] = {}
    try:
        raw = dict(getattr(dec, "raw", None) or {})
    except Exception:
        raw = {}
    try:
        if getattr(dec, "go", None) is not None:
            data["go"] = float(dec.go)
        if getattr(dec, "tier", None) in ("fast", "balanced", "deep"):
            data["tier"] = dec.tier
            if getattr(dec, "tier_confidence", None) is not None:
                confidence = float(dec.tier_confidence)
        if getattr(dec, "risky", None) is not None:
            data["risky"] = float(dec.risky)
        if getattr(dec, "effort", None) is not None:
            data["effort"] = float(dec.effort)
        answers = raw.get("answers") if isinstance(raw, dict) else None
        tier_a = (
            answers.get("tier")
            if isinstance(answers, dict) and isinstance(answers.get("tier"), dict)
            else None
        )
        probs = tier_a.get("probabilities") if tier_a else None
        if isinstance(probs, dict) and probs:
            probabilities = {
                str(k): float(v)
                for k, v in probs.items()
                if isinstance(v, (int, float))
            } or None
    except Exception:
        pass
    return AiAnswer(
        data=data,
        confidence=confidence,
        latency_ms=latency_ms,
        source=source if data else "fallback",
        model=str(model or "?"),
        probabilities=probabilities,
        raw=raw,
    )


class JevProvider:
    """Adaptateur proxy local :4000 (legacy). Fail-open, timeout court."""

    name = "jev"

    def __init__(self, config: Any = None) -> None:
        from src.bot import jev_gate as jev_mod

        self._mod = jev_mod
        self._config = config or jev_mod.JevGateConfig.from_env()

    def query(self, state: str, questions: dict[str, Any]) -> AiAnswer:
        started = time.monotonic()
        try:
            dec = self._mod.query(state, questions, config=self._config)
            model = getattr(self._config, "model", "?")
            base_url = str(getattr(self._config, "base_url", ""))
            source = "lan" if _is_loopback(base_url) else "cloud"
        except Exception as exc:  # jamais d'exception vers l'appelant
            logger.info("AI_PROVIDER | jev fail-open (%s)", type(exc).__name__)
            return AiAnswer(
                latency_ms=(time.monotonic() - started) * 1000.0,
                source="fallback",
                raw={"fail_open": f"jev {type(exc).__name__}"},
            )
        ans = _answer_from_decision(
            dec,
            source=source,
            model=model,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )
        try:
            ans.latency_ms = float(getattr(dec, "latency_ms", 0.0) or 0.0)
        except Exception:
            pass
        return ans

    def health(self) -> dict[str, Any]:
        base_url = str(getattr(self._config, "base_url", ""))
        if _is_loopback(base_url):
            try:
                endpoint = base_url.rstrip("/") + "/v1/systemone"
                req = urllib.request.Request(
                    endpoint, data=b"{}", headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=1.0):
                    return {"name": self.name, "status": "up", "url": endpoint}
            except Exception as exc:
                return {
                    "name": self.name,
                    "status": "down",
                    "url": base_url,
                    "error": type(exc).__name__,
                }
        return {"name": self.name, "status": "unknown", "url": base_url}


class DjevProvider:
    """Adaptateur officiel System One (LAN loopback ou cloud + clé env)."""

    name = "djev"

    def __init__(self, config: Any = None) -> None:
        from src.bot import djev_gate as djev_mod

        self._mod = djev_mod
        self._config = config or djev_mod.DjevGateConfig.from_env()

    def query(self, state: str, questions: dict[str, Any]) -> AiAnswer:
        started = time.monotonic()
        try:
            dec = self._mod.query(state, questions, config=self._config)
            model = getattr(self._config, "model", "?")
            base_url = str(getattr(self._config, "base_url", ""))
            source = "lan" if _is_loopback(base_url) else "cloud"
        except Exception as exc:  # jamais d'exception vers l'appelant
            logger.info("AI_PROVIDER | djev fail-open (%s)", type(exc).__name__)
            return AiAnswer(
                latency_ms=(time.monotonic() - started) * 1000.0,
                source="fallback",
                raw={"fail_open": f"djev {type(exc).__name__}"},
            )
        ans = _answer_from_decision(
            dec,
            source=source,
            model=model,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )
        try:
            ans.latency_ms = float(getattr(dec, "latency_ms", 0.0) or 0.0)
        except Exception:
            pass
        return ans

    def health(self) -> dict[str, Any]:
        base_url = str(getattr(self._config, "base_url", ""))
        if not _is_loopback(base_url):
            # Cloud : aucun ping réseau ici (coût + secret) -> statut unknown.
            key_env = str(getattr(self._config, "api_key_env", ""))
            has_key = bool(key_env and os.environ.get(key_env))
            return {
                "name": self.name,
                "status": "unknown",
                "url": base_url,
                "has_key": has_key,
            }
        try:
            endpoint = (
                base_url
                if base_url.rstrip("/").lower().endswith("/v1/systemone")
                else base_url.rstrip("/") + "/v1/systemone"
            )
            req = urllib.request.Request(
                endpoint, data=b"{}", headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=1.0):
                return {"name": self.name, "status": "up", "url": endpoint}
        except Exception as exc:
            return {
                "name": self.name,
                "status": "down",
                "url": base_url,
                "error": type(exc).__name__,
            }


def get_provider(name: str = "auto", config: Any = None) -> AiProvider:
    """Fabrique : ``jev`` / ``djev`` / ``auto`` (LAN si offline, cloud si clé)."""
    wanted = str(name or "auto").strip().lower()
    if wanted == "jev":
        return JevProvider(config)
    if wanted == "djev":
        return DjevProvider(config)
    offline = (
        str(os.environ.get("POKER_OFFLINE_MODE", "")).strip().lower()
        in _TRUE_VALUES
    )
    if offline:
        try:
            from src.bot import djev_gate as djev_mod

            dcfg = djev_mod.DjevGateConfig.from_env()
            if _is_loopback(getattr(dcfg, "lan_url", "")):
                return DjevProvider(dcfg)
        except Exception:
            pass
        return JevProvider(config)
    try:
        from src.bot import djev_gate as djev_mod

        dcfg = djev_mod.DjevGateConfig.from_env()
        key_env = str(getattr(dcfg, "api_key_env", ""))
        if key_env and os.environ.get(key_env):
            return DjevProvider(dcfg)
    except Exception:
        pass
    return JevProvider(config)
