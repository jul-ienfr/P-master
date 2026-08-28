import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Any

import numpy as np

from src.data.redis_cache import AsyncRedisCache
from src.solver.provider import SolverProvider

from .icm_calculator import ICMCalculator
from .preflop_ranges import PreflopManager
from .preflop_support import (  # noqa: F401  (réexports pour compat)
    BASE_GTO_RANGE,
    CARD_RANK_ORDER,
    PREFLOP_FAST_3BET_RANGE,
    PREFLOP_POSITION_ORDER,
)
from .preflop_support import (
    cached_range_items as _cached_range_items_impl,
)
from .preflop_support import (
    combo_in_range as _combo_in_range_impl,
)
from .preflop_support import (
    hero_combo_notation as _hero_combo_notation_impl,
)
from .preflop_support import (
    normalize_hero_hand_string as _normalize_hero_hand_string_impl,
)
from .preflop_support import (
    normalize_preflop_position as _normalize_preflop_position_impl,
)
from .preflop_support import (
    run_preflop_fast_path as _run_preflop_fast_path_impl,
)
from .range_updater import BayesianRangeUpdater

_DEFAULT_DEPENDENCY = object()

# Phase 2.6 — circuit breaker solver : seuil, base et cap du backoff exponentiel
_SOLVER_BREAKER_THRESHOLD = 3
_SOLVER_BREAKER_BASE_COOLDOWN_S = 60.0
_SOLVER_BREAKER_MAX_COOLDOWN_S = 300.0

try:
    from .rl_agent import RLAdapterAgent

    RL_AVAILABLE = True
except ImportError:
    RL_AVAILABLE = False
    logging.warning("Le module RLAdapterAgent n'est pas disponible.")

# On essaye d'importer le binding Rust compilé par PyO3
try:
    import postflop_solver_py

    RUST_SOLVER_AVAILABLE = True
except ImportError:
    postflop_solver_py = None
    RUST_SOLVER_AVAILABLE = False
    logging.warning(
        "Le module Rust 'postflop_solver_py' n'est pas disponible. Mode simulation activé."
    )

logger = logging.getLogger(__name__)

# Mapping des actions possibles
ACTION_MAP = {
    "FOLD": 0,
    "CHECK": 1,
    "CALL": 1,
    "BET": 2,
    "RAISE": 2,
    "BET_50": 2,
    "BET_75": 3,
    "ALL_IN": 4,
}
REVERSE_ACTION_MAP = {0: "FOLD", 1: "CHECK", 2: "BET", 3: "BET_75", 4: "ALL_IN"}

# Phase 2.7 — constantes et helpers preflop déplacés dans preflop_support.py ;
# alias conservés pour compat (tests, imports historiques).

