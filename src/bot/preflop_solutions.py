"""Solutions préflop pré-calculées + résolution live (Phase 1 — dual-mode).

Le moteur DCFR embarqué ne couvre que le postflop (BoardState::Flop..River). Les
"solutions" préflop sont donc dérivées hors-ligne des charts par position
(``PreflopManager``) : RFI, 3-bet et bande de call, puis compressées sous
``models/preflop/``. Pour ces tables, l'équité Monte-Carlo ne sert qu'à estimer
l'EV affiché — les anciens seuils étaient position-agnostiques et leur bande de
call était vide à 100 bb. Le loader runtime lit ce cache (<10ms une fois
chargé) ; à défaut, repli sur les charts existants.

Mode ``live`` : même calcul mais exécuté au moment de la décision avec un budget
d'échantillons supérieur (borné par ``live_time_budget_ms``).

Note : quand un arbre préflop natif sera disponible dans le moteur Rust, la
méthode ``resolve_live`` pourra être remplacée par un appel solveur sans changer
l'API du store.
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    from pokerkit import StandardHighHand

    POKERKIT_AVAILABLE = True
except ImportError:  # pragma: no cover
    StandardHighHand = None
    POKERKIT_AVAILABLE = False

PREFLOP_POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
DEPTH_BUCKETS = (20, 50, 100)
CONTEXTS = ("rfi", "vs_raise", "vs_3bet")
HU_CONTEXTS = ("hu_rfi", "hu_vs_raise")
HU_POSITIONS = ("SB", "BB")

# Ranges de relance par contexte. Les bandes de call viennent des charts du
# ``PreflopManager`` (défense BB et défenses heads-up) ; les positions 6-max
# hors BB jouent « 3-bet or fold », donc sans bande de call.
VS_RAISE_3BET_RANGE = "TT+, AQs+, AKo"
VS_3BET_RAISE_RANGE = "QQ+, AKs, AKo"
VS_3BET_CALL_RANGE = "JJ, TT, AQs"

DEFAULT_SOLUTIONS_PATH = "models/preflop"

_RANKS = "23456789TJQKA"
_RANKS_DESC = _RANKS[::-1]
_DECK = tuple(rank + suit for rank in _RANKS for suit in "cdhs")


def enumerate_combos() -> list[str]:
    """Toutes les notations de combos (169 mains : 'AA', 'AKs', 'AKo', ...).

    Les rangs sont **décroissants** ('AKs', '32o'), comme
    ``hero_combo_notation`` : les anciennes clés ascendantes ('KAs', '23o') ne
    matchaient que les paires.
    """
    combos: list[str] = []
    for i, high in enumerate(_RANKS_DESC):
        for low in _RANKS_DESC[i:]:
            if high == low:
                combos.append(f"{high}{low}")
            else:
                combos.append(f"{high}{low}s")
                combos.append(f"{high}{low}o")
    return combos


def combo_to_sample_hand(combo: str, rng) -> str:
    """Convertit une notation ('AKs') en deux cartes concrètes ('AsKh')."""
    high, low = combo[0], combo[1]
    suited = len(combo) == 3 and combo[2] == "s"
    suits = ["s", "h", "d", "c"]
    first_suit = suits[rng.randrange(4)]
    second_suit = (
        first_suit if suited else suits[(suits.index(first_suit) + rng.randrange(3) + 1) % 4]
    )
    return f"{high}{first_suit}{low}{second_suit}"


def monte_carlo_equity_vs_range(
    hole_cards: str,
    board: tuple[str, ...],
    *,
    samples: int,
    rng,
) -> float:
    """Équité MC d'une main précise contre une main aléatoire (approximation range)."""
    if not POKERKIT_AVAILABLE:
        return 0.5
    known = {hole_cards[i : i + 2] for i in range(0, len(hole_cards), 2)}
    known.update(board)
    remaining = [card for card in _DECK if card not in known]
    wins = 0.0
    runout_needed = 5 - len(board)

    for _ in range(samples):
        pool = remaining[:]
        villain_hole = pool.pop(rng.randrange(len(pool))) + pool.pop(rng.randrange(len(pool)))
        # Le runout doit être tiré, pas pris en tête de paquet : un board fixe
        # biaisait l'équité (72o « gagnait » 93 % sur un board 22233 commun).
        runout = "".join(
            pool.pop(rng.randrange(len(pool)))
            for _ in range(min(runout_needed, len(pool)))
        )
        full_board = "".join(board) + runout
        try:
            hero = StandardHighHand.from_game(hole_cards + full_board)
            villain = StandardHighHand.from_game(villain_hole + full_board)
        except Exception:
            continue
        if hero > villain:
            wins += 1.0
        elif hero == villain:
            wins += 0.5
    return wins / max(samples, 1)


