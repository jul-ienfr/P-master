"""Tests de l'annotateur automatique LLM (src/vision/auto_annotator.py)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.auto_annotator import AutoAnnotator


def test_convert_to_yolo_format_normalizes_and_filters():
    annotator = AutoAnnotator(providers=[])
    boxes = [
        {"class": "fold_button", "xmin": 0, "ymin": 0, "xmax": 100, "ymax": 50},
        {"class": "unknown_class", "xmin": 0, "ymin": 0, "xmax": 10, "ymax": 10},
        {"class": "call_button", "xmin": "bad", "ymin": 0, "xmax": 5, "ymax": 5},
    ]
    yolo = annotator.convert_to_yolo_format(boxes, 200, 100)
    lines = yolo.splitlines()
    assert len(lines) == 1  # classe inconnue + coords invalides filtrées
    cls_id, x_center, y_center, w, h = lines[0].split(" ")
    assert float(x_center) == pytest.approx(0.25)
    assert float(y_center) == pytest.approx(0.25)
    assert float(w) == pytest.approx(0.5)
    assert float(h) == pytest.approx(0.5)


def test_ask_ai_with_fallbacks_skips_remote_provider_without_key():
    annotator = AutoAnnotator(
        providers=[{"base_url": "https://api.openai.com/v1", "model": "gpt-4o", "api_key": ""}]
    )
    assert annotator.ask_ai_with_fallbacks("img.jpg", 800, 600) == []


def test_ask_ai_with_fallbacks_uses_first_working_provider(monkeypatch):
    annotator = AutoAnnotator(
        providers=[
            {"base_url": "", "model": "bad-model", "api_key": ""},
            {"base_url": "http://127.0.0.1:9/v1", "model": "local-vision", "api_key": ""},
        ]
    )
    calls = []

    def fake_single(client, model, image_path, width, height, frame=None):
        calls.append(model)
        if model == "bad-model":
            raise RuntimeError("down")
        return [{"class": "pot_area", "xmin": 1, "ymin": 2, "xmax": 3, "ymax": 4}]

    monkeypatch.setattr(AutoAnnotator, "_ask_single_ai", staticmethod(fake_single))
    monkeypatch.setattr("src.vision.auto_annotator.OpenAI", lambda api_key, base_url: SimpleNamespace(base_url=SimpleNamespace(host="127.0.0.1")))
    boxes = annotator.ask_ai_with_fallbacks("unused.jpg", 800, 600)
    assert boxes and boxes[0]["class"] == "pot_area"
    # le premier fournisseur distant sans clé est ignoré d'office
    assert calls == ["local-vision"]


def test_ask_single_ai_parses_markdown_wrapped_json(monkeypatch):
    annotator = AutoAnnotator(providers=[{"api_key": "k"}])
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"boxes": [{"class": "Ah", "xmin": 1}]}\n```'))]
    )
    captured = {}

    class FakeCompletions:
        def create(self, **params):
            captured["params"] = params
            return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
        base_url=SimpleNamespace(host="127.0.0.1"),
    )
    monkeypatch.setattr(annotator, "encode_image_frame", lambda frame: "ZmFrZQ==")
    boxes = annotator._ask_single_ai(
        client, "gpt-4o", "img.jpg", 800, 600, frame=np.zeros((4, 4, 3), dtype=np.uint8)
    )
    assert boxes == [{"class": "Ah", "xmin": 1}]
    # base locale : pas de response_format json_object
    assert "response_format" not in captured["params"]


def test_ask_single_ai_falls_back_to_first_list_value(monkeypatch):
    annotator = AutoAnnotator(providers=[{"api_key": "k"}])
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"detections": [{"class": "Kd"}]})))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **params: response)
        ),
        base_url=None,
    )
    monkeypatch.setattr(annotator, "encode_image", lambda path: "cGljdA==")
    boxes = annotator._ask_single_ai(client, "m", "img.jpg", 800, 600)
    assert boxes == [{"class": "Kd"}]


def test_process_dataset_annotates_missing_labels_only(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    labels_dir = tmp_path / "labels"
    raw_dir.mkdir()
    labels_dir.mkdir()
    # image déjà annotée : ignorée ; image à annoter : traitée ; fichier non-image : ignoré
    (raw_dir / "done.jpg").write_bytes(b"x")
    (labels_dir / "done.txt").write_text("0 0 0 0 0", encoding="utf-8")
    (raw_dir / "todo.png").write_bytes(b"x")
    (raw_dir / "notes.txt").write_bytes(b"x")

    import cv2

    monkeypatch.setattr(
        cv2, "imread", lambda path: np.zeros((60, 120, 3), dtype=np.uint8)
    )
    annotator = AutoAnnotator(providers=[{"api_key": "k", "base_url": "http://127.0.0.1:9"}])
    monkeypatch.setattr(
        annotator,
        "ask_ai_with_fallbacks",
        lambda img_path, width, height: [
            {"class": "stack_area", "xmin": 0, "ymin": 0, "xmax": 30, "ymax": 30}
        ],
    )
    annotator.process_dataset(raw_dir=str(raw_dir), labels_dir=str(labels_dir))

    written = labels_dir / "todo.txt"
    assert written.is_file()
    content = written.read_text(encoding="utf-8")
    assert content.startswith(f"{__import__('src.vision.yolo_schema', fromlist=['YOLO_CLASS_MAP']).YOLO_CLASS_MAP['stack_area']} ")


def test_process_dataset_noop_without_providers(tmp_path):
    annotator = AutoAnnotator(providers=[])
    annotator.process_dataset(raw_dir=str(tmp_path), labels_dir=str(tmp_path / "l"))
    assert not (tmp_path / "l").exists()
