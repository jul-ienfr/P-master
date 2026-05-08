import numpy as np

from src.bot.decision_maker import _normalize_hero_hand_string
from src.main import SuperBotController
from src.vision.detector import DetectionResult, TableState


def _make_controller():
    controller = object.__new__(SuperBotController)
    controller.ocr = type("DummyOCR", (), {"read_text": lambda self, image: ""})()
    return controller


def test_classify_action_button_label_uses_ocr_keywords():
    controller = _make_controller()
    controller._read_action_button_text = lambda crop: "suivre"

    assert controller._classify_action_button_label(np.zeros((8, 8, 3), dtype=np.uint8), 1, 3) == "call_button"


def test_classify_action_button_label_falls_back_to_geometry_for_two_buttons():
    controller = _make_controller()
    controller._read_action_button_text = lambda crop: ""

    assert controller._classify_action_button_label(np.zeros((8, 8, 3), dtype=np.uint8), 0, 2) == "check_button"
    assert controller._classify_action_button_label(np.zeros((8, 8, 3), dtype=np.uint8), 1, 2) == "bet_button"


def test_label_generic_action_buttons_relabels_and_sorts_buttons():
    controller = _make_controller()
    controller._classify_action_button_label = (
        lambda crop, index, count: "check_button" if index == 0 else "bet_button"
    )

    state = TableState(
        action_buttons=[
            DetectionResult(class_name="action_button_generic", confidence=0.9, bbox=(400, 700, 560, 790)),
            DetectionResult(class_name="action_button_generic", confidence=0.9, bbox=(180, 700, 340, 790)),
        ],
        metadata={},
    )
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    labeled_state = controller._label_generic_action_buttons(state, frame)

    assert [button.class_name for button in labeled_state.action_buttons] == ["bet_button", "check_button"]


def test_normalize_hero_hand_string_orders_cards_for_solver():
    assert _normalize_hero_hand_string("3h6d") == "6d3h"
    assert _normalize_hero_hand_string("KdQc") == "KdQc"


def test_stabilize_runtime_hero_cards_reuses_recent_cards_when_live_context_exists():
    controller = _make_controller()
    controller._last_good_runtime_hero_cards = ("Jd", "Td")
    controller._last_good_runtime_hero_cards_at = 10_000.0
    controller._runtime_hero_cards_ttl_s = 2.0

    import time as _time
    original_monotonic = _time.monotonic
    _time.monotonic = lambda: 10_001.0
    try:
        state = TableState(
            action_buttons=[DetectionResult(class_name="check_button", confidence=0.9, bbox=(0, 0, 10, 10))],
            metadata={"table_detected": True},
        )
        assert controller._stabilize_runtime_hero_cards((), ("7d", "2h", "Ad"), state) == ("Jd", "Td")
    finally:
        _time.monotonic = original_monotonic
