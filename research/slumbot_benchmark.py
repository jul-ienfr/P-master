"""Benchmark externe HU no-limit contre Slumbot (Phase 1.5).

Le protocole HTTP de Slumbot est public : ``POST /api/new_hand`` ouvre une main,
``POST /api/act`` joue un incrément (``k``, ``c``, ``f`` ou ``bN`` où N est la
contribution totale du joueur sur la street, blindes incluses). Une réponse
contient l'historique complet dans ``action`` ; ce module le rejoue pour
reconstruire le pot, le montant à payer et la fenêtre de relance légale.

La politique évaluée est ``hero_heuristic`` de ``research.monte_carlo_sim``,
celle-là même qui sert aux simulations internes. Le résultat est donc un
benchmark de la politique réellement livrée, pas du solveur Rust.

Usage :
    python -m research.slumbot_benchmark --hands 1000 \
        --output research/results/slumbot_1000.jsonl

Le JSONL contient une ligne par main (résultat, décisions, latence) et le
résumé agrégé est écrit à côté (``.summary.json``). Aucun token n'est journalisé.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.monte_carlo_sim import (  # noqa: E402
    View,
    make_heuristic_hero_policy,
)

API_URL = "https://slumbot.com/api"
SMALL_BLIND = 50
BIG_BLIND = 100
STACK = 20_000
SCALE = 50
STREETS = ("preflop", "flop", "turn", "river")
TOKEN_RX = re.compile(r"k|c|f|b\d+")


class SlumbotError(RuntimeError):
    """Réponse métier d'erreur (token invalide, action illégale, main finie)."""


class SlumbotHTTPError(RuntimeError):
    """Erreur réseau persistante après les tentatives de reprise."""


@dataclass
class ParsedState:
    """État reconstruit depuis la chaîne d'actions de Slumbot."""

    street: int = 0
    hero_total: int = 0
    bot_total: int = 0
    hero_street: int = 0
    bot_street: int = 0
    to_call: int = 0
    last_increment: int = BIG_BLIND
    level: int = 0
    hero_turn: bool = False
    log: list[tuple[str, str]] = field(default_factory=list)
    street_logs: list[list[tuple[str, str]]] = field(default_factory=list)

    @property
    def pot(self) -> int:
        return self.hero_total + self.bot_total

    @property
    def hero_stack(self) -> int:
        return STACK - self.hero_total

    @property
    def bot_stack(self) -> int:
        return STACK - self.bot_total

    @property
    def effective_stack(self) -> int:
        """Tapis réellement en jeu pour la décision du héros.

        Quand l'adversaire est all-in, ``min(hero_stack, bot_stack)`` vaut 0 et
        le solveur refuse un arbre à tapis nul. Le héros ne peut alors plus
        engager que son appel (``to_call``), c'est donc le tapis effectif du
        spot ; un tapis terminal (``to_call == 0``) reste à 0.
        """
        return max(
            min(self.hero_stack, self.bot_stack),
            min(self.hero_stack, self.to_call),
        )

    def raise_window(self) -> tuple[int | None, int | None]:
        """Fenêtre ``(min_to, max_to)`` en contribution totale de street."""
        max_to = self.hero_street + self.hero_stack
        if max_to <= self.level:
            return None, None
        min_to = min(self.level + max(self.last_increment, BIG_BLIND), max_to)
        return min_to, max_to


def parse_action(action: str, client_pos: int) -> ParsedState:
    """Rejoue une chaîne Slumbot. ``client_pos`` 0 = BB, 1 = SB."""
    state = ParsedState()
    hero_is_sb = client_pos == 1
    contrib = {"sb": SMALL_BLIND, "bb": BIG_BLIND}
    totals = {"sb": SMALL_BLIND, "bb": BIG_BLIND}
    state.level = BIG_BLIND
    state.last_increment = BIG_BLIND

    for street_index, street_text in enumerate(action.split("/")):
        state.street = min(street_index, len(STREETS) - 1)
        state.street_logs.append([])
        if street_index > 0:
            contrib = {"sb": 0, "bb": 0}
            state.level = 0
            state.last_increment = 0

        order = ("sb", "bb") if street_index == 0 else ("bb", "sb")
        turn = 0
        for token in TOKEN_RX.findall(street_text):
            who = order[turn % 2]
            name = "hero" if (who == "sb") == hero_is_sb else "bot"
            if token == "k":
                entry = (name, "checks")
            elif token == "c":
                paid = state.level - contrib[who]
                totals[who] += paid
                contrib[who] = state.level
                entry = (name, f"calls {paid}" if paid else "checks")
            elif token == "f":
                entry = (name, "folds")
            else:
                to = int(token[1:])
                increment = to - state.level
                if increment > 0:
                    state.last_increment = max(increment, state.last_increment)
                verb = "bets" if state.level == 0 else "raises to"
                totals[who] += to - contrib[who]
                contrib[who] = to
                state.level = to
                entry = (name, f"{verb} {to}")
            state.log.append(entry)
            state.street_logs[-1].append(entry)
            turn += 1

        next_who = order[turn % 2]
        state.hero_turn = (next_who == "sb") == hero_is_sb

    hero_key = "sb" if hero_is_sb else "bb"
    bot_key = "bb" if hero_is_sb else "sb"
    state.hero_total = totals[hero_key]
    state.bot_total = totals[bot_key]
    state.hero_street = contrib[hero_key]
    state.bot_street = contrib[bot_key]
    state.to_call = max(0, state.level - state.hero_street)
    return state


