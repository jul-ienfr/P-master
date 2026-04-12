"""Dataset builders for offline opponent modeling and replay calibration."""

from __future__ import annotations

from typing import Any

from poker.decisionmaker.v2_contracts import ReplayRecord


def _action_ratios(action_history: list[str]) -> dict[str, float]:
    if not action_history:
        return {
            "aggression_frequency": 0.0,
            "passive_frequency": 0.0,
            "fold_frequency": 0.0,
        }

    normalized = [str(action).strip().lower() for action in action_history]
    total = float(len(normalized))
    aggressive = sum(1 for action in normalized if any(token in action for token in ("bet", "raise", "jam")))
    passive = sum(1 for action in normalized if any(token in action for token in ("call", "check")))
    folds = sum(1 for action in normalized if "fold" in action)
    return {
        "aggression_frequency": round(aggressive / total, 4),
        "passive_frequency": round(passive / total, 4),
        "fold_frequency": round(folds / total, 4),
    }


def _profile_bucket(action_history: list[str]) -> str:
    ratios = _action_ratios(action_history)
    aggression = ratios["aggression_frequency"]
    passive = ratios["passive_frequency"]
    folds = ratios["fold_frequency"]
    if passive >= 0.5 and aggression <= 0.2:
        return "LoosePassive"
    if aggression >= 0.45:
        return "Aggressive"
    if folds >= 0.35 and aggression <= 0.2:
        return "TightPassive"
    return "Balanced"


def build_opponent_dataset(
    records: list[ReplayRecord] | tuple[ReplayRecord, ...],
) -> list[dict[str, Any]]:
    dataset: list[dict[str, Any]] = []
    for record in records:
        action_history = list(record.spot.action_history)
        action_ratios = _action_ratios(action_history)
        dataset.append(
            {
                "replay_id": record.replay_id,
                "spot_id": record.spot.spot_id,
                "street": record.spot.game_stage,
                "hero_position": record.spot.hero_position,
                "pot": record.spot.pot,
                "stack": record.spot.stack,
                "hero_range": record.spot.hero_range,
                "villain_ranges": list(record.spot.villain_ranges),
                "action_history": action_history,
                "chosen_action": record.decision.action,
                "confidence": record.decision.confidence,
                "result_bb": float(record.result_metadata.get("result_bb", 0.0) or 0.0),
                "opponent_profile_bucket": _profile_bucket(action_history),
                **action_ratios,
                "tags": list(record.tags),
            }
        )
    return dataset
