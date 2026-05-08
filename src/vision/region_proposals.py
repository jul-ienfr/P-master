from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from src.vision.detector import DetectionResult, TableState


@dataclass(frozen=True)
class RegionProposal:
    field_name: str
    bbox: tuple[int, int, int, int]
    source: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "bbox": [int(value) for value in self.bbox],
            "source": self.source,
            "score": float(self.score),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RegionResolution:
    field_name: str
    selected: RegionProposal
    candidates: tuple[RegionProposal, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "selected": self.selected.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _union_bbox(detections: Iterable[DetectionResult]) -> Optional[tuple[int, int, int, int]]:
    boxes = [tuple(det.bbox) for det in detections if getattr(det, "bbox", None)]
    if not boxes:
        return None
    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[2] for box in boxes)
    y2 = max(box[3] for box in boxes)
    return (int(x1), int(y1), int(x2), int(y2))


def build_region_proposals(
    state: TableState,
    geometry_regions: dict[str, tuple[int, int, int, int]],
) -> dict[str, list[RegionProposal]]:
    proposals: dict[str, list[RegionProposal]] = {}
    for field_name, bbox in geometry_regions.items():
        proposals.setdefault(field_name, []).append(
            RegionProposal(
                field_name=field_name,
                bbox=bbox,
                source="preset_geometry",
                score=0.85 if field_name != "table" else 0.95,
            )
        )

    table_bbox = state.metadata.get("table_bbox") if isinstance(getattr(state, "metadata", None), dict) else None
    if isinstance(table_bbox, list) and len(table_bbox) == 4:
        proposals.setdefault("table", []).append(
            RegionProposal(
                field_name="table",
                bbox=tuple(int(value) for value in table_bbox),
                source="detector_table_bbox",
                score=1.0,
            )
        )

    if getattr(state, "pots", None):
        for detection in state.pots:
            proposals.setdefault("pot", []).append(
                RegionProposal(
                    field_name="pot",
                    bbox=tuple(int(value) for value in detection.bbox),
                    source="detector_pot",
                    score=float(getattr(detection, "confidence", 0.0) or 0.0),
                    metadata={"class_name": getattr(detection, "class_name", "")},
                )
            )

    hero_union = _union_bbox(getattr(state, "hero_cards", []) or [])
    if hero_union is not None:
        proposals.setdefault("hero", []).append(
            RegionProposal(field_name="hero", bbox=hero_union, source="detector_hero_cards", score=0.92)
        )

    board_union = _union_bbox(getattr(state, "board_cards", []) or [])
    if board_union is not None:
        proposals.setdefault("board", []).append(
            RegionProposal(field_name="board", bbox=board_union, source="detector_board_cards", score=0.92)
        )

    action_union = _union_bbox(getattr(state, "action_buttons", []) or [])
    if action_union is not None:
        proposals.setdefault("actions", []).append(
            RegionProposal(field_name="actions", bbox=action_union, source="detector_action_buttons", score=0.94)
        )

    return proposals


def resolve_region_proposals(
    proposals: dict[str, list[RegionProposal]],
    *,
    preferred_sources: tuple[str, ...] = ("detector_pot", "detector_action_buttons", "detector_hero_cards", "preset_geometry"),
) -> dict[str, RegionResolution]:
    priority_index = {source: index for index, source in enumerate(preferred_sources)}
    resolved: dict[str, RegionResolution] = {}
    for field_name, candidates in proposals.items():
        if not candidates:
            continue
        ordered = tuple(
            sorted(
                candidates,
                key=lambda proposal: (
                    -float(proposal.score),
                    priority_index.get(proposal.source, len(priority_index)),
                    proposal.source,
                    proposal.bbox,
                ),
            )
        )
        resolved[field_name] = RegionResolution(field_name=field_name, selected=ordered[0], candidates=ordered)
    return resolved
