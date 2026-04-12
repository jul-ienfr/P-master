"""Automation helpers for reproducible V2/refonte validation artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "research" / "results"


@dataclass(frozen=True)
class AutomationArtifact:
    key: str
    path: Path
    description: str


ARTIFACT_CATALOG: tuple[AutomationArtifact, ...] = (
    AutomationArtifact(
        key="validation_suite",
        path=RESULTS_DIR / "validation_suite.json",
        description="Randomized oracle parity and representative replay validation",
    ),
    AutomationArtifact(
        key="native_latency",
        path=RESULTS_DIR / "native_latency.json",
        description="Native solver warm/cold latency benchmark",
    ),
    AutomationArtifact(
        key="rl_lab_summary",
        path=RESULTS_DIR / "rl_lab_summary.json",
        description="Offline RL/replay tournament and challenger smoke suite",
    ),
    AutomationArtifact(
        key="refonte_ci_summary",
        path=RESULTS_DIR / "refonte_ci_summary.json",
        description="Unified phase-2 validation runner summary",
    ),
)


def read_json_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_automation_payload(results_dir: str | Path | None = None) -> dict[str, Any]:
    base_dir = Path(results_dir) if results_dir is not None else RESULTS_DIR
    artifacts: list[dict[str, Any]] = []
    ready_count = 0

    for artifact in ARTIFACT_CATALOG:
        path = base_dir / artifact.path.name
        payload = read_json_artifact(path)
        exists = path.exists()
        if exists:
            ready_count += 1
        artifacts.append(
            {
                "key": artifact.key,
                "description": artifact.description,
                "path": str(path.as_posix()),
                "exists": exists,
                "kind": payload.get("kind", "") if isinstance(payload, dict) else "",
                "summary_keys": sorted(payload.keys())[:12] if isinstance(payload, dict) else [],
            }
        )

    return {
        "kind": "automation",
        "results_dir": str(base_dir.as_posix()),
        "artifacts": artifacts,
        "ready_count": ready_count,
        "missing_count": len(artifacts) - ready_count,
        "status": "ready" if ready_count == len(artifacts) else "partial",
    }
