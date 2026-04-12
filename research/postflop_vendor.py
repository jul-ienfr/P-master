"""Compatibility bundles for desktop-postflop and wasm-postflop reuse."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from poker.decisionmaker.tree_presets import list_tree_presets


_SOURCE_REPOSITORIES: tuple[dict[str, str], ...] = (
    {
        "name": "desktop-postflop",
        "url": "https://github.com/b-inary/desktop-postflop",
    },
    {
        "name": "wasm-postflop",
        "url": "https://github.com/b-inary/wasm-postflop",
    },
    {
        "name": "postflop-solver",
        "url": "https://github.com/b-inary/postflop-solver",
    },
)


def build_postflop_bundle(target: str = "desktop-postflop") -> dict[str, Any]:
    presets = []
    for preset in list_tree_presets():
        presets.append(
            {
                "preset_id": preset.preset_id,
                "title": preset.title,
                "description": preset.description,
                "family": preset.family,
                "street_focus": preset.street_focus,
                "target_profile": target,
                "desktop_profile": preset.desktop_profile,
                "wasm_profile": preset.wasm_profile,
                "compression": preset.compression,
                "default_time_budget_ms": preset.default_time_budget_ms,
                "tags": list(preset.tags),
                "solve_request": preset.build_solve_request().to_dict(),
                "spot_snapshot": preset.build_spot_snapshot().to_dict(),
            }
        )

    return {
        "format_version": "postflop_bridge_v1",
        "generated_by": "PokerMaster",
        "target": target,
        "source_repositories": list(_SOURCE_REPOSITORIES),
        "presets": presets,
    }


def summarize_postflop_bundle(
    output_dir: str | Path = "research/vendor/postflop",
) -> dict[str, Any]:
    base_path = Path(output_dir)
    bundle_targets = ("desktop-postflop", "wasm-postflop")
    files = [
        {
            "target": target,
            "path": str((base_path / f"{target}.presets.json").as_posix()),
            "exists": (base_path / f"{target}.presets.json").exists(),
        }
        for target in bundle_targets
    ]
    return {
        "format_version": "postflop_bridge_v1",
        "targets": list(bundle_targets),
        "preset_count": len(list_tree_presets()),
        "source_repositories": list(_SOURCE_REPOSITORIES),
        "output_dir": str(base_path.as_posix()),
        "files": files,
    }


def write_postflop_bundle(
    output_dir: str | Path = "research/vendor/postflop",
) -> list[str]:
    base_path = Path(output_dir)
    base_path.mkdir(parents=True, exist_ok=True)
    written_paths: list[str] = []
    for target in ("desktop-postflop", "wasm-postflop"):
        bundle = build_postflop_bundle(target)
        file_path = base_path / f"{target}.presets.json"
        file_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written_paths.append(str(file_path.as_posix()))
    return written_paths
