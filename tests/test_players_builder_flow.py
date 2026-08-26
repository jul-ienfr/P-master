"""Tests du chemin complet _build_players : cache, placeholders, OCR."""
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
    def read_name(self, seat_id, crop, seat_cache):
        return SimpleNamespace(
            selected_name=f"Name_{seat_id}",
            resolution_source="ocr",
            metadata={"raw_text": f"Name_{seat_id}"},
            evidence=FakeEvidence(),
        )


def make_controller(numeric_value=1000.0):
    class Shim(PlayersBuilderMixin):
        _center = staticmethod(detection_center)
        _safe_crop = staticmethod(safe_crop)

    c = Shim()
    c.frame = np.full((400, 600, 3), 60, dtype=np.uint8)
    c.tracker = SimpleNamespace(players={})
    c.tracker.sanity = None
    c.numeric_reader = FakeNumericReader(numeric_value)
    c.amount_ocr = SimpleNamespace(get_metadata=lambda: {"engine": "stub"})
    c.player_name_reader = FakeNameReader()
    c._last_valid_player_names_by_seat = {}
    c.last_tracker_snapshot = {"hero_seat_id": ""}
    c._last_hero_seat_id = None
    c._recent_runtime_hero_seat_ids = []
    c._cached_runtime_players = ()
    c._cached_runtime_players_signature = None
    c._cached_runtime_players_at = 0.0
    c._player_ocr_refresh_interval_s = 5.0

    class IdentityState:
        def update(self, seat_id, name, source):
            return {"seat_id": seat_id}

    c.player_identity_state = IdentityState()
    return c


def state_with(buttons=(), reused=False):
    return TableState(
        stacks=[
            DetectionResult(class_name="stack_area", confidence=0.9, bbox=(60, 300, 120, 340)),
            DetectionResult(class_name="stack_area", confidence=0.9, bbox=(420, 300, 480, 340)),
        ],
        player_names=[
            DetectionResult(class_name="player_name_area", confidence=0.8, bbox=(55, 345, 130, 360)),
            DetectionResult(class_name="player_name_area", confidence=0.8, bbox=(415, 345, 490, 360)),
        ],
        pots=[DetectionResult(class_name="pot_area", confidence=0.9, bbox=(280, 150, 330, 170))],
        action_buttons=list(buttons),
        metadata={"reused_visual_state": reused},
    )


def test_build_players_returns_empty_without_stacks(make=None):
    c = make_controller()
    assert c._build_players(TableState(), c.frame) == []


def test_build_players_full_ocr_path_caches_result():
    c = make_controller()
    players = c._build_players(state_with(), c.frame)
    assert len(players) == 2
    assert players[0].name.startswith("Name_")
    assert players[1].stack == 1000.0
    assert c._cached_runtime_players == tuple(players)

    # second appel sans boutons mais dans l'intervalle de refresh -> cache réutilisé
    second = c._build_players(state_with(), c.frame)
    assert [p.seat_id for p in second] == [p.seat_id for p in players]
    assert second[0] is not None


def test_build_players_responsive_path_uses_quick_pairing_when_no_meaningful_stacks():
    c = make_controller(numeric_value=None)
    buttons = [
        DetectionResult(class_name="fold_button", confidence=0.9, bbox=(250, 350, 280, 370)),
        DetectionResult(class_name="call_button", confidence=0.9, bbox=(300, 350, 330, 370)),
    ]
    players = c._build_players(state_with(buttons=buttons), c.frame)
    assert len(players) == 2
    assert all(p.metadata.get("responsive_stack_seed") for p in players)


def test_build_players_placeholder_path_with_meaningful_cached_stacks():
    c = make_controller()

    def cached_player(seat, stack):
        return CanonicalPlayer(
            seat_id=seat,
            seat_index=0,
            stack=stack,
            name=f"Cached{seat}",
            is_active=True,
            has_folded=False,
            is_hero=False,
            has_button=False,
            confidence=0.85,
            metadata={"old_key": 1},
        )

    # trois joueurs en cache avec des stacks significatifs
    c._cached_runtime_players = (
        cached_player("seat_1", 5000.0),
        cached_player("seat_2", 4000.0),
        cached_player("seat_9", 300.0),
    )
    # nombre de stacks détectés différent -> pas de réutilisation directe du cache ;
    # boutons visibles + stacks significatifs -> chemin placeholder
    state = state_with(
        buttons=[DetectionResult(class_name="fold_button", confidence=0.9, bbox=(0, 0, 10, 10))]
    )
    players = c._build_players(state, c.frame)
    assert len(players) == 2
    placeholders = [p for p in players if p.metadata.get("placeholder_runtime_player")]
    assert len(placeholders) == 2
