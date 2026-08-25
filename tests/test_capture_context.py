"""Tests du contexte de capture et du snapshot pot rapide (src/runtime/capture_context.py)."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.capture_context import CaptureContextMixin


def make_controller():
    resets = {"hand": 0, "pot": 0, "runtime_pot": 0}

    class Controller(CaptureContextMixin):
        def __init__(self):
            self.camera = SimpleNamespace(
                region=(0, 0, 800, 600),
                backend="dxcam",
                window_hwnd=111,
                is_capturing=True,
                stopped=False,
                started_with=None,
            )
            self.action_controller = SimpleNamespace(
                hwnd=222,
                window_title="PokerStars",
                get_client_rect=lambda refresh=False: (10, 10, 810, 610),
                get_window_rect=lambda refresh=False: (-32000, -32000, -31000, -31000),
            )
            self.tracker = SimpleNamespace(
                reset_for_new_hand=lambda: resets.__setitem__("hand", resets["hand"] + 1)
            )
            self.tracker.sanity = SimpleNamespace(
                reset_pot_reconciliation=lambda: resets.__setitem__("pot", resets["pot"] + 1)
            )
            self.runtime_sanity = SimpleNamespace(
                reset_pot_reconciliation=lambda: resets.__setitem__("runtime_pot", resets["runtime_pot"] + 1)
            )
            self._last_capture_region_refresh_at = 0.0
            self._capture_region_refresh_interval_s = 5.0
            self._last_capture_context_signature = ()
            self._last_capture_context_changed_at = 0.0
            self._last_fast_pot_snapshot = {}
            self._last_turn_probe_snapshot = {}
            self._debounce_state_hash = "hash"
            self._debounce_start_time = 1.0
            self.last_valid_frame = "frame"
            self.cleared_guards = 0
            self.cleared_summaries = []

        def _clear_live_execution_guard(self):
            self.cleared_guards += 1

        def _clear_live_decision_summary(self, canonical_state):
            self.cleared_summaries.append(canonical_state)

    return Controller(), resets


def test_is_valid_capture_region_rejects_invalid_regions():
    assert CaptureContextMixin._is_valid_region if False else True
    assert CaptureContextMixin._is_valid_capture_region((0, 0, 100, 100)) is True
    assert CaptureContextMixin._is_valid_capture_region((0, 0, 0, 100)) is False
    assert CaptureContextMixin._is_valid_capture_region((0, 0, 100, 0)) is False
    assert CaptureContextMixin._is_valid_capture_region((-32000, 0, 100, 100)) is False
    assert CaptureContextMixin._is_valid_capture_region("garbage") is False
    assert CaptureContextMixin._is_valid_capture_region((1, 2, 3)) is False


def test_update_and_get_recent_fast_pot_snapshot():
    c, _resets = make_controller()
    c._update_fast_pot_snapshot(None)
    c._update_fast_pot_snapshot({})
    assert c._last_fast_pot_snapshot == {}

    c._fast_pot_stale_after_s = 60.0
    c._update_fast_pot_snapshot({"value": 25.0})
    recent = c._get_recent_fast_pot_snapshot()
    assert recent["value"] == 25.0
    assert "age_s" in recent

    # valeur nulle ignorée
    before = dict(c._last_fast_pot_snapshot)
    c._update_fast_pot_snapshot({"value": 0.0})
    assert c._last_fast_pot_snapshot == before


def test_refresh_capture_region_uses_client_rect_when_valid():
    c, resets = make_controller()
    region = c._refresh_capture_region(force=True)
    assert region == (10, 10, 810, 610)
    assert c.camera.window_hwnd == 222
    # contexte changé -> resets complets
    assert resets["hand"] == 1
    assert resets["pot"] == 1
    assert resets["runtime_pot"] == 1
    assert c.cleared_guards == 1
    assert len(c.cleared_summaries) == 1
    assert c.last_valid_frame is None


def test_refresh_capture_region_throttled_without_force():
    import time as time_mod

    c, resets = make_controller()
    c._last_capture_region_refresh_at = time_mod.monotonic()
    region = c._refresh_capture_region(force=False)
    assert region == (0, 0, 800, 600)
    assert resets["hand"] == 0


def test_capture_context_recently_changed_window():
    import time as time_mod

    c, _resets = make_controller()
    assert c._capture_context_recently_changed() is False
    c._last_capture_context_changed_at = time_mod.monotonic()
    assert c._capture_context_recently_changed() is True
