from __future__ import annotations

from src.bot.runtime_types import CanonicalTableState
from src.runtime.evidence_models import RuntimeReadiness
from src.runtime.poker_state_validator import PokerStateValidationResult


def build_runtime_readiness(
    canonical_state: CanonicalTableState,
    validation: PokerStateValidationResult,
) -> RuntimeReadiness:
    metadata = dict(canonical_state.metadata or {})
    vision = dict(metadata.get("vision", {}) or {})
    frame_quality = dict(vision.get("frame_quality", {}) or {})
    crop_quality = dict(vision.get("crop_quality", {}) or {})
    fallback_readiness = dict(metadata.get("fallback_execution_readiness", {}) or {})

    reasons = list(validation.reasons)
    critical_failures: list[str] = []
    degraded_fields: list[str] = []

    if frame_quality.get("rejected"):
        critical_failures.append(str(frame_quality.get("reject_reason") or "frame_rejected"))

    pot_crop_quality = crop_quality.get("pot", {}) if isinstance(crop_quality, dict) else {}
    if isinstance(pot_crop_quality, dict) and pot_crop_quality.get("rejected"):
        degraded_fields.append("pot")

    if validation.state == "hard_invalid":
        critical_failures.extend(reason for reason in validation.reasons if reason not in critical_failures)
    elif validation.state in {"soft_invalid", "degraded_valid"}:
        degraded_fields.extend(reason for reason in validation.reasons if reason not in degraded_fields)

    if float(canonical_state.state_confidence or 0.0) < 0.45:
        degraded_fields.append("state_confidence")

    score_parts = [
        float(canonical_state.state_confidence or 0.0),
        float(frame_quality.get("quality_score", 0.0) or 0.0),
        1.0 if validation.state == "fully_valid" else 0.7 if validation.state == "degraded_valid" else 0.4 if validation.state == "soft_invalid" else 0.0,
    ]
    score = round(sum(score_parts) / len(score_parts), 3)

    if critical_failures:
        state = "blocked_local"
        actionable = False
        conservative = False
    elif validation.state in {"soft_invalid", "degraded_valid"}:
        state = "conservative"
        actionable = False
        conservative = True
    else:
        state = "actionable"
        actionable = True
        conservative = False

    if fallback_readiness:
        reasons.extend(str(reason) for reason in fallback_readiness.get("reasons", []) if reason and reason not in reasons)

    return RuntimeReadiness(
        state=state,
        actionable=actionable,
        conservative=conservative,
        score=score,
        state_confidence=score,
        critical_failures=tuple(dict.fromkeys(critical_failures)),
        degraded_fields=tuple(dict.fromkeys(degraded_fields)),
        reasons=tuple(dict.fromkeys(reasons)),
        metadata={
            "validation": validation.to_dict(),
            "fallback_execution_readiness": fallback_readiness,
            "vision_quality": {
                "frame": frame_quality,
                "crop": crop_quality,
            },
        },
    )
