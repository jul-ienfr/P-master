"""Écritures dataset "Active Learning" bornées : quota par session + rate-limit.

Sans garde, chaque fallback OpenVL/LLM écrivait une frame complète sur disque
(`cv2.imwrite`) à chaque détection incertaine ; ce bornier évite le remplissage
silencieux du disque par `dataset/needs_annotation` et `dataset/raw_images`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class ActiveLearningWriter:
    """Quota par session + intervalle minimum entre deux écritures disque."""

    def __init__(
        self,
        max_images_per_session: int = 50,
        min_interval_s: float = 30.0,
    ):
        self.max_images_per_session = max(0, int(max_images_per_session))
        self.min_interval_s = max(0.0, float(min_interval_s))
        self.written_count = 0
        self.skipped_quota_count = 0
        self.skipped_rate_count = 0
        self._last_write_monotonic = 0.0

    @property
    def quota_exhausted(self) -> bool:
        return self.written_count >= self.max_images_per_session

    def allow_write(self) -> bool:
        if self.quota_exhausted:
            self.skipped_quota_count += 1
            return False
        now = time.monotonic()
        if self.written_count > 0 and (now - self._last_write_monotonic) < self.min_interval_s:
            self.skipped_rate_count += 1
            return False
        return True

    def _record_written(self) -> None:
        self.written_count += 1
        self._last_write_monotonic = time.monotonic()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    def save_image(self, directory: str | Path, prefix: str, frame: np.ndarray) -> Path | None:
        """Écrit la frame si le bornier l'autorise ; retourne le chemin ou None."""
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return None
        if not self.allow_write():
            return None
        try:
            directory_path = Path(directory)
            directory_path.mkdir(parents=True, exist_ok=True)
            image_path = directory_path / f"{prefix}_{self._timestamp()}.jpg"
            cv2.imwrite(str(image_path), frame)
            self._record_written()
            return image_path
        except Exception as exc:
            logger.error("ActiveLearningWriter: échec d'écriture d'image: %s", exc)
            return None

    def save_labeled_image(
        self,
        image_directory: str | Path,
        labels_directory: str | Path,
        prefix: str,
        frame: np.ndarray,
        yolo_label_content: str,
    ) -> Path | None:
        """Écrit une paire image + label YOLO sous bornier ; chemin image ou None."""
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return None
        if not self.allow_write():
            return None
        try:
            image_dir_path = Path(image_directory)
            labels_dir_path = Path(labels_directory)
            image_dir_path.mkdir(parents=True, exist_ok=True)
            labels_dir_path.mkdir(parents=True, exist_ok=True)
            timestamp = self._timestamp()
            image_path = image_dir_path / f"{prefix}_{timestamp}.jpg"
            label_path = labels_dir_path / f"{prefix}_{timestamp}.txt"
            cv2.imwrite(str(image_path), frame)
            with open(label_path, "w") as handle:
                handle.write(yolo_label_content)
            self._record_written()
            return image_path
        except Exception as exc:
            logger.error("ActiveLearningWriter: échec d'écriture étiquetée: %s", exc)
            return None
