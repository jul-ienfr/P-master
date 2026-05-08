from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def load_runtime_failure_records(manifest_path: str) -> list[dict[str, Any]]:
    path = Path(manifest_path)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def summarize_runtime_failure_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "record_count": len(records),
        "categories": {},
        "incident_ids": {},
        "severities": {},
        "artifacts": {
            "frame_count": 0,
            "crop_count": 0,
        },
    }
    for record in records:
        category = str(record.get("category") or "unknown")
        incident_id = str(record.get("incident_id") or "unknown")
        severity = str(record.get("severity") or "unknown")
        summary["categories"][category] = int(summary["categories"].get(category, 0)) + 1
        summary["incident_ids"][incident_id] = int(summary["incident_ids"].get(incident_id, 0)) + 1
        summary["severities"][severity] = int(summary["severities"].get(severity, 0)) + 1
        artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
        if artifacts.get("frame"):
            summary["artifacts"]["frame_count"] += 1
        crops = artifacts.get("crops") if isinstance(artifacts.get("crops"), dict) else {}
        summary["artifacts"]["crop_count"] += len(crops)
    return summary


def load_runtime_failure_artifacts(record: dict[str, Any]) -> dict[str, Any]:
    artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
    frame_path = Path(artifacts.get("frame")) if artifacts.get("frame") else None
    crops = artifacts.get("crops") if isinstance(artifacts.get("crops"), dict) else {}
    return {
        "frame": str(frame_path) if frame_path and frame_path.is_file() else None,
        "crops": {
            str(name): str(Path(path))
            for name, path in crops.items()
            if str(path).strip() and Path(path).is_file()
        },
    }


def replay_runtime_failures(
    manifest_path: str,
    *,
    incident_id: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
) -> dict[str, Any]:
    records = load_runtime_failure_records(manifest_path)
    if incident_id:
        records = [record for record in records if str(record.get("incident_id") or "") == str(incident_id)]
    if category:
        records = [record for record in records if str(record.get("category") or "") == str(category)]
    if severity:
        records = [record for record in records if str(record.get("severity") or "") == str(severity)]
    enriched_records = []
    for record in records:
        enriched = dict(record)
        enriched["resolved_artifacts"] = load_runtime_failure_artifacts(record)
        enriched_records.append(enriched)
    return {
        "records": enriched_records,
        "summary": summarize_runtime_failure_records(enriched_records),
    }


def export_runtime_failure_review_bundle(
    manifest_path: str,
    output_path: str,
    *,
    incident_id: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
) -> str:
    replay = replay_runtime_failures(
        manifest_path,
        incident_id=incident_id,
        category=category,
        severity=severity,
    )
    payload = {
        "kind": "runtime_failure_review_bundle",
        "source": str(manifest_path),
        "summary": replay["summary"],
        "records": replay["records"],
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return str(target)
