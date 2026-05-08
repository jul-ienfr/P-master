import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.vision.detector import PokerDetector, decode_card_token


def _load_image(path: Path) -> np.ndarray:
    payload = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(payload, cv2.IMREAD_COLOR)
    assert image is not None
    return image


def _paste(frame: np.ndarray, image: np.ndarray, x: int, y: int) -> None:
    height, width = image.shape[:2]
    frame[y:y + height, x:x + width] = image


def _resize(image: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-6:
        return image
    width = max(4, int(round(image.shape[1] * scale)))
    height = max(4, int(round(image.shape[0] * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(image, (width, height), interpolation=interpolation)


def _scaled(value: int, scale: float) -> int:
    return int(round(value * scale))


def _sorted_area_map(area_map):
    return [area_map[key] for key in sorted(area_map, key=lambda item: int(item) if str(item).isdigit() else str(item))]


def test_template_fallback_detects_table_hero_cards_and_buttons_without_yolo_model():
    manifest_path = ROOT / "poker" / "pokerstars-7-fr-6-max" / "draft" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset_root = manifest_path.parent
    table_data = manifest["table_data"]
    assets = manifest["assets"]
    anchor_offset = table_data.get("anchor_offset", {"x": 0, "y": 0})

    frame = np.zeros((1200, 1600, 3), dtype=np.uint8)
    frame[:] = (20, 30, 40)
    table_window_x = 120
    table_window_y = 90

    _paste(
        frame,
        _load_image(asset_root / assets["topleft_corner"]),
        table_window_x + anchor_offset["x"],
        table_window_y + anchor_offset["y"],
    )

    my_cards_area = table_data["my_cards_area"]
    board_area = table_data["table_cards_area"]
    left_card_area = table_data.get("left_card_area")
    right_card_area = table_data.get("right_card_area")
    board_card_areas = _sorted_area_map(table_data.get("board_card_areas", {}))
    buttons_area = table_data["buttons_search_area"]
    ah_image = _load_image(asset_root / assets["ah"])
    kd_image = _load_image(asset_root / assets["kd"])
    jh_image = _load_image(asset_root / assets["jh"])
    eight_h_image = _load_image(asset_root / assets["8h"])
    two_h_image = _load_image(asset_root / assets["2h"])

    _paste(
        frame,
        ah_image,
        table_window_x + (left_card_area["x1"] if left_card_area else my_cards_area["x1"] + 6) + 2,
        table_window_y + (left_card_area["y1"] if left_card_area else my_cards_area["y1"] + 3) + 3,
    )
    _paste(
        frame,
        kd_image,
        table_window_x + (right_card_area["x1"] if right_card_area else my_cards_area["x1"] + 6 + ah_image.shape[1] + 8) + 2,
        table_window_y + (right_card_area["y1"] if right_card_area else my_cards_area["y1"] + 3) + 3,
    )
    _paste(
        frame,
        _load_image(asset_root / assets["fold_button"]),
        table_window_x + buttons_area["x1"] + 18,
        table_window_y + buttons_area["y1"] + 8,
    )
    _paste(
        frame,
        _load_image(asset_root / assets["call_button"]),
        table_window_x + buttons_area["x1"] + 140,
        table_window_y + buttons_area["y1"] + 8,
    )
    _paste(
        frame,
        jh_image,
        table_window_x + (board_card_areas[0]["x1"] if board_card_areas else board_area["x1"] + 10) + 2,
        table_window_y + (board_card_areas[0]["y1"] if board_card_areas else board_area["y1"] + 4) + 2,
    )
    _paste(
        frame,
        eight_h_image,
        table_window_x + (board_card_areas[1]["x1"] if board_card_areas else board_area["x1"] + 78) + 2,
        table_window_y + (board_card_areas[1]["y1"] if board_card_areas else board_area["y1"] + 4) + 2,
    )
    _paste(
        frame,
        two_h_image,
        table_window_x + (board_card_areas[2]["x1"] if board_card_areas else board_area["x1"] + 146) + 2,
        table_window_y + (board_card_areas[2]["y1"] if board_card_areas else board_area["y1"] + 4) + 2,
    )

    detector = PokerDetector(model_path="models/definitely_missing.engine")
    state = detector.analyze_frame(frame)

    assert state.metadata["detector_mode"] == "template"
    assert state.metadata["table_detected"] is True
    assert state.metadata["fallback_preset"] == "PokerStars 7 FR 6-max"

    detected_cards = sorted(decode_card_token(card.class_name) for card in state.hero_cards)
    assert detected_cards == ["Ah", "Kd"]
    detected_board = sorted(decode_card_token(card.class_name) for card in state.board_cards)
    assert detected_board == ["2h", "8h", "Jh"]

    action_names = {button.class_name for button in state.action_buttons}
    assert "fold_button" in action_names
    assert "call_button" in action_names
    assert state.pots
    assert len(state.stacks) == 6
    assert len(state.player_names) == 6


def test_template_fallback_reads_real_pokerstars_capture_with_slot_calibration():
    detector = PokerDetector(model_path="models/definitely_missing.engine")
    frame = _load_image(ROOT / "POKERSTAR CAPTURE" / "2026-04-12_01.08.14,170.png")

    state = detector.analyze_frame(frame)

    assert state.metadata["detector_mode"] == "template"
    assert state.metadata["table_detected"] is True
    assert state.metadata["fallback_preset"] == "PokerStars 7 FR 6-max"
    assert state.metadata["topleft_anchor_asset"] == "topleft_corner"

    hero_cards = [decode_card_token(card.class_name) for card in state.hero_cards]
    board_cards = [decode_card_token(card.class_name) for card in state.board_cards]

    assert hero_cards == ["Tc", "5s"]
    assert board_cards == ["4h", "Jh", "As", "9s", "2s"]
    assert {button.class_name for button in state.action_buttons} == {"bet_button", "check_button"}


@pytest.mark.parametrize("scale", [0.8, 0.9, 1.2, 1.35])
def test_template_fallback_scales_with_window_size_variants(scale: float):
    manifest_path = ROOT / "poker" / "pokerstars-7-fr-6-max" / "draft" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset_root = manifest_path.parent
    table_data = manifest["table_data"]
    assets = manifest["assets"]
    anchor_name = "topleft_corner"
    anchor_offset = table_data.get("anchor_offsets", {}).get(anchor_name, table_data.get("anchor_offset", {"x": 0, "y": 0}))

    frame = np.zeros((_scaled(689, scale) + 70, _scaled(955, scale) + 60, 3), dtype=np.uint8)
    frame[:] = (20, 30, 40)
    table_window_x = 0
    table_window_y = 0

    _paste(
        frame,
        _resize(_load_image(asset_root / assets[anchor_name]), scale),
        table_window_x + _scaled(anchor_offset["x"], scale),
        table_window_y + _scaled(anchor_offset["y"], scale),
    )

    left_card_area = table_data["left_card_area"]
    right_card_area = table_data["right_card_area"]
    board_card_areas = _sorted_area_map(table_data["board_card_areas"])
    buttons_area = table_data["buttons_search_area"]

    ah_image = _resize(_load_image(asset_root / assets["ah"]), scale)
    kd_image = _resize(_load_image(asset_root / assets["kd"]), scale)
    jh_image = _resize(_load_image(asset_root / assets["jh"]), scale)
    eight_h_image = _resize(_load_image(asset_root / assets["8h"]), scale)
    two_h_image = _resize(_load_image(asset_root / assets["2h"]), scale)
    fold_button = _resize(_load_image(asset_root / assets["fold_button"]), scale)
    call_button = _resize(_load_image(asset_root / assets["call_button"]), scale)

    _paste(
        frame,
        ah_image,
        table_window_x + _scaled(left_card_area["x1"] + 2, scale),
        table_window_y + _scaled(left_card_area["y1"] + 3, scale),
    )
    _paste(
        frame,
        kd_image,
        table_window_x + _scaled(right_card_area["x1"] + 2, scale),
        table_window_y + _scaled(right_card_area["y1"] + 3, scale),
    )
    _paste(
        frame,
        fold_button,
        table_window_x + _scaled(buttons_area["x1"] + 18, scale),
        table_window_y + _scaled(buttons_area["y1"] + 8, scale),
    )
    _paste(
        frame,
        call_button,
        table_window_x + _scaled(buttons_area["x1"] + 140, scale),
        table_window_y + _scaled(buttons_area["y1"] + 8, scale),
    )
    _paste(
        frame,
        jh_image,
        table_window_x + _scaled(board_card_areas[0]["x1"] + 2, scale),
        table_window_y + _scaled(board_card_areas[0]["y1"] + 2, scale),
    )
    _paste(
        frame,
        eight_h_image,
        table_window_x + _scaled(board_card_areas[1]["x1"] + 2, scale),
        table_window_y + _scaled(board_card_areas[1]["y1"] + 2, scale),
    )
    _paste(
        frame,
        two_h_image,
        table_window_x + _scaled(board_card_areas[2]["x1"] + 2, scale),
        table_window_y + _scaled(board_card_areas[2]["y1"] + 2, scale),
    )

    detector = PokerDetector(model_path="models/definitely_missing.engine")
    state = detector.analyze_frame(frame)

    assert state.metadata["detector_mode"] == "template"
    assert state.metadata["table_detected"] is True
    assert state.metadata["fallback_preset"] == "PokerStars 7 FR 6-max"
    assert str(state.metadata["topleft_anchor_asset"]).startswith("topleft_corner")
    assert state.metadata["topleft_match_scale"] == pytest.approx(scale, abs=0.06)
    assert sorted(decode_card_token(card.class_name) for card in state.hero_cards) == ["Ah", "Kd"]
    assert sorted(decode_card_token(card.class_name) for card in state.board_cards) == ["2h", "8h", "Jh"]
    assert {button.class_name for button in state.action_buttons} == {"call_button", "fold_button"}


def test_template_fallback_accepts_strong_compact_anchor_match_inside_fullscreen_frame():
    manifest_path = ROOT / "poker" / "pokerstars-7-fr-6-max" / "draft" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset_root = manifest_path.parent
    compact_anchor = _load_image(asset_root / manifest["assets"]["topleft_corner_compact"])

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[:] = (18, 24, 32)
    _paste(frame, compact_anchor, 687, 201)

    detector = PokerDetector(model_path="models/definitely_missing.engine")
    state = detector.analyze_frame(frame)

    assert state.metadata["detector_mode"] == "template"
    assert state.metadata["table_detected"] is True
    assert state.metadata["fallback_preset"] == "PokerStars 7 FR 6-max"
    assert state.metadata["topleft_anchor_asset"] == "topleft_corner_compact"


def test_template_fallback_keeps_empty_board_slots_empty_on_preflop_capture():
    detector = PokerDetector(model_path="models/definitely_missing.engine")
    frame = _load_image(ROOT / "POKERSTAR CAPTURE" / "2026-04-12_01.07.20,983.png")

    state = detector.analyze_frame(frame)

    assert state.metadata["table_detected"] is True
    assert state.metadata["fallback_preset"] == "PokerStars 7 FR 6-max"
    assert [decode_card_token(card.class_name) for card in state.hero_cards] == ["Tc", "5s"]
    assert state.board_cards == []


def test_template_fallback_reads_evening_capture_with_updated_native_cards():
    detector = PokerDetector(model_path="models/definitely_missing.engine")
    frame = _load_image(ROOT / "POKERSTAR CAPTURE" / "2026-04-12_22.54.41,196.png")

    state = detector.analyze_frame(frame)

    assert state.metadata["table_detected"] is True
    assert state.metadata["fallback_preset"] == "PokerStars 7 FR 6-max"
    assert state.metadata["topleft_anchor_asset"] == "topleft_corner_live"
    assert [decode_card_token(card.class_name) for card in state.hero_cards] == ["Jh", "Tc"]
    assert [decode_card_token(card.class_name) for card in state.board_cards] == ["Jd", "Jc", "Th", "Td", "As"]
