"""Board-aware villain range tracking with calibration-ready exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Optional

from poker.decisionmaker.v2_contracts import RangeModelVersion

logger = logging.getLogger(__name__)


class PreflopAction(Enum):
    OPEN_RAISE = "open_raise"
    THREE_BET = "three_bet"
    FOUR_BET = "four_bet"
    CALL_OPEN = "call_open"
    CALL_3BET = "call_3bet"
    LIMP = "limp"


class PostflopAction(Enum):
    CHECK = "check"
    BET = "bet"
    RAISE = "raise"
    CALL = "call"
    FOLD = "fold"


PREFLOP_RANGES: dict[tuple[int, PreflopAction], str] = {
    (0, PreflopAction.OPEN_RAISE): "AA,KK,QQ,JJ,TT,99,88,AKs,AQs,AJs,ATs,KQs,AKo,AQo",
    (0, PreflopAction.CALL_OPEN): "77,66,55,44,33,22,AJo,KQo,KJs,QJs,JTs",
    (0, PreflopAction.THREE_BET): "AA,KK,QQ,AKs,AKo",
    (1, PreflopAction.OPEN_RAISE): "AA,KK,QQ,JJ,TT,99,88,77,AKs,AQs,AJs,ATs,A9s,KQs,KJs,QJs,AKo,AQo,AJo,KQo",
    (1, PreflopAction.CALL_OPEN): "66,55,44,33,22,JTs,T9s,98s,87s,76s",
    (1, PreflopAction.THREE_BET): "AA,KK,QQ,JJ,AKs,AKo,AQs",
    (2, PreflopAction.OPEN_RAISE): "AA,KK,QQ,JJ,TT,99,88,77,66,AKs,AQs,AJs,ATs,A9s,A8s,KQs,KJs,KTs,QJs,QTs,JTs,T9s,AKo,AQo,AJo,ATo,KQo,KJo",
    (2, PreflopAction.CALL_OPEN): "55,44,33,22,98s,87s,76s,65s",
    (2, PreflopAction.THREE_BET): "AA,KK,QQ,JJ,AKs,AQs,AKo,AQo",
    (3, PreflopAction.OPEN_RAISE): "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22,AKs,AQs,AJs,ATs,A9s,A8s,A7s,A6s,A5s,A4s,A3s,A2s,KQs,KJs,KTs,K9s,QJs,QTs,Q9s,JTs,J9s,T9s,T8s,98s,97s,87s,76s,65s,AKo,AQo,AJo,ATo,A9o,KQo,KJo,KTo,QJo",
    (3, PreflopAction.CALL_OPEN): "55,44,33,22,A5s-A2s,K8s-K6s,Q8s,J8s,T7s,96s,86s,75s,64s,54s",
    (3, PreflopAction.THREE_BET): "AA,KK,QQ,JJ,TT,AKs,AQs,AJs,AKo,AQo,A5s,A4s",
    (4, PreflopAction.OPEN_RAISE): "AA,KK,QQ,JJ,TT,99,88,77,66,55,44,33,22,AKs,AQs,AJs,ATs,A9s,A8s,A7s,A6s,A5s,A4s,A3s,A2s,KQs,KJs,KTs,K9s,K8s,QJs,QTs,Q9s,JTs,J9s,J8s,T9s,T8s,98s,97s,87s,86s,76s,75s,65s,64s,54s,AKo,AQo,AJo,ATo,A9o,A8o,KQo,KJo,KTo,QJo,QTo,JTo",
    (4, PreflopAction.CALL_OPEN): "77,66,55,44,33,22,AJo,KQo",
    (4, PreflopAction.THREE_BET): "AA,KK,QQ,JJ,AKs,AKo,A5s,A4s,A3s",
    (5, PreflopAction.CALL_OPEN): "22+,A2s+,K2s+,Q5s+,J7s+,T7s+,97s+,87s,76s,65s,A2o+,K9o+,Q9o+,J9o+",
    (5, PreflopAction.THREE_BET): "AA,KK,QQ,JJ,TT,AKs,AQs,AJs,AKo,AQo,A5s,A4s,76s",
}

DEFAULT_RANGE = "22+,A2s+,K9s+,Q9s+,J9s+,T9s,A2o+,K9o+,Q9o+"
RANK_ORDER = "23456789TJQKA"


def _split_range_tokens(range_string: str) -> list[str]:
    return [token.strip() for token in str(range_string).split(",") if token.strip()]


def _expand_token(token: str) -> list[str]:
    token = token.strip()
    if not token:
        return []
    if "-" not in token:
        return [token]
    left, right = token.split("-", 1)
    if len(left) != len(right):
        return [left, right]
    if len(left) == 3 and left[2] == right[2]:
        start = RANK_ORDER.index(right[0])
        end = RANK_ORDER.index(left[0])
        second = left[1]
        suffix = left[2]
        return [f"{RANK_ORDER[index]}{second}{suffix}" for index in range(start, end + 1)]
    if len(left) == 2 and left[0] == right[0]:
        start = RANK_ORDER.index(right[1])
        end = RANK_ORDER.index(left[1])
        first = left[0]
        return [f"{first}{RANK_ORDER[index]}" for index in range(start, end + 1)]
    return [left, right]


def _token_rank(token: str) -> tuple[int, int, int]:
    compact = token.replace("+", "")
    if len(compact) < 2:
        return (-1, -1, 0)
    first = RANK_ORDER.index(compact[0])
    second = RANK_ORDER.index(compact[1])
    suited = 1 if len(compact) == 3 and compact[2].lower() == "s" else 0
    return (first, second, suited)


def _token_features(token: str) -> dict[str, bool]:
    compact = token.replace("+", "")
    first = compact[0] if len(compact) >= 1 else ""
    second = compact[1] if len(compact) >= 2 else ""
    suited = len(compact) == 3 and compact[2].lower() == "s"
    pair = len(compact) >= 2 and first == second
    broadway = first in "TJQKA" and second in "TJQKA"
    connector = len(compact) >= 2 and abs(RANK_ORDER.index(first) - RANK_ORDER.index(second)) == 1
    wheel_ace = first == "A" and second in "2345"
    return {
        "pair": pair,
        "suited": suited,
        "broadway": broadway,
        "connector": connector,
        "wheel_ace": wheel_ace,
        "premium": pair and first in "AKQJT" or compact.startswith("AK") or compact.startswith("AQ"),
    }


def _board_texture(board: list[str]) -> dict[str, bool | int]:
    ranks = [card[0].upper() for card in board if card]
    suits = [card[1].lower() for card in board if len(card) >= 2]
    paired = len(set(ranks)) < len(ranks)
    monotone = len(set(suits)) == 1 if suits else False
    two_tone = len(set(suits)) == 2 if suits else False
    high_card_count = sum(1 for rank in ranks if rank in "TJQKA")
    connected = any(
        abs(RANK_ORDER.index(ranks[index]) - RANK_ORDER.index(ranks[index + 1])) <= 2
        for index in range(len(ranks) - 1)
    ) if len(ranks) >= 2 else False
    return {
        "paired": paired,
        "monotone": monotone,
        "two_tone": two_tone,
        "high_card_count": high_card_count,
        "connected": connected,
    }


def _calibration_multiplier(
    token: str,
    action: PostflopAction,
    street: str,
    calibration_profile: dict[str, float] | None,
) -> float:
    if not calibration_profile:
        return 1.0
    features = _token_features(token)
    feature_keys = [
        f"{street.lower()}:{action.value}",
        f"{street.lower()}:{action.value}:pair" if features["pair"] else "",
        f"{street.lower()}:{action.value}:suited" if features["suited"] else "",
        f"{street.lower()}:{action.value}:broadway" if features["broadway"] else "",
    ]
    multiplier = 1.0
    for feature_key in feature_keys:
        if feature_key and feature_key in calibration_profile:
            multiplier *= float(calibration_profile[feature_key])
    return max(0.75, min(multiplier, 1.3))


def _action_multiplier(
    token: str,
    action: PostflopAction,
    street: str,
    board: list[str],
    calibration_profile: dict[str, float] | None = None,
) -> float:
    features = _token_features(token)
    texture = _board_texture(board)
    multiplier = 1.0

    if action == PostflopAction.CHECK:
        multiplier *= 1.06 if features["connector"] or features["wheel_ace"] else 0.96
        multiplier *= 1.03 if texture["paired"] and features["pair"] else 1.0
    elif action == PostflopAction.CALL:
        multiplier *= 1.15 if features["pair"] or features["broadway"] else 0.88
        multiplier *= 1.08 if texture["two_tone"] and features["suited"] else 1.0
    elif action == PostflopAction.BET:
        multiplier *= 1.24 if features["premium"] else 0.82
        multiplier *= 1.12 if texture["monotone"] and features["suited"] else 1.0
    elif action == PostflopAction.RAISE:
        multiplier *= 1.34 if features["premium"] or features["pair"] else 0.72
        multiplier *= 1.08 if texture["high_card_count"] >= 2 and features["broadway"] else 1.0
    elif action == PostflopAction.FOLD:
        multiplier = 0.0

    if street == "Turn":
        multiplier *= 1.06 if features["pair"] else 0.96
    elif street == "River":
        multiplier *= 1.08 if features["premium"] or features["pair"] else 0.9

    multiplier *= _calibration_multiplier(token, action, street, calibration_profile)
    return max(0.0, min(multiplier, 1.75))


@dataclass
class VillainRange:
    """Track a single villain range through a staged model."""

    position_utg: int = 0
    is_hero: bool = False
    model_version: RangeModelVersion = RangeModelVersion.CALIBRATED_V3
    current_range: str = field(default=DEFAULT_RANGE)
    weighted_tokens: dict[str, float] = field(default_factory=dict)
    preflop_action: Optional[PreflopAction] = None
    postflop_actions: list[PostflopAction] = field(default_factory=list)
    action_history: list[str] = field(default_factory=list)
    last_update_fingerprint: str = ""
    calibration_profile: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not self.weighted_tokens:
            self._seed_weights(self.current_range)

    def _seed_weights(self, range_string: str) -> None:
        expanded_tokens: list[str] = []
        for token in _split_range_tokens(range_string or DEFAULT_RANGE):
            expanded_tokens.extend(_expand_token(token))
        ordered = sorted(set(expanded_tokens), key=_token_rank, reverse=True)
        self.weighted_tokens = {token: 1.0 for token in ordered}
        self.current_range = ",".join(ordered) if ordered else DEFAULT_RANGE

    def update_preflop(self, action: PreflopAction) -> None:
        self.preflop_action = action
        self.action_history.append(f"preflop:{action.value}")
        self._seed_weights(PREFLOP_RANGES.get((self.position_utg, action), DEFAULT_RANGE))

    def update_postflop(self, action: PostflopAction, board: list[str], street: str) -> None:
        self.postflop_actions.append(action)
        self.action_history.append(f"{street.lower()}:{action.value}")
        updated: dict[str, float] = {}
        for token, weight in self.weighted_tokens.items():
            adjusted = round(
                weight
                * _action_multiplier(
                    token,
                    action,
                    street,
                    board,
                    calibration_profile=self.calibration_profile,
                ),
                3,
            )
            if adjusted >= 0.08:
                updated[token] = adjusted
        self.weighted_tokens = updated

    def get_range_string(self) -> str:
        if not self.weighted_tokens:
            return "22:0.01"
        parts: list[str] = []
        for token, weight in sorted(
            self.weighted_tokens.items(),
            key=lambda item: (item[1], *_token_rank(item[0])),
            reverse=True,
        ):
            if weight >= 0.98:
                parts.append(token)
            else:
                parts.append(f"{token}:{weight:.2f}")
        return ",".join(parts)

    def calibration_row(self, board: list[str], street: str) -> dict[str, object]:
        return {
            "position_utg": self.position_utg,
            "model_version": self.model_version.value,
            "preflop_action": self.preflop_action.value if self.preflop_action else "",
            "postflop_actions": [action.value for action in self.postflop_actions],
            "board": list(board),
            "street": street,
            "range_size": len(self.weighted_tokens),
            "top_tokens": list(sorted(self.weighted_tokens, key=self.weighted_tokens.get, reverse=True)[:8]),
        }

    def reset(self) -> None:
        self.current_range = DEFAULT_RANGE
        self.weighted_tokens = {}
        self.preflop_action = None
        self.postflop_actions = []
        self.action_history = []
        self.last_update_fingerprint = ""
        self._seed_weights(DEFAULT_RANGE)


class RangeTrackerManager:
    """Manage villains through priors, board-aware updates, and calibration output."""

    def __init__(self):
        self.trackers: dict[int, VillainRange] = {}
        self._last_game_id: Optional[str] = None
        self.calibration_profile: dict[str, float] = {}

    def set_calibration_profile(self, profile: dict[str, float] | None) -> None:
        self.calibration_profile = dict(profile or {})
        for tracker in self.trackers.values():
            tracker.calibration_profile = dict(self.calibration_profile)

    def update_from_table(self, t) -> None:
        game_id = str(getattr(t, "GameID", "") or getattr(t, "game_id", "") or "")
        if game_id and game_id != self._last_game_id:
            self._reset_all()
            self._last_game_id = game_id

        board = [str(card) for card in getattr(t, "cardsOnTable", []) if card]
        street = str(getattr(t, "gameStage", "PreFlop") or "PreFlop")
        pot = float(getattr(t, "totalPotValue", 0.0) or 0.0)
        min_call = float(getattr(t, "minCall", 0.0) or 0.0)
        min_bet = float(getattr(t, "minBet", 0.0) or 0.0)

        for index, player in enumerate(getattr(t, "other_players", []) or []):
            tracker = self.trackers.get(index)
            if tracker is None:
                hero_pos = int(getattr(t, "position_utg_plus", 0) or 0)
                villain_pos = (hero_pos + index + 1) % max(getattr(t, "total_players", 6), 2)
                tracker = VillainRange(
                    position_utg=villain_pos,
                    calibration_profile=dict(self.calibration_profile),
                )
                self.trackers[index] = tracker

            if tracker.preflop_action is None:
                tracker.update_preflop(self._infer_preflop_action(t, index))

            fingerprint = ":".join(
                [
                    self._last_game_id or "unknown",
                    street,
                    ",".join(board),
                    str(player.get("status", "")),
                    f"{pot:.2f}",
                    f"{min_call:.2f}",
                    f"{min_bet:.2f}",
                ]
            )
            if tracker.last_update_fingerprint == fingerprint:
                continue

            if street != "PreFlop":
                tracker.update_postflop(
                    self._infer_postflop_action(t, player, street),
                    board,
                    street,
                )
            tracker.last_update_fingerprint = fingerprint

    def get_primary_villain_range(self) -> str:
        active_ranges = [
            tracker
            for tracker in self.trackers.values()
            if tracker.get_range_string() not in ("", "22:0.01")
        ]
        if not active_ranges:
            return DEFAULT_RANGE
        ranked = sorted(active_ranges, key=lambda item: len(item.weighted_tokens))
        return ranked[0].get_range_string()

    def get_primary_villain_state(self) -> VillainRange | None:
        if not self.trackers:
            return None
        ranked = sorted(self.trackers.values(), key=lambda item: len(item.weighted_tokens))
        return ranked[0] if ranked else None

    def build_calibration_rows(self, t) -> list[dict[str, object]]:
        board = [str(card) for card in getattr(t, "cardsOnTable", []) if card]
        street = str(getattr(t, "gameStage", "PreFlop") or "PreFlop")
        return [tracker.calibration_row(board, street) for tracker in self.trackers.values()]

    def _infer_preflop_action(self, t, villain_idx: int) -> PreflopAction:
        player = (getattr(t, "other_players", []) or [{}])[villain_idx]
        if int(player.get("status", 1)) == 0:
            return PreflopAction.CALL_OPEN

        first_raiser = getattr(t, "first_raiser_utg", None)
        first_caller = getattr(t, "first_caller_utg", None)
        second_raiser = getattr(t, "second_raiser_utg", None)
        utg_position = player.get("utg_position", villain_idx)

        if utg_position == second_raiser:
            return PreflopAction.FOUR_BET
        if utg_position == first_raiser:
            return PreflopAction.OPEN_RAISE
        if utg_position == first_caller:
            return PreflopAction.CALL_OPEN
        if float(getattr(t, "minCall", 0.0) or 0.0) == 0.0:
            return PreflopAction.LIMP
        return PreflopAction.CALL_OPEN

    def _infer_postflop_action(self, t, player: dict, street: str) -> PostflopAction:
        if int(player.get("status", 1)) == 0:
            return PostflopAction.FOLD

        min_call = float(getattr(t, "minCall", 0.0) or 0.0)
        min_bet = float(getattr(t, "minBet", 0.0) or 0.0)
        has_initiative = bool(getattr(t, "other_player_has_initiative", False))

        if min_call <= 0:
            return PostflopAction.CHECK
        if has_initiative and min_bet >= max(min_call * 2.0, 1.0):
            return PostflopAction.RAISE if street in {"Turn", "River"} else PostflopAction.BET
        return PostflopAction.CALL

    def _reset_all(self) -> None:
        for tracker in self.trackers.values():
            tracker.reset()
        self.trackers = {}