class SlumbotClient:
    """Client HTTP minimal, une session à la fois, reprise sur erreurs transitoires."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_attempts: int = 5,
        base_delay: float = 0.25,
    ) -> None:
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.token: str | None = None
        self.client_pos = 0
        self.debug = False

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            if self.debug:
                print(f"[http] POST {path} attempt={attempt}", file=sys.stderr, flush=True)
            request = urllib.request.Request(
                f"{API_URL}/{path}",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "poker-master-benchmark/0.1",
                    "Connection": "close",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                result = json.loads(body)
                if self.debug:
                    print(f"[http] {path} -> {result}", file=sys.stderr, flush=True)
                if "error_msg" in result:
                    raise SlumbotError(str(result["error_msg"]))
                return result
            except SlumbotError:
                raise
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                http.client.HTTPException,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                retryable = not (
                    isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 401, 403, 404}
                )
                if not retryable or attempt == self.max_attempts:
                    break
                print(
                    f"[slumbot] {path} tentative {attempt}/{self.max_attempts} : {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(self.base_delay * (2 ** (attempt - 1)))
        raise SlumbotHTTPError(f"{path}: {last_error}") from last_error

    def new_hand(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"token": self.token} if self.token else {}
        result = self._post("new_hand", payload)
        if result.get("token"):
            self.token = str(result["token"])
        if "client_pos" in result:
            self.client_pos = int(result["client_pos"])
        return result

    def act(self, incr: str) -> dict[str, Any]:
        if self.token is None:
            raise SlumbotError("new_hand() requis avant act()")
        result = self._post("act", {"token": self.token, "incr": incr})
        if result.get("token"):
            self.token = str(result["token"])
        return result


def _clamp_raise(amount: float, window: tuple[int | None, int | None]) -> int | None:
    minimum, maximum = window
    if minimum is None or maximum is None:
        return None
    rounded = int(round(amount / SCALE) * SCALE)
    return max(int(minimum), min(int(maximum), rounded))


def choose_increment(
    state: ParsedState,
    hole_cards: list[str],
    board: list[str],
    policy: Any,
    *,
    is_button: bool = False,
) -> str:
    """Traduit la décision de la politique en incrément Slumbot légal.

    La politique de recherche raisonne en **gros blindes** (comme dans
    ``monte_carlo_sim``) ; Slumbot raisonne en jetons. La vue est donc convertie
    en bb avant l'appel, puis le montant de relance est reconverti en jetons.
    Sans cette conversion, ``to_call <= BIG_BLIND`` (2 bb) était comparé à
    100 jetons et la politique abandonnait presque tout.
    """
    window = state.raise_window()
    view = View(
        street_index=state.street,
        hole_cards="".join(hole_cards),
        board_cards="".join(board),
        pot_amount=state.pot / BIG_BLIND,
        to_call=state.to_call / BIG_BLIND,
        effective_stack=state.effective_stack / BIG_BLIND,
        min_raise_to=float(window[0] or 0) / BIG_BLIND,
        max_raise_to=float(window[1] or 0) / BIG_BLIND,
        can_raise=window[1] is not None,
        is_button=is_button,
    )
    action, amount = policy(view)

    if action == "fold":
        return "f" if state.to_call > 0 else "k"
    if action == "raise_to" and window[1] is not None:
        target = _clamp_raise(float(amount or 0.0) * BIG_BLIND, window)
        if target is not None:
            return f"b{target}"
    return "c" if state.to_call > 0 else "k"


def play_hand(
    client: SlumbotClient,
    policy: Any,
    *,
    hand_number: int,
    debug: bool = False,
) -> dict[str, Any]:
    """Joue une main complète et retourne une ligne de résultat."""
    started = time.perf_counter()
    response = client.new_hand()
    client_pos = int(response.get("client_pos", client.client_pos))
    hole_cards = [str(card) for card in response.get("hole_cards", [])]
    board = [str(card) for card in response.get("board", [])]
    action_string = str(response.get("action", ""))
    increments: list[str] = []
    decision_ms: list[float] = []

    if debug:
        print(
            f"[hand {hand_number}] pos={client_pos} hole={hole_cards} action={action_string!r}",
            file=sys.stderr,
            flush=True,
        )

    for _ in range(64):
        if "winnings" in response:
            break
        state = parse_action(action_string, client_pos)
        if debug:
            print(
                f"[hand {hand_number}] street={state.street} pot={state.pot} "
                f"to_call={state.to_call} window={state.raise_window()} "
                f"hero_turn={state.hero_turn}",
                file=sys.stderr,
                flush=True,
            )
        if not state.hero_turn:
            raise SlumbotError(
                f"main {hand_number}: ce n'est pas au héros de parler ({action_string!r})"
            )
        decision_started = time.perf_counter()
        increment = choose_increment(
            state,
            hole_cards,
            board,
            policy,
            is_button=client_pos == 1,
        )
        decision_ms.append((time.perf_counter() - decision_started) * 1000.0)
        increments.append(increment)
        if debug:
            print(f"[hand {hand_number}] act={increment}", file=sys.stderr, flush=True)
        response = client.act(increment)
        action_string = str(response.get("action", ""))
        board = [str(card) for card in response.get("board", board)]
        if debug:
            print(
                f"[hand {hand_number}] -> action={action_string!r} "
                f"winnings={response.get('winnings')}",
                file=sys.stderr,
                flush=True,
            )

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
        "increments": increments,
        "decisions": len(increments),
        "decision_ms": [round(value, 3) for value in decision_ms],
        "hand_ms": round(elapsed_ms, 3),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"hands": 0, "error": "aucune main"}
    winnings_bb = [float(row["winnings_bb"]) for row in rows]
    mean_bb = statistics.fmean(winnings_bb)
    std_bb = statistics.stdev(winnings_bb) if len(winnings_bb) > 1 else 0.0
    ci95_bb100 = 1.96 * std_bb / math.sqrt(len(winnings_bb)) * 100.0
    decision_ms = [
        float(value)
        for row in rows
        for value in row.get("decision_ms", [])
    ]
    wins = sum(1 for value in winnings_bb if value > 0)
    losses = sum(1 for value in winnings_bb if value < 0)
    return {
        "hands": len(rows),
        "total_winnings_bb": round(sum(winnings_bb), 3),
        "winrate_bb100": round(mean_bb * 100.0, 3),
        "ci95_bb100": round(ci95_bb100, 3),
        "winrate_low": round(mean_bb * 100.0 - ci95_bb100, 3),
        "winrate_high": round(mean_bb * 100.0 + ci95_bb100, 3),
        "std_per_hand_bb": round(std_bb, 4),
        "wins": wins,
        "losses": losses,
        "ties": len(rows) - wins - losses,
        "decisions": len(decision_ms),
        "decisions_per_hand": round(len(decision_ms) / len(rows), 2),
        "decision_ms_p50": round(statistics.median(decision_ms), 3) if decision_ms else 0.0,
        "decision_ms_p95": round(
            sorted(decision_ms)[min(len(decision_ms) - 1, int(0.95 * len(decision_ms)))], 3
        )
        if decision_ms
        else 0.0,
        "hands_per_minute": round(
            60_000.0 / statistics.fmean(float(row["hand_ms"]) for row in rows), 2
        )
        if rows
        else 0.0,
    }


def run_benchmark(
    *,
    hands: int,
    output: Path,
    seed: int = 20261115,
    resume: bool = False,
    progress_every: int = 25,
    delay_seconds: float = 0.5,
    debug: bool = False,
) -> dict[str, Any]:
    """Joue ``hands`` mains, écrit le JSONL et retourne le résumé."""
    random.seed(seed)
    rows: list[dict[str, Any]] = []
    if resume and output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    elif output.exists():
        raise FileExistsError(f"{output} existe déjà ; utiliser --resume ou --overwrite")

    client = SlumbotClient()
    client.debug = debug
    policy = make_heuristic_hero_policy()
    started_at = datetime.now(UTC).isoformat()
    errors = 0
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("a" if resume else "w", encoding="utf-8") as handle:
        while len(rows) < hands:
            hand_number = len(rows) + 1
            try:
                row = play_hand(client, policy, hand_number=hand_number, debug=debug)
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
                partial = summarize(rows)
                print(
                    f"[{hand_number}/{hands}] bb/100={partial['winrate_bb100']:+.1f} "
                    f"IC95=±{partial['ci95_bb100']:.1f} "
                    f"({partial['hands_per_minute']:.0f} mains/min)",
                    flush=True,
                )

    summary = summarize(rows)
    summary.update(
        {
            "kind": "slumbot_benchmark",
            "policy": "hero_heuristic",
            "opponent": "slumbot.com",
            "blinds": "50/100",
            "starting_stack_bb": 200,
            "seed": seed,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "errors": errors,
            "output": str(output),
        }
    )
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hands", type=int, default=100)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research" / "results" / "slumbot_benchmark.jsonl",
    )
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--delay", type=float, default=0.5, help="pause entre deux mains (s)")
    parser.add_argument("--debug", action="store_true", help="trace HTTP et décisions sur stderr")
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
        debug=args.debug,
    )
    print(json.dumps(summary, indent=2))
    print(f"saved={args.output}")
    print(f"summary={args.output.with_suffix('.summary.json')}")


if __name__ == "__main__":
    main()
