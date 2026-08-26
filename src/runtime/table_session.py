from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.runtime.evidence_models import RuntimeReadiness
from src.vision.site_adapter import SiteAdapterProtocol


@dataclass
class TableSession:
    session_id: str
    hwnd: int | None
    adapter: SiteAdapterProtocol
    tracker_state: dict[str, Any] = field(default_factory=dict)
    visual_state: dict[str, Any] = field(default_factory=dict)
    temporal_state: dict[str, Any] = field(default_factory=dict)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_valid_state: dict[str, Any] | None = None
    readiness: RuntimeReadiness = field(default_factory=RuntimeReadiness)
    # --- Phase 1 multi-table ---
    table_id: str = ""
    window_title: str = ""
    last_seen_monotonic: float = field(default_factory=time.monotonic)
    priority: int = 0
    # Handles et caches légers par session (camera, tracker, previews…).
    # Les ressources lourdes partagées (YOLO, OCR, DB, decision maker) restent
    # hors de ce dictionnaire.
    runtime: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.table_id:
            self.table_id = str(self.session_id)

    def record_incident(self, code: str, **context: Any) -> dict[str, Any]:
        incident = {
            "code": str(code or "unknown"),
            "context": dict(context),
            "recorded_at_monotonic": time.monotonic(),
        }
        self.incidents.append(incident)
        return incident

    def update_readiness(self, readiness: RuntimeReadiness) -> None:
        self.readiness = readiness

    def touch(self) -> None:
        self.last_seen_monotonic = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "table_id": self.table_id,
            "hwnd": self.hwnd,
            "window_title": self.window_title,
            "priority": int(self.priority),
            "site_key": self.adapter.site_key,
            "readiness": self.readiness.to_dict(),
            "tracker_state": dict(self.tracker_state),
            "visual_state": dict(self.visual_state),
            "temporal_state": dict(self.temporal_state),
            "incident_count": len(self.incidents),
            "last_valid_state": dict(self.last_valid_state)
            if isinstance(self.last_valid_state, dict)
            else self.last_valid_state,
            "metadata": dict(self.metadata),
        }
