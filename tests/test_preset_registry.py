from pathlib import Path

from src.vision.preset_registry import PresetRegistry
from src.vision.site_adapter import PokerStarsAdapter


def test_preset_registry_from_adapter_returns_existing_pokerstars_manifest():
    registry = PresetRegistry.from_adapter(PokerStarsAdapter())

    assert registry.all()
    assert registry.existing()
    assert all(isinstance(path, Path) for path in registry.all())


def test_preset_registry_from_paths_normalizes_paths(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    registry = PresetRegistry.from_paths([manifest])

    assert registry.all() == (manifest.resolve(),)
    assert registry.existing() == (manifest.resolve(),)


def test_preset_registry_can_find_loaded_manifest_by_display_name():
    registry = PresetRegistry.from_adapter(PokerStarsAdapter())

    preset = registry.find_by_display_name("PokerStars 7 FR 6-max")

    assert preset is not None
    assert preset.display_name == "PokerStars 7 FR 6-max"
