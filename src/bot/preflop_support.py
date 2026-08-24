"""Support preflop — Phase 2.7 (extraction de src/bot/decision_maker.py)

Utilitaires purs : normalisation main/position, notation combo,
appartenance à une range, fast-path preflop. Aucun changement
comportemental — les tests existants font office de garde-fou.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

BASE_GTO_RANGE = "55+, A2s+, K5s+, Q8s+, J8s+, T8s+, 98s, 87s, 76s, ATo+, KJo+, QJo"
CARD_RANK_ORDER: Dict[str, int] = {rank: index for index, rank in enumerate("23456789TJQKA")}
PREFLOP_POSITION_ORDER = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
PREFLOP_FAST_3BET_RANGE = "TT+, AQs+, AKo"


def normalize_action_name(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    return str(action).strip().upper()


def normalize_hero_hand_string(hero_hand: str) -> str:
    raw_value = str(hero_hand or "").strip()
    compact = raw_value.replace(" ", "")
    if len(compact) != 4:
        return raw_value

    cards = [compact[:2], compact[2:4]]
    if any(len(card) != 2 for card in cards):
        return raw_value

    normalized_cards: List[str] = []
    for card in cards:
        rank = card[0].upper()
        suit = card[1].lower()
        if rank not in CARD_RANK_ORDER or suit not in {"s", "h", "d", "c"}:
            return raw_value
        normalized_cards.append(f"{rank}{suit}")

    normalized_cards.sort(
        key=lambda card: (CARD_RANK_ORDER[card[0]], card[1]),
        reverse=True,
    )
    return "".join(normalized_cards)


def normalize_preflop_position(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in PREFLOP_POSITION_ORDER else None


def hero_combo_notation(hero_hand: str) -> str:
    normalized_hand = normalize_hero_hand_string(hero_hand)
    if len(normalized_hand) != 4:
        return ""

    card_one = normalized_hand[:2]
    card_two = normalized_hand[2:4]
    if len(card_one) != 2 or len(card_two) != 2:
        return ""

    rank_one, suit_one = card_one[0], card_one[1]
    rank_two, suit_two = card_two[0], card_two[1]
    if rank_one == rank_two:
        return f"{rank_one}{rank_two}"

    suited_flag = "s" if suit_one == suit_two else "o"
    return f"{rank_one}{rank_two}{suited_flag}"


@lru_cache(maxsize=256)
def cached_range_items(range_text: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(range_text or "").split(",") if item and item.strip())


def combo_matches_range_token(combo: str, token: str) -> bool:
    combo = str(combo or "").strip()
    token = str(token or "").strip()
    if not combo or not token:
        return False

    if len(combo) == 2:
        if len(token) < 2 or token[0] != token[1]:
            return False
        threshold_rank = token[0]
        if threshold_rank not in CARD_RANK_ORDER or combo[0] not in CARD_RANK_ORDER:
            return False
        if token.endswith("+"):
            return CARD_RANK_ORDER[combo[0]] >= CARD_RANK_ORDER[threshold_rank]
        return combo == token[:2]

    if len(combo) != 3:
        return False

    suited_flag = combo[2].lower()
    raw_token = token.rstrip("+")
    if len(raw_token) != 3:
        return False

    token_high, token_low, token_suited_flag = raw_token[0], raw_token[1], raw_token[2].lower()
    if (
        token_high not in CARD_RANK_ORDER
        or token_low not in CARD_RANK_ORDER
        or combo[0] not in CARD_RANK_ORDER
        or combo[1] not in CARD_RANK_ORDER
    ):
        return False
    if combo[2].lower() != token_suited_flag:
        return False

    if token.endswith("+"):
        return (
            combo[0] == token_high
            and CARD_RANK_ORDER[combo[1]] >= CARD_RANK_ORDER[token_low]
            and CARD_RANK_ORDER[combo[1]] < CARD_RANK_ORDER[combo[0]]
        )

    return combo == raw_token


@lru_cache(maxsize=512)
def combo_in_range(combo: str, range_text: str) -> bool:
    if not combo or not range_text:
        return False
    return any(combo_matches_range_token(combo, token) for token in cached_range_items(range_text))


def run_preflop_fast_path(
    *,
    hero_hand: str,
    legal_actions: List[str],
    hero_position: str,
    effective_stack: float,
    pot: float,
    preflop_manager: Any,
    facing_raise: bool,
    aggressive_action: Optional[str],
) -> tuple[str, dict]:
    """Décision preflop instantanée (ranges chartées), sans solve."""
    normalized_hero_position = normalize_preflop_position(hero_position) or "BTN"
    hero_combo = hero_combo_notation(hero_hand)
    hero_range = preflop_manager.get_hero_range(normalized_hero_position, facing_raise=facing_raise)
    in_range = combo_in_range(hero_combo, hero_range)

    chosen_action = "CHECK" if "CHECK" in legal_actions else "FOLD"
    dynamic_amount = None

    if in_range:
        if facing_raise:
            if aggressive_action and combo_in_range(hero_combo, PREFLOP_FAST_3BET_RANGE):
                chosen_action = aggressive_action
                dynamic_amount = pot * 3.2 if normalized_hero_position in ["SB", "BB"] else pot * 2.8
            elif "CALL" in legal_actions:
                chosen_action = "CALL"
            elif "CHECK" in legal_actions:
                chosen_action = "CHECK"
            elif "FOLD" in legal_actions:
                chosen_action = "FOLD"
        else:
            if aggressive_action:
                chosen_action = aggressive_action
                if effective_stack > pot * 50:
                    dynamic_amount = pot * 1.5
                elif effective_stack < pot * 15 and effective_stack > 0:
                    dynamic_amount = effective_stack
                else:
                    dynamic_amount = pot * 1.8
            elif "CHECK" in legal_actions:
                chosen_action = "CHECK"
            elif "CALL" in legal_actions:
                chosen_action = "CALL"
    else:
        if "CHECK" in legal_actions:
            chosen_action = "CHECK"
        elif facing_raise and "FOLD" in legal_actions:
            chosen_action = "FOLD"
        elif legal_actions:
            chosen_action = legal_actions[0]

    confidence = 0.94 if in_range else 0.78
    response = {
        "chosen_action": chosen_action,
        "hero_ev": 0.0,
        "exploitability": 0.0,
        "decision_confidence": confidence,
        "dynamic_amount": dynamic_amount,
        "actions": [{"action": chosen_action, "freq": 1.0, "source": "preflop_fast_path"}],
        "elapsed_ms": 0,
        "backend": "preflop_fast_path",
        "cache_hit": True,
        "solve_mode": "preflop_fast_path",
        "backend_details": {
            "name": "preflop_fast_path",
            "hero_position": normalized_hero_position,
            "facing_raise": facing_raise,
            "hero_combo": hero_combo,
        },
    }
    return chosen_action, response
