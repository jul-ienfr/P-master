"""Tests de PokerDetector (src/vision/detector.py) avec modèle YOLO factice."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.vision.detector as detector_module
from src.vision.detector import PokerDetector
from src.vision.models import DetectionResult, TableState


def make_detector(monkeypatch, yolo_available=True, model_path="models/missing.engine"):
    if yolo_available:
        monkeypatch.setattr(detector_module, "YOLO", lambda path, task=None: SimpleNamespace(names={}))
    else:
        monkeypatch.setattr(detector_module, "YOLO", None)
    return PokerDetector(model_path=model_path)


class FakeBox:
    def __init__(self, cls_id, conf, bbox):
        self.cls = [cls_id]
        self.conf = [conf]
        self.xyxy = [list(bbox)]


def stub_model_with_boxes(detector, boxes_by_frame):
    """Remplace le modèle YOLO par un stub qui renvoie des boîtes figées."""

    class FakeModel:
        _labels = ["Ah", "Kd", "fold_button", "call_button", "pot_area", "stack_area", "player_name_area", "dealer_button"]
        names = dict(enumerate(_labels))

        def predict(self, source, conf, verbose, half):
            return boxes_by_frame

    detector.model = FakeModel()
    detector.names = FakeModel.names
    return detector


def test_analyze_frame_none_returns_empty_state():
    detector = PokerDetector.__new__(PokerDetector)
    state = detector.analyze_frame(None)
    assert state.metadata["detector_mode"] == "none"


def test_init_without_yolo_keeps_template_backend(monkeypatch):
    detector = make_detector(monkeypatch, yolo_available=False)
    assert detector.model is None
    assert detector.fallback_detector is not None


def test_init_without_model_file_keeps_template_backend(monkeypatch):
    detector = make_detector(monkeypatch, yolo_available=True, model_path="models/absent.engine")
    assert detector.model is None


def test_has_meaningful_signal_and_button_layout():
    empty = TableState()
    assert PokerDetector._has_meaningful_signal(empty) is False
    with_buttons = TableState(action_buttons=[DetectionResult(class_name="fold_button", confidence=0.9, bbox=(0, 0, 5, 5))])
    assert PokerDetector._has_meaningful_signal(with_buttons) is True
    fold_only = TableState(action_buttons=[DetectionResult(class_name="fold_button", confidence=0.9, bbox=(0, 0, 5, 5))])
    assert PokerDetector._has_actionable_button_layout(fold_only.action_buttons) is False
    both = TableState(
        action_buttons=[
            DetectionResult(class_name="fold_button", confidence=0.9, bbox=(0, 0, 5, 5)),
            DetectionResult(class_name="call_button", confidence=0.9, bbox=(10, 0, 15, 5)),
        ]
    )
    assert PokerDetector._has_actionable_button_layout(both.action_buttons) is True


def test_should_query_llm_for_hero_rules():
    detector = PokerDetector.__new__(PokerDetector)
    table_detected = {"table_detected": True}
    hero_pair = TableState(hero_cards=[DetectionResult(class_name="Ah", confidence=0.9, bbox=(0, 0, 4, 6)), DetectionResult(class_name="Kd", confidence=0.9, bbox=(8, 0, 12, 6))], metadata=table_detected)
    assert detector._should_query_llm_for_hero(hero_pair) is False  # déjà 2 cartes résolues
    one_card = TableState(hero_cards=[DetectionResult(class_name="Ah", confidence=0.9, bbox=(0, 0, 4, 6))], metadata=table_detected)
    assert detector._should_query_llm_for_hero(one_card) is True
    no_table = TableState(hero_cards=[DetectionResult(class_name="Ah", confidence=0.9, bbox=(0, 0, 4, 6))], metadata={})
    assert detector._should_query_llm_for_hero(no_table) is False


def test_run_yolo_detection_maps_classes_to_state(tmp_path, monkeypatch):
    detector = PokerDetector.__new__(PokerDetector)
    frame = np.zeros((200, 400, 3), dtype=np.uint8)

    def box(cls_id, conf, bbox):
        return SimpleNamespace(cls=[cls_id], conf=[conf], xyxy=[[bbox[0], bbox[1], bbox[2], bbox[3]]])

    # indices : 0=Ah 1=Kd 2=fold 3=call 4=pot 5=stack 6=name 7=dealer
    result = SimpleNamespace(
        boxes=[
            box(0, 0.95, (50, 150, 70, 190)),   # Ah bas -> hero
            box(1, 0.95, (90, 40, 110, 80)),    # Kd haut -> board
            box(2, 0.9, (250, 170, 280, 195)),  # fold_button
            box(3, 0.9, (300, 170, 330, 195)),  # call_button
            box(4, 0.8, (180, 100, 220, 120)),  # pot_area
            box(5, 0.8, (20, 60, 60, 90)),      # stack_area
            box(6, 0.7, (10, 95, 70, 105)),     # player_name_area
            box(7, 0.85, (200, 130, 210, 140)), # dealer_button
        ]
    )
    stub_model_with_boxes(detector, [result])
    state = detector._run_yolo_detection(frame, 0.6)
    assert len(state.hero_cards) == 1 and state.hero_cards[0].class_name == "Ah"
    assert len(state.board_cards) == 1 and state.board_cards[0].class_name == "Kd"
    assert {b.class_name for b in state.action_buttons} == {"fold_button", "call_button"}
    assert len(state.pots) == 1 and len(state.stacks) == 1 and len(state.player_names) == 1
    assert state.dealer_button is not None
    assert state.metadata["detector_mode"] == "yolo"


def test_run_yolo_drops_low_confidence_non_card(tmp_path, monkeypatch):
    detector = PokerDetector.__new__(PokerDetector)
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    result = SimpleNamespace(
        boxes=[SimpleNamespace(cls=[2], conf=[0.3], xyxy=[[0, 0, 10, 10]])]
    )
    stub_model_with_boxes(detector, [result])
    state = detector._run_yolo_detection(frame, 0.6)
    assert state.action_buttons == []


def test_hybrid_validate_card_requires_presets():
    detector = PokerDetector.__new__(PokerDetector)
    detector.fallback_detector = SimpleNamespace(presets=[])
    crop = np.full((30, 20, 3), 128, dtype=np.uint8)
    assert detector._hybrid_validate_card(crop, "Ah") == "Ah"


def test_draw_debug_frame_annotates_copy():
    detector = PokerDetector.__new__(PokerDetector)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    state = TableState(
        board_cards=[DetectionResult(class_name="Ah", confidence=0.9, bbox=(10, 10, 30, 30))],
        dealer_button=DetectionResult(class_name="dealer_button", confidence=0.8, bbox=(50, 50, 60, 60)),
        metadata={"fallback_preset": "stars"},
    )
    debug = detector.draw_debug_frame(frame, state)
    assert debug is not frame
    assert debug.shape == frame.shape
