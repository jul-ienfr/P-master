"""Tests de build_dynamic_coordinates et copy_table_state (table_geometry)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.models import DetectionResult, TableState
from src.vision.table_geometry import build_dynamic_coordinates, copy_table_state


def det(cls, x1, y1, x2, y2, confidence=0.9):
    return DetectionResult(class_name=cls, confidence=confidence, bbox=(x1, y1, x2, y2))


def test_build_dynamic_coordinates_prefers_detected_buttons():
    state = TableState(
        action_buttons=[
            det("fold_button", 100, 200, 140, 220),
            det("raise_button", 300, 200, 340, 220),
        ],
        metadata={},
    )
    fallback = {"FOLD": (1, 1), "CALL": (2, 2), "BET_BTN": (3, 3), "BET_BOX": (4, 4)}
    mapping, diagnostics = build_dynamic_coordinates(state, fallback)
    assert mapping["FOLD"] == (120, 210)
    assert mapping["BET_BTN"] == (320, 210)  # raise -> BET_BTN
    assert diagnostics["FOLD"]["source"] == "detected_button"
    assert diagnostics["FOLD"]["label"] == "fold_button"


def test_build_dynamic_coordinates_uses_slot_boxes_when_button_missing():
    state = TableState(
        action_buttons=[det("check_button", 150, 200, 170, 220)],
        metadata={
            "button_slot_boxes": {
                "BET_BOX": (400, 180, 500, 220),
                "FOLD": (10, 10, 50, 30),
            }
        },
    )
    fallback = {}
    mapping, diagnostics = build_dynamic_coordinates(state, fallback)
    # check_button est mappé sur CALL
    assert mapping["CALL"] == (160, 210)
    # FOLD absent des boutons détectés -> slot box
    assert mapping["FOLD"] == (30, 20)
    assert diagnostics["FOLD"]["source"] == "slot_box"
    # BET_BOX vient aussi du slot
    assert mapping["BET_BOX"] == (450, 200)


def test_build_dynamic_coordinates_falls_back_to_static_coords():
    state = TableState(metadata={})
    fallback = {"FOLD": (10, 10), "CALL": (20, 20)}
    mapping, diagnostics = build_dynamic_coordinates(state, fallback)
    assert mapping["FOLD"] == (10, 10)
    assert mapping["CALL"] == (20, 20)
    assert diagnostics["FOLD"]["source"] == "fallback"


def test_copy_table_state_deep_copies_pydantic_state():
    state = TableState(
        board_cards=[det("Ah", 0, 0, 5, 5)],
        metadata={"a": {"nested": True}},
    )
    copied = copy_table_state(state)
    assert copied is not state
    copied.metadata["a"]["nested"] = False
    assert state.metadata["a"]["nested"] is True
