"""Harnais de mesure de vision par site (spec 010, constat F-08).

Sans capture, le harnais doit dire « non mesuré » (taux ``None``), jamais inventer
un taux. Avec captures étiquetées, il produit précision et effectif exacts, et un
champ illisible est compté comme échec, jamais exclu.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.vision_benchmark import (
    MEASURED,
    UNMEASURED,
    LabeledSample,
    run_vision_benchmark,
    write_report,
)


def _constant_reader(value):
    def reader(_image):
        return value

    return reader


def test_empty_sample_set_is_unmeasured_with_none_rates():
    report = run_vision_benchmark([], _constant_reader(100.0), site_key="pokerstars")

    assert report.status == UNMEASURED
    assert report.measured is False
    assert report.evaluated == 0
    payload = report.as_dict()
    assert payload["fields"] == []


def test_missing_labels_are_unevaluable_not_invented():
    samples = [
        LabeledSample(image=None, expected=None, field="pot"),
        LabeledSample(image=None, expected=None, field="pot"),
    ]

    report = run_vision_benchmark(samples, _constant_reader(100.0), site_key="pokerstars")

    assert report.status == UNMEASURED
    assert report.evaluated == 0
    field = report.fields[0]
    assert field.evaluated == 0
    assert field.unevaluable == 2
    assert field.accuracy is None


def test_labeled_samples_produce_exact_accuracy_and_count():
    samples = [
        LabeledSample(image=1, expected=100.0, field="pot"),
        LabeledSample(image=2, expected=200.0, field="pot"),
        LabeledSample(image=3, expected=300.0, field="pot"),
        LabeledSample(image=4, expected=999.0, field="pot"),
    ]
    # Le lecteur est juste sauf pour le crop 4 : 3/4 = 0.75.
    values = {1: 100.0, 2: 200.0, 3: 300.0, 4: 400.0}

    report = run_vision_benchmark(samples, lambda image: values[image], site_key="pokerstars")

    assert report.status == MEASURED
    assert report.evaluated == 4
    field = report.fields[0]
    assert field.evaluated == 4
    assert field.correct == 3
    assert field.accuracy == 0.75


def test_unreadable_field_is_a_failure_not_excluded():
    samples = [
        LabeledSample(image=1, expected=100.0, field="pot"),
        LabeledSample(image=2, expected=200.0, field="pot"),
    ]
    # Le second crop est illisible : il reste dans le dénominateur.
    values = {1: 100.0, 2: None}

    report = run_vision_benchmark(samples, lambda image: values[image], site_key="winamax")

    field = report.fields[0]
    assert field.evaluated == 2
    assert field.unreadable == 1
    assert field.correct == 1
    assert field.accuracy == 0.5


def test_reader_exception_is_counted_as_unreadable():
    def exploding_reader(_image):
        raise RuntimeError("ocr crash")

    samples = [LabeledSample(image=1, expected=100.0, field="pot")]

    report = run_vision_benchmark(samples, exploding_reader, site_key="winamax")

    field = report.fields[0]
    assert field.evaluated == 1
    assert field.unreadable == 1
    assert field.accuracy == 0.0


def test_measurement_is_split_by_field():
    samples = [
        LabeledSample(image=1, expected=10.0, field="pot"),
        LabeledSample(image=2, expected=20.0, field="stack"),
    ]

    report = run_vision_benchmark(samples, _constant_reader(10.0), site_key="pokerstars")

    fields = {item.field: item for item in report.fields}
    assert set(fields) == {"pot", "stack"}
    assert fields["pot"].accuracy == 1.0
    assert fields["stack"].accuracy == 0.0


def test_report_is_written_as_a_dated_json_artifact(tmp_path):
    report = run_vision_benchmark(
        [LabeledSample(image=1, expected=100.0, field="pot")],
        _constant_reader(100.0),
        site_key="pokerstars",
    )

    output = write_report(report, tmp_path / "vision_benchmark_pokerstars.json")

    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "vision_benchmark"
    assert payload["site_key"] == "pokerstars"
    assert payload["status"] == MEASURED
    assert payload["generated_at"]
    assert payload["fields"][0]["accuracy"] == 1.0
