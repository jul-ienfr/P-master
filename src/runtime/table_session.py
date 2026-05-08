from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.runtime.evidence_models import RuntimeReadiness
from src.vision.site_adapter import SiteAdapterProtocol


@dataclass
class TableSession:
    session_id: str
    hwnd: Optional[int]
    adapter: SiteAdapterProtocol
    tracker_state: dict[str, Any] = field(default_factory=dict)
    visual_state: dict[str, Any] = field(default_factory=dict)
    temporal_state: dict[str, Any] = field(default_factory=dict)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_valid_state: Optional[dict[str, Any]] = None
    readiness: RuntimeReadiness = field(default_factory=RuntimeReadiness)

    def record_incident(self, code: str, **context: Any) -> dict[str, Any]:
        incident = {
            "code": str(code or "unknown"),
            "context": dict(context),
        }
        self.incidents.append(incident)
        return incident

    def update_readiness(self, readiness: RuntimeReadiness) -> None:
        self.readiness = readiness

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "hwnd": self.hwnd,
            "site_key": self.adapter.site_key,
            "readiness": self.readiness.to_dict(),
            "tracker_state": dict(self.tracker_state),
            "visual_state": dict(self.visual_state),
            "temporal_state": dict(self.temporal_state),
            "incident_count": len(self.incidents),
            "last_valid_state": dict(self.last_valid_state) if isinstance(self.last_valid_state, dict) else self.last_valid_state,
            "metadata": dict(self.metadata),
        }
