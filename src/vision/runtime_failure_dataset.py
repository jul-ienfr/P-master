from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np


class RuntimeFailureDataset:
    def __init__(self, *, enabled: bool = True, dataset_dir: str = "dataset/runtime_failures") -> None:
        self.enabled = bool(enabled)
        self.dataset_root = Path(dataset_dir)
        self.manifest_path = self.dataset_root / "incidents.jsonl"
        self.images_dir = self.dataset_root / "images"
        self.crops_dir = self.dataset_root / "crops"
        if self.enabled:
            self.dataset_root.mkdir(parents=True, exist_ok=True)
            self.images_dir.mkdir(parents=True, exist_ok=True)
            self.crops_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_stem(value: object) -> str:
        text = str(value or "incident").strip()
        return "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text)[:80] or "incident"

    def _write_image(self, image: np.ndarray, destination: Path) -> Optional[Path]:
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        success = cv2.imwrite(str(destination), image)
        return destination if success else None

    def record_incident(self, payload: dict[str, Any]) -> Optional[Path]:
        if not self.enabled:
            return None
        record = dict(payload or {})
        artifact_paths = {}
        artifact_key = self._safe_stem(record.get("timestamp") or record.get("incident_id") or "incident")

        frame = record.pop("frame", None)
        if isinstance(frame, np.ndarray):
            frame_path = self._write_image(frame, self.images_dir / f"{artifact_key}.png")
            if frame_path is not None:
                artifact_paths["frame"] = str(frame_path)

        crops = record.pop("crops", None)
        crop_paths = {}
        if isinstance(crops, dict):
            for crop_name, crop_image in crops.items():
                if not isinstance(crop_image, np.ndarray):
                    continue
                crop_path = self._write_image(crop_image, self.crops_dir / f"{artifact_key}_{self._safe_stem(crop_name)}.png")
                if crop_path is not None:
                    crop_paths[str(crop_name)] = str(crop_path)

        if artifact_paths or crop_paths:
            record["artifacts"] = {
                **artifact_paths,
                "crops": crop_paths,
            }

        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        return self.manifest_path
