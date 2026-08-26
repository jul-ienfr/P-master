"""Simulateur Monte-Carlo multi-politiques pour l'évaluation scientifique (Phase 5.16).

Fait jouer des politiques HU no-limit hold'em (100bb) l'une contre l'autre via pokerkit,
sur un pool d'opposants synthétiques (nit / TAG / LAG / station / whale), et produit un
winrate bb/100 avec intervalle de confiance 95%.

Usage :
    python -m research.monte_carlo_sim --hands 10000 --seed 42
    python -m research.monte_carlo_sim --hands 500 --opponents nit whale
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokerkit import Automation, Mode, NoLimitTexasHoldem, StandardHighHand  # noqa: E402

BIG_BLIND = 2.0
STARTING_STACK_BB = 100.0

AUTOMATION = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
    Automation.CARD_BURNING,
    Automation.BOARD_DEALING,
)

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)

ActionFn = Callable[["View"], tuple[str, float | None]]


def new_state(rng: Random) -> tuple[NoLimitTexasHoldem, list[str]]:
    """Crée un état HU 100bb et distribue deux mains depuis le rng fourni."""
    deck = list(DECK)
    rng.shuffle(deck)
    cards = iter(deck)
    hole_hero = next(cards) + next(cards)
    hole_villain = next(cards) + next(cards)
    stack = STARTING_STACK_BB * BIG_BLIND
    state = NoLimitTexasHoldem.create_state(
        AUTOMATION,
        False,
        {},
        (BIG_BLIND / 2, BIG_BLIND),
        BIG_BLIND,
        (stack, stack),
        2,
        mode=Mode.CASH_GAME,
    )
    state.deal_hole(hole_hero)
    state.deal_hole(hole_villain)
    return state, [hole_hero, hole_villain]


def monte_carlo_equity(
    hole_cards: str,
    board: Sequence[str],
    *,
    samples: int = 120,
    rng: Random | None = None,
) -> float:
    """Équité de la main héro contre une main aléatoire par échantillonnage."""
    rng = rng or Random()
    known = {hole_cards[i : i + 2] for i in range(0, len(hole_cards), 2)}
    known.update(board)
    remaining = [card for card in DECK if card not in known]
    wins = ties = 0.0

    for _ in range(samples):
        pool = remaining[:]
        rng.shuffle(pool)
        villain_hole = pool[0] + pool[1]
        runout_needed = 5 - len(board)
        runout = "".join(pool[2 : 2 + runout_needed])
        hero_all = hole_cards + "".join(board) + runout
        villain_all = villain_hole + "".join(board) + runout
        try:
            hero_hand = StandardHighHand.from_game(hero_all)
            villain_hand = StandardHighHand.from_game(villain_all)
        except Exception:
            continue
        if hero_hand > villain_hand:
            wins += 1.0
        elif hero_hand == villain_hand:
            ties += 0.5

    return wins / samples if samples else 0.5


def chen_formula(hole_cards: str) -> float:
    """Score de Chen canonique (préflop) pour une main de deux cartes type 'AsKd'."""
    points = {"A": 10.0, "K": 8.0, "Q": 7.0, "J": 6.0}
    first, second = hole_cards[0], hole_cards[2]
    suited = hole_cards[1] == hole_cards[3]

    def card_points(rank: str) -> float:
        if rank in points:
            return points[rank]
        return RANKS.index(rank) / 2.0 + 0.5

    high_rank, low_rank = (
        (first, second) if card_points(first) >= card_points(second) else (second, first)
    )

    if first == second:
        return round(max(card_points(first) * 2.0, 5.0), 2)

    score = card_points(high_rank)
    gap = RANKS.index(high_rank) - RANKS.index(low_rank) - 1
    score -= {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}.get(gap, 5.0)
    if 0 < gap <= 1 and RANKS.index(low_rank) < RANKS.index("Q"):
        score += 1.0
    if suited:
        score += 2.0
    return round(max(score, -1.0), 2)


@dataclass
class View:
    """Vue d'un agent sur l'état courant."""

    street_index: int
    hole_cards: str
    board_cards: str
    pot_amount: float
    to_call: float
    effective_stack: float
    min_raise_to: float
    max_raise_to: float
    can_raise: bool
    is_button: bool


@dataclass(frozen=True)
class ArchetypeParams:
    """Paramètres d'un profil synthétique."""

    name: str
    vpip_chen: float = 8.0           # seuil Chen pour entrer dans le coup
    raise_chen: float = 12.0         # seuil Chen pour relancer préflop
    aggression: float = 0.35         # proba de miser quand équité correcte
    call_equity_margin: float = 0.0  # marge d'équité exigée pour payer
    fold_equity_threshold: float = 0.33  # abandonne en dessous de cette équité
    bluff_frequency: float = 0.05
    equity_samples: int = 80


