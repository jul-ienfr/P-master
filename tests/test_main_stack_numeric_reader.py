import types

import numpy as np

from src.bot.runtime_types import CanonicalPlayer
from src.main import SuperBotController


def test_read_player_stack_uses_numeric_reader_and_preserves_metadata():
    controller = object.__new__(SuperBotController)
    controller.amount_ocr = types.SimpleNamespace(
        read_and_parse_amount=lambda crop: 2500.0,
        get_metadata=lambda: {
            "selected_engine": "rapidocr",
            "selected_text": "2 500",
            "selected_confidence": 0.9,
        },
    )
    controller.tracker = types.SimpleNamespace(sanity=None, players={})
    controller.numeric_reader = None
    controller._known_stack_fallback = SuperBotController._known_stack_fallback.__get__(controller, SuperBotController)

    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    value, metadata = SuperBotController._read_player_stack(
        controller,
        stack_crop=crop,
        seat_id="seat_1",
        cached_player=CanonicalPlayer(seat_id="seat_1", stack=3000.0),
    )

    assert value == 2500.0
    assert metadata["numeric_reader"]["selected_value"] == 2500.0
    assert metadata["numeric_reader"]["evidence"]["field_name"] == "stack"


def test_read_player_stack_keeps_previous_value_when_numeric_reader_quarantines_drop():
    controller = object.__new__(SuperBotController)
    controller.amount_ocr = types.SimpleNamespace(
        read_and_parse_amount=lambda crop: 100.0,
        get_metadata=lambda: {
            "selected_engine": "rapidocr",
            "selected_text": "100",
            "selected_confidence": 0.95,
        },
    )
    controller.tracker = types.SimpleNamespace(sanity=None, players={})
    controller.numeric_reader = None
    controller._known_stack_fallback = SuperBotController._known_stack_fallback.__get__(controller, SuperBotController)

    crop = np.zeros((20, 60, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    value, metadata = SuperBotController._read_player_stack(
        controller,
        stack_crop=crop,
        seat_id="seat_1",
        cached_player=CanonicalPlayer(seat_id="seat_1", stack=5000.0),
    )

    assert value == 5000.0
    assert metadata["numeric_reader"]["evidence"]["state"] == "quarantined"
    assert metadata["numeric_reader"]["evidence"]["rejection_reason"] == "implausible_pot_drop"
