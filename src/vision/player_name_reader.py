from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from src.runtime.evidence_models import FieldCandidate, FieldCriticality, FieldEvidence
from src.runtime.player_name_resolver import resolve_player_name
from src.vision.crop_quality import analyze_crop_quality


@dataclass(frozen=True)
class PlayerNameReadResult:
    selected_name: str
    resolution_source: str
    evidence: FieldEvidence
    metadata: dict[str, Any]


class PlayerNameReader:
    def __init__(self, ocr_engine) -> None:
        self.ocr_engine = ocr_engine

    def read_name(self, seat_id: str, image_crop: np.ndarray, seat_cache: dict[str, str]) -> PlayerNameReadResult:
        crop_quality = analyze_crop_quality("player_name", image_crop)
        raw_text = self.ocr_engine.read_player_name(image_crop).strip() if image_crop is not None and image_crop.size else ""
        ocr_metadata = dict(self.ocr_engine.get_metadata() or {}) if hasattr(self.ocr_engine, "get_metadata") else {}
        resolved_name, resolution_source = resolve_player_name(
            seat_id=seat_id,
            candidate_name=raw_text,
            seat_cache=seat_cache,
        )
        confidence = float(ocr_metadata.get("selected_confidence", 0.0) or 0.0)
        candidate = FieldCandidate(
            field_name="player_name",
            value=resolved_name,
            raw_text=raw_text,
            confidence=confidence,
            source="player_name_reader",
            engine=str(ocr_metadata.get("selected_engine", "") or ""),
            variant="selected",
            metadata={"ocr": ocr_metadata, "resolution_source": resolution_source},
        )
        evidence = FieldEvidence(
            field_name="player_name",
            criticality=FieldCriticality.CONTEXTUAL,
            selected_value=resolved_name,
            selected_candidate=candidate,
            candidates=(candidate,),
            confidence=confidence,
            crop_quality=crop_quality,
            state="confirmed" if resolved_name else "quarantined",
            rejection_reason="" if resolved_name else resolution_source,
            metadata={
                "raw_text": raw_text,
                "resolved_text": resolved_name,
                "resolution_source": resolution_source,
                "ocr": ocr_metadata,
            },
        )
        return PlayerNameReadResult(
            selected_name=resolved_name,
            resolution_source=resolution_source,
            evidence=evidence,
            metadata={
                "raw_text": raw_text,
                "resolved_text": resolved_name,
                "resolution_source": resolution_source,
                "ocr": ocr_metadata,
            },
        )
