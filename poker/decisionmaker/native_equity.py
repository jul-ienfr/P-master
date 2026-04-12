"""Native equity adapter with HTTP and Python fallbacks."""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
from collections import Counter

try:
    import requests
except ImportError:  # pragma: no cover - optional at runtime
    requests = None

from poker.decisionmaker.equity_backends import (
    build_equity_plan,
    normalize_equity_response,
)
from poker.decisionmaker.gto_runtime import ensure_local_gto_server
from poker.decisionmaker.oracle_backends import rank_with_phevaluator
from poker.tools.helper import get_dir

logger = logging.getLogger(__name__)

GTO_SERVER_URL = "http://127.0.0.1:8765"
GTO_TIMEOUT_SEC = 5

NATIVE_GTO_MODULE_CANDIDATES = (
    "poker.gto_binding",
    "poker.postflop_solver",
    "poker.native_gto",
    "gto_binding",
    "postflop_solver",
    "postflop_solver_py",
)

_PREFLOP_RANGE_CACHE: dict[bool, list[tuple[str, float]]] = {}
RANK_ORDER = "23456789TJQKA"


class NativeEquityResult:
    """Compatibility object for the legacy UI update path."""

    def __init__(self):
        self.equity = 0.0
        self.winnerCardTypeList = Counter()
        self.winTypesDict = self.winnerCardTypeList.items()
        self.runs = 0
        self.passes = 0
        self.opponent_range = ""
        self.collusion_cards = ""


def run_native_equity_wrapper(p, ui_action_and_signals, config, ui, t, L, preflop_state, h):
    """Populate the legacy table fields through the native Rust equity APIs."""
    result = NativeEquityResult()

    if len(getattr(t, "mycards", []) or []) < 2:
        raise RuntimeError("missing hero cards for native equity")

    board = normalize_cards(getattr(t, "cardsOnTable", []) or [])
    hero_hand = normalize_cards(getattr(t, "mycards", []) or [])
    dead_cards = []

    t.assumedPlayers = derive_assumed_players(p, t)
    villain_ranges, display_range = derive_villain_ranges(p, t, preflop_state, h)
    result.opponent_range = display_range

    collusion_cards = ""
    if p.selected_strategy.get("collusion") == 1:
        collusion_cards, collusion_player_dropped_out = L.get_collusion_cards(
            h.game_number_on_screen, t.gameStage
        )
        if collusion_cards:
            normalized_collusion = normalize_cards(collusion_cards)
            collusion_cards = normalized_collusion
            result.collusion_cards = normalized_collusion
            if collusion_player_dropped_out:
                dead_cards.extend(normalized_collusion)
            else:
                villain_ranges.insert(0, "".join(normalized_collusion))

    max_runs = stage_max_samples(t.gameStage)
    ui_action_and_signals.signal_status.emit(f"Running native equity: {max_runs}")
    preferred_mode = str(p.selected_strategy.get("equity_backend_mode", "auto"))
    oracle_ready = (
        board_len_is_closed(board)
        and villain_ranges_are_exact(villain_ranges)
        and importlib.util.find_spec("phevaluator") is not None
    )
    plan = build_equity_plan(
        board,
        villain_ranges,
        preferred_mode=preferred_mode,
        time_budget_ms=max_runs,
        allow_oracle=oracle_ready,
    )
    backend = plan.backend
    mode = plan.mode

    equity_payload = {
        "hero_hand": hero_hand,
        "villain_ranges": villain_ranges,
        "board": board,
        "dead_cards": dead_cards,
        "mode": mode,
        "max_samples": max_runs,
        "use_cache": True,
    }
    if backend.value == "oracle_backend":
        equity_response = call_phevaluator_showdown_oracle(hero_hand, villain_ranges, board)
    else:
        equity_response = call_native_api("evaluate_equity", "/equity", equity_payload)
    equity_response = normalize_equity_response(
        equity_response,
        backend=backend,
        mode=mode,
        reason=plan.reason,
    )

    t.abs_equity = round(float(equity_response["equity"]), 2)
    t.winnerCardTypeList = normalize_winner_types(equity_response.get("winner_types", {}))
    t.range_equity = t.abs_equity
    t.relative_equity = t.abs_equity
    t.equity_backend = equity_response.get("backend", backend.value)
    t.equity_cache_tier = equity_response.get("cache_tier", "none")

    hero_range = ""
    if t.gameStage != "PreFlop" and p.selected_strategy.get("use_relative_equity"):
        hero_range = range_set_to_string(getattr(preflop_state, "preflop_bot_ranges", None))
        if hero_range:
            strength_payload = {
                "hero_hand": hero_hand,
                "hero_range": hero_range,
                "villain_ranges": villain_ranges,
                "board": board,
                "dead_cards": dead_cards,
                "mode": mode,
                "max_samples": max_runs,
                "use_cache": True,
            }
            strength_response = call_native_api(
                "range_relative_strength", "/range-strength", strength_payload
            )
            t.range_equity = round(float(strength_response["range_average_equity"]), 2)
            t.relative_equity = round(float(strength_response["relative_strength"]), 2)
        else:
            logger.warning(
                "Native range strength skipped: no hero preflop range available, falling back to abs equity"
            )

    result.equity = t.abs_equity
    result.runs = int(equity_response.get("samples", 0))
    result.winTypesDict = t.winnerCardTypeList.items()

    ui_action_and_signals.signal_status.emit("Native equity completed")
    return result


