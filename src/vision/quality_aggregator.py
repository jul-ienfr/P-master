"""Agrégation de la qualité vision par élément (cartes/boutons/pot/stacks/noms).

Consomme les métadonnées `detection_quality` / `crop_quality` déjà produites par
le pipeline et maintient des compteurs publiés dans `runtime_bridge_state`
(`vision_quality`). Un incident dédié est émis quand un élément reste
rejeté/dégradé trop longtemps (thème changé, résolution, OCR cassé…).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

_LOW_DETECTION_SCORE = 0.30


class VisionQualityAggregator:
    def __init__(
        self,
        *,
        rejection_incident_threshold: int = 10,
        incident_callback: Callable[..., None] | None = None,
    ):
        self.rejection_incident_threshold = max(1, int(rejection_incident_threshold))
        self.incident_callback = incident_callback
        self.elements: dict[str, dict[str, Any]] = {}

    def observe(
        self,
        detection_quality: dict[str, Any] | None,
        crop_quality: dict[str, Any] | None,
    ) -> None:
        for field_name, info in dict(detection_quality or {}).items():
            if not isinstance(info, dict):
                continue
            count = int(info.get("count", 0) or 0)
            average = float(info.get("average_score", 0.0) or 0.0)
            degraded = count > 0 and average < _LOW_DETECTION_SCORE
            self._update(
                f"detection:{field_name}",
                score=average if count > 0 else None,
                seen=count > 0,
                rejected=degraded,
            )
        for region_name, info in dict(crop_quality or {}).items():
            if not isinstance(info, dict):
                continue
            rejected = bool(info.get("rejected", False))
            score = float(info.get("quality_score", 0.0) or 0.0)
            self._update(
                f"crop:{region_name}",
                score=score,
                seen=True,
                rejected=rejected,
            )

    def _element_entry(self, element: str) -> dict[str, Any]:
        entry = self.elements.get(element)
        if entry is None:
            entry = {
                "samples": 0,
                "seen": 0,
                "sum_score": 0.0,
                "avg_score": 0.0,
                "last_score": None,
                "consecutive_rejected": 0,
                "incident_active": False,
                "updated_at_monotonic": 0.0,
            }
            self.elements[element] = entry
        return entry

    def _update(
        self,
        element: str,
        *,
        score: float | None,
        seen: bool,
        rejected: bool,
    ) -> None:
        entry = self._element_entry(element)
        entry["samples"] += 1
        if seen:
            entry["seen"] += 1
        if score is not None:
            entry["sum_score"] += float(score)
            entry["avg_score"] = round(entry["sum_score"] / max(1, entry["seen"]), 4)
            entry["last_score"] = round(float(score), 4)
        if rejected:
            entry["consecutive_rejected"] += 1
        else:
            entry["consecutive_rejected"] = 0
            entry["incident_active"] = False
        entry["updated_at_monotonic"] = time.monotonic()

        if (
            rejected
            and entry["consecutive_rejected"] >= self.rejection_incident_threshold
            and not entry["incident_active"]
        ):
            entry["incident_active"] = True
            if self.incident_callback is not None:
                try:
                    self.incident_callback(
                        "vision_quality_degraded",
                        severity="warning",
                        element=str(element),
                        consecutive_rejected=int(entry["consecutive_rejected"]),
                        avg_score=float(entry["avg_score"]),
                    )
                except Exception:
                    pass

    def snapshot(self) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for element, entry in self.elements.items():
            snapshot[element] = {
                "samples": int(entry["samples"]),
                "seen": int(entry["seen"]),
                "avg_score": float(entry["avg_score"]),
                "last_score": entry["last_score"],
                "consecutive_rejected": int(entry["consecutive_rejected"]),
                "incident_active": bool(entry["incident_active"]),
            }
        return snapshot
