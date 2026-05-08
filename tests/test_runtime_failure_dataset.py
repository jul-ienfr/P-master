import json
from pathlib import Path

import cv2
import numpy as np

from src.scripts.replay_runtime_failures import export_runtime_failure_review_bundle, replay_runtime_failures
from src.vision.runtime_failure_dataset import RuntimeFailureDataset


def test_runtime_failure_dataset_writes_jsonl_records(tmp_path):
    dataset = RuntimeFailureDataset(dataset_dir=str(tmp_path))

    manifest_path = dataset.record_incident({"incident_id": "gate_blocked", "category": "incident", "severity": "warning"})

    assert manifest_path is not None
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8").strip())
    assert payload["incident_id"] == "gate_blocked"


def test_replay_runtime_failures_filters_and_summarizes_records(tmp_path):
    manifest = tmp_path / "incidents.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"incident_id": "gate_blocked", "category": "incident", "severity": "warning"}),
                json.dumps({"incident_id": "runtime_readiness_not_fully_valid", "category": "near_miss", "severity": "error"}),
            ]
        ),
        encoding="utf-8",
    )

    replay = replay_runtime_failures(str(manifest), incident_id="runtime_readiness_not_fully_valid", severity="error")

    assert replay["summary"]["record_count"] == 1
    assert replay["summary"]["categories"] == {"near_miss": 1}
    assert replay["summary"]["severities"] == {"error": 1}
    assert replay["records"][0]["incident_id"] == "runtime_readiness_not_fully_valid"


def test_export_runtime_failure_review_bundle_writes_filtered_bundle(tmp_path):
    manifest = tmp_path / "incidents.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"incident_id": "gate_blocked", "category": "incident", "severity": "warning"}),
                json.dumps({"incident_id": "runtime_readiness_not_fully_valid", "category": "near_miss", "severity": "error"}),
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "review_bundle.json"

    path = export_runtime_failure_review_bundle(str(manifest), str(output), category="near_miss")

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["kind"] == "runtime_failure_review_bundle"
    assert payload["summary"]["categories"] == {"near_miss": 1}
    assert payload["records"][0]["incident_id"] == "runtime_readiness_not_fully_valid"


def test_runtime_failure_dataset_persists_frame_and_crop_artifacts(tmp_path):
    dataset = RuntimeFailureDataset(dataset_dir=str(tmp_path))
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    frame[:, ::2] = 255
    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    crop[:, ::2] = 255

    manifest_path = dataset.record_incident(
        {
            "incident_id": "gate_blocked",
            "category": "incident",
            "severity": "warning",
            "timestamp": "2026-04-11T12:30:00Z",
            "frame": frame,
            "crops": {"pot": crop},
        }
    )

    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8").strip())
    frame_path = Path(payload["artifacts"]["frame"])
    crop_path = Path(payload["artifacts"]["crops"]["pot"])
    assert frame_path.is_file()
    assert crop_path.is_file()
    assert cv2.imread(str(frame_path)) is not None


def test_replay_runtime_failures_resolves_artifact_paths(tmp_path):
    dataset = RuntimeFailureDataset(dataset_dir=str(tmp_path))
    frame = np.zeros((20, 30, 3), dtype=np.uint8)
    crop = np.zeros((10, 10, 3), dtype=np.uint8)
    manifest_path = dataset.record_incident(
        {
            "incident_id": "runtime_readiness_not_fully_valid",
            "category": "near_miss",
            "severity": "error",
            "timestamp": "2026-04-11T12:31:00Z",
            "frame": frame,
            "crops": {"pot": crop},
        }
    )

    replay = replay_runtime_failures(str(manifest_path), incident_id="runtime_readiness_not_fully_valid")

    assert replay["summary"]["artifacts"]["frame_count"] == 1
    assert replay["summary"]["artifacts"]["crop_count"] == 1
    assert replay["records"][0]["resolved_artifacts"]["frame"]
    assert replay["records"][0]["resolved_artifacts"]["crops"]["pot"]
