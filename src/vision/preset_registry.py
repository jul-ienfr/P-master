from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from src.vision.site_adapter import SiteAdapterProtocol


@dataclass(frozen=True)
class PresetManifest:
    path: Path
    display_name: str
    site_key: str
    theme_key: str
    manifest: dict[str, Any]


@dataclass(frozen=True)
class PresetRegistry:
    manifests: tuple[Path, ...]

    @classmethod
    def from_adapter(cls, adapter: SiteAdapterProtocol) -> "PresetRegistry":
        manifests = tuple(path for path in adapter.preset_manifests() if isinstance(path, Path))
        return cls(manifests=manifests)

    @classmethod
    def from_paths(cls, manifests: Iterable[Path]) -> "PresetRegistry":
        return cls(manifests=tuple(Path(path).resolve() for path in manifests))

    def all(self) -> Sequence[Path]:
        return self.manifests

    def existing(self) -> tuple[Path, ...]:
        return tuple(path for path in self.manifests if path.is_file())

    def load(self) -> tuple[PresetManifest, ...]:
        loaded: list[PresetManifest] = []
        for path in self.existing():
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            identity = dict(manifest.get("identity", {}) or {})
            loaded.append(
                PresetManifest(
                    path=path,
                    display_name=str(manifest.get("display_name") or path.stem),
                    site_key=str(identity.get("site") or identity.get("network") or ""),
                    theme_key=str(identity.get("theme") or ""),
                    manifest=manifest,
                )
            )
        return tuple(loaded)

    def find_by_display_name(self, display_name: str) -> Optional[PresetManifest]:
        target = str(display_name or "").strip().lower()
        if not target:
            return None
        for preset in self.load():
            if preset.display_name.strip().lower() == target:
                return preset
        return None
