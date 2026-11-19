"""Benchmark externe du runtime de production contre Slumbot (Phase 1.8).

``research/slumbot_benchmark.py`` mesure ``hero_heuristic``, la politique de
recherche utilisée par les simulations internes. Ce module mesure l'autre
chaîne : ``DecisionMaker.get_best_action`` (préflop store, solveur Rust, cache,
sélecteur exploit, fallbacks), c'est-à-dire le produit réel, contre l'API
publique de Slumbot.

Le protocole HTTP et le parseur d'état sont réutilisés tels quels depuis
``research.slumbot_benchmark``. Seule la traduction décision → incrément change :
le runtime raisonne en gros blindes et en noms d'action abstraits
(``BET``/``RAISE`` avec ``bet_size``), Slumbot attend un incrément légal
``k``/``c``/``f``/``bN`` en jetons.

Usage :
    python -m research.slumbot_runtime_benchmark --hands 100 \
        --output research/results/slumbot_runtime_100.jsonl

Le JSONL contient une ligne par main, avec les décisions, leur source
(``GTO_RUST``, préflop, fallback), la latence par décision et le résultat.
Aucune main n'est jouée en argent réel : Slumbot est un bot d'entraînement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.slumbot_benchmark import (  # noqa: E402
    BIG_BLIND,
    ParsedState,
    SlumbotClient,
    SlumbotError,
    _clamp_raise,
    parse_action,
    summarize,
)

DEFAULT_OUTPUT = ROOT / "research" / "results" / "slumbot_runtime_benchmark.jsonl"

POSTFLOP_LEGAL_NO_BET = ["check", "bet_50", "bet_75", "allin"]
POSTFLOP_LEGAL_FACING_BET = ["fold", "call", "raise"]
PREFLOP_LEGAL_FACING_BET = ["fold", "call", "raise"]
PREFLOP_LEGAL_NO_BET = ["check", "raise"]


def legal_actions_for(state: ParsedState) -> list[str]:
    """Liste d'actions légales au format attendu par ``DecisionMaker``."""
    if state.to_call > 0:
        return PREFLOP_LEGAL_FACING_BET if state.street == 0 else POSTFLOP_LEGAL_FACING_BET
    return PREFLOP_LEGAL_NO_BET if state.street == 0 else POSTFLOP_LEGAL_NO_BET


def hero_position_for(client_pos: int, street: int) -> str:
    """Position du héros : bouton/SB en HU est IP postflop, BB est OOP."""
    if street == 0:
        return "btn" if client_pos == 1 else "bb"
    return "ip" if client_pos == 1 else "oop"


_STREET_LABELS = {0: "PREFLOP", 1: "FLOP", 2: "TURN", 3: "RIVER"}


def action_history_from_log(state: ParsedState) -> list[dict[str, Any]]:
    """Convertit la rue courante de Slumbot en historique au format runtime.

    Les montants agressifs sont des **contributions totales de rue** en bb
    (``bets 300`` / ``raises to 900``), pas des incréments : c'est le contrat
    attendu par le solveur pour rapprocher l'action observée d'une taille de
    l'arbre.
    """
    label = _STREET_LABELS.get(state.street)
    if label is None or not state.street_logs:
        return []
    history: list[dict[str, Any]] = []
    for who, text in state.street_logs[-1]:
        parts = text.split()
        if not parts:
            continue
        verb = parts[0]
        if verb in {"checks", "folds", "calls"}:
            action = {"checks": "check", "folds": "fold", "calls": "call"}[verb]
            amount = 0.0
        elif verb in {"bets", "raises"}:
            amount = float(int(parts[-1]))
            action = "bet" if verb == "bets" else "raise"
        else:
            continue
        actor = "villain" if who == "bot" else "hero"
        history.append(
            {
                "player": actor,
                "actor": actor,
                "action": action,
                "amount": round(amount / BIG_BLIND, 4),
                "street": label,
            }
        )
    return history


def _solver_size_bb(result: dict[str, Any]) -> float | None:
    """Taille en bb de l'action recommandée, lue dans les détails du solveur."""
    for detail in result.get("details") or []:
        if not isinstance(detail, dict):
            continue
        if detail.get("is_recommended") and detail.get("size") is not None:
            try:
                return float(detail["size"])
            except (TypeError, ValueError):
                return None
    return None