def board_len_is_closed(board):
    return len(board) >= 5


def _split_exact_range_tokens(range_string):
    return [token.strip() for token in str(range_string or "").split(",") if token.strip()]


def _is_exact_combo(token):
    compact = str(token or "").replace(" ", "")
    return (
        len(compact) == 4
        and compact[0].upper() in RANK_ORDER
        and compact[2].upper() in RANK_ORDER
        and compact[1].lower() in "shdc"
        and compact[3].lower() in "shdc"
    )


def villain_ranges_are_exact(villain_ranges):
    tokens = []
    for range_string in villain_ranges:
        next_tokens = _split_exact_range_tokens(range_string)
        if not next_tokens:
            return False
        if not all(_is_exact_combo(token) for token in next_tokens):
            return False
        tokens.extend(next_tokens)
    return bool(tokens)


def call_phevaluator_showdown_oracle(hero_hand, villain_ranges, board):
    hero_rank = int(rank_with_phevaluator([*hero_hand, *board])["rank"])
    wins = 0.0
    ties = 0.0
    total = 0

    for range_string in villain_ranges:
        for token in _split_exact_range_tokens(range_string):
            if not _is_exact_combo(token):
                continue
            villain_hand = [normalize_card(token[:2]), normalize_card(token[2:4])]
            villain_rank = int(rank_with_phevaluator([*villain_hand, *board])["rank"])
            total += 1
            if hero_rank < villain_rank:
                wins += 1.0
            elif hero_rank == villain_rank:
                ties += 1.0

    if total <= 0:
        raise RuntimeError("oracle backend requires exact villain combos at showdown")

    equity = (wins + 0.5 * ties) / float(total)
    return {
        "equity": round(equity, 4),
        "samples": total,
        "cache_hit": False,
        "winner_types": {"showdown_oracle": round(equity, 4)},
    }


def derive_assumed_players(p, t):
    """Mirror the existing assumed player logic with the same bounds."""
    if t.gameStage == "PreFlop":
        assumed_players = 2
    elif t.gameStage == "Flop":
        if t.isHeadsUp:
            opponent_range = normalize_range_percent(
                p.selected_strategy[f"range_utg{active_villain_utg(t)}"]
            )
        else:
            opponent_range = normalize_range_percent(
                p.selected_strategy["range_multiple_players"]
            )
        assumed_players = t.other_active_players - int(round(t.playersAhead * (1 - opponent_range))) + 1
    else:
        assumed_players = t.other_active_players + 1

    max_assumed_players = max(2, t.total_players - 1)
    assumed_players = min(max(int(assumed_players), 2), max_assumed_players)
    return assumed_players


def derive_villain_ranges(p, t, preflop_state, h):
    """Prefer tracked ranges; fall back to broad percentage-based ranges."""
    tracked_ranges = []

    if t.gameStage != "PreFlop":
        try:
            for abs_pos in range(t.total_players - 1):
                if t.other_players[abs_pos]["status"] == 1:
                    sheet_name = preflop_state.get_reverse_sheetname(abs_pos, t, h)
                    hands = preflop_state.get_rangecards_from_sheetname(abs_pos, sheet_name, t, h, p)
                    range_string = range_set_to_string(hands)
                    if range_string:
                        tracked_ranges.append(range_string)
        except Exception as exc:  # pragma: no cover - runtime fallback path
            logger.warning("Tracked villain ranges unavailable: %s", exc)

    if tracked_ranges:
        display = tracked_ranges[0] if len(tracked_ranges) == 1 else f"{len(tracked_ranges)} tracked ranges"
        return tracked_ranges, display

    if t.gameStage == "PreFlop":
        percent = normalize_range_percent(p.selected_strategy["range_preflop"])
        return [percent_to_range_string(percent)], percent

    if t.isHeadsUp:
        percent = normalize_range_percent(p.selected_strategy[f"range_utg{active_villain_utg(t)}"])
        return [percent_to_range_string(percent)], percent

    percent = normalize_range_percent(p.selected_strategy["range_multiple_players"])
    villain_count = max(1, int(getattr(t, "assumedPlayers", 2)) - 1)
    return [percent_to_range_string(percent) for _ in range(villain_count)], percent