PROFILE_RANGES = {
    "LoosePassive": "22+, A2s+, K2s+, Q4s+, J5s+, T6s+, 96s+, 86s+, 75s+, 64s+, 54s, A2o+, K7o+, Q8o+, J8o+, T8o+",
    "LooseAggressive": "22+, A2s+, K4s+, Q7s+, J7s+, T7s+, 97s+, 87s, 76s, 65s, A8o+, K9o+, QTo+, JTo",
    "TightPassive": "88+, ATs+, KQs, AQo+, AKo",
    "TightAggressive": "66+, A9s+, KTs+, QTs+, JTs, AJo+, KQo",
    "RegPassive": "55+, A5s+, K9s+, QTs+, JTs, T9s, ATo+, KJo+",
    "RegAggressive": "44+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s, 87s, A9o+, KTo+, QJo",
    "Balanced": BASE_GTO_RANGE,
    "Maniac": "22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, 52s+, 42s+, 32s+, A2o+, K2o+, Q2o+, J2o+, T2o+",
    "Whale": "22+, A2s+, K2s+, Q2s+, J2s+, T2s+, 92s+, 82s+, 72s+, 62s+, 52s+, 42s+, 32s+, A2o+, K2o+, Q2o+, J2o+, T2o+",
    "Nit": "99+, AJs+, AKo",
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _rate_from_profile(profile: dict, raw_key: str, derived_key: str) -> float:
    derived = profile.get("derived_profile") or {}
    if derived_key in derived:
        return float(derived.get(derived_key, 0.0) or 0.0)
    sample_hands = max(
        int(
            derived.get("observed_hands", 0)
            or profile.get("observed_hands", 0)
            or profile.get("hands_played", 0)
            or 0
        ),
        1,
    )
    return float(profile.get(raw_key, 0) or 0) / float(sample_hands)


def _profile_sample_hands(profile: dict) -> int:
    derived = profile.get("derived_profile") or {}
    return int(
        derived.get("observed_hands", 0)
        or profile.get("observed_hands", 0)
        or derived.get("hands_played", 0)
        or profile.get("hands_played", 0)
        or 0
    )


def _normalize_action_name(action: str | None) -> str | None:
    if not action:
        return None
    return str(action).strip().upper()


def _normalize_hero_hand_string(hero_hand: str) -> str:
    return _normalize_hero_hand_string_impl(hero_hand)


def _normalize_preflop_position(value: str | None) -> str | None:
    return _normalize_preflop_position_impl(value)


def _hero_combo_notation(hero_hand: str) -> str:
    return _hero_combo_notation_impl(hero_hand)


@lru_cache(maxsize=512)
def _combo_in_range(combo: str, range_text: str) -> bool:
    return _combo_in_range_impl(combo, range_text)


def _cached_range_items(range_text: str) -> tuple[str, ...]:
    return _cached_range_items_impl(range_text)


@lru_cache(maxsize=256)
def _build_structured_profile_cached(profile_blob: str) -> dict:
    profile = json.loads(profile_blob) if profile_blob else None
    if not profile:
        return {
            "style": "Unknown",
            "hands_played": 0,
            "observed_hands": 0,
            "reliability": 0.0,
            "vpip": 0.0,
            "pfr": 0.0,
            "gap": 0.0,
            "aggression_frequency": 0.0,
            "exploit_confidence": 0.0,
            "range_hint": BASE_GTO_RANGE,
            "pressure_bias": 0.0,
            "call_bias": 0.0,
            "fold_bias": 0.0,
            "deviation_cap": 0.0,
            "rl_ready": False,
        }

    derived = profile.get("derived_profile") or {}
    hands_played = int(derived.get("hands_played", profile.get("hands_played", 0)) or 0)
    observed_hands = int(derived.get("observed_hands", profile.get("observed_hands", 0)) or 0)
    vpip = _rate_from_profile(profile, "vpip_count", "vpip_rate")
    pfr = _rate_from_profile(profile, "pfr_count", "pfr_rate")
    aggression_frequency = float(derived.get("aggression_frequency", profile.get("af", 0.0)) or 0.0)
    reliability = float(derived.get("reliability", min(1.0, observed_hands / 120.0)) or 0.0)
    style = str(derived.get("style") or profile.get("player_type") or "Balanced")
    gap = round(max(0.0, vpip - pfr), 4)

    pressure_bias = 0.0
    call_bias = 0.0
    fold_bias = 0.0

    if style == "LoosePassive" or style == "Whale":
        call_bias = 0.22
        pressure_bias = 0.18
        fold_bias = -0.08
    elif style == "LooseAggressive" or style == "Maniac":
        call_bias = -0.06
        pressure_bias = -0.14
        fold_bias = 0.16
    elif style == "TightPassive" or style == "Nit":
        call_bias = -0.18
        pressure_bias = 0.12
        fold_bias = 0.18
    elif style == "TightAggressive":
        call_bias = -0.08
        pressure_bias = -0.06
        fold_bias = 0.1
    elif style == "RegPassive":
        call_bias = 0.08
        pressure_bias = 0.06
        fold_bias = 0.05
    elif style == "RegAggressive":
        call_bias = -0.04
        pressure_bias = -0.04
        fold_bias = 0.04

    exploit_confidence = round(
        _clamp(reliability * (0.55 + min(gap, 0.2) + abs(aggression_frequency - 0.33)), 0.0, 1.0),
        3,
    )
    deviation_cap = round(_clamp(0.05 + (exploit_confidence * 0.2), 0.0, 0.25), 3)

    return {
        "style": style,
        "hands_played": hands_played,
        "observed_hands": observed_hands,
        "reliability": reliability,
        "vpip": vpip,
        "pfr": pfr,
        "gap": gap,
        "aggression_frequency": aggression_frequency,
        "exploit_confidence": exploit_confidence,
        "range_hint": PROFILE_RANGES.get(style, BASE_GTO_RANGE),
        "pressure_bias": pressure_bias,
        "call_bias": call_bias,
        "fold_bias": fold_bias,
        "deviation_cap": deviation_cap,
        "rl_ready": bool(derived.get("rl_ready", False)),
    }


def _analyze_board_texture(board: list[str]) -> str:
    """Analyse la texture des cartes communes (board) pour ajuster le bet sizing."""
    if not board or len(board) < 3:
        return "DRY"  # Préflop

    ranks = "23456789TJQKA"
    board_suits = [card[-1] for card in board if len(card) == 2]
    board_ranks = [ranks.find(card[0]) for card in board if len(card) == 2 and card[0] in ranks]

    if not board_suits or not board_ranks:
        return "DRY"

    from collections import Counter

    suit_counts = Counter(board_suits)
    max_suit_count = max(suit_counts.values())

    if max_suit_count >= 3:
        return "MONOTONE"

    board_ranks = sorted(board_ranks)
    gaps = sum(board_ranks[i + 1] - board_ranks[i] for i in range(len(board_ranks) - 1))

    if gaps <= 3 or max_suit_count == 2:
        return "WET"

    return "DRY"


def _bet_size_suffix(action_name: str) -> tuple[str, float | None]:
    """Extrait (préfixe, valeur) d'un nom d'action comme BET_75, RAISE_2.5X, ALLIN_500."""
    normalized = _normalize_action_name(action_name)
    if not normalized:
        return "", None

    for prefix in ("BET", "RAISE", "ALLIN", "ALL_IN"):
        if normalized == prefix:
            return prefix, None
        if normalized.startswith(prefix + "_"):
            raw = normalized[len(prefix) + 1 :].strip().rstrip("X").rstrip("%")
            try:
                return prefix, float(raw)
            except ValueError:
                return prefix, None
    return "", None


def _bet_amount_from_value(prefix: str, value: float, pot: float) -> float | None:
    """Convertit une taille abstraite en fraction de pot exécutable.

    - BET_X   : X <= 1.5 -> fraction de pot ; sinon pourcentage de pot.
    - RAISE_X : X <= 10  -> multiple de pot ; sinon pourcentage de pot.
    """
    if value is None:
        return None
    if prefix == "RAISE":
        ratio = value if value <= 10 else value / 100.0
        return max(ratio, 0.0) * pot
    ratio = value if value <= 1.5 else value / 100.0
    return max(ratio, 0.0) * pot


def _bet_size_from_action(
    action_name: str | None, pot: float, effective_stack: float, board: list[str] = None
) -> float | None:
    normalized = _normalize_action_name(action_name)
    if not normalized:
        return None

    if (
        normalized == "ALL_IN"
        or normalized.startswith("ALLIN")
        or normalized.startswith("ALL_IN")
    ):
        return round(max(effective_stack, 0.0), 2)

    # Tailles explicites du solveur (BET_50, BET_0.75, RAISE_2.5, ALLIN_*, etc.)
    prefix, value = _bet_size_suffix(normalized)
    if prefix in {"BET", "RAISE"} and value is not None and pot > 0:
        amount = _bet_amount_from_value(prefix, value, pot)
        if amount is not None:
            return round(min(max(amount, 1.0), effective_stack), 2)

    spr = effective_stack / pot if pot > 0 else 100.0

    if normalized in {"BET", "RAISE"} and spr <= 0.8:
        return round(max(effective_stack, 0.0), 2)

    if normalized in {"BET", "RAISE"}:
        texture = _analyze_board_texture(board or [])

        if texture == "DRY":
            target_size = pot * 0.33
        elif texture == "WET":
            target_size = pot * 0.75
        elif texture == "MONOTONE":
            target_size = pot * 0.50
        else:
            target_size = pot * 0.50

        streets_remaining = 4 - len(board) if board else 3
        if streets_remaining > 0 and 1.0 < spr <= 4.0:
            geometric_ratio = (spr + 1) ** (1 / streets_remaining) - 1
            target_size = max(target_size, pot * geometric_ratio)

        return round(min(max(target_size, 1.0), effective_stack), 2)

    if normalized == "BET_50":
        return round(min(max(pot * 0.5, 1.0), effective_stack), 2)
    if normalized == "BET_75":
        return round(min(max(pot * 0.75, 1.0), effective_stack), 2)

    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _compact_solver_list(value: Any) -> list | None:
    if not isinstance(value, list):
        return None

    compact: list = []
    for item in value:
        if isinstance(item, dict):
            compact.append(dict(item))
        else:
            text = _safe_string(item)
            if text is not None:
                compact.append(text)
    return compact


class DecisionMaker:
    def __init__(
        self,
        db_manager,
        solver_backend: Any = _DEFAULT_DEPENDENCY,
        solver_provider: SolverProvider | None = None,
        rl_agent: Any = _DEFAULT_DEPENDENCY,
        create_rl_agent: bool = True,
        enable_validated_rl: bool = False,
        autoload_rl_model: bool = True,
        redis_cache: Any = None,
    ):
        self.db = db_manager
        self.icm_calculator = ICMCalculator()
        self.preflop_manager = PreflopManager()
        resolved_solver_backend = (
            postflop_solver_py
            if solver_backend is _DEFAULT_DEPENDENCY and RUST_SOLVER_AVAILABLE
            else None
            if solver_backend is _DEFAULT_DEPENDENCY
            else solver_backend
        )
        self.solver_backend = resolved_solver_backend
        self._solver_backend_explicit = solver_backend is not _DEFAULT_DEPENDENCY
        self.solver_provider = solver_provider
        if self.solver_provider is None and resolved_solver_backend is not None:
            self.solver_provider = SolverProvider(native_backend=resolved_solver_backend)

        self.hero_base_range = BASE_GTO_RANGE

        # Circuit Breaker variables
        self._consecutive_solver_timeouts = 0
        self._solver_cooldown_until = 0.0

        if rl_agent is _DEFAULT_DEPENDENCY:
            self.rl_agent = RLAdapterAgent() if create_rl_agent and RL_AVAILABLE else None
        else:
            self.rl_agent = rl_agent

        self.create_rl_agent = create_rl_agent
        self.enable_validated_rl = enable_validated_rl
        self.autoload_rl_model = autoload_rl_model
        # Phase 3.3 — cache L2 optionnel (no-op sans POKER_REDIS_URL).
        self.redis_cache = redis_cache if redis_cache is not None else AsyncRedisCache()
        # Phase 3.6 — cache solve en mémoire (LRU + TTL), évite les re-solves
        # identiques quand les frames se répètent sur un même état de table.
        self._solve_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._solve_cache_ttl_s = 10.0
        self._solve_cache_max_entries = 256
        self.enable_llm_assist = False  # Par défaut, le LLM est désactivé (100% local)

        # Configuration de la Rake (Commission du Casino) - NL2 à NL10 = 5%
        self.rake_percentage = 0.05
        # Plafond de rake transmis au solveur (0 = pas de cap)
        self.rake_cap = 0.0
        # Échantillonnage mixte : jouer parfois les fréquences du combo héro
        # au lieu de l'action à EV max (défaut: déterministe).
        self.sample_mixed = False
        # Phase 1 — préflop dual-mode : "precomputed" (défaut) | "live" | "charts"
        self.preflop_mode = "precomputed"
        self.preflop_live_budget_ms = 800
        self.preflop_solutions_path = "models/preflop"
        self._preflop_store: Any = None
        self._profile_cache: dict[str, tuple[float, dict | None]] = {}
        self._profile_cache_ttl_s = 30.0

        if (
            self.rl_agent
            and rl_agent is _DEFAULT_DEPENDENCY
            and self.create_rl_agent
            and self.autoload_rl_model
        ):
            self.rl_agent.load_model()

    def _solver_backend_name(self) -> str:
        provider_backend = self.solver_provider.active_backend() if self.solver_provider else ""
        if provider_backend and provider_backend != "fallback":
            return provider_backend
        if not self.solver_backend:
            return "fallback"
        if self.solver_backend is postflop_solver_py:
            return "native_solver"
        return getattr(self.solver_backend, "backend_name", self.solver_backend.__class__.__name__)

    def _call_solver_backend(
        self,
        hero_hand: str,
        villain_range: str,
        board: list[str],
        pot: float,
        effective_stack: float,
        legal_actions: list[str],
        spot_id: str,
        hero_position: str,
        state_confidence: float,
        action_history: list[dict[str, Any]] | None,
        time_budget_ms: int = 1000,
    ) -> dict:
        # La rake est désormais modélisée DANS l'arbre (rake_rate/rake_cap) et non
        # plus en déflatant le pot.
        if not self.solver_provider:
            raise RuntimeError("rust_solver_unavailable")

        cache_key = self._solve_cache_key(
            hero_hand=hero_hand,
            villain_range=villain_range,
            board=board,
            pot=pot,
            effective_stack=effective_stack,
            legal_actions=legal_actions,
            spot_id=spot_id,
            hero_position=hero_position,
            rake=self.rake_percentage,
            action_history=[
                f"{item.get('player', '')}:{item.get('action', '')}:{item.get('amount', 0)}"
                for item in (action_history or [])
            ],
        )
        cached_response = self._solve_cache_get(cache_key)
        if cached_response is not None:
            return cached_response

        response = self.solver_provider.solve_spot_v2(
            hero_range=hero_hand,
            villain_ranges=[villain_range],
            board=board,
            starting_pot=pot,
            effective_stack=effective_stack,
            legal_actions=legal_actions,
            spot_id=spot_id,
            hero_position=hero_position,
            state_confidence=state_confidence,
            action_history=[
                f"{item.get('player', '')}:{item.get('action', '')}:{item.get('amount', 0)}"
                for item in (action_history or [])
            ],
            use_cache=True,
            time_budget_ms=time_budget_ms,
            rake=self.rake_percentage,
            rake_cap=self.rake_cap,
            hero_hand=hero_hand,
            sample_mixed=self.sample_mixed,
        )
        self._solve_cache_put(cache_key, response)
        return response

    @staticmethod
    def _solve_cache_key(
        *,
        hero_hand: str,
        villain_range: str,
        board: list[str],
        pot: float,
        effective_stack: float,
        legal_actions: list[str],
        spot_id: str,
        hero_position: str,
        action_history: list[str],
        rake: float = 0.0,
    ) -> str:
        blob = json.dumps(
            {
                "hero": hero_hand,
                "villain": villain_range,
                "board": list(board or []),
                "pot": round(float(pot), 4),
                "stack": round(float(effective_stack), 4),
                "legal": list(legal_actions or []),
                "spot": spot_id,
                "pos": hero_position,
                "hist": action_history,
                "rake": round(float(rake), 4),
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _solve_cache_get(self, key: str) -> dict | None:
        entry = self._solve_cache.get(key)
        if entry is None:
            return None
        stored_at, response = entry
        if (time.monotonic() - stored_at) > self._solve_cache_ttl_s:
            del self._solve_cache[key]
            return None
        self._solve_cache.move_to_end(key)
        hit = dict(response)
        hit["cache_hit"] = True
        hit["solve_cache"] = {"hit": True}
        return hit

    def _solve_cache_put(self, key: str, response: dict) -> None:
        if not isinstance(response, dict) or response.get("fallback_used"):
            return
        self._solve_cache[key] = (time.monotonic(), dict(response))
        while len(self._solve_cache) > self._solve_cache_max_entries:
            self._solve_cache.popitem(last=False)

    def _state_to_vector(
        self, hero_hand: str, board: list[str], pot: float, effective_stack: float, profile: dict
    ) -> np.ndarray:
        derived = profile.get("derived_profile") or {}
        sample_hands = max(_profile_sample_hands(profile), 1)
        vpip = float(derived.get("vpip_rate", profile.get("vpip_count", 0) / sample_hands) or 0.0)
        pfr = float(derived.get("pfr_rate", profile.get("pfr_count", 0) / sample_hands) or 0.0)
        af = float(derived.get("aggression_ratio", profile.get("af", 1.0)) or 1.0)

        state = np.zeros(50)
        state[0] = pot / max(effective_stack, 1.0)
        state[1] = effective_stack / 100.0
        state[2] = vpip
        state[3] = pfr
        state[4] = af
        return state

    def _build_structured_profile(self, profile: dict | None) -> dict:
        profile_blob = ""
        if profile:
            try:
                profile_blob = json.dumps(profile, sort_keys=True, default=str)
            except TypeError:
                profile_blob = json.dumps(dict(profile), sort_keys=True, default=str)
        return dict(_build_structured_profile_cached(profile_blob))

    async def _get_cached_profile(self, villain_name: str, *, allow_fetch: bool) -> dict | None:
        cache_key = str(villain_name or "").strip()
        if not cache_key:
            return None

        cached_entry = self._profile_cache.get(cache_key)
        now = time.monotonic()
        if cached_entry is not None:
            cached_at, cached_profile = cached_entry
            if (now - cached_at) <= self._profile_cache_ttl_s:
                return dict(cached_profile) if isinstance(cached_profile, dict) else None

        if (
            not allow_fetch
            or not self.db
            or not getattr(self.db, "is_available", bool(getattr(self.db, "pool", None)))
        ):
            return (
                dict(cached_entry[1])
                if cached_entry and isinstance(cached_entry[1], dict)
                else None
            )

        # Phase 3.3 — L2 Redis (opt-in POKER_REDIS_URL) devant le fetch DB.
        profile = None
        redis_cache = getattr(self, "redis_cache", None)
        if redis_cache is not None:
            profile = await redis_cache.get_json(f"profile:{cache_key}")

        if profile is None:
            profile = await self.db.get_player_profile(villain_name)
            if isinstance(profile, dict) and redis_cache is not None:
                await redis_cache.set_json(
                    f"profile:{cache_key}",
                    profile,
                    ttl_s=self._profile_cache_ttl_s,
                )

        stored_profile = dict(profile) if isinstance(profile, dict) else None
        self._profile_cache[cache_key] = (now, stored_profile)
        return dict(stored_profile) if isinstance(stored_profile, dict) else None

    def _infer_villain_position(
        self,
        villain_name: str,
        hero_position: str,
        action_history: list[dict[str, Any]] | None,
    ) -> str:
        normalized_villain_name = str(villain_name or "").strip().lower()
        for item in reversed(action_history or []):
            if not isinstance(item, dict):
                continue
            actor_name = str(item.get("player") or item.get("name") or "").strip().lower()
            if normalized_villain_name and actor_name and actor_name != normalized_villain_name:
                continue
            for key in ("position", "player_position", "villain_position", "seat_position"):
                inferred = _normalize_preflop_position(item.get(key))
                if inferred:
                    return inferred
        return _normalize_preflop_position(hero_position) or "HJ"

    @staticmethod
    def _has_aggressive_preflop_history(action_history: list[dict[str, Any]] | None) -> bool:
        for item in action_history or []:
            if not isinstance(item, dict):
                continue
            action_name = _normalize_action_name(item.get("action"))
            if not action_name:
                continue
            if (
                action_name.startswith("BET")
                or action_name.startswith("RAISE")
                or action_name in {"OPEN", "3BET"}
            ):
                return True
        return False

    @staticmethod
    def _preferred_aggressive_action(legal_actions: list[str]) -> str | None:
        normalized_legal_actions = [_normalize_action_name(action) for action in legal_actions]
        if "RAISE" in normalized_legal_actions:
            return "RAISE"
        if "BET" in normalized_legal_actions:
            return "BET"
        if "ALL_IN" in normalized_legal_actions:
            return "ALL_IN"
        return None

    def _run_preflop_fast_path(
        self,
        *,
        hero_hand: str,
        legal_actions: list[str],
        hero_position: str,
        action_history: list[dict[str, Any]] | None,
        effective_stack: float = 0.0,
        pot: float = 0.0,
    ) -> tuple[str, dict]:
        # Phase 2.7 — logique déléguée à preflop_support.run_preflop_fast_path.
        facing_raise = (
            "CALL" in legal_actions and "CHECK" not in legal_actions
        ) or self._has_aggressive_preflop_history(action_history)
        aggressive_action = self._preferred_aggressive_action(legal_actions)
        return _run_preflop_fast_path_impl(
            hero_hand=hero_hand,
            legal_actions=legal_actions,
            hero_position=hero_position,
            effective_stack=effective_stack,
            pot=pot,
            preflop_manager=self.preflop_manager,
            facing_raise=facing_raise,
            aggressive_action=aggressive_action,
        )

    def _should_allow_rl_override(self, structured_profile: dict) -> bool:
        if not self.rl_agent or not self.enable_validated_rl:
            return False
        return bool(
            structured_profile.get("rl_ready")
            and structured_profile.get("reliability", 0.0) >= 0.75
            and structured_profile.get("exploit_confidence", 0.0) >= 0.7
        )

    def configure_preflop(
        self,
        *,
        mode: str | None = None,
        solutions_path: str | None = None,
        live_budget_ms: int | None = None,
    ) -> None:
        """Phase 1 — configure le dual-mode préflop (config/env -> runtime)."""
        normalized = str(mode or "").strip().lower()
        if normalized in {"precomputed", "live", "charts"}:
            self.preflop_mode = normalized
        if solutions_path:
            self.preflop_solutions_path = str(solutions_path)
        if live_budget_ms is not None and int(live_budget_ms) > 0:
            self.preflop_live_budget_ms = int(live_budget_ms)
        # Invalide le store si le chemin change.
        self._preflop_store = None

    def _get_preflop_store(self):
        if self._preflop_store is None:
            from .preflop_solutions import PreflopSolutionStore

            self._preflop_store = PreflopSolutionStore(self.preflop_solutions_path)
        return self._preflop_store

    @staticmethod
    def _multiway_time_budget(active_villain_count: int) -> int:
        """Phase 3, garde-fou : budget solve réduit automatiquement en multiway."""
        if active_villain_count <= 2:
            return 1000
        if active_villain_count == 3:
            return 700
        return 500

    def _run_preflop_dual_mode(
        self,
        *,
        hero_hand: str,
        legal_actions: list[str],
        hero_position: str,
        action_history: list[dict[str, Any]] | None,
        effective_stack: float,
        pot: float,
        facing_raise: bool,
        aggressive_action: str | None,
    ) -> tuple[str, dict]:
        """Résolution préflop selon preflop_mode, avec repli charts garanti."""
        can_check = "CHECK" in legal_actions

        def chart_fallback() -> tuple[str, dict]:
            return self._run_preflop_fast_path(
                hero_hand=hero_hand,
                legal_actions=legal_actions,
                hero_position=hero_position,
                action_history=action_history,
                effective_stack=effective_stack,
                pot=pot,
            )

        mode = str(self.preflop_mode or "charts").strip().lower()

        if mode == "live":
            try:
                from .preflop_solutions import resolve_live_decision

                resolution = resolve_live_decision(
                    _hero_combo_notation_impl(hero_hand),
                    context="vs_raise" if facing_raise else "rfi",
                    depth_bb=effective_stack,
                    pot=pot,
                    to_call=pot * 0.5 if facing_raise else 0.0,
                    effective_stack=effective_stack,
                    time_budget_ms=self.preflop_live_budget_ms,
                )
                chosen = self._normalize_solver_action(
                    resolution["chosen_action"], legal_actions
                )
                return chosen, {
                    "chosen_action": chosen,
                    "hero_ev": 0.0,
                    "exploitability": 0.0,
                    "decision_confidence": 0.88 if resolution.get("budget_respected") else 0.8,
                    "dynamic_amount": resolution.get("dynamic_amount"),
                    "actions": [
                        {"action": chosen, "freq": 1.0, "source": "preflop_live"}
                    ],
                    "elapsed_ms": int(resolution.get("elapsed_ms", 0)),
                    "backend": "preflop_live",
                    "cache_hit": False,
                    "solve_mode": "preflop_live",
                    "equity": resolution.get("equity"),
                    "samples": resolution.get("samples"),
                    "backend_details": {
                        "name": "preflop_live",
                        "facing_raise": facing_raise,
                        "budget_respected": bool(resolution.get("budget_respected")),
                    },
                }
            except Exception as exc:  # pragma: no cover
                logger.warning("Preflop live échec (%s), repli charts.", exc)

        if mode in {"precomputed", "live"}:
            try:
                store = self._get_preflop_store()
                from random import Random

                chosen, dynamic_amount, metadata = store.decide(
                    _hero_combo_notation_impl(hero_hand),
                    context="vs_raise" if facing_raise else "rfi",
                    position=_normalize_preflop_position_impl(hero_position) or "BTN",
                    depth_bb=effective_stack,
                    facing_raise=facing_raise,
                    aggressive_action=aggressive_action,
                    can_check=can_check,
                    sample_mixed=self.sample_mixed,
                    rng=Random(),
                )
                if chosen:
                    chosen = self._normalize_solver_action(chosen, legal_actions)
                    return chosen, {
                        "chosen_action": chosen,
                        "hero_ev": 0.0,
                        "exploitability": 0.0,
                        "decision_confidence": 0.9,
                        "dynamic_amount": dynamic_amount,
                        "actions": [
                            {"action": chosen, "freq": metadata.get("frequencies", {}).get("call", 1.0),
                             "source": "preflop_precomputed"}
                        ],
                        "elapsed_ms": int(metadata.get("elapsed_ms", 0)),
                        "backend": "preflop_precomputed",
                        "cache_hit": True,
                        "solve_mode": "preflop_precomputed",
                        "preflop_solution": metadata,
                        "backend_details": {"name": "preflop_precomputed", **metadata},
                    }
            except Exception as exc:  # pragma: no cover
                logger.warning("Preflop precomputed échec (%s), repli charts.", exc)

        return chart_fallback()

    def _select_exploit_action(
        self,
        legal_actions: list[str],
        gto_action: str,
        rl_action_name: str | None,
        structured_profile: dict,
        ev_by_action: dict[str, float] | None = None,
    ) -> tuple[str, str]:
        """Phase 2.10 — déviation exploitative basée EV-delta (plus de biais scalaires).

        On ne dévie de l'action GTO que si une action légale apporte un gain EV
        significatif pour le combo héro, proportionnel au profil villain
        (exploit_confidence) et borné par le deviation_cap. Sans données EV
        fiables, on reste sur la stratégie GTO.
        """
        normalized_legal_actions = {
            _normalize_action_name(action): action for action in legal_actions
        }
        normalized_gto = _normalize_action_name(gto_action)
        normalized_rl = _normalize_action_name(rl_action_name)

        if self._should_allow_rl_override(structured_profile):
            if (
                normalized_rl
                and normalized_rl in normalized_legal_actions
                and normalized_rl != normalized_gto
            ):
                return normalized_legal_actions[normalized_rl], "RL_VALIDATED"

        deviation_cap = float(structured_profile.get("deviation_cap", 0.0) or 0.0)
        exploit_confidence = float(
            structured_profile.get("exploit_confidence", 0.0) or 0.0
        )

        if deviation_cap < 0.08:
            return gto_action, "GTO_RUST"

        # Exploitation par EV-delta : uniquement si les EV par action du solveur
        # sont disponibles et différenciés.
        if ev_by_action:
            gto_ev = ev_by_action.get(normalized_gto)
            if gto_ev is not None and exploit_confidence >= 0.3:
                gain_threshold = deviation_cap * 0.5
                candidates = [
                    (float(ev), action)
                    for action, ev in ev_by_action.items()
                    if action in normalized_legal_actions
                    and action != normalized_gto
                    and isinstance(ev, (int, float))
                    and ev - gto_ev >= gain_threshold
                ]
                if candidates:
                    candidates.sort(reverse=True)
                    best_ev, best_action = candidates[0]
                    return normalized_legal_actions[best_action], "EXPLOIT_EV"

        return gto_action, "GTO_RUST"

    def _build_rl_ab_metadata(
        self,
        legal_actions: list[str],
        gto_action: str,
        rl_action_name: str | None,
        structured_profile: dict,
        final_action: str,
        decision_source: str,
        alternatives: list[dict],
    ) -> dict:
        normalized_legal_actions = self._normalize_runtime_actions(legal_actions)
        rl_available = bool(self.rl_agent)
        if not rl_available:
            return {}

        normalized_rl = (
            self._normalize_solver_action(rl_action_name, legal_actions) if rl_action_name else None
        )
        rl_eligible = self._should_allow_rl_override(structured_profile)
        compared = bool(rl_available and normalized_legal_actions)
        rl_differs_from_gto = bool(normalized_rl and normalized_rl != gto_action)

        eligibility_reasons: list[str] = []
        if not rl_available:
            eligibility_reasons.append("rl_unavailable")
        if not self.enable_validated_rl:
            eligibility_reasons.append("validated_rl_disabled")
        if not structured_profile.get("rl_ready"):
            eligibility_reasons.append("profile_not_rl_ready")
        if structured_profile.get("reliability", 0.0) < 0.75:
            eligibility_reasons.append("profile_reliability_too_low")
        if structured_profile.get("exploit_confidence", 0.0) < 0.7:
            eligibility_reasons.append("exploit_confidence_too_low")
        if rl_eligible:
            eligibility_reasons.append("validated_rl_ready")

        comparison = self._build_rl_ab_comparison(
            legal_actions=legal_actions,
            gto_action=gto_action,
            rl_action_name=rl_action_name,
            structured_profile=structured_profile,
            alternatives=alternatives,
        )

        return {
            "available": rl_available,
            "validated_enabled": bool(self.enable_validated_rl),
            "compared": compared,
            "eligible": rl_eligible,
            "eligibility_reasons": eligibility_reasons,
            "applied": decision_source == "RL_VALIDATED",
            "gto_action": gto_action,
            "rl_action": normalized_rl,
            "final_action": final_action,
            "comparison": comparison,
            "rl_differs_from_gto": rl_differs_from_gto,
            "would_override": bool(rl_eligible and rl_differs_from_gto),
            "profile_snapshot": {
                "style": structured_profile.get("style", "Unknown"),
                "observed_hands": int(structured_profile.get("observed_hands", 0) or 0),
                "reliability": float(structured_profile.get("reliability", 0.0) or 0.0),
                "exploit_confidence": float(
                    structured_profile.get("exploit_confidence", 0.0) or 0.0
                ),
                "deviation_cap": float(structured_profile.get("deviation_cap", 0.0) or 0.0),
                "rl_ready": bool(structured_profile.get("rl_ready", False)),
            },
        }

    def _extract_solver_alternatives(
        self, gto_details: dict, legal_actions: list[str]
    ) -> list[dict]:
        alternatives: list[dict] = []
        for item in gto_details.get("actions", []) or []:
            if not isinstance(item, dict):
                continue

            normalized_action = self._normalize_solver_action(item.get("action"), legal_actions)
            alternative = {
                "action": normalized_action,
                "raw_action": item.get("action"),
            }

            freq = _safe_float(item.get("freq"))
            if freq is None:
                freq = _safe_float(item.get("frequency"))
            if freq is not None:
                alternative["freq"] = freq

            ev = _safe_float(item.get("ev"))
            if ev is None:
                ev = _safe_float(item.get("hero_ev"))
            if ev is not None:
                alternative["ev"] = ev

            if alternative not in alternatives:
                alternatives.append(alternative)
        return alternatives

    def _enrich_solver_alternatives(
        self,
        alternatives: list[dict],
        *,
        gto_details: dict,
        gto_action: str,
        final_action: str,
        rl_ab_metadata: dict,
    ) -> list[dict]:
        enriched = [dict(item) for item in alternatives if isinstance(item, dict)]
        seen_actions = {
            _normalize_action_name(item.get("action"))
            for item in enriched
            if _normalize_action_name(item.get("action"))
        }

        def append_candidate(
            action_name: str | None,
            *,
            raw_action: str | None = None,
            freq: Any = None,
            ev: Any = None,
            source: str | None = None,
        ) -> None:
            normalized_action = _normalize_action_name(action_name)
            if not normalized_action or normalized_action in seen_actions:
                return

            candidate = {
                "action": normalized_action,
                "raw_action": raw_action or normalized_action,
            }
            normalized_freq = _safe_float(freq)
            if normalized_freq is not None:
                candidate["freq"] = normalized_freq
            normalized_ev = _safe_float(ev)
            if normalized_ev is not None:
                candidate["ev"] = normalized_ev
            if source:
                candidate["source"] = source

            enriched.append(candidate)
            seen_actions.add(normalized_action)

        append_candidate(
            gto_action,
            raw_action=gto_details.get("chosen_action"),
            ev=gto_details.get("hero_ev"),
            source="gto_action",
        )
        append_candidate(final_action, source="final_action")

        comparison = rl_ab_metadata.get("comparison") if isinstance(rl_ab_metadata, dict) else {}
        if isinstance(comparison, dict):
            for branch_name in ("rl_off", "rl_on"):
                branch_snapshot = comparison.get(branch_name)
                if not isinstance(branch_snapshot, dict):
                    continue
                append_candidate(
                    branch_snapshot.get("action"),
                    freq=branch_snapshot.get("freq"),
                    ev=branch_snapshot.get("ev"),
                    source=branch_name,
                )

        return enriched

    def _find_alternative_for_action(
        self, alternatives: list[dict], action_name: str | None
    ) -> dict:
        normalized_action = _normalize_action_name(action_name)
        if not normalized_action:
            return {}

        for alternative in alternatives:
            if alternative.get("action") == normalized_action:
                return dict(alternative)
        return {}

    def _build_ab_branch_snapshot(
        self,
        branch_name: str,
        action_name: str,
        alternatives: list[dict],
    ) -> dict:
        alternative = self._find_alternative_for_action(alternatives, action_name)
        return {
            "branch": branch_name,
            "action": action_name,
            "freq": _safe_float(alternative.get("freq")),
            "ev": _safe_float(alternative.get("ev")),
            "present_in_solver": bool(alternative),
        }

    def _build_rl_ab_comparison(
        self,
        legal_actions: list[str],
        gto_action: str,
        rl_action_name: str | None,
        structured_profile: dict,
        alternatives: list[dict],
    ) -> dict:
        normalized_rl = (
            self._normalize_solver_action(rl_action_name, legal_actions) if rl_action_name else None
        )
        rl_eligible = self._should_allow_rl_override(structured_profile)
        rl_on_action = normalized_rl if rl_eligible and normalized_rl else gto_action
        rl_off_snapshot = self._build_ab_branch_snapshot("rl_off", gto_action, alternatives)
        rl_on_snapshot = self._build_ab_branch_snapshot("rl_on", rl_on_action, alternatives)

        freq_delta = None
        if rl_off_snapshot["freq"] is not None and rl_on_snapshot["freq"] is not None:
            freq_delta = round(rl_on_snapshot["freq"] - rl_off_snapshot["freq"], 4)

        ev_delta = None
        if rl_off_snapshot["ev"] is not None and rl_on_snapshot["ev"] is not None:
            ev_delta = round(rl_on_snapshot["ev"] - rl_off_snapshot["ev"], 4)

        return {
            "rl_off": rl_off_snapshot,
            "rl_on": rl_on_snapshot,
            "action_changed": rl_off_snapshot["action"] != rl_on_snapshot["action"],
            "freq_delta": freq_delta,
            "ev_delta": ev_delta,
        }

    def _build_profile_metadata(self, structured_profile: dict) -> dict:
        return {
            "style": structured_profile.get("style", "Unknown"),
            "hands_played": int(structured_profile.get("hands_played", 0) or 0),
            "observed_hands": int(structured_profile.get("observed_hands", 0) or 0),
            "reliability": float(structured_profile.get("reliability", 0.0) or 0.0),
            "vpip": float(structured_profile.get("vpip", 0.0) or 0.0),
            "pfr": float(structured_profile.get("pfr", 0.0) or 0.0),
            "gap": float(structured_profile.get("gap", 0.0) or 0.0),
            "aggression_frequency": float(
                structured_profile.get("aggression_frequency", 0.0) or 0.0
            ),
            "exploit_confidence": float(structured_profile.get("exploit_confidence", 0.0) or 0.0),
            "range_hint": structured_profile.get("range_hint", BASE_GTO_RANGE),
            "pressure_bias": float(structured_profile.get("pressure_bias", 0.0) or 0.0),
            "call_bias": float(structured_profile.get("call_bias", 0.0) or 0.0),
            "fold_bias": float(structured_profile.get("fold_bias", 0.0) or 0.0),
            "deviation_cap": float(structured_profile.get("deviation_cap", 0.0) or 0.0),
            "rl_ready": bool(structured_profile.get("rl_ready", False)),
        }

    def _build_exploit_metadata(
        self,
        *,
        decision_source: str,
        gto_action: str,
        final_action: str,
        structured_profile: dict,
    ) -> dict:
        source_slug = {
            "GTO_RUST": "gto_solver",
            "GTO_PREFLOP_FAST": "preflop_fast_path",
            "EXPLOIT_PROFILE": "profile_exploit",
            "EXPLOIT_EV": "ev_delta_exploit",
            "RL_VALIDATED": "validated_rl",
            "ICM_SURVIVAL": "icm_survival",
        }.get(decision_source, str(decision_source or "unknown").strip().lower() or "unknown")
        return {
            "decision_source": decision_source,
            "source_slug": source_slug,
            "applied": decision_source != "GTO_RUST",
            "gto_action": gto_action,
            "final_action": final_action,
            "exploit_confidence": float(structured_profile.get("exploit_confidence", 0.0) or 0.0),
            "deviation_cap": float(structured_profile.get("deviation_cap", 0.0) or 0.0),
            "pressure_bias": float(structured_profile.get("pressure_bias", 0.0) or 0.0),
            "call_bias": float(structured_profile.get("call_bias", 0.0) or 0.0),
            "fold_bias": float(structured_profile.get("fold_bias", 0.0) or 0.0),
        }

    def _build_solver_maps(self, alternatives: list[dict]) -> tuple[dict, dict, dict]:
        ev_by_action: dict[str, float] = {}
        freq_by_action: dict[str, float] = {}
        action_metadata: dict[str, dict] = {}

        for item in alternatives:
            if not isinstance(item, dict):
                continue

            action = _normalize_action_name(item.get("action"))
            if not action:
                continue

            raw_action = _safe_string(item.get("raw_action"))
            source = _safe_string(item.get("source"))
            ev = _safe_float(item.get("ev"))
            freq = _safe_float(item.get("freq"))

            if ev is not None and action not in ev_by_action:
                ev_by_action[action] = ev
            if freq is not None and action not in freq_by_action:
                freq_by_action[action] = freq

            compact_item: dict[str, Any] = {}
            if raw_action is not None:
                compact_item["raw_action"] = raw_action
            if ev is not None:
                compact_item["ev"] = ev
            if freq is not None:
                compact_item["freq"] = freq
            if source is not None:
                compact_item["source"] = source
            if compact_item and action not in action_metadata:
                action_metadata[action] = compact_item

        return ev_by_action, freq_by_action, action_metadata

    def _build_solver_metadata(
        self,
        *,
        gto_details: dict,
        alternatives: list[dict],
        gto_action: str,
        final_action: str,
    ) -> dict:
        solver_metadata = {
            "chosen_action_raw": gto_details.get("chosen_action"),
            "alternatives": alternatives,
            "alternatives_complete": alternatives,
            "has_alternatives": bool(alternatives),
            "action_count": len(alternatives),
            "cache_hit": bool(gto_details.get("cache_hit", False)),
            "elapsed_ms": gto_details.get("elapsed_ms", 0),
            "backend": gto_details.get("backend", self._solver_backend_name()),
            "gto_action": gto_action,
            "final_action": final_action,
            "circuit_breaker": self.solver_circuit_breaker_state(),
        }

        ev_by_action, freq_by_action, action_metadata = self._build_solver_maps(alternatives)
        if ev_by_action:
            solver_metadata["ev_by_action"] = ev_by_action
        if freq_by_action:
            solver_metadata["freq_by_action"] = freq_by_action
        if action_metadata:
            solver_metadata["action_metadata"] = action_metadata

        node_count = _safe_int(gto_details.get("node_count"))
        if node_count is not None:
            solver_metadata["node_count"] = node_count

        exploitability = _safe_float(gto_details.get("exploitability"))
        if exploitability is not None:
            solver_metadata["exploitability"] = exploitability

        for string_key in ("solver_id", "preset_id"):
            string_value = _safe_string(gto_details.get(string_key))
            if string_value is not None:
                solver_metadata[string_key] = string_value

        action_buckets = _compact_solver_list(gto_details.get("action_buckets"))
        if action_buckets:
            solver_metadata["action_buckets"] = action_buckets

        warning_details = _compact_solver_list(gto_details.get("warning_details"))
        if warning_details:
            solver_metadata["warning_details"] = warning_details

        warnings = []
        for item in gto_details.get("warnings", []) or []:
            text = _safe_string(item)
            if text and text not in warnings:
                warnings.append(text)
        if warnings:
            solver_metadata["warnings"] = warnings

        backend_details = {}
        backend_name = _safe_string(gto_details.get("backend")) or self._solver_backend_name()
        if backend_name:
            backend_details["name"] = backend_name
        backend_version = _safe_string(gto_details.get("backend_version"))
        if backend_version:
            backend_details["version"] = backend_version
        solve_mode = _safe_string(gto_details.get("solve_mode"))
        if solve_mode:
            backend_details["solve_mode"] = solve_mode
        if node_count is not None:
            backend_details["node_count"] = node_count
        if backend_details:
            solver_metadata["backend_details"] = backend_details

        cache_details = {}
        if "cache_hit" in gto_details:
            cache_details["hit"] = bool(gto_details.get("cache_hit"))
        cache_key = _safe_string(gto_details.get("cache_key"))
        if cache_key:
            cache_details["key"] = cache_key
        cache_tier = _safe_string(gto_details.get("cache_tier"))
        if cache_tier:
            cache_details["tier"] = cache_tier
        if cache_details:
            solver_metadata["cache_details"] = cache_details

        return solver_metadata

    def _normalize_runtime_actions(self, legal_actions: list[str]) -> list[str]:
        normalized: list[str] = []
        for action in legal_actions:
            raw = _normalize_action_name(action)
            if not raw:
                continue
            if raw.startswith("BET"):
                normalized.append("BET")
            elif raw.startswith("RAISE"):
                normalized.append("RAISE")
            elif raw.startswith("ALLIN") or raw.startswith("ALL_IN"):
                normalized.append("ALL_IN")
            else:
                normalized.append(raw)
        return list(dict.fromkeys(normalized))

    def _normalize_solver_action(self, action_name: str | None, legal_actions: list[str]) -> str:
        normalized = _normalize_action_name(action_name)
        normalized_legal_actions = self._normalize_runtime_actions(legal_actions)
        # allin_* ne doit JAMAIS être traduit en FOLD : toute variante d'all-in
        # est ramenée vers ALL_IN quand celle-ci est légale.
        if normalized and (
            normalized.startswith("ALLIN") or normalized.startswith("ALL_IN")
        ):
            if "ALL_IN" in normalized_legal_actions or "ALLIN" in normalized_legal_actions:
                return "ALL_IN"
        if normalized in normalized_legal_actions:
            return normalized
        if normalized and normalized.startswith("BET") and "BET" in normalized_legal_actions:
            return "BET"
        if normalized and normalized.startswith("RAISE") and "RAISE" in normalized_legal_actions:
            return "RAISE"
        if (
            normalized == "CHECK"
            and "CALL" in normalized_legal_actions
            and "CHECK" not in normalized_legal_actions
        ):
            return "CALL"
        if (
            normalized == "CALL"
            and "CHECK" in normalized_legal_actions
            and "CALL" not in normalized_legal_actions
        ):
            return "CHECK"
        if "FOLD" in normalized_legal_actions:
            return "FOLD"
        return normalized_legal_actions[0] if normalized_legal_actions else "CHECK"

    def _apply_node_locking(self, base_villain_range: str, profile: dict, board: list[str]) -> str:
        """
        NODE-LOCKING GTO PROFOND :
        Modifie mathématiquement la range de l'adversaire envoyée au Solveur Rust
        en fonction de son profil IA (K-Means) pour forcer la Maximal Exploitative Strategy (MES).
        """
        if not profile or profile.get("hands_played", 0) < 30:
            return base_villain_range  # Pas assez de données, on joue GTO pur.

        player_type = profile.get("player_type", "Balanced")

        range_items = list(_cached_range_items(base_villain_range))
        locked_range = []

        if player_type == "Nit" or player_type == "TightPassive":
            for hand in range_items:
                if "s" in hand and hand[0] not in "AKQJ":
                    continue
                if hand in ["22+", "33+", "44+"]:
                    locked_range.append("77+")
                else:
                    locked_range.append(hand)

        elif player_type == "Whale" or player_type == "LoosePassive":
            locked_range = range_items.copy()
            locked_range.extend(["K2s+", "Q5s+", "J7s+", "T7s+", "A2o+", "K7o+", "Q9o+"])

        elif player_type == "Maniac" or player_type == "LooseAggressive":
            locked_range = range_items.copy()
            locked_range.extend(["75s+", "64s+", "53s+", "K5o+", "Q8o+"])

        else:
            locked_range = range_items

        final_range = ", ".join(list(dict.fromkeys(locked_range)))
        return final_range if final_range else base_villain_range

    async def get_best_action(
        self,
        hero_hand: str,
        board: list[str],
        pot: float,
        effective_stack: float,
        villain_name: str,
        legal_actions: list[str],
        spot_id: str = "",
        hero_position: str = "ip",
        state_confidence: float = 0.0,
        action_history: list[dict[str, Any]] | None = None,
        tournament_data: dict[str, Any] | None = None,
        active_villain_count: int | None = None,
    ) -> dict:
        """
        Détermine la meilleure action à prendre en combinant GTO (Solver Rust),
        Reinforcement Learning (Agent RL), Node-Locking, et ICM.

        ``active_villain_count`` (>2) déclenche le mode multiway approché
        (Phase 3, garde-fous) : solve HU contre le villain principal avec range
        resserrée et budget d'itérations réduit, signalé dans les métadonnées.
        """
        logger.info(f"Calcul de décision contre {villain_name}. Board: {board}, Pot: {pot}")
        hero_hand = _normalize_hero_hand_string(hero_hand)
        legal_actions = self._normalize_runtime_actions(legal_actions)
        if not legal_actions:
            return self._fallback_action([])

        # CIRCUIT BREAKER CHECK
        if time.monotonic() < self._solver_cooldown_until:
            logger.error("🛑 CIRCUIT BREAKER ACTIF: Solver en cooldown. Auto-Fallback.")
            return self._fallback_action(legal_actions)

        is_preflop = len(board or []) == 0
        use_preflop_fast_path = bool(
            is_preflop
            and self.solver_backend is not None
            and (not self._solver_backend_explicit or _normalize_preflop_position(hero_position))
            and not self.enable_validated_rl
        )

        # 1. Profilage & Node-Locking GTO
        profile = await self._get_cached_profile(
            villain_name,
            allow_fetch=not use_preflop_fast_path,
        )
        structured_profile = self._build_structured_profile(profile)
        villain_position = self._infer_villain_position(villain_name, hero_position, action_history)

        # Obtenir la range théorique via le PreflopManager
        base_villain_range = self.preflop_manager.get_villain_range(villain_position)

        # Phase 2.9 — resserrement bayésien de la range villain par action observée
        range_updater = BayesianRangeUpdater()
        villain_range_observed = range_updater.update(
            base_villain_range,
            action_history,
            street=max(len(board or []) - 3, 0),
            board_texture=_analyze_board_texture(board or []),
        )
        if villain_range_observed:
            base_villain_range = villain_range_observed

        # Phase 3 — garde-fous multiway : le moteur ne supporte que HU. En 3+ way,
        # on résout en HU contre le villain principal avec une range encore plus
        # resserrée (les autres joueurs exercent une pression supplémentaire) et un
        # budget d'itérations réduit ; l'approximation est tracée dans les métadonnées.
        multiway_players = int(active_villain_count or 2)
        multiway_approximation = multiway_players > 2
        if multiway_approximation:
            second_pass = BayesianRangeUpdater(min_weight=0.6)
            tightened = second_pass.update(
                base_villain_range,
                action_history,
                street=max(len(board or []) - 3, 0),
                board_texture=_analyze_board_texture(board or []),
            )
            base_villain_range = tightened or base_villain_range
            logger.warning(
                "Multiway (%d joueurs) non supporté par le moteur : approximation "
                "HU vs villain principal activée.",
                multiway_players,
            )

        # Appliquer le Node-Locking
        villain_range = self._apply_node_locking(base_villain_range, profile, board)

        # 2. Utilisation du Deep Reinforcement Learning pour dévier de la GTO
        rl_action_name = None
        preflop_fast_used = False
        if self.rl_agent and not use_preflop_fast_path:
            state_vector = self._state_to_vector(
                hero_hand, board, pot, effective_stack, profile or {}
            )

            valid_mask = np.zeros(self.rl_agent.action_dim)
            for action in legal_actions:
                if action in ACTION_MAP:
                    valid_mask[ACTION_MAP[action]] = 1

            rl_action_idx = self.rl_agent.select_action(
                state_vector, valid_mask, exploit_mode=False
            )

            if "CALL" in legal_actions and rl_action_idx == 1:
                rl_action_name = "CALL"
            else:
                rl_action_name = REVERSE_ACTION_MAP.get(rl_action_idx, None)

            if rl_action_name and rl_action_name in legal_actions:
                logger.info(f"L'Agent RL recommande une action exploitative : {rl_action_name}")

        # 3. Appel au solver Rust ultra-rapide (CFR+)
        gto_action = "FOLD"
        gto_details = {}
        fallback_used = False
        fallback_reason = None
        if use_preflop_fast_path:
            facing_raise_preflop = (
                "CALL" in legal_actions and "CHECK" not in legal_actions
            ) or self._has_aggressive_preflop_history(action_history)
            gto_action, gto_details = self._run_preflop_dual_mode(
                hero_hand=hero_hand,
                legal_actions=legal_actions,
                hero_position=hero_position,
                action_history=action_history,
                effective_stack=effective_stack,
                pot=pot,
                facing_raise=facing_raise_preflop,
                aggressive_action=self._preferred_aggressive_action(legal_actions),
            )
            preflop_fast_used = True
            logger.info("Réponse préflop (%s) : %s", self.preflop_mode, gto_action)
        elif self.solver_provider:
            try:
                if logger.isEnabledFor(logging.DEBUG):
                    try:
                        from src.runtime.debug import set_debug_context as _set_dbg_ctx_dm

                        _set_dbg_ctx_dm(spot_id=str(spot_id))
                    except Exception:
                        pass
                    logger.debug(
                        "decision_maker: solve start spot_id=%s board=%s pot=%.1f stack=%.1f hero=%s pos=%s legal=%s",
                        spot_id,
                        board,
                        float(pot or 0.0),
                        float(effective_stack or 0.0),
                        hero_hand,
                        hero_position,
                        legal_actions,
                    )
                try:
                    from src.runtime.debug import to_thread_with_context as _to_thread_ctx_dm
                except ImportError:
                    _to_thread_ctx_dm = None  # type: ignore[assignment]
                _solver_call = _to_thread_ctx_dm or asyncio.to_thread  # type: ignore[assignment]
                response = await asyncio.wait_for(
                    _solver_call(
                        self._call_solver_backend,
                        hero_hand=hero_hand,
                        villain_range=villain_range,
                        board=board,
                        pot=pot,
                        effective_stack=effective_stack,
                        legal_actions=legal_actions,
                        spot_id=spot_id,
                        hero_position=hero_position,
                        state_confidence=state_confidence,
                        action_history=action_history,
                        time_budget_ms=self._multiway_time_budget(multiway_players),
                    ),
                    timeout=10.0,
                )
                fallback_used = bool(response.get("fallback_used", False))
                fallback_reason = str(response.get("fallback_reason") or "") or None
                gto_action = self._normalize_solver_action(
                    response.get("chosen_action", "FOLD"), legal_actions
                )
                if multiway_approximation:
                    warnings = list(response.get("warnings") or [])
                    if "multiway_approximation" not in warnings:
                        warnings.append("multiway_approximation")
                    response["warnings"] = warnings
                    response["multiway"] = {
                        "approximation": True,
                        "players": multiway_players,
                    }
                gto_details = response
                logger.info(
                    "Réponse GTO Rust reçue en %sms : %s", response.get("elapsed_ms"), gto_action
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "decision_maker: solve done spot_id=%s action=%s elapsed_ms=%s fallback=%s warnings=%s",
                        spot_id,
                        gto_action,
                        response.get("elapsed_ms"),
                        fallback_used,
                        response.get("warnings"),
                    )
            except TimeoutError:
                logger.error("Solver Rust timeout (>10s). Fail-safe to FOLD/CHECK.")
                self._register_solver_timeout()
                fallback_used = True
                fallback_reason = "solver_timeout"
                gto_action = "CHECK" if "CHECK" in legal_actions else "FOLD"
            except Exception as e:
                logger.error(f"Erreur lors de l'appel au Solver Rust: {e}")
                fallback_used = True
                fallback_reason = str(e)
        else:
            fallback_used = True
            fallback_reason = "rust_solver_unavailable"

        # Résilience: si la requête réussit, on reset le circuit breaker
        if not fallback_used:
            self._consecutive_solver_timeouts = 0

        # 4. Orchestration exploitative bornée (EV-delta, Phase 2.10)
        alternatives = self._extract_solver_alternatives(gto_details, legal_actions)
        ev_by_action, _, _ = self._build_solver_maps(alternatives)
        final_action, decision_source = self._select_exploit_action(
            legal_actions,
            gto_action,
            rl_action_name,
            structured_profile,
            ev_by_action=ev_by_action or None,
        )
        if decision_source != "GTO_RUST":
            logger.info(
                "Déviation bornée appliquée. source=%s style=%s confidence=%.3f cap=%.3f",
                decision_source,
                structured_profile.get("style"),
                structured_profile.get("exploit_confidence", 0.0),
                structured_profile.get("deviation_cap", 0.0),
            )
        elif preflop_fast_used:
            decision_source = "GTO_PREFLOP_FAST"

        final_action = self._normalize_solver_action(final_action, legal_actions)

        # 4.5 Assistance LLM (Optionnelle et asynchrone)
        llm_advice = None
        if (
            self.enable_llm_assist
            and self.solver_backend
            and hasattr(self.solver_backend, "llm_assist_stub")
        ):
            try:
                # On utilise l'API LLM embarquée dans le bridge Rust pour demander une explication de la décision
                prompt_context = f"Hero: {hero_hand}, Board: {board}, Pot: {pot}. L'adversaire est classé '{structured_profile.get('style')}'. Le solver GTO propose {gto_action}, mais le bot d'exploitation a choisi {final_action}. Peux-tu expliquer pourquoi en une phrase ?"

                def _llm_call():
                    try:
                        llm_res = self.solver_backend.llm_assist_stub(
                            task="decision_rationale",
                            prompt=prompt_context,
                            enabled=True,
                            provider_mode="openai_compatible_remote",
                            spot_summary=f"Decision: {final_action} vs GTO: {gto_action}",
                        )
                        if isinstance(llm_res, dict):
                            advice = llm_res.get("summary")
                            logger.info(f"🤖 Conseil LLM : {advice}")
                    except Exception as e:
                        logger.error(f"Erreur trace appel LLM de fond: {e}")

                try:
                    from src.runtime.debug import to_thread_with_context as _to_thread_ctx_llm
                except ImportError:
                    _to_thread_ctx_llm = None  # type: ignore[assignment]
                _llm_thread = _to_thread_ctx_llm or asyncio.to_thread  # type: ignore[assignment]
                asyncio.create_task(_llm_thread(_llm_call))
            except Exception as e:
                logger.error(f"Erreur lors de l'appel LLM: {e}")

        # 5. Application de l'ICM (Tournois uniquement)
        if tournament_data:
            hero_stack = tournament_data.get("hero_stack", effective_stack)
            villain_stack = tournament_data.get("villain_stack", effective_stack)
            all_stacks = tournament_data.get("all_stacks", [])
            payouts = tournament_data.get("payouts", [])

            if all_stacks and payouts:
                icm_action = self.icm_calculator.adjust_gto_for_tournament(
                    gto_action=final_action,
                    hero_stack=hero_stack,
                    villain_stack=villain_stack,
                    all_stacks=all_stacks,
                    payouts=payouts,
                    pot_size=pot,
                )
                if icm_action != final_action:
                    decision_source = "ICM_SURVIVAL"
                    final_action = icm_action
                    logger.info(f"Action finale modifiée par l'ICM : {final_action}")

        # Geometric Sizing + SPR Optimization
        bet_size = gto_details.get("dynamic_amount")
        if bet_size is None:
            bet_size = _bet_size_from_action(
                gto_details.get("chosen_action", final_action), pot, effective_stack, board
            )

        if final_action not in {"BET", "RAISE", "ALL_IN"}:
            bet_size = None

        rl_ab_metadata = self._build_rl_ab_metadata(
            legal_actions=legal_actions,
            gto_action=gto_action,
            rl_action_name=rl_action_name,
            structured_profile=structured_profile,
            final_action=final_action,
            decision_source=decision_source,
            alternatives=alternatives,
        )
        if gto_details or alternatives:
            alternatives = self._enrich_solver_alternatives(
                alternatives,
                gto_details=gto_details,
                gto_action=gto_action,
                final_action=final_action,
                rl_ab_metadata=rl_ab_metadata,
            )

        decision_confidence = float(gto_details.get("decision_confidence", 0.0) or 0.0)
        if decision_confidence <= 0.0:
            decision_confidence = round(
                _clamp(
                    (state_confidence * 0.55) + (structured_profile.get("reliability", 0.0) * 0.45),
                    0.0,
                    1.0,
                ),
                3,
            )

        confidence_source = (
            "solver" if gto_details.get("decision_confidence") is not None else "derived"
        )
        confidence_gap = None
        if rl_ab_metadata:
            profile_exploit_confidence = _safe_float(
                rl_ab_metadata.get("profile_snapshot", {}).get("exploit_confidence")
            )
            if profile_exploit_confidence is not None:
                confidence_gap = round(decision_confidence - profile_exploit_confidence, 3)

        solver_metadata = self._build_solver_metadata(
            gto_details=gto_details,
            alternatives=alternatives,
            gto_action=gto_action,
            final_action=final_action,
        )

        confidence_metadata = {
            "value": decision_confidence,
            "source": confidence_source,
            "state_confidence": float(state_confidence or 0.0),
            "profile_reliability": float(structured_profile.get("reliability", 0.0) or 0.0),
        }
        if confidence_gap is not None:
            confidence_metadata["vs_profile_exploit_gap"] = confidence_gap

        metadata = {
            "profile": self._build_profile_metadata(structured_profile),
            "solver": solver_metadata,
            "confidence": confidence_metadata,
            "exploit": self._build_exploit_metadata(
                decision_source=decision_source,
                gto_action=gto_action,
                final_action=final_action,
                structured_profile=structured_profile,
            ),
            "preflop": {
                "fast_path": preflop_fast_used,
                "hero_position": _normalize_preflop_position(hero_position)
                or str(hero_position or "").strip().upper(),
                "villain_position": villain_position,
                "hero_combo": _hero_combo_notation(hero_hand),
            },
        }
        if rl_ab_metadata:
            metadata["rl_ab"] = rl_ab_metadata

        incidents: list[dict] = []
        if fallback_used:
            incidents.append(
                {
                    "id": "solver_fallback",
                    "severity": "warning",
                    "kind": "fallback",
                    "label": fallback_reason or "fallback_used",
                }
            )
        if state_confidence < 0.6:
            incidents.append(
                {
                    "id": "low_state_confidence",
                    "severity": "warning",
                    "kind": "runtime",
                    "label": f"state_confidence={state_confidence:.2f}",
                }
            )

        warnings: list[str] = []
        if fallback_used:
            warnings.append("fallback_used")
        if state_confidence < 0.6:
            warnings.append("ocr_low_confidence")

        return {
            "action": final_action,
            "bet_size": bet_size,
            "ev": gto_details.get("hero_ev", 0.0),
            "exploitability": gto_details.get("exploitability", 0.0),
            "details": gto_details.get("actions", []),
            "source": decision_source,
            "profile": structured_profile,
            "confidence": decision_confidence,
            "cache_hit": bool(gto_details.get("cache_hit", False)),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "warnings": warnings,
            "incidents": incidents,
            "backend": gto_details.get("backend", self._solver_backend_name()),
            "elapsed_ms": gto_details.get("elapsed_ms", 0),
            "metadata": metadata,
            "ab_decision": rl_ab_metadata or None,
            "llm_advice": llm_advice,
        }

    def _register_solver_timeout(self) -> None:
        """Phase 2.6 — backoff exponentiel : 60s, 120s, 240s, cap 300s."""
        self._consecutive_solver_timeouts += 1
        if self._consecutive_solver_timeouts < _SOLVER_BREAKER_THRESHOLD:
            return
        exponent = self._consecutive_solver_timeouts - _SOLVER_BREAKER_THRESHOLD
        cooldown_s = min(
            _SOLVER_BREAKER_BASE_COOLDOWN_S * (2**exponent),
            _SOLVER_BREAKER_MAX_COOLDOWN_S,
        )
        self._solver_cooldown_until = time.monotonic() + cooldown_s
        logger.critical(
            "CIRCUIT BREAKER DECLENCHE : %d timeouts consecutifs. Cooldown %.0fs.",
            self._consecutive_solver_timeouts,
            cooldown_s,
        )

    def solver_circuit_breaker_state(self) -> dict:
        now = time.monotonic()
        active = now < self._solver_cooldown_until
        return {
            "active": active,
            "consecutive_timeouts": self._consecutive_solver_timeouts,
            "cooldown_remaining_s": round(self._solver_cooldown_until - now, 3) if active else 0.0,
            "threshold": _SOLVER_BREAKER_THRESHOLD,
        }

    def _fallback_action(self, legal_actions: list[str]) -> dict:
        logger.warning("Utilisation de l'action de Fallback (FOLD).")
        normalized_legal_actions = self._normalize_runtime_actions(legal_actions)
        action = (
            "FOLD"
            if "FOLD" in normalized_legal_actions
            else normalized_legal_actions[0]
            if normalized_legal_actions
            else "CHECK"
        )
        return {
            "action": action,
            "bet_size": None,
            "ev": 0.0,
            "exploitability": 1.0,
            "details": [],
            "source": "FALLBACK",
            "confidence": 0.0,
            "cache_hit": False,
            "fallback_used": True,
            "fallback_reason": "solver_unavailable",
            "warnings": ["fallback_used"],
            "incidents": [
                {
                    "id": "solver_fallback",
                    "severity": "warning",
                    "kind": "fallback",
                    "label": "solver_unavailable",
                }
            ],
            "backend": "fallback",
            "elapsed_ms": 0,
            "metadata": {
                "confidence": {
                    "value": 0.0,
                    "source": "fallback",
                    "state_confidence": 0.0,
                    "profile_reliability": 0.0,
                },
                "profile": self._build_profile_metadata(self._build_structured_profile(None)),
                "solver": {
                    "chosen_action_raw": None,
                    "alternatives": [],
                    "alternatives_complete": [],
                    "has_alternatives": False,
                    "action_count": 0,
                    "cache_hit": False,
                    "elapsed_ms": 0,
                    "backend": "fallback",
                    "gto_action": action,
                    "final_action": action,
                    "circuit_breaker": self.solver_circuit_breaker_state(),
                },
            },
            "ab_decision": None,
        }