def _desired_total(state: ParsedState, result: dict[str, Any]) -> int | None:
    """Contribution totale de street visée par l'action agressive du runtime."""
    window = state.raise_window()
    if window[1] is None:
        return None

    action = str(result.get("action") or "").upper()
    if action == "ALL_IN":
        return int(window[1])

    bet_size_bb = result.get("bet_size")
    try:
        bet_size_bb = float(bet_size_bb) if bet_size_bb is not None else None
    except (TypeError, ValueError):
        bet_size_bb = None
    size_bb = _solver_size_bb(result)
    if size_bb is None:
        size_bb = bet_size_bb

    if state.street == 0:
        # Préflop, ``dynamic_amount`` du store est déjà un « raise to » en bb.
        if bet_size_bb is not None:
            return int(round(bet_size_bb * BIG_BLIND))
        if size_bb is not None:
            return int(round(size_bb * BIG_BLIND))
    elif action == "BET":
        if size_bb is not None:
            return int(round(state.hero_street + max(size_bb, 0.0) * BIG_BLIND))
    else:  # RAISE postflop : ``size`` est déjà la contribution totale visée.
        if size_bb is not None:
            return int(round(size_bb * BIG_BLIND))

    # Repli : demi-pot, borné par la fenêtre légale.
    pot = max(state.pot, 1)
    if state.level == 0:
        return int(state.hero_street + max(BIG_BLIND, round(0.5 * pot)))
    return int(state.level + max(state.level - state.hero_street, round(0.5 * pot)))


def runtime_increment(state: ParsedState, result: dict[str, Any]) -> str:
    """Traduit la décision du runtime en incrément Slumbot légal."""
    action = str(result.get("action") or "").upper()
    window = state.raise_window()

    if action in {"FOLD"}:
        return "f" if state.to_call > 0 else "k"
    if action in {"CALL", "CHECK"}:
        return "c" if state.to_call > 0 else "k"
    if action not in {"BET", "RAISE", "ALL_IN"}:
        return "c" if state.to_call > 0 else "k"

    if window[1] is None:
        return "c" if state.to_call > 0 else "k"
    target = _desired_total(state, result)
    if target is None:
        return "c" if state.to_call > 0 else "k"
    clamped = _clamp_raise(float(target), window)
    if clamped is None:
        return "c" if state.to_call > 0 else "k"
    return f"b{clamped}"


