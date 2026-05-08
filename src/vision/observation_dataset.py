from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import cv2
import numpy as np

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc

from src.bot.runtime_types import CanonicalTableState
from src.vision.detector import TableState
from src.vision.yolo_schema import write_dataset_yaml


logger = logging.getLogger("ObservationDataset")

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
_OBSERVATION_STATES = {"waiting_next_hand", "sitting_out", "observing_hand"}
_MEANINGFUL_BUTTONS = {"resume_hand", "im_back", "fast_fold_button"}
_MEANINGFUL_REGIONS = {"table", "board", "pot", "actions", "hero"}


class ObservationDatasetCollector:
    def __init__(
        self,
        *,
        enabled: bool = True,
        dataset_dir: str = "dataset/runtime_observation",
        capture_interval_s: float = 6.0,
        require_visual_change: bool = True,
        max_samples_per_session: int = 500,
    ) -> None:
        self.enabled = bool(enabled)
        self.dataset_root = Path(dataset_dir)
        self.images_dir = self.dataset_root / "images"
        self.labels_dir = self.dataset_root / "labels"
        self.manifest_path = self.dataset_root / "captures.jsonl"
        self.capture_interval_s = max(0.5, float(capture_interval_s or 0.5))
        self.require_visual_change = bool(require_visual_change)
        self.max_samples_per_session = max(1, int(max_samples_per_session or 1))
        self._last_capture_at = 0.0
        self._last_capture_signature: tuple | None = None
        self._last_capture_digest: tuple[int, int, float] | None = None
        self._captured_samples = 0
        self._session_captured_samples = 0
        self._labeled_samples = 0
        self._last_label_scan_at = 0.0

        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        self._refresh_counts(force=True)
        self._ensure_dataset_yaml()

    def snapshot(self) -> dict[str, object]:
        self._refresh_counts(force=False)
        return {
            "enabled": self.enabled,
            "dataset_dir": self.dataset_root.as_posix(),
            "captured_samples": self._captured_samples,
            "labeled_samples": self._labeled_samples,
            "session_captured_samples": self._session_captured_samples,
            "max_samples_per_session": self.max_samples_per_session,
            "capture_interval_s": self.capture_interval_s,
        }

    def maybe_capture(
        self,
        frame: np.ndarray,
        canonical_state: CanonicalTableState,
        detector_state: TableState | None = None,
    ) -> Path | None:
        if not self.enabled or frame is None:
            return None
        if self._session_captured_samples >= self.max_samples_per_session:
            return None

        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        hero_participation = str(metadata.get("hero_participation") or "")
        if hero_participation not in _OBSERVATION_STATES:
            return None
        if canonical_state.hero_cards or canonical_state.legal_actions:
            return None

        visual_metadata = dict(getattr(detector_state, "metadata", {}) or {}) if detector_state is not None else {}
        if self.require_visual_change:
            if bool(visual_metadata.get("reused_visual_state", False)):
                return None
            if not bool(visual_metadata.get("visual_changed", True)):
                return None
            changed_regions = {
                str(region_name)
                for region_name in (visual_metadata.get("visual_changed_regions", []) or [])
            }
            if changed_regions and not changed_regions.intersection(_MEANINGFUL_REGIONS):
                return None

        meaningful_context = (
            canonical_state.pot > 0.0
            or bool(canonical_state.board)
            or canonical_state.street in {"PREFLOP", "FLOP", "TURN", "RIVER", "SHOWDOWN"}
            or bool(set(canonical_state.action_buttons).intersection(_MEANINGFUL_BUTTONS))
        )
        if not meaningful_context:
            return None

        now = time.monotonic()
        if (now - self._last_capture_at) < self.capture_interval_s:
            return None

        capture_signature = (
            hero_participation,
            canonical_state.street,
            round(float(canonical_state.pot or 0.0), 1),
            tuple(canonical_state.board),
            tuple(canonical_state.action_buttons),
        )
        frame_digest = self._frame_digest(frame)
        if capture_signature == self._last_capture_signature and frame_digest == self._last_capture_digest:
            return None

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"obs_{hero_participation}_{timestamp}.jpg"
        image_path = self.images_dir / filename
        if not cv2.imwrite(str(image_path), frame):
            logger.warning("Capture observation YOLO ignoree: impossible d'ecrire %s", image_path)
            return None

        manifest_payload = {
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "image_path": image_path.as_posix(),
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "hero_participation": hero_participation,
            "observation_mode": bool(metadata.get("observation_mode", False)),
            "observation_street": str(metadata.get("observation_street") or ""),
            "pot": round(float(canonical_state.pot or 0.0), 1),
            "board": list(canonical_state.board),
            "hero_cards": list(canonical_state.hero_cards),
            "action_buttons": list(canonical_state.action_buttons),
            "legal_actions": list(canonical_state.legal_actions),
            "visual_changed_regions": list(visual_metadata.get("visual_changed_regions", []) or []),
            "visual_refresh_due": bool(visual_metadata.get("visual_refresh_due", False)),
        }
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest_payload, ensure_ascii=True) + "\n")

        self._last_capture_at = now
        self._last_capture_signature = capture_signature
        self._last_capture_digest = frame_digest
        self._captured_samples += 1
        self._session_captured_samples += 1
        self._ensure_dataset_yaml()
        logger.info(
            "Sample observation capture pour YOLO: %s (mode=%s street=%s pot=%.1f)",
            image_path.as_posix(),
            hero_participation,
            canonical_state.street,
            float(canonical_state.pot or 0.0),
        )
        return image_path

    def _frame_digest(self, frame: np.ndarray) -> tuple[int, int, float]:
        preview = cv2.resize(frame, (48, 32), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
        return (
            int(gray.mean()),
            int(gray.std()),
            round(float(gray[::4, ::4].mean()), 2),
        )

    def _refresh_counts(self, *, force: bool) -> None:
        if not force and (time.monotonic() - self._last_label_scan_at) < 10.0:
            return
        self._captured_samples = self._count_files(self.images_dir)
        self._labeled_samples = self._count_files(self.labels_dir, suffixes={".txt"})
        self._last_label_scan_at = time.monotonic()

    @staticmethod
    def _count_files(directory: Path, suffixes: set[str] | None = None) -> int:
        if not directory.exists():
            return 0
        allowed_suffixes = {suffix.lower() for suffix in (suffixes or _IMAGE_SUFFIXES)}
        return sum(
            1
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix.lower() in allowed_suffixes
        )

    def _ensure_dataset_yaml(self) -> None:
        yaml_path = self.dataset_root / "dataset.yaml"
        if yaml_path.exists():
            return
        write_dataset_yaml(
            output_path=yaml_path,
            dataset_root=self.dataset_root.resolve(),
            train_images_dir=self.images_dir.resolve(),
            val_images_dir=self.images_dir.resolve(),
        )
