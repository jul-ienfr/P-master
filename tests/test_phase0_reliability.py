"""Tests Phase 0 : scoring fenêtre (classe/process/regex), split cartes géométrique,
hash presets, bornes Active Learning."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.action_controller import ActionController
from src.vision.active_learning_writer import ActiveLearningWriter
from src.vision.models import BUILTIN_PRESET_MANIFESTS, DetectionResult, TableState
from src.vision.table_geometry import (
    TableGeometry,
    classify_card_detections,
)
from src.vision.template_store import load_presets, verify_preset_assets

# --- P0.3 : scoring fenêtre pondéré ---


def _install_windows(monkeypatch, windows):
    def fake_enum_windows(callback, context):
        for hwnd in windows:
            callback(hwnd, context)

    monkeypatch.setattr("src.bot.action_controller.win32gui.EnumWindows", fake_enum_windows)
    monkeypatch.setattr("src.bot.action_controller.win32gui.IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(
        "src.bot.action_controller.win32gui.GetWindowText", lambda hwnd: windows[hwnd][0]
    )
    monkeypatch.setattr(
        "src.bot.action_controller.win32gui.GetWindowRect", lambda hwnd: windows[hwnd][1]
    )


def test_window_scoring_prefers_class_and_process_match(monkeypatch):
    # Deux fenêtres au même titre ; seule l'une a classe + process attendus.
    windows = {
        1: ("NLHE 100/200", (0, 0, 800, 600)),
        2: ("NLHE 100/200", (0, 0, 800, 600)),
    }
    _install_windows(monkeypatch, windows)
    monkeypatch.setattr(
        "src.bot.action_controller.get_window_class_name",
        lambda hwnd: "PokerStarsTableFrameClass" if hwnd == 2 else "OtherClass",
    )
    monkeypatch.setattr(
        "src.bot.action_controller.get_window_process_name",
        lambda hwnd: "PokerStars.exe" if hwnd == 2 else "other.exe",
    )

    controller = ActionController.__new__(ActionController)
    controller.window_title_keywords = ""
    controller.hwnd = None
    controller.window_title = ""
    controller.site_profiles = {
        "PokerStars": {
            "window_class": "PokerStarsTableFrameClass",
            "process_name": "PokerStars.exe",
        }
    }
    controller._primary_keywords = []
    controller._profile_matchers = controller._build_profile_matchers(controller.site_profiles)

    best = controller._select_best_window([])
    assert best is not None and best[0] == 2


def test_title_regex_profile_scores(monkeypatch):
    windows = {5: ("Hold'em No Limit 100/200 — Table 12", (0, 0, 400, 300))}
    _install_windows(monkeypatch, windows)
    monkeypatch.setattr("src.bot.action_controller.get_window_class_name", lambda hwnd: "")
    monkeypatch.setattr("src.bot.action_controller.get_window_process_name", lambda hwnd: "")

    controller = ActionController.__new__(ActionController)
    controller.site_profiles = {"Winamax": {"title_regex": r"Hold'em No Limit\s+\d+/\d+"}}
    controller._primary_keywords = []  # aucun mot-clé : seul le regex doit porter
    controller._profile_matchers = controller._build_profile_matchers(controller.site_profiles)

    score, detail = controller._score_window_signals(5, windows[5][0])
    assert score >= 5 and "Winamax" in detail


def test_lobby_penalty_kept(monkeypatch):
    score = ActionController._score_window_title("PokerStars Lobby", ["PokerStars"])
    assert score <= 0


# --- P0.4 : split board/héro géométrique ---


def _card(cls_name, bbox):
    return DetectionResult(class_name=cls_name, confidence=0.9, bbox=bbox)


def test_classify_cards_uses_preset_geometry_over_heuristic():
    # Frame 1000x500 : heuristique y>290 classerait y=280 en board.
    # La géométrie place le héro en bas à droite (y normalisé 0.62..0.90).
    geometry = TableGeometry(
        regions={
            "board": (0.10, 0.10, 0.90, 0.40),
            "hero": (0.30, 0.62, 0.70, 0.95),
        },
        table_size=(1000, 500),
    )
    cards = [
        _card("Ah", (330, 320, 380, 380)),  # dans hero box
        _card("Kd", (420, 120, 470, 180)),  # dans board box
        _card("Qs", (10, 20, 60, 80)),      # hors zones -> heuristique (haut) -> board
    ]
    board, hero, source = classify_card_detections(
        cards, (500, 1000), table_bbox=(0, 0, 1000, 500), geometry=geometry
    )

    assert [c.class_name for c in hero] == ["Ah"]
    assert [c.class_name for c in board] == ["Kd", "Qs"]
    assert source == "preset_geometry"


def test_classify_cards_falls_back_to_y_heuristic_without_geometry():
    cards = [
        _card("Ah", (100, 100, 150, 160)),   # haut
        _card("Kd", (100, 400, 150, 460)),   # bas (> 58% de 500)
    ]
    board, hero, source = classify_card_detections(cards, (500, 1000))

    assert [c.class_name for c in hero] == ["Kd"]
    assert [c.class_name for c in board] == ["Ah"]
    assert source == "y_heuristic"


def test_detector_remembers_preset_geometry_from_fallback(monkeypatch):
    from src.vision.detector import PokerDetector

    detector = PokerDetector.__new__(PokerDetector)
    detector.fallback_detector = SimpleNamespace(presets=[])
    detector._last_fallback_preset_name = None
    detector._last_table_geometry = None
    detector._last_table_bbox = None

    fallback_state = TableState(
        metadata={
            "fallback_preset": "PS",
            "table_bbox": [10, 20, 640, 480],
        }
    )
    preset = SimpleNamespace(name="PS", table_data={"my_cards_area": {"x1": 0, "y1": 60, "x2": 50, "y2": 90}})

    def fake_analyze(frame):
        return fallback_state

    detector.fallback_detector = SimpleNamespace(presets=[preset], analyze_frame=fake_analyze)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    detector._run_template_fallback(frame)

    assert detector._last_table_bbox == (10, 20, 640, 480)
    assert detector._last_table_geometry is not None
    assert "hero" in detector._last_table_geometry.regions


# --- P0.7 : hash presets ---


def test_builtin_manifests_point_to_stable_promoted_files():
    for relative in BUILTIN_PRESET_MANIFESTS:
        path = ROOT / relative
        assert path.is_file(), relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["lifecycle"]["status"] == "stable", relative


def test_load_presets_reports_hash_and_verification():
    manifests = [ROOT / relative for relative in BUILTIN_PRESET_MANIFESTS]
    presets = load_presets(manifests)
    assert len(presets) >= 1
    for preset in presets:
        assert isinstance(preset.preset_hash, str)
        assert preset.hash_verified is True or preset.hash_mismatches
        if preset.geometry is not None:
            assert "hero" in preset.geometry.regions or "board" in preset.geometry.regions


def test_verify_preset_assets_detects_mismatch(tmp_path):
    asset = tmp_path / "assets" / "topleft_corner.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"\x89PNG fake payload")
    manifest = {
        "assets": {"topleft_corner": "assets/topleft_corner.png"},
        "fingerprint": {
            "hash": "deadbeef",
            "asset_hashes": {"topleft_corner": "0" * 64},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verified, mismatches, preset_hash = verify_preset_assets(manifest_path)

    assert verified is False
    assert "topleft_corner" in mismatches
    assert preset_hash == "deadbeef"


def test_verify_preset_assets_passes_when_hashes_match(tmp_path):
    import hashlib

    asset = tmp_path / "assets" / "topleft_corner.png"
    asset.parent.mkdir(parents=True)
    payload = b"\x89PNG real payload"
    asset.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "assets": {"topleft_corner": "assets/topleft_corner.png"},
        "fingerprint": {"hash": "abc123", "asset_hashes": {"topleft_corner": digest}},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verified, mismatches, _ = verify_preset_assets(manifest_path)

    assert verified is True and mismatches == []


# --- P0.8 : bornes Active Learning ---


def test_active_learning_writer_quota_and_rate_limit(tmp_path, monkeypatch):
    writer = ActiveLearningWriter(max_images_per_session=2, min_interval_s=30.0)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    clock = {"now": 0.0}
    monkeypatch.setattr(
        "src.vision.active_learning_writer.time.monotonic", lambda: clock["now"]
    )

    first = writer.save_image(tmp_path / "ds", "al", frame)
    assert first is not None and first.exists()
    clock["now"] += 1.0  # < min_interval_s -> rate limit
    assert writer.save_image(tmp_path / "ds", "al", frame) is None
    clock["now"] += 100.0
    second = writer.save_image(tmp_path / "ds", "al", frame)
    assert second is not None
    clock["now"] += 100.0  # quota atteint (2/2)
    assert writer.save_image(tmp_path / "ds", "al", frame) is None
    assert writer.skipped_rate_count == 1
    assert writer.skipped_quota_count == 1
    assert writer.quota_exhausted is True


def test_active_learning_writer_labeled_pair(tmp_path, monkeypatch):
    writer = ActiveLearningWriter(max_images_per_session=5, min_interval_s=0.0)
    frame = np.full((6, 6, 3), 7, dtype=np.uint8)
    path = writer.save_labeled_image(
        tmp_path / "images", tmp_path / "labels", "al_llm", frame, "0 0.5 0.5 0.1 0.1"
    )
    assert path is not None and path.exists()
    label_path = tmp_path / "labels" / (path.stem + ".txt")
    assert label_path.exists() and "0.5" in label_path.read_text()


def test_zero_quota_disables_writes(tmp_path):
    writer = ActiveLearningWriter(max_images_per_session=0, min_interval_s=0.0)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    assert writer.save_image(tmp_path, "al", frame) is None
