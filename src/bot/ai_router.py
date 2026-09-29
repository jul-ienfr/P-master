"""Routeur IA : jev (proxy local :4000, LAN gratuit sans cle) vs djev (cloud / LAN).

Lock LAN prioritaire / Offline strict (cloud desactive par choix) :
  provider=jev (DEFAUT) -> toujours jev_gate (proxy local, jamais le cloud,
    meme si TYPESAFE_API_KEY est presente).
  provider=djev -> toujours djev_gate (module optionnel ; absent = fail-open).
  provider=auto :
    - offline_mode=True (DEFAUT) : loopback uniquement
      (proxy jev :4000 ou lan_url djev), JAMAIS de WAN — le cloud est
      saute avec une raison loggee, puis fail-open heuristique.
    - en ligne (offline_mode=False explicite) : djev cloud si la cle
      (os.environ[api_key_env]) est presente, sinon proxy jev,
      sinon fail-open heuristique.

Config : bloc ``bot.ai_gate`` (``base`` = bloc bot, config racine, ou bloc
ai_gate lui-meme), puis env (POKER_AI_PROVIDER, POKER_OFFLINE_MODE,
POKER_DJEV_CLOUD_FALLBACK), puis ``overrides`` explicites.
Precedence : overrides > env > base. ``bot.jev_gate`` reste l'alias compat
pour les reglages jev. Chaque decision loggue source+modele+probabilites.
Jamais d'exception vers l'appelant (fail-open heuristique).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.bot.jev_gate import JevDecision, JevGateConfig, decide as jev_decide

logger = logging.getLogger("SuperBot2026")

PROVIDER_JEV = "jev"
PROVIDER_DJEV = "djev"
PROVIDER_AUTO = "auto"

DEFAULT_PROXY_URL = "http://127.0.0.1:4000"
DEFAULT_DJEV_API_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_DJEV_CLOUD_URL = "https://api.typesafe.ai/v1/systemone"

_TRUE_VALUES = ("1", "true", "yes", "on")


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE_VALUES


def _is_loopback(url: Any) -> bool:
    """True si l'URL vise le loopback (127.0.0.1, localhost, ::1)."""
    try:
        s = str(url or "").strip()
        if not s:
            return False
        if "://" not in s:
            s = "//" + s
        host = (urlparse(s).hostname or "").strip().lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


