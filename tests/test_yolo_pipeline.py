from pathlib import Path

from src.vision.detector import DetectionResult, resolve_model_path
from src.vision.yolo_schema import YOLO_CLASS_MAP, YOLO_CLASS_NAMES, validate_dataset_yaml_schema, write_dataset_yaml
import pytest

from scripts.bootstrap_yolo_labels_from_template import state_to_yolo_lines
from scripts.train_yolo_detector import resolve_training_device
from scripts.validate_proposed_yolo_labels import inspect_labels, write_validated_labels


def test_resolve_model_path_finds_onnx_when_engine_is_missing(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    onnx_path = models_dir / "poker_yolo_v11.onnx"
    onnx_path.write_bytes(b"dummy")

    resolved = resolve_model_path(str(models_dir / "poker_yolo_v11.engine"))

    assert resolved == onnx_path


def test_write_dataset_yaml_serializes_expected_structure(tmp_path):
    dataset_root = tmp_path / "dataset"
    train_images = dataset_root / "images" / "train"
    val_images = dataset_root / "images" / "val"
    train_images.mkdir(parents=True)
    val_images.mkdir(parents=True)

    yaml_path = write_dataset_yaml(
        dataset_root / "data.yaml",
        dataset_root=dataset_root,
        train_images_dir=train_images,
        val_images_dir=val_images,
        class_names=YOLO_CLASS_NAMES,
    )

    content = yaml_path.read_text(encoding="utf-8")

    assert "train: images/train" in content
    assert "val: images/val" in content
    assert f"nc: {len(YOLO_CLASS_NAMES)}" in content
    assert "0: 2h" in content
    assert f"{YOLO_CLASS_MAP['board_card']}: board_card" in content
    assert f"{YOLO_CLASS_MAP['raise_button']}: raise_button" in content
    assert validate_dataset_yaml_schema(yaml_path) == YOLO_CLASS_NAMES


def test_state_to_yolo_lines_maps_runtime_groups_to_generic_yolo_classes():
    class DummyState:
        board_cards = [DetectionResult(class_name="As", confidence=1.0, bbox=(10, 10, 30, 50))]
        hero_cards = [DetectionResult(class_name="Kd", confidence=1.0, bbox=(40, 10, 60, 50))]
        pots = [DetectionResult(class_name="pot_area", confidence=1.0, bbox=(70, 10, 110, 40))]
        stacks = []
        player_names = []
        action_buttons = [DetectionResult(class_name="fold_button", confidence=1.0, bbox=(20, 60, 80, 100))]
        dealer_button = DetectionResult(class_name="dealer_button", confidence=1.0, bbox=(120, 20, 140, 40))

    lines = state_to_yolo_lines(DummyState(), width=200, height=100)

    assert any(line.startswith(f"{YOLO_CLASS_MAP['board_card']} ") for line in lines)
    assert any(line.startswith(f"{YOLO_CLASS_MAP['hero_card']} ") for line in lines)
    assert any(line.startswith(f"{YOLO_CLASS_MAP['pot_area']} ") for line in lines)
    assert any(line.startswith(f"{YOLO_CLASS_MAP['fold_button']} ") for line in lines)
    assert any(line.startswith(f"{YOLO_CLASS_MAP['dealer_button']} ") for line in lines)


def test_inspect_labels_reports_generic_card_labels(tmp_path):
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    (labels_dir / "sample.txt").write_text(
        f"{YOLO_CLASS_MAP['hero_card']} 0.5 0.5 0.1 0.1\n"
        f"{YOLO_CLASS_MAP['pot_area']} 0.5 0.3 0.2 0.1\n",
        encoding="utf-8",
    )
    (labels_dir / "empty.txt").write_text("", encoding="utf-8")

    report = inspect_labels(labels_dir)

    assert report["files"] == 2
    assert report["empty_files"] == 1
    assert report["generic_card_labels"] == 1
    assert report["class_counts"]["hero_card"] == 1
    assert report["class_counts"]["pot_area"] == 1


def test_write_validated_labels_can_drop_generic_cards_for_zones_only_dataset(tmp_path):
    labels_dir = tmp_path / "labels"
    output_dir = tmp_path / "validated"
    labels_dir.mkdir()
    (labels_dir / "sample.txt").write_text(
        f"{YOLO_CLASS_MAP['hero_card']} 0.5 0.5 0.1 0.1\n"
        f"{YOLO_CLASS_MAP['pot_area']} 0.5 0.3 0.2 0.1\n",
        encoding="utf-8",
    )
    (labels_dir / "sample.json").write_text('{"status": "proposed"}\n', encoding="utf-8")

    summary = write_validated_labels(labels_dir, output_dir, drop_generic_cards=True, overwrite=False)

    assert summary["files"] == 1
    assert summary["dropped_generic_card_labels"] == 1
    assert summary["excluded_empty_after_drop"] == 0
    validated_lines = (output_dir / "sample.txt").read_text(encoding="utf-8").splitlines()
    assert validated_lines == [f"{YOLO_CLASS_MAP['pot_area']} 0.5 0.3 0.2 0.1"]
    metadata = (output_dir / "sample.json").read_text(encoding="utf-8")
    assert '"status": "validated_zones_only"' in metadata
    assert '"dropped_generic_card_labels": 1' in metadata


def test_write_validated_labels_can_exclude_generic_only_images_after_drop(tmp_path):
    labels_dir = tmp_path / "labels"
    output_dir = tmp_path / "validated"
    labels_dir.mkdir()
    (labels_dir / "sample.txt").write_text(
        f"{YOLO_CLASS_MAP['hero_card']} 0.5 0.5 0.1 0.1\n",
        encoding="utf-8",
    )
    (labels_dir / "sample.json").write_text('{"status": "proposed", "empty": false}\n', encoding="utf-8")

    summary = write_validated_labels(
        labels_dir,
        output_dir,
        drop_generic_cards=True,
        overwrite=False,
        exclude_empty_after_drop=True,
    )

    assert summary["files"] == 0
    assert summary["empty_files"] == 0
    assert summary["dropped_generic_card_labels"] == 1
    assert summary["excluded_empty_after_drop"] == 1
    assert not (output_dir / "sample.txt").exists()
    metadata = (output_dir / "sample.excluded.json").read_text(encoding="utf-8")
    assert '"status": "excluded_generic_only"' in metadata
    assert '"hard_negative": false' in metadata


def test_resolve_training_device_accepts_explicit_cpu():
    assert resolve_training_device("cpu") == "cpu"


def test_resolve_training_device_accepts_available_gpu_index():
    try:
        resolved = resolve_training_device("0")
    except SystemExit as exc:
        pytest.skip(str(exc))
    assert resolved == "0"
