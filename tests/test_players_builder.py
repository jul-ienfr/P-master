"""Tests du players builder extrait dans src/bot/players_builder.py."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.players_builder import PlayersBuilderMixin
from src.vision.models import DetectionResult, TableState


def make_controller(tracker_players=None):
    class Controller(PlayersBuilderMixin):
        def __init__(self):
            self.tracker = SimpleNamespace(players=tracker_players or {})

    return Controller()


def test_known_stack_fallback_prefers_cached_player_stack():
    c = make_controller()
    cached = SimpleNamespace(stack=2500.0)
    assert c._known_stack_fallback("seat_1", cached) == 2500.0


def test_known_stack_fallback_falls_back_to_tracker_then_zero():
    tracked = SimpleNamespace(current_stack=1800.0)
    c = make_controller({"seat_2": tracked})
    assert c._known_stack_fallback("seat_2", None) == 1800.0

    empty = make_controller({})
    assert empty._known_stack_fallback("missing", None) == 0.0


def test_build_stack_quarantine_metadata_shape():
    c = make_controller()
    meta = c._build_stack_quarantine_metadata("seat_3", 1200.0, 2.5)
    assert meta["field"] == "amount"
    assert meta["agreement"] == "quarantined"
    assert meta["seat_id"] == "seat_3"
    assert meta["selected_amount"] == 1200.0
    assert meta["skipped_due_to_quarantine"] is True
    assert meta["quarantine_remaining_s"] == 2.5

    meta_zero = c._build_stack_quarantine_metadata("seat_3", 0.0, -1.0)
    assert meta_zero["selected_amount"] is None
    assert meta_zero["quarantine_remaining_s"] == 0.0


def test_runtime_players_have_meaningful_stacks_rules():
    def p(seat, stack):
        return SimpleNamespace(seat_id=seat, stack=stack)
    assert PlayersBuilderMixin._runtime_players_have_meaningful_stacks([], "s1") is False
    two_small = [p("s1", 100), p("s2", 200)]
    assert PlayersBuilderMixin._runtime_players_have_meaningful_stacks(two_small, "s1") is True
    # moins de deux stacks positifs
    one_positive = [p("s1", 100), p("s2", 0)]
    assert PlayersBuilderMixin._runtime_players_have_meaningful_stacks(one_positive, "s1") is False
    # hero sans stack -> non significatif
    hero_busted = [p("s1", 0), p("s2", 300)]
    assert PlayersBuilderMixin._runtime_players_have_meaningful_stacks(hero_busted, "s1") is False


def test_refresh_cached_player_runtime_flags_recomputes_hero_and_button():
    state = TableState(
        dealer_button=DetectionResult(
            class_name="dealer_button", confidence=0.9, bbox=(500, 500, 520, 520)
        ),
    )
    players = (
        SimpleNamespace(
            seat_id="s1",
            seat_index=0,
            stack=100,
            name="hero",
            is_active=False,
            has_folded=True,
            is_hero=False,
            has_button=False,
            confidence=0.8,
            metadata={"stack_bbox": (480, 480, 510, 510)},
        ),
        SimpleNamespace(
            seat_id="s2",
            seat_index=1,
            stack=200,
            name="villain",
            is_active=True,
            has_folded=False,
            is_hero=True,
            has_button=True,
            confidence=0.7,
            metadata={},
        ),
    )
    refreshed = PlayersBuilderMixin._refresh_cached_player_runtime_flags(players, "s1", state)
    assert len(refreshed) == 2
    s1, s2 = refreshed
    assert s1.is_hero is True
    assert s1.has_button is True  # centre du stack proche du bouton
    assert s2.is_hero is False
    assert s2.has_button is False
    assert s2.has_folded is False


def test_refresh_cached_player_runtime_flags_empty():
    assert PlayersBuilderMixin._refresh_cached_player_runtime_flags((), "s1", TableState()) == ()


def test_player_detection_signature_is_order_sensitive():
    c = make_controller()
    stacks = [("s1", DetectionResult(class_name="stack", confidence=0.9, bbox=(0, 0, 10, 20)))]
    names = [DetectionResult(class_name="player_name", confidence=0.9, bbox=(30, 30, 90, 40))]
    state = TableState(player_names=names)
    sig_a = c._player_detection_signature(stacks, state)
    assert sig_a == c._player_detection_signature(list(reversed(stacks)) and stacks, state)

    moved = [("s1", DetectionResult(class_name="stack", confidence=0.9, bbox=(5, 5, 15, 25)))]
    assert c._player_detection_signature(moved, state) != sig_a


def test_ordered_stacks_by_table_geometry_maps_seat_ids():
    frame = np.zeros((600, 900, 3), dtype=np.uint8)
    c = make_controller()
    state = TableState(
        stacks=[
            DetectionResult(class_name="stack", confidence=0.9, bbox=(80, 80, 160, 120)),
            DetectionResult(class_name="stack", confidence=0.9, bbox=(700, 450, 800, 500)),
        ],
        pots=[DetectionResult(class_name="pot", confidence=0.9, bbox=(420, 280, 500, 310))],
    )
    ordered = c._ordered_stacks_by_table_geometry(state, frame)
    assert len(ordered) == 2
    seat_ids = {seat_id for seat_id, _det in ordered}
    assert all(seat_id.startswith("seat_") for seat_id in seat_ids)
    # les détections restent appariées à leur bbox d'origine
    assert {det.bbox for _seat_id, det in ordered} == {
        (80, 80, 160, 120),
        (700, 450, 800, 500),
    }
