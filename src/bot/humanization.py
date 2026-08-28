"""Humanisation comportementale de la couche d'exécution.

Phase 1 : profil d'humanisation chargé depuis ``config.json → bot.humanization``
et contexte d'exécution riche (ExecutionContext) construit au call-site
gate_flow. Toutes les distributions sont log-normales pour les temps de
réaction ; le RNG est déterministe en tests (seed dédié ou random global
piloté par ``src/utils/seed.py``).
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from src.runtime.session import parse_bool_flag

logger = logging.getLogger(__name__)

BACKEND_WIN32 = "win32"
BACKEND_HID = "hid"


def _as_float(
    value: Any, default: float, lo: float | None = None, hi: float | None = None
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    if lo is not None:
        parsed = max(lo, parsed)
    if hi is not None:
        parsed = min(hi, parsed)
    return parsed


def _as_int(value: Any, default: int, lo: int | None = None, hi: int | None = None) -> int:
    return int(
        round(
            _as_float(
                value,
                float(default),
                None if lo is None else float(lo),
                None if hi is None else float(hi),
            )
        )
    )


def _as_range(value: Any, default: tuple[float, float]) -> tuple[float, float]:
    """Parse un couple [a, b] tolérant ; retombe sur default sinon."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low = _as_float(value[0], default[0])
        high = _as_float(value[1], default[1])
        if low > high:
            low, high = high, low
        return (low, high)
    return default


@dataclass
class MouseConfig:
    speed_px_s: tuple[float, float] = (800.0, 1500.0)
    move_min_duration_s: float = 0.18
    move_max_duration_s: float = 0.85
    overshoot_probability: float = 0.35
    overshoot_amplitude_px: int = 15
    hover_s: tuple[float, float] = (0.10, 0.40)
    hover_jitter_px: float = 3.0
    divergence_px: tuple[int, int] = (20, 60)
    click_down_s: tuple[float, float] = (0.04, 0.12)


@dataclass
class TypingConfig:
    key_delay_s: tuple[float, float] = (0.02, 0.09)
    inter_key_delay_s: tuple[float, float] = (0.04, 0.14)
    group_pause_probability: float = 0.12
    group_pause_s: tuple[float, float] = (0.25, 0.80)
    typo_probability: float = 0.02
    select_ctrl_a_probability: float = 0.50
    select_triple_click_probability: float = 0.10
    legacy_double_enter: bool = False


@dataclass
class ThinkTimeConfig:
    fold_median_s: float = 1.2
    passive_median_s: float = 2.5
    aggressive_median_s: float = 4.5
    sigma: float = 0.45
    preflop_factor: float = 0.75
    big_pot_threshold_bb: float = 8.0
    big_pot_bb_reference: float = 0.0
    big_pot_factor: float = 1.35
    low_confidence_threshold: float = 0.5
    low_confidence_factor: float = 1.30
    min_think_time_s: float = 0.15
    max_think_time_s: float = 12.0


@dataclass
class SessionRhythmConfig:
    enabled: bool = True
    micro_pause_probability: float = 0.05
    micro_pause_s: tuple[float, float] = (3.0, 15.0)
    fatigue_enabled: bool = True
    fatigue_drift_per_hour: float = 0.06
    fatigue_max_drift: float = 0.20


