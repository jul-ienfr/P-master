import logging
from typing import List, Dict, Optional, Any
import numpy as np

from .icm_calculator import ICMCalculator
from .preflop_ranges import PreflopManager

_DEFAULT_DEPENDENCY = object()

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
    logging.warning("Le module Rust 'postflop_solver_py' n'est pas disponible. Mode simulation activé.")

logger = logging.getLogger(__name__)

# Mapping des actions possibles
ACTION_MAP = {"FOLD": 0, "CHECK": 1, "CALL": 1, "BET": 2, "RAISE": 2, "BET_50": 2, "BET_75": 3, "ALL_IN": 4}
REVERSE_ACTION_MAP = {0: "FOLD", 1: "CHECK", 2: "BET", 3: "BET_75", 4: "ALL_IN"}
BASE_GTO_RANGE = "55+, A2s+, K5s+, Q8s+, J8s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo"

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
    "Nit": "99+, AJs+, AKo"
}

def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

def _rate_from_profile(profile: dict, raw_key: str, derived_key: str) -> float:
    derived = profile.get("derived_profile") or {}
    if derived_key in derived:
        return float(derived.get(derived_key, 0.0) or 0.0)
    sample_hands = max(
        int(derived.get("observed_hands", 0) or profile.get("observed_hands", 0) or profile.get("hands_played", 0) or 0),
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

def _normalize_action_name(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    return str(action).strip().upper()

def _analyze_board_texture(board: List[str]) -> str:
    """Analyse la texture des cartes communes (board) pour ajuster le bet sizing."""
    if not board or len(board) < 3:
        return "DRY" # Préflop

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
    gaps = sum(board_ranks[i+1] - board_ranks[i] for i in range(len(board_ranks)-1))
    
    if gaps <= 3 or max_suit_count == 2:
        return "WET"
        
    return "DRY"

def _bet_size_from_action(action_name: Optional[str], pot: float, effective_stack: float, board: List[str] = None) -> Optional[float]:
    normalized = _normalize_action_name(action_name)
    if not normalized:
        return None
        
    if normalized == "ALL_IN":
        return round(max(effective_stack, 0.0), 2)
        
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

def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None

def _safe_string(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None

def _compact_solver_list(value: Any) -> Optional[list]:
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
        rl_agent: Any = _DEFAULT_DEPENDENCY,
        create_rl_agent: bool = True,
        enable_validated_rl: bool = False,
        autoload_rl_model: bool = True,
    ):
        self.db = db_manager
        self.icm_calculator = ICMCalculator()
        self.preflop_manager = PreflopManager()
        self.solver_backend = postflop_solver_py if solver_backend is _DEFAULT_DEPENDENCY and RUST_SOLVER_AVAILABLE else None if solver_backend is _DEFAULT_DEPENDENCY else solver_backend
        
        self.hero_base_range = BASE_GTO_RANGE
        
        if rl_agent is _DEFAULT_DEPENDENCY:
            self.rl_agent = RLAdapterAgent() if create_rl_agent and RL_AVAILABLE else None
        else:
            self.rl_agent = rl_agent
            
        self.create_rl_agent = create_rl_agent
        self.enable_validated_rl = enable_validated_rl
        self.autoload_rl_model = autoload_rl_model
        
        # Configuration de la Rake (Commission du Casino) - NL2 à NL10 = 5%
        self.rake_percentage = 0.05
        
        if self.rl_agent and rl_agent is _DEFAULT_DEPENDENCY and self.create_rl_agent and self.autoload_rl_model:
            self.rl_agent.load_model()

    def _solver_backend_name(self) -> str:
        if not self.solver_backend:
            return "fallback"
        if self.solver_backend is postflop_solver_py:
            return "native_solver"
        return getattr(self.solver_backend, "backend_name", self.solver_backend.__class__.__name__)

    def _call_solver_backend(
        self,
        hero_hand: str,
        villain_range: str,
        board: List[str],
        pot: float,
        effective_stack: float,
        legal_actions: List[str],
        spot_id: str,
        hero_position: str,
        state_confidence: float,
        action_history: Optional[List[Dict[str, Any]]],
    ) -> dict:
        if not self.solver_backend:
            raise RuntimeError("rust_solver_unavailable")
            
        # Ajustement du pot pour simuler la Rake (5%)
        net_pot = pot * (1.0 - self.rake_percentage) if pot > 0 else pot

        return self.solver_backend.solve_spot_v2(
            hero_range=hero_hand,
            villain_ranges=[villain_range],
            board=board,
            starting_pot=net_pot,
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
            time_budget_ms=1000,
        )

    def _state_to_vector(self, hero_hand: str, board: List[str], pot: float, effective_stack: float, profile: dict) -> np.ndarray:
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

    def _build_structured_profile(self, profile: Optional[dict]) -> dict:
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

    def _should_allow_rl_override(self, structured_profile: dict) -> bool:
        if not self.rl_agent or not self.enable_validated_rl:
            return False
        return bool(
            structured_profile.get("rl_ready")
            and structured_profile.get("reliability", 0.0) >= 0.75
            and structured_profile.get("exploit_confidence", 0.0) >= 0.7
        )

    def _select_exploit_action(
        self,
        legal_actions: List[str],
        gto_action: str,
        rl_action_name: Optional[str],
        structured_profile: dict,
    ) -> tuple[str, str]:
        normalized_legal_actions = {_normalize_action_name(action): action for action in legal_actions}
        normalized_gto = _normalize_action_name(gto_action)
        normalized_rl = _normalize_action_name(rl_action_name)
        deviation_cap = float(structured_profile.get("deviation_cap", 0.0) or 0.0)

        if self._should_allow_rl_override(structured_profile):
            if normalized_rl and normalized_rl in normalized_legal_actions and normalized_rl != normalized_gto:
                return normalized_legal_actions[normalized_rl], "RL_VALIDATED"

        if deviation_cap < 0.08:
            return gto_action, "GTO_RUST"

        if structured_profile.get("pressure_bias", 0.0) >= 0.1:
            for candidate in ("RAISE_POT", "RAISE_HALF", "BET"):
                if candidate in normalized_legal_actions and candidate != normalized_gto:
                    return normalized_legal_actions[candidate], "EXPLOIT_PROFILE"

        if structured_profile.get("fold_bias", 0.0) >= 0.12:
            for candidate in ("CHECK", "CALL", "FOLD"):
                if candidate in normalized_legal_actions and candidate != normalized_gto:
                    return normalized_legal_actions[candidate], "EXPLOIT_PROFILE"

        if structured_profile.get("call_bias", 0.0) >= 0.12 and "CALL" in normalized_legal_actions and normalized_gto == "FOLD":
            return normalized_legal_actions["CALL"], "EXPLOIT_PROFILE"
        
        return gto_action, "GTO_RUST"

    def _build_rl_ab_metadata(
        self,
        legal_actions: List[str],
        gto_action: str,
        rl_action_name: Optional[str],
        structured_profile: dict,
        final_action: str,
        decision_source: str,
        alternatives: List[dict],
    ) -> dict:
        normalized_legal_actions = self._normalize_runtime_actions(legal_actions)
        rl_available = bool(self.rl_agent)
        if not rl_available:
            return {}

        normalized_rl = self._normalize_solver_action(rl_action_name, legal_actions) if rl_action_name else None
        rl_eligible = self._should_allow_rl_override(structured_profile)
        compared = bool(rl_available and normalized_legal_actions)
        rl_differs_from_gto = bool(normalized_rl and normalized_rl != gto_action)

        eligibility_reasons: List[str] = []
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
                "exploit_confidence": float(structured_profile.get("exploit_confidence", 0.0) or 0.0),
                "deviation_cap": float(structured_profile.get("deviation_cap", 0.0) or 0.0),
                "rl_ready": bool(structured_profile.get("rl_ready", False)),
            },
        }

    def _extract_solver_alternatives(self, gto_details: dict, legal_actions: List[str]) -> List[dict]:
        alternatives: List[dict] = []
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
        alternatives: List[dict],
        *,
        gto_details: dict,
        gto_action: str,
        final_action: str,
        rl_ab_metadata: dict,
    ) -> List[dict]:
        enriched = [dict(item) for item in alternatives if isinstance(item, dict)]
        seen_actions = {
            _normalize_action_name(item.get("action"))
            for item in enriched
            if _normalize_action_name(item.get("action"))
        }

        def append_candidate(
            action_name: Optional[str],
            *,
            raw_action: Optional[str] = None,
            freq: Any = None,
            ev: Any = None,
            source: Optional[str] = None,
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

    def _find_alternative_for_action(self, alternatives: List[dict], action_name: Optional[str]) -> dict:
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
        alternatives: List[dict],
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
        legal_actions: List[str],
        gto_action: str,
        rl_action_name: Optional[str],
        structured_profile: dict,
        alternatives: List[dict],
    ) -> dict:
        normalized_rl = self._normalize_solver_action(rl_action_name, legal_actions) if rl_action_name else None
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
            "aggression_frequency": float(structured_profile.get("aggression_frequency", 0.0) or 0.0),
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
            "EXPLOIT_PROFILE": "profile_exploit",
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

    def _build_solver_maps(self, alternatives: List[dict]) -> tuple[dict, dict, dict]:
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
        alternatives: List[dict],
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

    def _normalize_runtime_actions(self, legal_actions: List[str]) -> List[str]:
        normalized: List[str] = []
        for action in legal_actions:
            raw = _normalize_action_name(action)
            if not raw:
                continue
            if raw.startswith("BET"):
                normalized.append("BET")
            elif raw.startswith("RAISE"):
                normalized.append("RAISE")
            else:
                normalized.append(raw)
        return list(dict.fromkeys(normalized))

    def _normalize_solver_action(self, action_name: Optional[str], legal_actions: List[str]) -> str:
        normalized = _normalize_action_name(action_name)
        normalized_legal_actions = self._normalize_runtime_actions(legal_actions)
        if normalized in normalized_legal_actions:
            return normalized
        if normalized and normalized.startswith("BET") and "BET" in normalized_legal_actions:
            return "BET"
        if normalized and normalized.startswith("RAISE") and "RAISE" in normalized_legal_actions:
            return "RAISE"
        if normalized == "CHECK" and "CALL" in normalized_legal_actions and "CHECK" not in normalized_legal_actions:
            return "CALL"
        if normalized == "CALL" and "CHECK" in normalized_legal_actions and "CALL" not in normalized_legal_actions:
            return "CHECK"
        if "FOLD" in normalized_legal_actions:
            return "FOLD"
        return normalized_legal_actions[0] if normalized_legal_actions else "CHECK"

    def _apply_node_locking(self, base_villain_range: str, profile: dict, board: List[str]) -> str:
        """
        NODE-LOCKING GTO PROFOND : 
        Modifie mathématiquement la range de l'adversaire envoyée au Solveur Rust
        en fonction de son profil IA (K-Means) pour forcer la Maximal Exploitative Strategy (MES).
        """
        if not profile or profile.get("hands_played", 0) < 30:
            return base_villain_range # Pas assez de données, on joue GTO pur.
            
        player_type = profile.get("player_type", "Balanced")
        
        range_items = [item.strip() for item in base_villain_range.split(",")]
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

    async def get_best_action(self, hero_hand: str, board: List[str], pot: float, 
                              effective_stack: float, villain_name: str, 
                              legal_actions: List[str], spot_id: str = "",
                              hero_position: str = "ip", state_confidence: float = 0.0,
                              action_history: Optional[List[Dict[str, Any]]] = None,
                              tournament_data: Optional[Dict[str, Any]] = None) -> dict:
        """
        Détermine la meilleure action à prendre en combinant GTO (Solver Rust), 
        Reinforcement Learning (Agent RL), Node-Locking, et ICM.
        """
        logger.info(f"Calcul de décision contre {villain_name}. Board: {board}, Pot: {pot}")
        legal_actions = self._normalize_runtime_actions(legal_actions)
        if not legal_actions:
            return self._fallback_action([])
        
        # 1. Profilage & Node-Locking GTO
        profile = None
        if self.db and getattr(self.db, "is_available", bool(getattr(self.db, "pool", None))):
            profile = await self.db.get_player_profile(villain_name)
        structured_profile = self._build_structured_profile(profile)
        
        # Obtenir la range théorique via le PreflopManager
        base_villain_range = self.preflop_manager.get_villain_range("UTG")
        
        # Appliquer le Node-Locking
        villain_range = self._apply_node_locking(base_villain_range, profile, board)
        
        # 2. Utilisation du Deep Reinforcement Learning pour dévier de la GTO
        rl_action_name = None
        if self.rl_agent:
            state_vector = self._state_to_vector(hero_hand, board, pot, effective_stack, profile or {})
            
            valid_mask = np.zeros(self.rl_agent.action_dim)
            for action in legal_actions:
                if action in ACTION_MAP:
                    valid_mask[ACTION_MAP[action]] = 1
                    
            rl_action_idx = self.rl_agent.select_action(state_vector, valid_mask, exploit_mode=False)
            
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
        if self.solver_backend:
            try:
                response = self._call_solver_backend(
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
                )
                gto_action = self._normalize_solver_action(response.get("chosen_action", "FOLD"), legal_actions)
                gto_details = response
                logger.info(f"Réponse GTO Rust reçue en {response.get('elapsed_ms')}ms : {gto_action}")
            except Exception as e:
                logger.error(f"Erreur lors de l'appel au Solver Rust: {e}")
                fallback_used = True
                fallback_reason = str(e)
        else:
            fallback_used = True
            fallback_reason = "rust_solver_unavailable"
                
        # 4. Orchestration exploitative bornée
        final_action, decision_source = self._select_exploit_action(
            legal_actions,
            gto_action,
            rl_action_name,
            structured_profile,
        )
        if decision_source != "GTO_RUST":
            logger.info(
                "Déviation bornée appliquée. source=%s style=%s confidence=%.3f cap=%.3f",
                decision_source,
                structured_profile.get("style"),
                structured_profile.get("exploit_confidence", 0.0),
                structured_profile.get("deviation_cap", 0.0),
            )

        final_action = self._normalize_solver_action(final_action, legal_actions)

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
                    pot_size=pot
                )
                if icm_action != final_action:
                    decision_source = "ICM_SURVIVAL"
                    final_action = icm_action
                    logger.info(f"Action finale modifiée par l'ICM : {final_action}")

        # Geometric Sizing + SPR Optimization
        bet_size = _bet_size_from_action(gto_details.get("chosen_action", final_action), pot, effective_stack, board)
        
        if final_action not in {"BET", "RAISE", "ALL_IN"}:
            bet_size = None
            
        alternatives = self._extract_solver_alternatives(gto_details, legal_actions)
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
                _clamp((state_confidence * 0.55) + (structured_profile.get("reliability", 0.0) * 0.45), 0.0, 1.0),
                3,
            )

        confidence_source = "solver" if gto_details.get("decision_confidence") is not None else "derived"
        confidence_gap = None
        if rl_ab_metadata:
            profile_exploit_confidence = _safe_float(rl_ab_metadata.get("profile_snapshot", {}).get("exploit_confidence"))
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
        }
        if rl_ab_metadata:
            metadata["rl_ab"] = rl_ab_metadata

        incidents: List[dict] = []
        if fallback_used:
            incidents.append({
                "id": "solver_fallback",
                "severity": "warning",
                "kind": "fallback",
                "label": fallback_reason or "fallback_used",
            })
        if state_confidence < 0.6:
            incidents.append({
                "id": "low_state_confidence",
                "severity": "warning",
                "kind": "runtime",
                "label": f"state_confidence={state_confidence:.2f}",
            })

        warnings: List[str] = []
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
        }

    def _fallback_action(self, legal_actions: List[str]) -> dict:
        logger.warning("Utilisation de l'action de Fallback (FOLD).")
        normalized_legal_actions = self._normalize_runtime_actions(legal_actions)
        action = "FOLD" if "FOLD" in normalized_legal_actions else normalized_legal_actions[0] if normalized_legal_actions else "CHECK"
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
            "incidents": [{"id": "solver_fallback", "severity": "warning", "kind": "fallback", "label": "solver_unavailable"}],
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
                },
            },
            "ab_decision": None,
        }