ARCHETYPES: dict[str, ArchetypeParams] = {
    "nit": ArchetypeParams("nit", vpip_chen=11.0, raise_chen=13.0, aggression=0.25,
                           call_equity_margin=0.06, fold_equity_threshold=0.40),
    "tag": ArchetypeParams("tag", vpip_chen=9.0, raise_chen=12.0, aggression=0.40,
                           call_equity_margin=0.02, fold_equity_threshold=0.34),
    "lag": ArchetypeParams("lag", vpip_chen=6.0, raise_chen=10.0, aggression=0.55,
                           call_equity_margin=-0.02, fold_equity_threshold=0.28),
    "station": ArchetypeParams("station", vpip_chen=7.0, raise_chen=14.0, aggression=0.20,
                               call_equity_margin=-0.08, fold_equity_threshold=0.05),
    "whale": ArchetypeParams("whale", vpip_chen=4.0, raise_chen=15.0, aggression=0.30,
                             call_equity_margin=-0.15, fold_equity_threshold=0.0),
}


def make_archetype_policy(params: ArchetypeParams, seed: int) -> ActionFn:
    """Construit la fonction d'action d'un profil synthétique."""
    rng = Random(seed * 7919 + sum(map(ord, params.name)))

    def act(view: View) -> tuple[str, float | None]:
        if view.street_index == 0:
            strength = chen_formula(view.hole_cards)
            if strength >= params.raise_chen and view.can_raise:
                target = view.pot_amount * 2.5 + view.to_call
                return "raise_to", min(target, view.max_raise_to)
            if strength >= params.vpip_chen or view.to_call <= 0:
                return "check_call", None
            if view.to_call >= view.pot_amount:
                return "fold", None
            return "check_call", None

        equity = monte_carlo_equity(
            view.hole_cards,
            view.board_cards,
            samples=params.equity_samples,
            rng=rng,
        )

        if view.to_call <= 0:
            if equity >= 0.62 and rng.random() < params.aggression and view.can_raise:
                size = view.pot_amount * (0.66 + 0.34 * rng.random())
                target = max(size + view.to_call, view.min_raise_to)
                return "raise_to", min(target, view.max_raise_to)
            if equity < 0.30 and rng.random() < params.bluff_frequency and view.can_raise:
                target = max(view.pot_amount * 0.5, view.min_raise_to)
                return "raise_to", min(target, view.max_raise_to)
            return "check_call", None

        required_equity = (
            view.to_call / max(view.pot_amount + view.to_call, 1e-9)
            + params.call_equity_margin
        )
        if equity < max(required_equity, params.fold_equity_threshold):
            return "fold", None
        if equity >= 0.75 and rng.random() < params.aggression and view.can_raise:
            target = max(view.pot_amount * 0.75 + view.to_call, view.min_raise_to)
            return "raise_to", min(target, view.max_raise_to)
        return "check_call", None

    return act


def make_heuristic_hero_policy() -> ActionFn:
    """Politique héro par défaut : jeu serré/agressif basé équité (baseline GTO-like)."""
    rng = Random(0x5EED_1234)

    def act(view: View) -> tuple[str, float | None]:
        if view.street_index == 0:
            strength = chen_formula(view.hole_cards)
            if strength >= 12.0 and view.can_raise:
                target = view.pot_amount * 3.0 + view.to_call
                return "raise_to", min(max(target, view.min_raise_to), view.max_raise_to)
            if strength >= 9.0 or (view.to_call <= BIG_BLIND and strength >= 7.0):
                return "check_call", None
            if view.to_call > 0:
                return "fold", None
            return "check_call", None

        equity = monte_carlo_equity(
            view.hole_cards, view.board_cards, samples=140, rng=rng
        )
        if view.to_call <= 0:
            if equity >= 0.60 and view.can_raise:
                target = max(view.pot_amount * 0.66, view.min_raise_to)
                return "raise_to", min(target, view.max_raise_to)
            if equity >= 0.45 and rng.random() < 0.25 and view.can_raise:
                target = max(view.pot_amount * 0.5, view.min_raise_to)
                return "raise_to", min(target, view.max_raise_to)
            return "check_call", None

        required = view.to_call / max(view.pot_amount + view.to_call, 1e-9)
        if equity < required - 0.01:
            return "fold", None
        if equity >= 0.70 and view.can_raise:
            target = max(view.pot_amount * 0.75 + view.to_call, view.min_raise_to)
            return "raise_to", min(target, view.max_raise_to)
        return "check_call", None

    return act


POLICY_FACTORIES: dict[str, Callable[[], ActionFn]] = {
    "hero_heuristic": make_heuristic_hero_policy,
}