@lru_cache(maxsize=512)
def _cached_combo_equity(combo: str, samples: int, seed: int) -> float:
    """Équité MC d'un combo contre une main aléatoire, stable et mise en cache."""
    from random import Random

    rng = Random(f"{seed}:{combo}")
    hand = combo_to_sample_hand(combo, rng)
    return monte_carlo_equity_vs_range(hand, (), samples=samples, rng=rng)


def _chart_ranges(context: str, position: str, heads_up: bool) -> tuple[str, str]:
    """(range de relance, range de call) du chart pour ce contexte/position."""
    from .preflop_ranges import PreflopManager

    manager = PreflopManager(heads_up=heads_up)
    base_context = context[3:] if context.startswith("hu_") else context
    position = manager.hu_position(position) if heads_up else position

    if base_context == "rfi":
        return manager.get_hero_range(position, facing_raise=False), ""
    if base_context == "vs_raise":
        return VS_RAISE_3BET_RANGE, manager.get_hero_range(position, facing_raise=True)
    return VS_3BET_RAISE_RANGE, VS_3BET_CALL_RANGE


def build_spot_solution(
    *,
    context: str,
    position: str,
    depth_bb: int,
    samples_per_combo: int = 24,
    seed: int = 0,
    heads_up: bool = False,
) -> dict[str, dict[str, float]]:
    """Construit {combo: {'raise', 'call', 'fold', 'ev'}} depuis les charts.

    L'action suit l'appartenance aux ranges de la position (RFI, 3-bet, défense
    BB / heads-up) : une vraie bande de call existe là où le chart en prévoit
    une. L'équité Monte-Carlo ne sert qu'à l'EV indicatif.
    """
    from .preflop_support import combo_in_range

    raise_range, call_range = _chart_ranges(context, position, heads_up)

    table: dict[str, dict[str, float]] = {}
    for combo in enumerate_combos():
        if combo_in_range(combo, raise_range):
            entry = {"raise": 1.0, "call": 0.0, "fold": 0.0}
        elif combo_in_range(combo, call_range):
            entry = {"raise": 0.0, "call": 1.0, "fold": 0.0}
        else:
            entry = {"raise": 0.0, "call": 0.0, "fold": 1.0}
        equity = (
            _cached_combo_equity(combo, samples_per_combo, seed)
            if samples_per_combo > 0
            else 0.5
        )
        entry["ev"] = round(equity * depth_bb / 2.0, 3)
        table[combo] = entry
    return table