class RuntimePolicy:
    """Adaptateur synchrone autour de ``DecisionMaker.get_best_action``."""

    def __init__(self, maker: Any) -> None:
        self.maker = maker
        self.loop = asyncio.new_event_loop()

    def __call__(
        self,
        state: ParsedState,
        hole_cards: list[str],
        board: list[str],
        *,
        client_pos: int,
        hand_number: int,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        hero_hand = "".join(hole_cards)
        position = hero_position_for(client_pos, state.street)
        decision = self.loop.run_until_complete(
            self.maker.get_best_action(
                hero_hand,
                list(board),
                state.pot / BIG_BLIND,
                state.effective_stack / BIG_BLIND,
                "slumbot",
                legal_actions_for(state),
                spot_id=f"slumbot_hand_{hand_number}_s{state.street}",
                hero_position=position,
                state_confidence=0.95,
                action_history=action_history_from_log(state),
            )
        )
        increment = runtime_increment(state, decision)
        return increment, decision, {
            "street": state.street,
            "pot_bb": round(state.pot / BIG_BLIND, 3),
            "to_call_bb": round(state.to_call / BIG_BLIND, 3),
            "action": decision.get("action"),
            "bet_size": decision.get("bet_size"),
            "source": decision.get("source"),
            "backend": decision.get("backend"),
            "fallback_used": bool(decision.get("fallback_used")),
            "fallback_reason": decision.get("fallback_reason"),
            "cache_hit": bool(decision.get("cache_hit")),
            "exploitability": decision.get("exploitability"),
            "elapsed_ms": decision.get("elapsed_ms"),
            "increment": increment,
        }


def play_hand_runtime(
    client: SlumbotClient,
    policy: RuntimePolicy,
    *,
    hand_number: int,
) -> dict[str, Any]:
    """Joue une main avec le runtime de production et journalise les décisions."""
    started = time.perf_counter()
    response = client.new_hand()
    client_pos = int(response.get("client_pos", client.client_pos))
    hole_cards = [str(card) for card in response.get("hole_cards", [])]
    board = [str(card) for card in response.get("board", [])]
    action_string = str(response.get("action", ""))
    decisions: list[dict[str, Any]] = []
    decision_ms: list[float] = []

    for _ in range(64):
        if "winnings" in response:
            break
        state = parse_action(action_string, client_pos)
        if not state.hero_turn:
            raise SlumbotError(
                f"main {hand_number}: ce n'est pas au héros de parler ({action_string!r})"
            )
        decision_started = time.perf_counter()
        increment, _, metadata = policy(
            state,
            hole_cards,
            board,
            client_pos=client_pos,
            hand_number=hand_number,
        )
        decision_ms.append((time.perf_counter() - decision_started) * 1000.0)
        decisions.append(metadata)
        response = client.act(increment)
        action_string = str(response.get("action", ""))
        board = [str(card) for card in response.get("board", board)]

    if "winnings" not in response:
        raise SlumbotError(f"main {hand_number}: limite de 64 actions atteinte")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    winnings = int(response["winnings"])
    return {
        "hand": hand_number,
        "winnings": winnings,
        "winnings_bb": round(winnings / BIG_BLIND, 4),
        "client_pos": client_pos,
        "hole_cards": hole_cards,
        "board": board,
        "bot_hole_cards": [str(card) for card in response.get("bot_hole_cards", [])],
        "action": action_string,
        "decisions": decisions,
        "decision_count": len(decisions),
        "decision_ms": [round(value, 3) for value in decision_ms],
        "hand_ms": round(elapsed_ms, 3),
    }


def summarize_runtime(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Résumé du benchmark runtime : winrate, latence, sources, fallbacks."""
    summary = summarize(rows)
    decisions = [
        decision
        for row in rows
        for decision in row.get("decisions", [])
    ]
    sources: dict[str, int] = {}
    backends: dict[str, int] = {}
    for decision in decisions:
        source = str(decision.get("source") or "unknown")
        backend = str(decision.get("backend") or "unknown")
        sources[source] = sources.get(source, 0) + 1
        backends[backend] = backends.get(backend, 0) + 1
    solver_decisions = [
        float(decision.get("elapsed_ms") or 0.0)
        for decision in decisions
        if decision.get("source") == "GTO_RUST"
    ]
    summary.update(
        {
            "kind": "slumbot_runtime_benchmark",
            "policy": "DecisionMaker.get_best_action",
            "opponent": "slumbot.com",
            "blinds": "50/100",
            "starting_stack_bb": 200,
            "decisions": len(decisions),
            "decisions_per_hand": round(len(decisions) / len(rows), 2) if rows else 0.0,
            "fallbacks": sum(1 for d in decisions if d.get("fallback_used")),
            "cache_hits": sum(1 for d in decisions if d.get("cache_hit")),
            "sources": dict(sorted(sources.items())),
            "backends": dict(sorted(backends.items())),
            "solver_decisions": len(solver_decisions),
            "solver_elapsed_ms_p50": round(statistics.median(solver_decisions), 1)
            if solver_decisions
            else 0.0,
            "solver_elapsed_ms_p95": round(
                sorted(solver_decisions)[
                    min(len(solver_decisions) - 1, int(0.95 * len(solver_decisions)))
                ],
                1,
            )
            if solver_decisions
            else 0.0,
        }
    )
    return summary


def run_benchmark(
    *,
    hands: int,
    output: Path,
    seed: int = 20261116,
    resume: bool = False,
    progress_every: int = 10,
    delay_seconds: float = 0.05,
    bet_sizes: str | None = None,
    raise_sizes: str | None = None,
) -> dict[str, Any]:
    """Joue ``hands`` mains avec le runtime, écrit le JSONL et retourne le résumé."""
    from src.bot.decision_maker import DecisionMaker

    rows: list[dict[str, Any]] = []
    if resume and output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    elif output.exists():
        raise FileExistsError(f"{output} existe déjà ; utiliser --resume ou --overwrite")

    maker = DecisionMaker(
        None,
        create_rl_agent=False,
        autoload_rl_model=False,
        heads_up=True,
    )
    if bet_sizes:
        maker.solver_bet_sizes = bet_sizes
    if raise_sizes:
        maker.solver_raise_sizes = raise_sizes

    policy = RuntimePolicy(maker)
    client = SlumbotClient()
    started_at = datetime.now(UTC).isoformat()
    errors = 0
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("a" if resume else "w", encoding="utf-8") as handle:
        while len(rows) < hands:
            hand_number = len(rows) + 1
            try:
                row = play_hand_runtime(client, policy, hand_number=hand_number)
            except SlumbotError:
                errors += 1
                if errors >= 5:
                    raise
                time.sleep(1.0)
                continue
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            if progress_every and hand_number % progress_every == 0:
                partial = summarize_runtime(rows)
                print(
                    f"[{hand_number}/{hands}] bb/100={partial['winrate_bb100']:+.1f} "
                    f"IC95=±{partial['ci95_bb100']:.1f} "
                    f"fallbacks={partial['fallbacks']} "
                    f"({partial['hands_per_minute']:.0f} mains/min)",
                    flush=True,
                )

    summary = summarize_runtime(rows)
    summary.update(
        {
            "seed": seed,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "errors": errors,
            "bet_sizes": maker.solver_bet_sizes,
            "raise_sizes": maker.solver_raise_sizes,
            "output": str(output),
        }
    )
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hands", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--bet-sizes", type=str, default=None)
    parser.add_argument("--raise-sizes", type=str, default=None)
    args = parser.parse_args()

    if args.overwrite and args.output.exists():
        args.output.unlink()
        args.output.with_suffix(".summary.json").unlink(missing_ok=True)

    summary = run_benchmark(
        hands=args.hands,
        output=args.output,
        seed=args.seed,
        resume=args.resume,
        progress_every=args.progress_every,
        delay_seconds=args.delay,
        bet_sizes=args.bet_sizes,
        raise_sizes=args.raise_sizes,
    )
    print(json.dumps(summary, indent=2))
    print(f"saved={args.output}")
    print(f"summary={args.output.with_suffix('.summary.json')}")


if __name__ == "__main__":
    main()