@dataclass
class HumanizationProfile:
    """Profil d'humanisation global, sérialisé dans bot.humanization."""

    enabled: bool = True
    input_backend: str = BACKEND_WIN32
    seed: int | None = None
    mouse: MouseConfig = field(default_factory=MouseConfig)
    typing: TypingConfig = field(default_factory=TypingConfig)
    think: ThinkTimeConfig = field(default_factory=ThinkTimeConfig)
    rhythm: SessionRhythmConfig = field(default_factory=SessionRhythmConfig)
    _rng: random.Random | None = field(default=None, repr=False, compare=False)
    _session_started_monotonic: float = field(
        default_factory=time.monotonic, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if isinstance(self.mouse, dict):
            self.mouse = self._parse_mouse(self.mouse)
        if isinstance(self.typing, dict):
            self.typing = self._parse_typing(self.typing)
        if isinstance(self.think, dict):
            self.think = self._parse_think(self.think)
        if isinstance(self.rhythm, dict):
            self.rhythm = self._parse_rhythm(self.rhythm)
        if self.seed is not None:
            self._rng = random.Random(int(self.seed))
        elif self._rng is None:
            # Pas de seed dédié : on utilisera le random global, piloté par
            # src/utils/seed.seed_everything() en run comme en CI.
            self._rng = None

    # --- RNG -------------------------------------------------------------
    @property
    def rng_active(self) -> bool:
        return self._rng is not None

    def random(self) -> float:
        if self._rng is not None:
            return self._rng.random()
        return random.random()

    def uniform(self, a: float, b: float) -> float:
        if b < a:
            a, b = b, a
        if self._rng is not None:
            return self._rng.uniform(a, b)
        return random.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        if b < a:
            a, b = b, a
        if self._rng is not None:
            return self._rng.randint(a, b)
        return random.randint(a, b)

    def chance(self, probability: float) -> bool:
        return self.random() < float(probability)

    # --- Distributions ----------------------------------------------------
    def sample_reaction_time(self, median: float, sigma: float) -> float:
        """Temps de réaction log-normal (médiane + dispersion)."""
        median = max(0.01, float(median))
        sigma = max(0.05, float(sigma))
        z = self.random()
        # Inverse CDF approx via Box-Muller (sans dépendance numpy).
        u1 = max(z, 1e-9)
        u2 = self.random()
        gauss = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return median * math.exp(sigma * gauss)

    # --- Fatigue / session -------------------------------------------------
    def reset_session_clock(self) -> None:
        """Reset de la dérive de fatigue (pause opérateur, replay, tests)."""
        self._session_started_monotonic = time.monotonic()

    def fatigue_multiplier(self) -> float:
        """Dérive douce des délais sur plusieurs heures, bornée."""
        cfg = self.rhythm
        if not self.enabled or not cfg.enabled or not cfg.fatigue_enabled:
            return 1.0
        elapsed_h = max(0.0, (time.monotonic() - self._session_started_monotonic) / 3600.0)
        drift = min(float(cfg.fatigue_max_drift), elapsed_h * float(cfg.fatigue_drift_per_hour))
        return 1.0 + drift

    def sample_session_micro_pause(self) -> float | None:
        """Pause probabiliste entre les mains ; None si pas de pause ce coup-ci."""
        cfg = self.rhythm
        if not self.enabled or not cfg.enabled:
            return None
        if not self.chance(cfg.micro_pause_probability):
            return None
        low, high = sorted(cfg.micro_pause_s)
        return self.uniform(low, high)

    # --- Config ------------------------------------------------------------
    @staticmethod
    def _parse_mouse(raw: dict[str, Any]) -> MouseConfig:
        d = MouseConfig()
        mouse_speed = _as_range(raw.get("speed_px_s"), d.speed_px_s)
        hover_s = _as_range(raw.get("hover_s"), d.hover_s)
        click_down_s = _as_range(raw.get("click_down_s"), d.click_down_s)
        divergence = _as_range(raw.get("divergence_px"), tuple(map(float, d.divergence_px)))
        return MouseConfig(
            speed_px_s=(max(50.0, mouse_speed[0]), max(100.0, mouse_speed[1])),
            move_min_duration_s=_as_float(
                raw.get("move_min_duration_s"), d.move_min_duration_s, lo=0.02
            ),
            move_max_duration_s=_as_float(
                raw.get("move_max_duration_s"), d.move_max_duration_s, lo=0.05
            ),
            overshoot_probability=_as_float(
                raw.get("overshoot_probability"), d.overshoot_probability, lo=0.0, hi=1.0
            ),
            overshoot_amplitude_px=_as_int(
                raw.get("overshoot_amplitude_px"), d.overshoot_amplitude_px, lo=0
            ),
            hover_s=(hover_s[0], hover_s[1]),
            hover_jitter_px=_as_float(raw.get("hover_jitter_px"), d.hover_jitter_px, lo=0.0),
            divergence_px=(int(divergence[0]), int(divergence[1])),
            click_down_s=(click_down_s[0], click_down_s[1]),
        )

    @staticmethod
    def _parse_typing(raw: dict[str, Any]) -> TypingConfig:
        d = TypingConfig()
        legacy_enter_flag = parse_bool_flag(raw.get("legacy_double_enter"))
        return TypingConfig(
            key_delay_s=_as_range(raw.get("key_delay_s"), d.key_delay_s),
            inter_key_delay_s=_as_range(raw.get("inter_key_delay_s"), d.inter_key_delay_s),
            group_pause_probability=_as_float(
                raw.get("group_pause_probability"), d.group_pause_probability, lo=0.0, hi=1.0
            ),
            group_pause_s=_as_range(raw.get("group_pause_s"), d.group_pause_s),
            typo_probability=_as_float(
                raw.get("typo_probability"), d.typo_probability, lo=0.0, hi=1.0
            ),
            select_ctrl_a_probability=_as_float(
                raw.get("select_ctrl_a_probability"), d.select_ctrl_a_probability, lo=0.0, hi=1.0
            ),
            select_triple_click_probability=_as_float(
                raw.get("select_triple_click_probability"),
                d.select_triple_click_probability,
                lo=0.0,
                hi=1.0,
            ),
            legacy_double_enter=True if legacy_enter_flag is None else legacy_enter_flag,
        )

    @staticmethod
    def _parse_think(raw: dict[str, Any]) -> ThinkTimeConfig:
        d = ThinkTimeConfig()
        return ThinkTimeConfig(
            fold_median_s=_as_float(raw.get("fold_median_s"), d.fold_median_s, lo=0.05),
            passive_median_s=_as_float(raw.get("passive_median_s"), d.passive_median_s, lo=0.05),
            aggressive_median_s=_as_float(
                raw.get("aggressive_median_s"), d.aggressive_median_s, lo=0.05
            ),
            sigma=_as_float(raw.get("sigma"), d.sigma, lo=0.05, hi=1.5),
            preflop_factor=_as_float(raw.get("preflop_factor"), d.preflop_factor, lo=0.1, hi=3.0),
            big_pot_threshold_bb=_as_float(
                raw.get("big_pot_threshold_bb"), d.big_pot_threshold_bb, lo=0.0
            ),
            big_pot_bb_reference=_as_float(
                raw.get("big_pot_bb_reference"), d.big_pot_bb_reference, lo=0.0
            ),
            big_pot_factor=_as_float(raw.get("big_pot_factor"), d.big_pot_factor, lo=0.1, hi=5.0),
            low_confidence_threshold=_as_float(
                raw.get("low_confidence_threshold"), d.low_confidence_threshold, lo=0.0, hi=1.0
            ),
            low_confidence_factor=_as_float(
                raw.get("low_confidence_factor"), d.low_confidence_factor, lo=0.1, hi=5.0
            ),
            min_think_time_s=_as_float(raw.get("min_think_time_s"), d.min_think_time_s, lo=0.0),
            max_think_time_s=_as_float(raw.get("max_think_time_s"), d.max_think_time_s, lo=0.5),
        )

    @staticmethod
    def _parse_rhythm(raw: dict[str, Any]) -> SessionRhythmConfig:
        d = SessionRhythmConfig()
        rhythm_enabled_flag = parse_bool_flag(raw.get("enabled"))
        fatigue_enabled_flag = parse_bool_flag(raw.get("fatigue_enabled"))
        return SessionRhythmConfig(
            enabled=True if rhythm_enabled_flag is None else rhythm_enabled_flag,
            micro_pause_probability=_as_float(
                raw.get("micro_pause_probability"), d.micro_pause_probability, lo=0.0, hi=1.0
            ),
            micro_pause_s=_as_range(raw.get("micro_pause_s"), d.micro_pause_s),
            fatigue_enabled=True if fatigue_enabled_flag is None else fatigue_enabled_flag,
            fatigue_drift_per_hour=_as_float(
                raw.get("fatigue_drift_per_hour"), d.fatigue_drift_per_hour, lo=0.0, hi=2.0
            ),
            fatigue_max_drift=_as_float(
                raw.get("fatigue_max_drift"), d.fatigue_max_drift, lo=0.0, hi=5.0
            ),
        )

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> HumanizationProfile:
        raw = dict(raw or {})
        if raw and not isinstance(raw, dict):
            raise ValueError("bot.humanization doit être une table de configuration")

        enabled_flag = parse_bool_flag(raw.get("enabled"))
        enabled = True if enabled_flag is None else enabled_flag

        backend = str(raw.get("input_backend") or BACKEND_WIN32).strip().lower()
        if backend == BACKEND_HID:
            raise ValueError(
                "bot.humanization.input_backend='hid' n'est pas encore implémenté : "
                "voir docs/hid_bridge.md pour le pont HID matériel (Arduino Pro Micro / KMBox)."
            )
        if backend != BACKEND_WIN32:
            raise ValueError(
                f"bot.humanization.input_backend inconnu : '{backend}' "
                f"(attendu : '{BACKEND_WIN32}' ou '{BACKEND_HID}')"
            )

        seed_raw = raw.get("seed")
        seed: int | None = None
        if seed_raw is not None:
            try:
                seed = int(seed_raw)
            except (TypeError, ValueError):
                logger.warning("bot.humanization.seed invalide (%r), ignoré.", seed_raw)

        return cls(
            enabled=enabled,
            input_backend=backend,
            seed=seed,
            mouse=cls._parse_mouse(dict(raw.get("mouse") or {})),
            typing=cls._parse_typing(dict(raw.get("typing") or {})),
            think=cls._parse_think(dict(raw.get("think") or {})),
            rhythm=cls._parse_rhythm(dict(raw.get("session_rhythm") or {})),
        )


def compute_think_time(
    profile: HumanizationProfile,
    action_name: str,
    bet_size: float | None = None,
    context: ExecutionContext | None = None,
) -> float:
    """Think time contextuel : base par action × modulateurs × fatigue, borné."""
    cfg = profile.think
    action = str(action_name or "").strip().upper()

    if action == "FOLD":
        median = cfg.fold_median_s
    elif action in {"CHECK", "CALL"} and bet_size is None:
        median = cfg.passive_median_s
    else:
        median = cfg.aggressive_median_s

    seconds = profile.sample_reaction_time(median, cfg.sigma)

    street = str(getattr(context, "street", "") or "").strip().upper()
    if street == "PREFLOP":
        seconds *= cfg.preflop_factor

    pot = getattr(context, "pot", None)
    bb_reference = float(cfg.big_pot_bb_reference or 0.0)
    if pot is not None and bb_reference > 0.0:
        try:
            if float(pot) >= cfg.big_pot_threshold_bb * bb_reference:
                seconds *= cfg.big_pot_factor
        except (TypeError, ValueError):
            pass

    confidence = getattr(context, "state_confidence", None)
    if confidence is not None:
        try:
            if 0.0 <= float(confidence) < cfg.low_confidence_threshold:
                seconds *= cfg.low_confidence_factor
        except (TypeError, ValueError):
            pass

    seconds *= profile.fatigue_multiplier()

    lower = min(cfg.min_think_time_s, cfg.max_think_time_s)
    upper = max(cfg.min_think_time_s, cfg.max_think_time_s)
    return float(min(max(seconds, lower), upper))


@dataclass(frozen=True)
class ExecutionContext:
    """Contexte de spot disponible au moment de l'exécution (gate_flow)."""

    street: str = ""
    pot: float | None = None
    state_confidence: float | None = None
    spot_id: str = ""
    hand_elapsed_s: float | None = None

    @classmethod
    def from_canonical_state(cls, canonical_state: Any) -> ExecutionContext:
        def _optional_float(value: Any) -> float | None:
            if value is None:
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return None
            if math.isnan(parsed) or math.isinf(parsed):
                return None
            return parsed

        return cls(
            street=str(getattr(canonical_state, "street", "") or ""),
            pot=_optional_float(getattr(canonical_state, "pot", None)),
            state_confidence=_optional_float(getattr(canonical_state, "state_confidence", None)),
            spot_id=str(getattr(canonical_state, "spot_id", "") or ""),
            hand_elapsed_s=None,
        )
