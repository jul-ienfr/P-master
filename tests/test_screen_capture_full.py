# -*- coding: utf-8 -*-
"""Tests de ScreenCapture (src/vision/capture.py) avec backends mockés."""
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision import capture as capture_module
from src.vision.capture import ScreenCapture, WgcWindowCapture


class FakeDxcam:
    def __init__(self):
        self.grabs = []

    def grab(self, region=None):
        self.grabs.append(region)
        return np.full((60, 120, 3), 77, dtype=np.uint8)


@pytest.fixture()
def dxcam_capture(monkeypatch):
    fake_dxcam = types.SimpleNamespace(create=lambda output_color: FakeDxcam())
    monkeypatch.setattr(capture_module, "dxcam", fake_dxcam)
    cap = ScreenCapture(target_fps=0)
    return cap


def test_wgc_window_capture_raises_when_module_missing(monkeypatch):
    monkeypatch.setattr(capture_module, "WINDOWS_CAPTURE_AVAILABLE", False)
    with pytest.raises(RuntimeError):
        WgcWindowCapture(1234)


def test_is_valid_dxcam_region_rules():
    assert ScreenCapture._is_valid_dxcam_region((0, 0, 100, 100)) is True
    assert ScreenCapture._is_valid_dxcam_region(None) is False
    assert ScreenCapture._is_valid_dxcam_region((1, 2, 3)) is False
    assert ScreenCapture._is_valid_dxcam_region((10, 10, 5, 50)) is False
    assert ScreenCapture._is_valid_dxcam_region((-32000, 0, 100, 100)) is False


def test_start_rejects_when_no_backend():
    cap = ScreenCapture.__new__(ScreenCapture)
    cap.backend = "none"
    cap.is_capturing = False
    assert cap.start() is False


def test_start_selects_dxcam_mode_with_valid_region(dxcam_capture):
    assert dxcam_capture.start(region=(10, 10, 300, 200)) is True
    assert dxcam_capture.is_capturing is True
    assert dxcam_capture.capture_mode == "dxcam"
    # second start : no-op (déjà en capture)
    assert dxcam_capture.start(region=(0, 0, 100, 100)) is True
    assert dxcam_capture.region == (10, 10, 300, 200)


def test_get_latest_frame_dxcam_returns_frame(dxcam_capture):
    dxcam_capture.start(region=(10, 10, 130, 70))
    frame = dxcam_capture.get_latest_frame()
    assert frame is not None and frame.shape == (60, 120, 3)
    assert dxcam_capture.camera.grabs[-1] == (10, 10, 130, 70)


def test_get_latest_frame_without_capture_is_none(dxcam_capture):
    assert dxcam_capture.get_latest_frame() is None


def test_stop_clears_state(dxcam_capture):
    dxcam_capture.start()
    stopped = []
    dxcam_capture._wgc_session = types.SimpleNamespace(stop=lambda: stopped.append(True))
    dxcam_capture.stop()
    assert dxcam_capture.is_capturing is False
    assert dxcam_capture._wgc_session is None
    assert stopped == [True]


def test_target_fps_throttles_frames(dxcam_capture, monkeypatch):
    cap = dxcam_capture
    cap.target_fps = 30
    cap.start()
    times = iter([0.0, 0.2])
    monkeypatch.setattr(capture_module.time, "perf_counter", lambda: next(times))
    assert cap.get_latest_frame() is None  # première frame : horloge initialisée
    assert cap.get_latest_frame() is not None  # délai écoulé -> frame


def test_window_mode_uses_win32_stack(monkeypatch, tmp_path):
    """Mode window : la pile win32 est mockée de bout en bout."""
    import win32con  # noqa: F401  (présent dans l'env)

    frame_bgra = np.zeros((20, 40, 4), dtype=np.uint8)
    frame_bgra[:, :, 0] = 255

    class FakeBitmap:
        def CreateCompatibleBitmap(self, dc, w, h):
            self.w, self.h = w, h

        def GetInfo(self):
            return {"bmWidth": self.w, "bmHeight": self.h}

        def GetBitmapBits(self, full):
            return frame_bgra.tobytes()

        def GetHandle(self):
            return 7

    fake_win32gui = types.SimpleNamespace(
        GetClientRect=lambda hwnd: (0, 0, 40, 20),
        ClientToScreen=lambda hwnd, pt: (5, 6),
        IsIconic=lambda hwnd: False,
        GetDC=lambda arg: 11,
        ReleaseDC=lambda arg, handle: None,
        DeleteObject=lambda handle: None,
    )
    fake_win32ui = types.SimpleNamespace(
        CreateDCFromHandle=lambda handle: types.SimpleNamespace(
            CreateCompatibleDC=lambda: types.SimpleNamespace(
                SelectObject=lambda bitmap: None,
                BitBlt=lambda *args: None,
                DeleteDC=lambda: None,
                GetSafeHdc=lambda: 13,
            )
        ),
        CreateBitmap=lambda: FakeBitmap(),
    )
    fake_user32 = types.SimpleNamespace(PrintWindow=lambda hwnd, hdc, flags: 1)

    monkeypatch.setattr(capture_module.win32gui, "GetClientRect", fake_win32gui.GetClientRect)
    monkeypatch.setattr(capture_module.win32gui, "ClientToScreen", fake_win32gui.ClientToScreen)
    monkeypatch.setattr(capture_module.win32gui, "IsIconic", fake_win32gui.IsIconic)
    monkeypatch.setattr(capture_module.win32gui, "GetDC", fake_win32gui.GetDC)
    monkeypatch.setattr(capture_module.win32gui, "ReleaseDC", fake_win32gui.ReleaseDC)
    monkeypatch.setattr(capture_module.win32gui, "DeleteObject", fake_win32gui.DeleteObject)
    monkeypatch.setattr(capture_module, "win32ui", fake_win32ui)
    monkeypatch.setattr(
        capture_module,
        "ctypes",
        types.SimpleNamespace(windll=types.SimpleNamespace(user32=fake_user32)),
    )

    cap = ScreenCapture.__new__(ScreenCapture)
    cap.target_fps = 0
    cap.prefer_window_capture = True
    cap.region = None
    cap.window_hwnd = 555
    cap.backend = "dxcam"
    cap.capture_mode = "window"
    cap.is_capturing = True
    cap.camera = None
    cap._wgc_session = None
    cap._wgc_failures = 0

    frame = cap._capture_window_frame()
    assert frame is not None
    assert frame.shape == (20, 40, 3)


def test_capture_window_frame_returns_none_without_hwnd():
    cap = ScreenCapture.__new__(ScreenCapture)
    cap.window_hwnd = None
    assert cap._capture_window_frame() is None


def test_try_start_wgc_falls_back_after_timeout(monkeypatch):
    cap = ScreenCapture.__new__(ScreenCapture)
    cap._wgc_session = None
    cap._wgc_failures = 0

    class NeverReady:
        def get_frame(self):
            return None

        def stop(self):
            self.stopped = True

    session = NeverReady()
    monkeypatch.setattr(capture_module, "WgcWindowCapture", lambda hwnd: session)
    sleeps = []
    monkeypatch.setattr(capture_module.time, "sleep", lambda s: sleeps.append(s))
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(capture_module.time, "perf_counter", lambda: next(clock))
    assert cap._try_start_wgc(42) is False
    assert getattr(session, "stopped", False) is True
