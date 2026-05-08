from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FieldCriticality(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    CONTEXTUAL = "contextual"
    DECORATIVE = "decorative"


FIELD_CRITICALITY: dict[str, FieldCriticality] = {
    "hero_cards": FieldCriticality.CRITICAL,
    "action_buttons": FieldCriticality.CRITICAL,
    "hero_turn": FieldCriticality.CRITICAL,
    "window_identity": FieldCriticality.CRITICAL,
    "frame_freshness": FieldCriticality.CRITICAL,
    "button_target": FieldCriticality.CRITICAL,
    "street": FieldCriticality.CRITICAL,
    "board": FieldCriticality.CRITICAL,
    "pot": FieldCriticality.IMPORTANT,
    "hero_stack": FieldCriticality.IMPORTANT,
    "main_villain_stack": FieldCriticality.IMPORTANT,
    "dealer_button": FieldCriticality.IMPORTANT,
    "active_players": FieldCriticality.IMPORTANT,
    "player_name": FieldCriticality.CONTEXTUAL,
    "secondary_stack": FieldCriticality.CONTEXTUAL,
    "chat": FieldCriticality.DECORATIVE,
}


@dataclass(frozen=True)
class FrameQualityReport:
    frame_timestamp: float = 0.0
    frame_age_ms: float = 0.0
    width: int = 0
    height: int = 0
    blur_score: float = 0.0
    contrast_score: float = 0.0
    luma_score: float = 0.0
    quality_score: float = 0.0
    rejected: bool = False
    reject_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def state_confidence(self) -> float:
        return float(self.quality_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_timestamp": self.frame_timestamp,
            "frame_age_ms": self.frame_age_ms,
            "width": self.width,
            "height": self.height,
            "blur_score": self.blur_score,
            "contrast_score": self.contrast_score,
            "luma_score": self.luma_score,
            "quality_score": self.quality_score,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CropQualityReport:
    field_name: str
    width: int = 0
    height: int = 0
    blur_score: float = 0.0
    contrast_score: float = 0.0
    luma_score: float = 0.0
    signal_score: float = 0.0
    quality_score: float = 0.0
    rejected: bool = False
    reject_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def state_confidence(self) -> float:
        return float(self.quality_score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "width": self.width,
            "height": self.height,
            "blur_score": self.blur_score,
            "contrast_score": self.contrast_score,
            "luma_score": self.luma_score,
            "signal_score": self.signal_score,
            "quality_score": self.quality_score,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FieldCandidate:
    field_name: str
    value: Any = None
    raw_text: str = ""
    confidence: float = 0.0
    source: str = ""
    engine: str = ""
    variant: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "source": self.source,
            "engine": self.engine,
            "variant": self.variant,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FieldEvidence:
    field_name: str
    criticality: FieldCriticality
    selected_value: Any = None
    selected_candidate: Optional[FieldCandidate] = None
    candidates: tuple[FieldCandidate, ...] = ()
    confidence: float = 0.0
    crop_quality: Optional[CropQualityReport] = None
    state: str = "empty"
    rejection_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def state_confidence(self) -> float:
        return float(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "criticality": self.criticality.value,
            "selected_value": self.selected_value,
            "selected_candidate": self.selected_candidate.to_dict() if self.selected_candidate else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "confidence": self.confidence,
            "crop_quality": self.crop_quality.to_dict() if self.crop_quality else None,
            "state": self.state,
            "rejection_reason": self.rejection_reason,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RuntimeReadiness:
    state: str = "blocked_local"
    actionable: bool = False
    conservative: bool = False
    score: float = 0.0
    state_confidence: float = 0.0
    critical_failures: tuple[str, ...] = ()
    degraded_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    field_evidence: dict[str, FieldEvidence] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "actionable": self.actionable,
            "conservative": self.conservative,
            "score": self.score,
            "state_confidence": self.state_confidence,
            "critical_failures": list(self.critical_failures),
            "degraded_fields": list(self.degraded_fields),
            "reasons": list(self.reasons),
            "field_evidence": {key: value.to_dict() for key, value in self.field_evidence.items()},
            "metadata": dict(self.metadata),
        }