def active_villain_utg(t):
    for player in t.other_players:
        if player["status"] == 1:
            return player["utg_position"]
    return 0


def stage_max_samples(stage):
    if stage == "PreFlop":
        return 3000
    if stage == "Flop":
        return 5000
    if stage == "Turn":
        return 4000
    if stage == "River":
        return 3000
    raise NotImplementedError(f"unsupported game stage: {stage}")


def call_native_api(function_name, endpoint, payload):
    response = call_native_binding(function_name, payload)
    if response is not None:
        return response
    return call_native_http(endpoint, payload)


def call_native_binding(function_name, payload):
    for module_name in NATIVE_GTO_MODULE_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        except Exception as exc:  # pragma: no cover - runtime fallback path
            logger.debug("Native module import failed for %s: %s", module_name, exc)
            continue

        func = getattr(module, function_name, None)
        if not callable(func):
            continue

        try:
            result = func(**payload)
        except TypeError:
            result = func(payload)
        except Exception as exc:  # pragma: no cover - runtime fallback path
            logger.debug("Native call failed for %s.%s: %s", module_name, function_name, exc)
            continue

        if isinstance(result, dict):
            return result
        if hasattr(result, "items"):
            return dict(result)
        raise RuntimeError(f"unexpected native result from {module_name}.{function_name}: {type(result)!r}")

    return None


def call_native_http(endpoint, payload):
    if requests is None:
        raise RuntimeError("requests is not installed for HTTP fallback")

    ensure_local_gto_server()

    response = requests.post(
        f"{GTO_SERVER_URL}{endpoint}",
        json=payload,
        timeout=GTO_TIMEOUT_SEC,
    )
    response.raise_for_status()
    return response.json()


def normalize_cards(cards):
    return [normalize_card(card) for card in cards if card]


def normalize_card(card):
    card = str(card).strip()
    if not card:
        return ""
    if len(card) == 3 and card[:2] == "10":
        return f"T{card[2].lower()}"
    return f"{card[0].upper()}{card[1].lower()}"


def range_set_to_string(hands):
    if not hands:
        return ""

    tokens = []
    for hand in hands:
        token = normalize_range_token(hand)
        if token:
            tokens.append(token)

    return ",".join(sorted(set(tokens)))


def normalize_range_token(token):
    token = str(token).strip()
    if not token:
        return ""

    compact = token.replace(" ", "").upper()
    if len(compact) == 2:
        first, second = sort_ranks_desc(compact[0], compact[1])
        return f"{first}{second}"
    if len(compact) == 3 and compact[2] in ("S", "O"):
        first, second = sort_ranks_desc(compact[0], compact[1])
        return f"{first}{second}{compact[2].lower()}"
    if len(compact) == 4:
        first = (compact[0], compact[1].lower())
        second = (compact[2], compact[3].lower())
        ordered = sorted((first, second), key=lambda card: (rank_index(card[0]), card[1]), reverse=True)
        return "".join(f"{rank}{suit}" for rank, suit in ordered)
    return compact


def percent_to_range_string(percent, use_range_of_range=False):
    percent = normalize_range_percent(percent)
    ranked_hands = load_ranked_preflop_hands(use_range_of_range)
    take_top = max(1, int(len(ranked_hands) * percent))
    selected = [normalize_range_token(hand) for hand, _ in ranked_hands[-take_top:]]
    return ",".join(sorted(set(selected)))


def normalize_range_percent(percent):
    percent = float(percent)
    if percent > 1.0:
        percent /= 100.0
    return max(0.0, min(percent, 1.0))


def sort_ranks_desc(first, second):
    if rank_index(first) >= rank_index(second):
        return first, second
    return second, first


def rank_index(rank):
    return RANK_ORDER.index(rank)


def load_ranked_preflop_hands(use_range_of_range=False):
    cache_key = bool(use_range_of_range)
    if cache_key in _PREFLOP_RANGE_CACHE:
        return _PREFLOP_RANGE_CACHE[cache_key]

    suffix = "-50" if use_range_of_range else ""
    with open(
        os.path.join(get_dir("codebase"), f"decisionmaker/preflop_equity{suffix}.json"),
        encoding="utf-8",
    ) as handle:
        equities = json.load(handle)

    ranked = sorted(equities.items(), key=lambda item: item[1])
    _PREFLOP_RANGE_CACHE[cache_key] = ranked
    return ranked


def normalize_winner_types(winner_types):
    if isinstance(winner_types, dict):
        return Counter({str(key): float(value) for key, value in winner_types.items()})

    counter = Counter()
    for item in winner_types:
        if isinstance(item, dict):
            counter[str(item["name"])] = float(item["frequency"])
    return counter
