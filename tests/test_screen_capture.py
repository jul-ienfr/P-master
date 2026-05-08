import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.vision.capture import ScreenCapture


class _FakeGrabber:
    def __init__(self):
        self.calls = []

    def grab(self, **kwargs):
        self.calls.append(dict(kwargs))
        return np.zeros((12, 16, 3), dtype=np.uint8)


class _FakeDxcam:
    def __init__(self):
        self.calls = []

    def grab(self, region=None):
        self.calls.append(region)
        return np.zeros((12, 16, 3), dtype=np.uint8)


def test_imagegrab_uses_all_screens_when_no_region(monkeypatch):
    fake = _FakeGrabber()
    monkeypatch.setattr("src.vision.capture.ImageGrab", fake)

    capture = ScreenCapture()
    capture.backend = "imagegrab"
    capture.capture_mode = "imagegrab"
    capture.camera = None
    capture.is_capturing = True
    capture.region = None

    frame = capture.get_latest_frame()

    assert frame is not None
    assert fake.calls == [{"all_screens": True}]


def test_imagegrab_preserves_bbox_when_region_is_set(monkeypatch):
    fake = _FakeGrabber()
    monkeypatch.setattr("src.vision.capture.ImageGrab", fake)

    capture = ScreenCapture()
    capture.backend = "imagegrab"
    capture.capture_mode = "imagegrab"
    capture.camera = None
    capture.is_capturing = True
    capture.region = (10, 20, 30, 40)

    frame = capture.get_latest_frame()

    assert frame is not None
    assert fake.calls == [{"bbox": (10, 20, 30, 40)}]


def test_start_prefers_dxcam_region_capture_by_default_even_with_hwnd(monkeypatch):
    capture = ScreenCapture()
    capture.backend = "dxcam"
    capture.camera = None
    capture.is_capturing = False

    monkeypatch.setattr("src.vision.capture.WINDOW_CAPTURE_AVAILABLE", True)

    capture.start(region=(10, 20, 30, 40), hwnd=1234)

    assert capture.capture_mode == "dxcam"
    assert capture.window_hwnd == 1234
    assert capture.region == (10, 20, 30, 40)


def test_start_can_force_window_capture_when_configured(monkeypatch):
    capture = ScreenCapture(prefer_window_capture=True)
    capture.backend = "dxcam"
    capture.camera = None
    capture.is_capturing = False

    monkeypatch.setattr("src.vision.capture.WINDOW_CAPTURE_AVAILABLE", True)

    capture.start(region=(10, 20, 30, 40), hwnd=1234)

    assert capture.capture_mode == "window"


def test_dxcam_mode_uses_grab_instead_of_buffered_stream():
    capture = ScreenCapture(target_fps=0)
    capture.backend = "dxcam"
    capture.capture_mode = "dxcam"
    capture.camera = _FakeDxcam()
    capture.is_capturing = True
    capture.region = (10, 20, 30, 40)

    frame = capture.get_latest_frame()

    assert frame is not None
    assert capture.camera.calls == [(10, 20, 30, 40)]
