"""Tests de crop_quality et des exclusivités de modes opérateur."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.operator_snapshot import OperatorSnapshotMixin
from src.runtime.session import RuntimeSessionMixin
from src.vision.crop_quality import analyze_crop_quality


def test_analyze_crop_quality_rejects_empty_crop():
    report = analyze_crop_quality("pot", None)
    assert report.rejected is True
    assert report.reject_reason == "empty_crop"
    report = analyze_crop_quality("pot", np.zeros((0,), dtype=np.uint8))
    assert report.reject_reason == "empty_crop"


def test_analyze_crop_quality_flags_blurry_and_low_contrast():
    blurry = np.full((20, 40), 128, dtype=np.uint8)  # uniforme -> net = 0
    report = analyze_crop_quality("hero", cv2_cvt(blurry))
    assert report.reject_reason in {"crop_blurry", "crop_low_contrast"}


def cv2_cvt(gray):
    import cv2

    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class Controller(OperatorSnapshotMixin, RuntimeSessionMixin):
    def __init__(self):
        self.operator_controls = {}
        self.events = []
        self.published = []

    def _push_runtime_event(self, kind, message, **context):
        self.events.append((kind, message))

    def _publish_runtime_bridge_state(self, force=False):
        self.published.append(force)

    def _copy_table_state(self, state):
        return state


def test_update_operator_controls_exclusive_modes_matrix():
    c = Controller()
    # shadow désactive assisted/observation/manual
    c.update_operator_controls({"shadow_mode_enabled": True})
    assert c.operator_controls["shadow_mode_enabled"] is True
    assert c.operator_controls["assisted_mode_enabled"] is False
    assert c.operator_controls["observation_mode_enabled"] is False
    assert c.operator_controls["manual_override_enabled"] is False

    # manual override désactive les autres
    c.update_operator_controls({"manual_override_enabled": True})
    assert c.operator_controls["shadow_mode_enabled"] is False
    assert c.operator_controls["assisted_mode_enabled"] is False
    assert c.operator_controls["observation_mode_enabled"] is False


def test_capture_async_skips_when_task_already_running():
    c = Controller()
    calls = []

    class Collector:
        def maybe_capture(self, **kwargs):
            calls.append(kwargs)

    c.observation_dataset = Collector()
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    canonical = SimpleNamespace(model_copy=lambda deep: SimpleNamespace(metadata={}))
    detector_state = None
    c._copy_table_state = lambda state: state

    async def scenario():
        c._observation_capture_task_running = True  # tâche déjà en cours
        await c._capture_observation_dataset_sample_async(frame, canonical, detector_state)
        assert calls == []
        assert c._observation_capture_task_running is True

    asyncio.run(scenario())


def test_analyze_crop_quality_accepts_detailed_crop():
    rng = np.random.default_rng(5)
    crop = rng.integers(0, 255, size=(40, 80), dtype=np.uint8)
    report = analyze_crop_quality("POT ", crop)
    assert report.field_name == "pot"
    assert report.rejected is False
    assert report.reject_reason == ""
    assert report.width == 80 and report.height == 40
    assert 0.0 <= report.quality_score <= 1.0
    assert 0.0 <= report.blur_score <= 1.0


def test_parse_bool_flag_numeric_branches_direct():
    from src.runtime.session import parse_bool_flag

    assert parse_bool_flag(2.5) is True
    assert parse_bool_flag("on") is True


def test_capture_async_noop_without_collector():
    c = Controller()
    c.observation_dataset = None

    async def scenario():
        await c._capture_observation_dataset_sample_async(
            np.zeros((4, 4, 3), dtype=np.uint8),
            SimpleNamespace(model_copy=lambda deep: SimpleNamespace(metadata={})),
            SimpleNamespace(),
        )

    asyncio.run(scenario())


def test_capture_sync_noop_without_collector():
    c = Controller()
    c.observation_dataset = None
    # ne doit rien faire ni lever
    c._capture_observation_dataset_sample(
        np.zeros((4, 4, 3), dtype=np.uint8), SimpleNamespace(metadata={}), SimpleNamespace()
    )


def test_template_store_area_helpers():
    from src.vision.template_store import _estimate_table_bounds, _is_area, _normalize_area

    assert _is_area({"x1": 1, "y1": 2, "x2": 3, "y2": 4}) is True
    assert _is_area({"x1": 1}) is False
    assert _is_area("nope") is False
    assert _normalize_area({"x1": "5", "y1": 6, "x2": 7.0, "y2": 8}) == (5, 6, 7, 8)
    assert _estimate_table_bounds({}) == (48, 48)
    assert _estimate_table_bounds({"zone": {"x1": 10, "y1": 20, "x2": 30, "y2": 40}}) == (
        78,
        88,
    )


def test_numeric_consensus_tolerance_boundary():
    from src.vision.numeric_consensus import NumericConsensus

    consensus = NumericConsensus(history_size=2, tolerance_ratio=0.0)
    consensus.update(100.0)
    result = consensus.update(101.0)  # marge minimale 0.01 -> non similaire
    assert result.support == 1
    # history_size < 3 : une seule lecture suffit à confirmer
    assert result.state == "confirmed"
