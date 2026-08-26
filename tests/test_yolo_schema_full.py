"""Tests du schéma de dataset YOLO (src/vision/yolo_schema.py)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.yolo_schema import (
    YOLO_CLASS_MAP,
    YoloDatasetSchemaError,
    normalize_dataset_names,
    read_dataset_yaml_schema,
    validate_dataset_yaml_schema,
    write_dataset_yaml,
)


@pytest.fixture()
def dataset_dir(tmp_path):
    root = tmp_path / "dataset"
    (root / "images" / "train").mkdir(parents=True)
    (root / "images" / "val").mkdir(parents=True)
    return root


def test_write_and_validate_roundtrip(dataset_dir):
    yaml_path = write_dataset_yaml(
        dataset_dir / "data.yaml",
        dataset_root=dataset_dir,
        train_images_dir=dataset_dir / "images" / "train",
        val_images_dir=dataset_dir / "images" / "val",
    )
    assert yaml_path.is_file()
    names = validate_dataset_yaml_schema(yaml_path)
    assert names[0] == "2h"
    assert names[-1] == "chip_stack_gold"
    # le champ nc correspond au nombre de classes
    schema = read_dataset_yaml_schema(yaml_path)
    assert schema["nc"] == 69


def test_write_dataset_yaml_includes_test_split_when_given(dataset_dir, tmp_path):
    test_dir = dataset_dir / "images" / "test"
    test_dir.mkdir(parents=True)
    yaml_path = write_dataset_yaml(
        dataset_dir / "data.yaml",
        dataset_root=dataset_dir,
        train_images_dir=dataset_dir / "images" / "train",
        val_images_dir=dataset_dir / "images" / "val",
        test_images_dir=test_dir,
        class_names=["a", "b"],
    )
    content = yaml_path.read_text(encoding="utf-8")
    assert "test: images/test" in content
    schema = read_dataset_yaml_schema(yaml_path)
    assert normalize_dataset_names(schema["names"]) == ["a", "b"]


def test_validate_rejects_wrong_nc(tmp_path):
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("nc: 3\nnames:\n  0: a\n  1: b\n  2: c\n", encoding="utf-8")
    with pytest.raises(YoloDatasetSchemaError, match="nc=3"):
        validate_dataset_yaml_schema(yaml_path)


def test_validate_rejects_missing_fields(tmp_path):
    missing_nc = tmp_path / "no_nc.yaml"
    missing_nc.write_text("names:\n  0: a\n", encoding="utf-8")
    with pytest.raises(YoloDatasetSchemaError, match="nc manquant"):
        validate_dataset_yaml_schema(missing_nc)

    missing_names = tmp_path / "no_names.yaml"
    missing_names.write_text("nc: 5\n", encoding="utf-8")
    with pytest.raises(YoloDatasetSchemaError, match="names manquant"):
        validate_dataset_yaml_schema(missing_names)


def test_validate_rejects_non_integer_nc(tmp_path):
    bad = tmp_path / "bad_nc.yaml"
    bad.write_text("nc: soixante-dix\nnames:\n  0: a\n", encoding="utf-8")
    with pytest.raises(YoloDatasetSchemaError, match="entier"):
        validate_dataset_yaml_schema(bad)


def test_validate_reports_first_class_mismatch(tmp_path):
    names = list(__import__("src.vision.yolo_schema", fromlist=["YOLO_CLASS_NAMES"]).YOLO_CLASS_NAMES)
    names[5] = "WRONG"
    lines = [f"nc: {len(names)}", "names:"]
    lines.extend(f"  {i}: {n}" for i, n in enumerate(names))
    yaml_path = tmp_path / "mismatch.yaml"
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(YoloDatasetSchemaError, match="classe #5='WRONG'"):
        validate_dataset_yaml_schema(yaml_path)


def test_normalize_dataset_names_accepts_list_dict_and_rejects_other():
    assert normalize_dataset_names(["a", "b"]) == ["a", "b"]
    assert normalize_dataset_names({1: "b", 0: "a"}) == ["a", "b"]
    with pytest.raises(YoloDatasetSchemaError):
        normalize_dataset_names("flat")


def test_minimal_parser_handles_comments_lists_and_bad_keys():
    from src.vision.yolo_schema import _parse_dataset_yaml_minimal, _parse_scalar

    parsed = _parse_dataset_yaml_minimal(
        "\n".join(
            [
                "# commentaire",
                "path: /tmp/ds",
                "nc: 70",
                'quoted: "hello"',
                "items: [a, b]",
                "empty_list: []",
                "names:",
                "  0: 2h",
                "  1: 3h",
                "",
            ]
        )
    )
    assert parsed["path"] == "/tmp/ds"
    assert parsed["nc"] == 70
    assert parsed["quoted"] == "hello"
    assert parsed["items"] == ["a", "b"]
    assert parsed["empty_list"] == []
    # pyyaml convertit les clés numériques en int ; le parseur minimal les garde str
    assert parsed["names"] in ({"0": "2h", "1": "3h"}, {0: "2h", 1: "3h"})

    with pytest.raises(YoloDatasetSchemaError, match="Clé names invalide"):
        _parse_dataset_yaml_minimal("names:\n  bad_key: x\n")

    assert _parse_scalar("") == ""
    assert _parse_scalar("42") == 42


def test_read_dataset_yaml_schema_raises_on_non_mapping(tmp_path):
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("just_a_string\n", encoding="utf-8")
    with pytest.raises(YoloDatasetSchemaError, match="invalide"):
        read_dataset_yaml_schema(scalar)


def test_yolo_class_map_is_contiguous():
    assert len(YOLO_CLASS_MAP) == 69
    assert sorted(YOLO_CLASS_MAP.values()) == list(range(69))
