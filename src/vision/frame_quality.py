from __future__ import annotations

import time

import cv2
import numpy as np

from src.runtime.evidence_models import FrameQualityReport


def _clamp_score(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _normalize_blur_score(variance: float) -> float:
    return _clamp_score(variance / 250.0)


def _normalize_contrast_score(stddev: float) -> float:
    return _clamp_score(stddev / 64.0)


def _normalize_luma_score(mean: float) -> float:
    distance = abs(float(mean) - 127.5)
    return _clamp_score(1.0 - (distance / 127.5))


def analyze_frame_quality(frame: np.ndarray, *, captured_at: float | None = None, max_age_ms: float = 300.0) -> FrameQualityReport:
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        return FrameQualityReport(rejected=True, reject_reason="empty_frame")

    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast_std = float(gray.std())
    luma_mean = float(gray.mean())
    now = time.monotonic()
    frame_age_ms = max(0.0, (now - float(captured_at or now)) * 1000.0)

    blur_score = _normalize_blur_score(laplacian_variance)
    contrast_score = _normalize_contrast_score(contrast_std)
    luma_score = _normalize_luma_score(luma_mean)
    freshness_score = _clamp_score(1.0 - (frame_age_ms / max(max_age_ms, 1.0)))
    quality_score = round((blur_score * 0.35) + (contrast_score * 0.25) + (luma_score * 0.20) + (freshness_score * 0.20), 3)

    reject_reason = ""
    if frame_age_ms > max_age_ms:
        reject_reason = "stale_frame"
    elif blur_score < 0.08:
        reject_reason = "blur_too_high"
    elif contrast_score < 0.08:
        reject_reason = "contrast_too_low"

    return FrameQualityReport(
        frame_timestamp=float(captured_at or now),
        frame_age_ms=round(frame_age_ms, 3),
        width=int(width),
        height=int(height),
        blur_score=round(blur_score, 3),
        contrast_score=round(contrast_score, 3),
        luma_score=round(luma_score, 3),
        quality_score=quality_score,
        rejected=bool(reject_reason),
        reject_reason=reject_reason,
        metadata={
            "laplacian_variance": round(laplacian_variance, 3),
            "contrast_std": round(contrast_std, 3),
            "luma_mean": round(luma_mean, 3),
            "freshness_score": round(freshness_score, 3),
        },
    )