class PreflopSolutionStore:
    """Cache disque + mémoire des stratégies préflop pré-calculées."""

    def __init__(self, path: str | os.PathLike[str] = DEFAULT_SOLUTIONS_PATH) -> None:
        self.path = Path(path)
        self._tables: dict[str, dict[str, dict[str, float]]] = {}
        self._load_started_at: float | None = None
        self._loaded = False

    @staticmethod
    def spot_key(context: str, position: str, depth_bb: float) -> str:
        bucket = min(DEPTH_BUCKETS, key=lambda d: abs(d - float(depth_bb)))
        return f"{context}_{position}_{bucket}"

    def ensure_loaded(self) -> bool:
        """Charge toutes les solutions du répertoire (lazy). Retourne True si dispo."""
        if self._loaded:
            return bool(self._tables)
        self._loaded = True
        self._load_started_at = time.perf_counter()
        if np is None or not self.path.exists():
            return False
        for file in sorted(self.path.glob("*.npz")):
            try:
                data = np.load(file, allow_pickle=False)
                keys = [str(k) for k in data["combos"]]
                values = data["values"].tolist()
                table = {
                    key: {
                        "raise": float(values[row][0]),
                        "call": float(values[row][1]),
                        "fold": float(values[row][2]),
                        "ev": float(values[row][3]),
                    }
                    for row, key in enumerate(keys)
                }
                name = file.stem
                context, position, bucket = name.rsplit("_", 2)
                self._tables[f"{context}_{position}_{bucket}"] = table
            except Exception as exc:  # pragma: no cover
                logger.warning("Solution préflop illisible (%s): %s", file.name, exc)
        logger.info(
            "PreflopSolutionStore: %d spots chargés depuis %s (%.1fms)",
            len(self._tables),
            self.path,
            (time.perf_counter() - (self._load_started_at or 0.0)) * 1000.0,
        )
        return bool(self._tables)

    def get_strategy(
        self, context: str, position: str, depth_bb: float
    ) -> dict[str, dict[str, float]] | None:
        self.ensure_loaded()
        return self._tables.get(self.spot_key(context, position, depth_bb))

    def decide(
        self,
        hero_combo: str,
        *,
        context: str,
        position: str,
        depth_bb: float,
        facing_raise: bool,
        aggressive_action: str | None,
        can_check: bool,
        sample_mixed: bool = False,
        rng=None,
    ) -> tuple[str | None, float | None, dict]:
        """Décision instantanée depuis la solution pré-calculée (None si spot absent).

        ``elapsed_ms`` ne compte que la décision ; le chargement disque initial
        (unique) est rapporté à part dans ``load_ms``.
        """
        load_started = time.perf_counter()
        strategy = self.get_strategy(context, position, depth_bb)
        load_ms = (time.perf_counter() - load_started) * 1000.0
        started = time.perf_counter()
        if strategy is None or hero_combo not in strategy:
            return None, None, {"backend": "preflop_precomputed", "available": False}

        entry = strategy[hero_combo]
        action_kind, frequency = self._sample(entry, sample_mixed, rng)

        chosen = self._map_action(
            action_kind,
            facing_raise=facing_raise,
            aggressive_action=aggressive_action,
            can_check=can_check,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metadata = {
            "backend": "preflop_precomputed",
            "available": True,
            "spot_key": self.spot_key(context, position, depth_bb),
            "hero_combo": hero_combo,
            "frequencies": {
                "raise": entry["raise"],
                "call": entry["call"],
                "fold": entry["fold"],
            },
            "ev": entry["ev"],
            "elapsed_ms": round(elapsed_ms, 3),
            "load_ms": round(load_ms, 3),
        }
        return chosen, None, metadata

    @staticmethod
    def _sample(entry: dict[str, float], sample_mixed: bool, rng) -> tuple[str, float]:
        options = [
            ("raise", entry.get("raise", 0.0)),
            ("call", entry.get("call", 0.0)),
            ("fold", entry.get("fold", 0.0)),
        ]
        if sample_mixed and rng is not None:
            total = sum(weight for _, weight in options)
            if total > 0:
                draw = rng.random() * total
                cumulative = 0.0
                for kind, weight in options:
                    cumulative += weight
                    if draw <= cumulative:
                        return kind, weight
        return max(options, key=lambda pair: pair[1])

    @staticmethod
    def _map_action(
        action_kind: str,
        *,
        facing_raise: bool,
        aggressive_action: str | None,
        can_check: bool,
    ) -> str | None:
        if action_kind == "raise":
            if facing_raise:
                return aggressive_action  # 3bet/4bet quand une action agressive existe
            return aggressive_action or ("BET" if aggressive_action is None else None)
        if action_kind == "call":
            if facing_raise:
                return "CALL"
            return "CHECK" if can_check else "CALL"
        # fold
        if facing_raise:
            return "FOLD"
        return "CHECK" if can_check else None

    def save_table(
        self, context: str, position: str, depth_bb: int, table: dict[str, dict[str, float]]
    ) -> Path:
        """Écrit une table compressée sur disque (usage générateur hors-ligne)."""
        if np is None:
            raise RuntimeError("numpy indisponible : impossible de sauvegarder les solutions")
        self.path.mkdir(parents=True, exist_ok=True)
        combos = sorted(table)
        values = [
            [
                table[combo].get("raise", 0.0),
                table[combo].get("call", 0.0),
                table[combo].get("fold", 0.0),
                table[combo].get("ev", 0.0),
            ]
            for combo in combos
        ]
        target = self.path / f"{self.spot_key(context, position, depth_bb)}.npz"
        np.savez_compressed(
            target,
            combos=np.array(combos),
            values=np.array(values, dtype=np.float32),
        )
        return target


def resolve_live_decision(
    hero_hand: str,
    *,
    context: str,
    depth_bb: float,
    pot: float,
    to_call: float,
    effective_stack: float,
    time_budget_ms: int = 800,
    seed: int = 0,
) -> dict:
    """Résolution live préflop : équité MC haute résolution dans un budget temps strict."""
    from random import Random

    started = time.perf_counter()
    rng = Random(seed)
    samples = 240
    equity = 0.5

    while samples >= 30:
        equity = monte_carlo_equity_vs_range(hero_hand, (), samples=samples, rng=rng)
        if (time.perf_counter() - started) * 1000.0 > time_budget_ms / 2:
            break
        samples += 120

    required_equity = to_call / max(pot + to_call, 1e-9) if to_call > 0 else 0.0
    spr = effective_stack / max(pot, 1e-9)
    aggression = {"rfi": 0.48, "vs_raise": 0.54, "vs_3bet": 0.60}.get(context, 0.52)
    aggression += max(0.0, (50.0 - min(depth_bb, 50.0))) / 250.0

    if equity >= aggression and spr > 1.2:
        action, amount = "RAISE", pot * 2.8
    elif equity >= max(required_equity + 0.02, 0.44 if context != "vs_3bet" else 0.50):
        action, amount = ("CALL", None)
    elif to_call <= 0:
        action, amount = "CHECK", None
    else:
        action, amount = "FOLD", None

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "chosen_action": action,
        "dynamic_amount": amount if action == "RAISE" else None,
        "equity": round(equity, 4),
        "samples": samples,
        "elapsed_ms": round(elapsed_ms, 2),
        "budget_respected": elapsed_ms <= time_budget_ms,
    }