def build_view(state: NoLimitTexasHoldem, hole_cards: str) -> View:
    bets_sum = float(sum(state.bets))
    return View(
        street_index=state.street_index,
        hole_cards=hole_cards,
        board_cards="".join(
            card for street in state.board_cards for card in street
        ),
        pot_amount=float(state.total_pot_amount) + bets_sum,
        to_call=float(state.checking_or_calling_amount or 0.0),
        effective_stack=float(min(state.stacks)),
        min_raise_to=float(state.min_completion_betting_or_raising_to_amount),
        max_raise_to=float(state.max_completion_betting_or_raising_to_amount),
        can_raise=bool(state.can_complete_bet_or_raise_to()),
        is_button=(state.actor_index == 0),
    )


def apply_action(state: NoLimitTexasHoldem, action: str, amount: float | None) -> None:
    if action == "fold" and state.can_fold():
        state.fold()
        return
    if action == "raise_to" and state.can_complete_bet_or_raise_to():
        clamped = min(
            max(float(amount or 0.0), state.min_completion_betting_or_raising_to_amount),
            state.max_completion_betting_or_raising_to_amount,
        )
        state.complete_bet_or_raise_to(clamped)
        return
    state.check_or_call()


def play_hand(
    hero_action_fn: ActionFn,
    villain_action_fn: ActionFn,
    rng: Random,
    *,
    hero_index: int = 0,
) -> float:
    """Joue une main HU ; retourne le résultat héro en gros blindes (+/-)."""
    state, holes = new_state(rng)

    while state.status:
        actor = state.actor_index
        if actor is None:
            break
        action_fn = hero_action_fn if actor == hero_index else villain_action_fn
        try:
            action, amount = action_fn(build_view(state, holes[actor]))
        except Exception:
            action, amount = "check_call", None
        try:
            apply_action(state, action, amount)
        except Exception:
            if state.can_check_or_call():
                state.check_or_call()
            elif state.can_fold():
                state.fold()

    payoffs = state.payoffs or (0.0, 0.0)
    return float(payoffs[hero_index]) / BIG_BLIND


def run_match(
    hero_action_fn: ActionFn,
    villain_params: ArchetypeParams,
    *,
    num_hands: int,
    seed: int,
) -> dict[str, object]:
    """Affronte la politique héro à un profil donné ; retourne stats bb/100 ± IC95."""
    villain_action_fn = make_archetype_policy(villain_params, seed)
    rng = Random(seed)
    results: list[float] = []
    started = time.perf_counter()

    for _ in range(num_hands):
        results.append(play_hand(hero_action_fn, villain_action_fn, rng))

    elapsed = time.perf_counter() - started
    n = len(results)
    total_bb = sum(results)
    winrate_bb100 = total_bb / n * 100.0 if n else 0.0
    mean = total_bb / n if n else 0.0
    variance = sum((value - mean) ** 2 for value in results) / n if n else 0.0
    std = math.sqrt(variance)
    ci95 = 1.96 * std / math.sqrt(n) * 100.0 if n else 0.0

    return {
        "villain": villain_params.name,
        "hands": n,
        "winrate_bb100": round(winrate_bb100, 3),
        "ci95_bb100": round(ci95, 3),
        "winrate_low": round(winrate_bb100 - ci95, 3),
        "winrate_high": round(winrate_bb100 + ci95, 3),
        "std_per_hand_bb": round(std, 4),
        "elapsed_s": round(elapsed, 2),
    }


def run_evaluation(
    *,
    hero_policy_name: str = "hero_heuristic",
    opponents: Sequence[str] = ("nit", "tag", "lag", "station", "whale"),
    num_hands: int = 10_000,
    seed: int = 20260826,
) -> dict[str, object]:
    """Évalue une politique sur tout le pool d'opposants."""
    factory = POLICY_FACTORIES.get(hero_policy_name, make_heuristic_hero_policy)
    hero_action_fn = factory()

    selected = [ARCHETYPES[name] for name in opponents if name in ARCHETYPES]
    selected = selected or list(ARCHETYPES.values())

    matches = [
        run_match(hero_action_fn, params, num_hands=num_hands, seed=seed + index)
        for index, params in enumerate(selected)
    ]

    hands_total = sum(int(match["hands"]) for match in matches)
    weighted = sum(
        float(match["winrate_bb100"]) * int(match["hands"]) for match in matches
    )
    return {
        "hero_policy": hero_policy_name,
        "hands_total": hands_total,
        "aggregate_winrate_bb100": round(weighted / hands_total, 3) if hands_total else 0.0,
        "beats_pool": all(float(match["winrate_bb100"]) > 0 for match in matches),
        "matches": matches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hands", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--policy", type=str, default="hero_heuristic")
    parser.add_argument("--opponents", type=str, nargs="*", default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    summary = run_evaluation(
        hero_policy_name=args.policy,
        opponents=tuple(args.opponents)
        if args.opponents
        else ("nit", "tag", "lag", "station", "whale"),
        num_hands=args.hands,
        seed=args.seed,
    )

    payload = json.dumps(summary, indent=2)
    print(payload)

    output_path = args.output or str(ROOT / "research" / "results" / "monte_carlo_sim.json")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(payload + "\n", encoding="utf-8")
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
