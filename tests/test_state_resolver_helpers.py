# -*- coding: utf-8 -*-
"""Tests des helpers de résolution d'état (src/bot/state_resolver.py)."""
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.state_resolver import StateResolverMixin


def make_controller():
    class Controller(StateResolverMixin):
        def __init__(self):
            self._recent_runtime_streets = deque(maxlen=5)
            self._recent_runtime_hero_seat_ids = deque(maxlen=5)
            self._last_hero_seat_id = None
            self._last_good_runtime_hero_cards = ()
            self._last_good_runtime_hero_cards_at = 0.0

        def _extract_actionable_runtime_buttons(self, buttons):
            actionable = {"fold_button", "check_button", "call_button", "bet_button", "raise_button"}
            return tuple(b for b in buttons if b in actionable)

    return Controller()


def test_derive_street_stabilizes_transient_values():
    c = make_controller()
    assert c._derive_street(["As", "Kd", "7h"], ["Ah", "Kd"]) == "FLOP"
    # le lissage garde la dernière rue stable plutôt qu'un retour instantané
    assert c._derive_street([], []) == "FLOP"


def test_normalize_board_for_street_truncates_to_street_length():
    c = make_controller()
    assert c._normalize_board_for_street(("As", "Kd", "7h", "2c", "9s"), "PREFLOP") == ()
    assert len(c._normalize_board_for_street(("As", "Kd", "7h", "2c", "9s"), "TURN")) == 4
    assert len(c._normalize_board_for_street(("As", "Kd", "7h", "2c", "9s"), "RIVER")) == 5


def test_derive_hero_participation_mode_matrix():
    c = make_controller()
    base = dict(
        board=(),
        hero_cards=(),
        pot_value=0.0,
        action_buttons=(),
    )
    assert c._derive_hero_participation_mode((), (), 0.0, ()) == "idle"
    assert c._derive_hero_participation_mode((), (), 0.0, ("resume_hand",)) == "waiting_next_hand"
    assert c._derive_hero_participation_mode((), (), 0.0, ("im_back",)) == "sitting_out"
    assert c._derive_hero_participation_mode((), (), 0.0, ("bet_button",)) == "actionable_without_hero"
    assert c._derive_hero_participation_mode(("As",), (), 10.0, ()) == "observing_hand"
    assert c._derive_hero_participation_mode((), ("Ah", "Kd"), 0.0, ()) == "active_hand"


def test_derive_runtime_street_resets_to_idle_without_signal():
    c = make_controller()
    c._recent_runtime_streets.extend(["FLOP", "TURN"])
    assert c._derive_runtime_street((), (), ()) == "IDLE"
    assert list(c._recent_runtime_streets) == []

    street = c._derive_runtime_street(("As", "Kd", "7h"), ("Ah", "Kd"), ())
    assert street == "FLOP"


def test_resolve_action_coord_key_normalizes_names():
    assert StateResolverMixin._resolve_action_coord_key("fold") == "FOLD"
    # check/call partagent la même zone de clic
    assert StateResolverMixin._resolve_action_coord_key("check") == "CALL"
    assert StateResolverMixin._resolve_action_coord_key("bet_box") == "BET_BOX"
    assert StateResolverMixin._resolve_action_coord_key("raise") == "BET_BTN"


def test_stabilize_runtime_hero_cards_reuses_recent_cards_on_rank_flip(monkeypatch):
    c = make_controller()
    c._last_good_runtime_hero_cards = ("Ah", "Kd")
    c._last_good_runtime_hero_cards_at = 100.0
    c._runtime_hero_cards_ttl_s = 5.0
    c._format_log_cards = lambda cards: ",".join(cards)
    monkeypatch.setattr("src.bot.state_resolver.time.monotonic", lambda: 100.5)

    class _State:
        pots = []

    reused = c._stabilize_runtime_hero_cards(
        hero_cards=("Ah", "Qd"),
        board=("As", "Kd", "7h"),
        state=_State(),
    )
    assert reused == ("Ah", "Kd")

    # un changement de couleur n'est pas suspect : la nouvelle lecture est acceptée
    accepted = c._stabilize_runtime_hero_cards(
        hero_cards=("Ah", "Qs"),
        board=("As", "Kd", "7h"),
        state=_State(),
    )
    assert accepted == ("Ah", "Qs")
