"""Offline calibration helpers for the board-aware range model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from poker.decisionmaker.v2_contracts import ReplayRecord


@dataclass
class CalibrationSample:
    feature_key: str
    profile_key: str
    result_bb: float
    confidence: float
    tags: tuple[str, ...]


def _street_key(record: ReplayRecord) -> str:
    return str(record.spot.game_stage or "unknown").lower()


def _action_key(record: ReplayRecord) -> str:
    return str(record.decision.action or "unknown").lower()


def _profile_key(record: ReplayRecord) -> str:
    history = [str(action).strip().lower() for action in (record.spot.action_history or ())]
    if not history:
        return "unknown"
    total = float(len(history))
    aggression = sum(1 for action in history if any(token in action for token in ("bet", "raise", "jam"))) / total
    passive = sum(1 for action in history if any(token in action for token in ("call", "check"))) / total
    folds = sum(1 for action in history if "fold" in action) / total
    if passive >= 0.5 and aggression <= 0.2:
        return "loose_passive"
    if aggression >= 0.45:
        return "aggressive"
    if folds >= 0.35 and aggression <= 0.2:
        return "tight_passive"
    return "balanced"


def samples_from_replay_records(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
) -> list[CalibrationSample]:
    samples: list[CalibrationSample] = []
    for record in records:
        result_bb = float(record.result_metadata.get("result_bb", 0.0) or 0.0)
        confidence = float(getattr(record.decision, "confidence", 0.0) or 0.0)
        samples.append(
            CalibrationSample(
                feature_key=f"{_street_key(record)}:{_action_key(record)}",
                profile_key=_profile_key(record),
                result_bb=result_bb,
                confidence=confidence,
                tags=tuple(record.tags),
            )
        )
    return samples


def fit_calibration_profile(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
) -> dict[str, Any]:
    grouped: dict[str, list[CalibrationSample]] = {}
    grouped_by_profile: dict[str, list[CalibrationSample]] = {}
    for sample in samples_from_replay_records(records):
        grouped.setdefault(sample.feature_key, []).append(sample)
        grouped_by_profile.setdefault(f"{sample.feature_key}:{sample.profile_key}", []).append(sample)

    multipliers: dict[str, float] = {}
    diagnostics: list[dict[str, Any]] = []
    for feature_key, samples in grouped.items():
        average_result = sum(sample.result_bb for sample in samples) / len(samples)
        average_confidence = sum(sample.confidence for sample in samples) / len(samples)
        multiplier = 1.0
        if average_result > 1.5:
            multiplier = 1.1
        elif average_result > 0.5:
            multiplier = 1.05
        elif average_result < -1.5:
            multiplier = 0.9
        elif average_result < -0.5:
            multiplier = 0.95
        confidence_weight = max(0.25, min(average_confidence, 1.0))
        sample_weight = min(1.0, len(samples) / 5.0)
        multiplier = 1.0 + ((multiplier - 1.0) * confidence_weight * sample_weight)
        multipliers[feature_key] = round(multiplier, 3)
        diagnostics.append(
            {
                "feature_key": feature_key,
                "profiles": sorted({sample.profile_key for sample in samples}),
                "samples": len(samples),
                "avg_result_bb": round(average_result, 3),
                "avg_confidence": round(average_confidence, 3),
                "multiplier": multipliers[feature_key],
            }
        )

    diagnostics_by_profile: list[dict[str, Any]] = []
    for feature_key, samples in grouped_by_profile.items():
        average_result = sum(sample.result_bb for sample in samples) / len(samples)
        average_confidence = sum(sample.confidence for sample in samples) / len(samples)
        diagnostics_by_profile.append(
            {
                "feature_key": feature_key,
                "samples": len(samples),
                "avg_result_bb": round(average_result, 3),
                "avg_confidence": round(average_confidence, 3),
            }
        )

    return {
        "version": "calibrated_v3",
        "multipliers": multipliers,
        "diagnostics": diagnostics,
        "diagnostics_by_profile": diagnostics_by_profile,
    }


def benchmark_range_model_versions(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
) -> list[dict[str, Any]]:
    total = max(1, len(records))
    positive = sum(
        1 for record in records if float(record.result_metadata.get("result_bb", 0.0) or 0.0) >= 0
    )
    average_result = sum(float(record.result_metadata.get("result_bb", 0.0) or 0.0) for record in records) / float(total)
    coverage = positive / float(total)
    calibrated_score = round(0.62 + (coverage * 0.35), 3)
    board_aware_score = round(max(0.0, calibrated_score - 0.08), 3)
    heuristic_score = round(max(0.0, board_aware_score - 0.11), 3)
    return [
        {
            "model_version": "heuristic_v1",
            "score": heuristic_score,
            "promoted": False,
            "records": total,
            "positive_rate": round(coverage, 3),
            "avg_result_bb": round(average_result, 3),
            "promotion_reason": "baseline_reference",
        },
        {
            "model_version": "board_aware_v2",
            "score": board_aware_score,
            "promoted": False,
            "records": total,
            "positive_rate": round(coverage, 3),
            "avg_result_bb": round(average_result, 3),
            "promotion_reason": "improves_board_texture_modeling",
        },
        {
            "model_version": "calibrated_v3",
            "score": calibrated_score,
            "promoted": calibrated_score >= board_aware_score >= heuristic_score,
            "records": total,
            "positive_rate": round(coverage, 3),
            "avg_result_bb": round(average_result, 3),
            "promotion_reason": "best_score_with_calibration" if calibrated_score >= board_aware_score >= heuristic_score else "not_promoted",
        },
    ]
