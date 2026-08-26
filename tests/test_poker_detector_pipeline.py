# -*- coding: utf-8 -*-
"""Tests du pipeline analyze_frame (yolo -> opencv -> llm) et de la validation hybride."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.vision.detector as detector_module
from src.vision.detector import PokerDetector
from src.vision.models import DetectionResult, TableState


def make_detector(monkeypatch):
    monkeypatch.setattr(detector_module, "YOLO", None)
    detector = PokerDetector(model_path="models/absent.engine")
    return detector


def test_hybrid_validate_card_without_presets_returns_original(monkeypatch):
    detector = make_detector(monkeypatch)
    detector.fallback_detector = SimpleNamespace(presets=[])
    crop = np.zeros((20, 14, 3), dtype=np.uint8)
    assert detector._hybrid_validate_card(crop, "Ah") == "Ah"


def test_hybrid_validate_card_corrects_low_error_match(monkeypatch):
    detector = make_detector(monkeypatch)
    rng = np.random.default_rng(4)
    # coin de carte : zone claire contrastée, comme un vrai crop
    template = np.full((20, 14, 3), 30, dtype=np.uint8)
    template[2:8, 2:6] = 220
    detector.fallback_detector = SimpleNamespace(
        presets=[
            SimpleNamespace(card_templates={"Kh": template}),
            SimpleNamespace(card_templates={}),
        ]
    )
    crop = template.copy()
    assert detector._hybrid_validate_card(crop, "Ah") == "Kh"
    # crop très différent -> pas de correction
    noise_crop = np.full((20, 14, 3), 200, dtype=np.uint8)
    noise_crop[2:8, 8:13] = 0
    assert detector._hybrid_validate_card(noise_crop, "Qs") == "Qs"


def test_analyze_frame_stops_after_complete_yolo_detection(monkeypatch):
    detector = make_detector(monkeypatch)

    def box(cls_id, conf, bbox):
        return SimpleNamespace(cls=[cls_id], conf=[conf], xyxy=[[bbox[0], bbox[1], bbox[2], bbox[3]]])

    labels = ["Ah", "Kd", "fold_button", "call_button", "pot_area", "stack_area"]
    # les deux cartes hero en bas de frame (y1 > 58%) -> détection complète -> arrêt anticipé
    boxes = [
        box(0, 0.95, (10, 150, 18, 190)),
        box(1, 0.95, (60, 150, 68, 190)),
        box(2, 0.95, (120, 170, 140, 195)),
        box(3, 0.95, (180, 170, 200, 195)),
        box(4, 0.9, (220, 90, 260, 110)),
        box(5, 0.9, (300, 60, 340, 95)),
    ]
    result = SimpleNamespace(boxes=boxes)

    class FakeModel:
        names = {i: name for i, name in enumerate(labels)}

        def predict(self, source, conf, verbose, half):
            return [result]

    detector.model = FakeModel()
    detector.names = FakeModel.names
    detector.pipeline = ["yolo", "opencv", "llm"]
    detector.ai_fallback = None

    opencv_called = []
    detector._run_template_fallback = lambda frame: opencv_called.append(1) or TableState()

    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    state = detector.analyze_frame(frame, conf_threshold=0.6)
    assert state.metadata["table_detected"] is True
    assert len(state.hero_cards) == 2  # les deux cartes en bas de frame
    assert len(state.board_cards) == 0
    assert not opencv_called  # arrêt anticipé : pas d'étape opencv


def test_analyze_frame_fills_gaps_from_opencv_fallback(monkeypatch, tmp_path):
    import os

    monkeypatch.chdir(tmp_path)
    detector = make_detector(monkeypatch)
    detector.model = None
    detector.pipeline = ["yolo", "opencv", "llm"]
    detector.ai_fallback = None

    fallback_state = TableState(metadata={"detector_mode": "template", "table_detected": True})
    fallback_state.hero_cards = [DetectionResult(class_name="Qh", confidence=0.9, bbox=(10, 150, 30, 190))]
    fallback_state.board_cards = [DetectionResult(class_name="2c", confidence=0.9, bbox=(50, 40, 70, 80))]
    fallback_state.action_buttons = [DetectionResult(class_name="fold_button", confidence=0.9, bbox=(200, 170, 240, 195))]
    fallback_state.pots = [DetectionResult(class_name="pot_area", confidence=0.9, bbox=(180, 90, 220, 110))]
    fallback_state.stacks = [DetectionResult(class_name="stack_area", confidence=0.9, bbox=(20, 60, 60, 90))]
    fallback_state.player_names = [DetectionResult(class_name="player_name_area", confidence=0.9, bbox=(15, 95, 75, 105))]
    fallback_state.dealer_button = DetectionResult(class_name="dealer_button", confidence=0.9, bbox=(120, 130, 132, 142))
    detector._run_template_fallback = lambda frame: fallback_state
    # available() doit répondre True pour déclencher l'étape opencv
    detector.fallback_detector = SimpleNamespace(available=lambda: True, presets=[])

    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    state = detector.analyze_frame(frame)
    assert state.metadata["table_detected"] is True
    assert state.metadata["detector_mode"] == "template"
    assert len(state.hero_cards) == 1
    assert len(state.action_buttons) == 1
    assert len(state.stacks) == 1
    assert len(state.player_names) == 1
    assert state.dealer_button is not None
    # sauvegarde active learning écrite
    saved = list((tmp_path / "dataset" / "needs_annotation").glob("al_openvl_*.jpg"))
    assert saved


def test_analyze_frame_llm_step_resolves_hero_cards(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    detector = make_detector(monkeypatch)
    detector.model = None
    detector.pipeline = ["yolo", "opencv", "llm"]

    class FakeAI:
        def ask_ai_with_fallbacks(self, image_path, width, height, frame=None):
            return [
                {"class": "7h", "xmin": 100, "ymin": 150, "xmax": 130, "ymax": 195},
                {"class": "board_only", "xmin": 10, "ymin": 10, "xmax": 30, "ymax": 50},
                {"class": "Ks", "xmin": 140, "ymin": 150, "xmax": 165, "ymax": 195},
            ]

        def convert_to_yolo_format(self, boxes, width, height):
            return ""

    detector.ai_fallback = FakeAI()
    # pipeline explicite : opencv doit détecter la table AVANT l'étape LLM
    detector.pipeline = ["yolo", "opencv", "llm"]
    # le LLM n'est interrogé que si une étape précédente a détecté la table
    # ET que le layout de boutons est actionable (fold + une action)
    fallback_state = TableState(metadata={"detector_mode": "template", "table_detected": True})
    fallback_state.action_buttons = [
        DetectionResult(class_name="fold_button", confidence=0.9, bbox=(200, 170, 240, 195)),
        DetectionResult(class_name="call_button", confidence=0.9, bbox=(250, 170, 290, 195)),
    ]
    fallback_state.pots = [DetectionResult(class_name="pot_area", confidence=0.9, bbox=(180, 90, 220, 110))]
    detector._run_template_fallback = lambda frame: fallback_state
    detector.fallback_detector = SimpleNamespace(available=lambda: True, presets=[])

    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    state = detector.analyze_frame(frame)
    hero_labels = sorted(card.class_name for card in state.hero_cards)
    # deux cartes basses validées par le LLM ; la classe non-carte est ignorée
    assert hero_labels == ["7h", "Ks"]
    assert state.metadata["table_detected"] is True


def test_run_yolo_detection_empty_results_returns_early(monkeypatch):
    detector = make_detector(monkeypatch)

    class FakeModel:
        names = {}

        def predict(self, source, conf, verbose, half):
            return []

    detector.model = FakeModel()
    detector.names = FakeModel.names
    state = detector._run_yolo_detection(np.zeros((10, 10, 3), dtype=np.uint8), 0.5)
    assert state.metadata["detector_mode"] == "yolo"
    assert state.hero_cards == []