@dataclass
class AiGateConfig:
    provider: str = PROVIDER_JEV  # jev | djev | auto (lock LAN : jev par defaut, zero cloud)
    offline_mode: bool = True  # lock Offline strict : loopback uniquement, JAMAIS de WAN
    cloud_fallback: bool = False  # cloud desactive par choix (force false si offline)
    jev_base: dict[str, Any] | None = None
    djev_base: dict[str, Any] | None = None

    @classmethod
    def from_env(
        cls,
        overrides: dict[str, Any] | None = None,
        base: dict[str, Any] | None = None,
    ) -> "AiGateConfig":
        """Construit la config : fichier (``base``) < env < ``overrides``."""
        cfg = cls()
        node: dict[str, Any] = {}
        if isinstance(base, dict):
            node = base
            if isinstance(node.get("bot"), dict):
                node = node["bot"]
        ai: dict[str, Any] = {}
        if isinstance(node.get("ai_gate"), dict):
            ai = node["ai_gate"]
        elif any(k in node for k in ("provider", "offline_mode",
                                     "cloud_fallback", "djev", "jev")):
            ai = node  # base est deja le bloc ai_gate lui-meme
        jev_alias = node.get("jev_gate")
        if not isinstance(jev_alias, dict):
            jev_alias = None
        if isinstance(ai.get("provider"), str) and ai["provider"].strip():
            cfg.provider = ai["provider"].strip().lower()
        for flag in ("offline_mode", "cloud_fallback"):
            value = ai.get(flag)
            if isinstance(value, bool):
                setattr(cfg, flag, value)
            elif isinstance(value, str) and value.strip():
                setattr(cfg, flag, value.strip().lower() in _TRUE_VALUES)
            elif isinstance(value, (int, float)):
                setattr(cfg, flag, bool(value))
        if isinstance(ai.get("jev"), dict):
            cfg.jev_base = dict(ai["jev"])
        elif jev_alias is not None:
            cfg.jev_base = dict(jev_alias)  # alias compat : bot.jev_gate
        if isinstance(ai.get("djev"), dict):
            cfg.djev_base = dict(ai["djev"])
        env = os.environ
        if env.get("POKER_AI_PROVIDER"):
            cfg.provider = str(env["POKER_AI_PROVIDER"]).strip().lower()
        if "POKER_OFFLINE_MODE" in env:
            cfg.offline_mode = _env_flag("POKER_OFFLINE_MODE")
        if "POKER_DJEV_CLOUD_FALLBACK" in env:
            cfg.cloud_fallback = _env_flag("POKER_DJEV_CLOUD_FALLBACK")
        if overrides:
            for key, value in overrides.items():
                if key in ("jev_base", "djev_base") and isinstance(value, dict):
                    setattr(cfg, key, dict(value))
                elif key == "jev" and isinstance(value, dict):
                    cfg.jev_base = dict(value)
                elif key == "djev" and isinstance(value, dict):
                    cfg.djev_base = dict(value)
                elif hasattr(cfg, key):
                    setattr(cfg, key, value)
        if cfg.provider not in (PROVIDER_JEV, PROVIDER_DJEV, PROVIDER_AUTO):
            logger.warning("AI_ROUTER | unknown provider %r, falling back to auto",
                           cfg.provider)
            cfg.provider = PROVIDER_AUTO
        return cfg


def _fmt(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.2f}"


def _log_decision(source: str, model: Any, allowed: bool,
                  reason: str, dec: JevDecision) -> None:
    logger.info(
        "AI_ROUTER | source=%s model=%s allowed=%s go=%s tier=%s (%s) "
        "risky=%s effort=%s (%s) %s",
        source, model, allowed,
        _fmt(dec.go), dec.tier, _fmt(dec.tier_confidence),
        _fmt(dec.risky), _fmt(dec.effort), _fmt(dec.effort_confidence),
        reason,
    )


def _build_jev_config(cfg: AiGateConfig) -> JevGateConfig:
    overrides = {"offline_mode": True} if cfg.offline_mode else None
    return JevGateConfig.from_env(base=cfg.jev_base, overrides=overrides)


def _djev_setting(dcfg: Any, base: dict[str, Any] | None,
                  name: str, default: Any) -> Any:
    if dcfg is not None:
        try:
            value = getattr(dcfg, name, None)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    if isinstance(base, dict) and base.get(name) not in (None, ""):
        return base[name]
    return default


def _via_jev(snapshot: Any, heuristic_allowed: bool, cfg: AiGateConfig,
             jev_cfg: JevGateConfig, source: str) -> tuple[bool, JevDecision, str, str]:
    try:
        allowed, dec, reason = jev_decide(snapshot, heuristic_allowed, config=jev_cfg)
        model = getattr(jev_cfg, "model", "?")
    except Exception as exc:  # jamais d'exception vers l'appelant
        dec = JevDecision(verdict=None,
                          reason=f"fail-open: jev {type(exc).__name__}")
        allowed, reason, model = (heuristic_allowed,
                                  "ai_router jev fail-open, heuristic kept", "?")
    _log_decision(source, model, allowed, reason, dec)
    return allowed, dec, reason, source


