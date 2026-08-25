# -*- coding: utf-8 -*-
"""Tests du chemin OCR complet du players builder (_pair_stack_and_name, _build_players)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.players_builder import PlayersBuilderMixin
from src.bot.runtime_types import CanonicalPlayer
from src.vision.models import DetectionResult, TableState
from src.vision.table_geometry import detection_center, safe_crop


class FakeEvidence:
    def to_dict(self):
        return {"engine": "stub"}


class FakeNumericReader:
    def __init__(self, value):
        self.value = value

    def read_amount(self, field, crop, previous_value=None):
        return SimpleNamespace(
            selected_value=self.value,
            evidence=FakeEvidence(),
            metadata={"previous": previous_value},
        )


class FakeNameReader:
    def __init__(self, name):
        self.name = name

    def read_name(self, seat_id, crop, seat_cache):
        return SimpleNamespace(
            selected_name=self.name,
            resolution_source="ocr",
            metadata={"ocr": {"text": self.name}, "raw_text": self.name},
            evidence=FakeEvidence(),
        )


def make_controller(numeric_value=2500.0, player_name="Villain1"):
    class Shim(PlayersBuilderMixin):
        _center = staticmethod(detection_center)
        _safe_crop = staticmethod(safe_crop)

    controller = Shim()
    frame = np.zeros((600, 900, 3), dtype=np.uint8)
    controller.frame = frame
    controller.tracker = SimpleNamespace(players={})
    controller.tracker.sanity = None
    controller.numeric_reader = FakeNumericReader(numeric_value)
    controller.amount_ocr = SimpleNamespace(get_metadata=lambda: {"engine": "stub"})
    controller.player_name_reader = FakeNameReader(player_name)
    controller._last_valid_player_names_by_seat = {}
    controller._last_tracker_snapshot = {}
    controller.last_tracker_snapshot = {}

    class IdentityState:
        def update(self, seat_id, name, source):
            return {"seat_id": seat_id, "name": name, "source": source}

    controller.player_identity_state = IdentityState()
    return controller


def stack_det(x, y):
    return DetectionResult(class_name="stack", confidence=0.9, bbox=(x, y, x + 60, y + 30))


def test_pair_stack_and_name_builds_canonical_player():
    c = make_controller()
    state = TableState(
        player_names=[DetectionResult(class_name="player_name", confidence=0.8, bbox=(70, 10, 160, 25))],
        dealer_button=DetectionResult(class_name="dealer_button", confidence=0.9, bbox=(75, 15, 95, 25)),
    )
    player = c._pair_stack_and_name(
        stack_det(0, 0),
        state,
        c.frame,
        seat_index=0,
        seat_id="seat_1",
        is_hero=True,
    )
    assert isinstance(player, CanonicalPlayer)
    assert player.seat_id == "seat_1"
    assert player.stack == 2500.0
    assert player.name == "Villain1"
    assert player.is_hero is True
    assert player.has_button is True  # bouton proche du centre du stack
    assert player.metadata["stack_bbox"] == [0, 0, 60, 30]
    assert player.metadata["name_ocr"]["resolved_text"] == "Villain1"


def test_pair_stack_quick_seeds_from_cached_player_and_seat_cache():
    c = make_controller()
    c.numeric_reader = FakeNumericReader(None)  # lecture OCR impossible
    c._last_valid_player_names_by_seat = {"seat_2": "CachedName"}
    cached = CanonicalPlayer(
        seat_id="seat_2",
        seat_index=0,
        stack=900.0,
        name="CachedName",
        is_active=True,
        has_folded=False,
        is_hero=False,
        has_button=False,
        confidence=0.7,
        metadata={"old": True},
    )
    state = TableState()
    player = c._pair_stack_quick(
        stack_det(100, 100),
        state,
        c.frame,
        seat_index=0,
        seat_id="seat_2",
        is_hero=False,
        cached_player=cached,
    )
    assert player.stack == 900.0  # valeur cache conservée quand l'OCR échoue
    assert player.name == "CachedName"
    assert player.metadata["responsive_stack_seed"] is True
    assert player.metadata["stack_bbox"] == [100, 100, 160, 130]


def test_read_player_stack_quarantine_returns_known_fallback():
    c = make_controller(numeric_value=None)
    tracked = SimpleNamespace(current_stack=1750.0)
    c.tracker = SimpleNamespace(players={"seat_5": tracked}, sanity=SimpleNamespace(
        is_stack_read_quarantined=lambda seat: True,
        get_stack_read_quarantine_remaining=lambda seat: 3.0,
    ))
    value, meta = c._read_player_stack(np.zeros((20, 40, 3), dtype=np.uint8), "seat_5")
    assert value == 1750.0
    assert meta["skipped_due_to_quarantine"] is True

    # crop absent -> pas de lecture du tout
    value_none, meta_empty = c._read_player_stack(None, "seat_5")
    assert value_none is None and meta_empty == {}
