from __future__ import annotations

import cv2
import numpy as np

from src.runtime.evidence_models import CropQualityReport


FIELD_SIGNAL_WEIGHTS: dict[str, float] = {
    "button": 0.40,
    "action_buttons": 0.40,
    "hero_cards": 0.45,
    "board_cards": 0.45,
    "pot": 0.35,
    "stack": 0.35,
    "player_name": 0.30,
}


def _clamp_score(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def analyze_crop_quality(field_name: str, crop: np.ndarray) -> CropQualityReport:
    normalized_field = str(field_name or "unknown").strip().lower()
    if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
        return CropQualityReport(field_name=normalized_field, rejected=True, reject_reason="empty_crop")

    height, width = crop.shape[:2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast_std = float(gray.std())
    luma_mean = float(gray.mean())
    edge_density = float(cv2.Canny(gray, 100, 200).mean() / 255.0)

    blur_score = _clamp_score(laplacian_variance / 220.0)
    contrast_score = _clamp_score(contrast_std / 64.0)
    luma_score = _clamp_score(1.0 - (abs(luma_mean - 127.5) / 127.5))
    signal_score = _clamp_score(edge_density * 3.0)
    signal_weight = FIELD_SIGNAL_WEIGHTS.get(normalized_field, 0.30)
    quality_score = round(
        (blur_score * 0.30) + (contrast_score * 0.25) + (luma_score * (0.45 - signal_weight)) + (signal_score * signal_weight),
        3,
    )

    reject_reason = ""
    if min(width, height) < 8:
        reject_reason = "crop_too_small"
    elif blur_score < 0.06:
        reject_reason = "crop_blurry"
    elif contrast_score < 0.05:
        reject_reason = "crop_low_contrast"

    return CropQualityReport(
        field_name=normalized_field,
        width=int(width),
        height=int(height),
        blur_score=round(blur_score, 3),
        contrast_score=round(contrast_score, 3),
        luma_score=round(luma_score, 3),
        signal_score=round(signal_score, 3),
        quality_score=quality_score,
        rejected=bool(reject_reason),
        reject_reason=reject_reason,
        metadata={
            "laplacian_variance": round(laplacian_variance, 3),
            "contrast_std": round(contrast_std, 3),
            "luma_mean": round(luma_mean, 3),
            "edge_density": round(edge_density, 3),
        },
    )