def _via_djev(snapshot: Any, heuristic_allowed: bool, cfg: AiGateConfig,
              source: str, base_url_override: Any = None,
              ) -> tuple[bool, JevDecision, str, str]:
    try:
        from src.bot import djev_gate as djev_mod
    except Exception as exc:  # module encore absent -> fail-open
        dec = JevDecision(verdict=None, reason=(
            f"fail-open: djev_gate unavailable ({type(exc).__name__})"))
        reason = "ai_router djev unavailable, heuristic kept"
        _log_decision("fail-open", "?", heuristic_allowed, reason, dec)
        return heuristic_allowed, dec, reason, "fail-open"
    try:
        if base_url_override:
            dcfg = djev_mod.DjevGateConfig.from_env(
                base=cfg.djev_base, overrides={"base_url": base_url_override})
        else:
            dcfg = djev_mod.DjevGateConfig.from_env(base=cfg.djev_base)
        model = _djev_setting(dcfg, cfg.djev_base, "model", "?")
        allowed, dec, reason = djev_mod.decide(snapshot, heuristic_allowed,
                                               config=dcfg)
    except Exception as exc:  # jamais d'exception vers l'appelant
        dec = JevDecision(verdict=None,
                          reason=f"fail-open: djev {type(exc).__name__}")
        allowed, reason, model = (heuristic_allowed,
                                  "ai_router djev fail-open, heuristic kept", "?")
    _log_decision(source, model, allowed, reason, dec)
    return allowed, dec, reason, source


def _auto(snapshot: Any, heuristic_allowed: bool,
           cfg: AiGateConfig) -> tuple[bool, JevDecision, str, str]:
    try:
        from src.bot import djev_gate as djev_mod
        dcfg = djev_mod.DjevGateConfig.from_env(base=cfg.djev_base)
    except Exception:
        dcfg = None  # module absent ou config illisible -> voies jev/fail-open
    api_key_env = str(_djev_setting(dcfg, cfg.djev_base, "api_key_env",
                                    DEFAULT_DJEV_API_KEY_ENV))
    cloud_url = _djev_setting(dcfg, cfg.djev_base, "cloud_url",
                              DEFAULT_DJEV_CLOUD_URL)
    lan_url = _djev_setting(dcfg, cfg.djev_base, "lan_url", "")
    if cfg.offline_mode:
        # WAN interdite : le cloud est saute, loopback uniquement.
        logger.info("AI_ROUTER | offline_mode: cloud %s skipped (no WAN), "
                    "loopback only", cloud_url)
        if lan_url and _is_loopback(lan_url):
            return _via_djev(snapshot, heuristic_allowed, cfg, "djev-lan",
                             base_url_override=lan_url)
        jev_cfg = _build_jev_config(cfg)  # jev_gate replie sur le proxy si WAN
        if not _is_loopback(jev_cfg.base_url):
            logger.info("AI_ROUTER | offline_mode: forcing loopback proxy %s",
                        DEFAULT_PROXY_URL)
            jev_cfg.base_url = DEFAULT_PROXY_URL
        return _via_jev(snapshot, heuristic_allowed, cfg, jev_cfg, "jev")
    if os.environ.get(api_key_env):
        return _via_djev(snapshot, heuristic_allowed, cfg, "djev-cloud")
    return _via_jev(snapshot, heuristic_allowed, cfg,
                    _build_jev_config(cfg), "jev")


def decide(
    snapshot: Any,
    heuristic_allowed: bool,
    *,
    config: AiGateConfig | None = None,
) -> tuple[bool, JevDecision, str, str]:
    """Point d'entree du routeur : choisit jev/djev puis delegue. Fail-open."""
    cfg = config or AiGateConfig.from_env()
    try:
        if cfg.provider == PROVIDER_JEV:
            return _via_jev(snapshot, heuristic_allowed, cfg,
                            _build_jev_config(cfg), "jev")
        if cfg.provider == PROVIDER_DJEV:
            return _via_djev(snapshot, heuristic_allowed, cfg, "djev")
        return _auto(snapshot, heuristic_allowed, cfg)
    except Exception as exc:  # jamais d'exception vers l'appelant
        dec = JevDecision(verdict=None,
                          reason=f"fail-open: ai_router {type(exc).__name__}")
        reason = "ai_router fail-open, heuristic kept"
        _log_decision("fail-open", "?", heuristic_allowed, reason, dec)
        return heuristic_allowed, dec, reason, "fail-open"
