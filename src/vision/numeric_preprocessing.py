from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np


def preprocess_numeric_variants(image_crop: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    if image_crop is None or not isinstance(image_crop, np.ndarray) or image_crop.size == 0:
        return []

    variants: List[Tuple[str, np.ndarray]] = [("original", image_crop)]
    gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY) if image_crop.ndim == 3 else image_crop.copy()
    normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    gray_bgr = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)
    variants.append(("gray_normalized", gray_bgr))

    upscaled = cv2.resize(normalized, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    variants.append(("upscaled_x2", cv2.cvtColor(upscaled, cv2.COLOR_GRAY2BGR)))

    _, otsu = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("threshold_otsu", cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)))

    adaptive = cv2.adaptiveThreshold(upscaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
    variants.append(("threshold_adaptive", cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR)))

    inverted = cv2.bitwise_not(adaptive)
    variants.append(("threshold_inverted", cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)))

    denoised = cv2.medianBlur(upscaled, 3)
    variants.append(("denoised", cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)))
    return variants
