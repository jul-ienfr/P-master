# -*- coding: utf-8 -*-
"""Tests des branches restantes de ScreenCapture : window mode, wgc fps, imagegrab bbox."""
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision import capture as capture_module
from src.vision.capture import ScreenCapture


def bare_capture(mode, **attrs):
    cap = ScreenCapture.__new__(ScreenCapture)
    cap.target_fps = 0
    cap.is_capturing = True
    cap.capture_mode = mode
    cap.region = None
    cap.window_hwnd = 42
    cap.camera = None
    cap._wgc_session = None
    cap._wgc_failures = 0
    for key, value in attrs.items():
        setattr(cap, key, value)
    return cap


def test_get_latest_frame_wgc_without_session_returns_none():
    cap = bare_capture("wgc")
    assert cap.get_latest_frame() is None


def test_get_latest_frame_wgc_respects_target_fps(monkeypatch):
    session = types.SimpleNamespace(get_frame=lambda: np.zeros((10, 10, 3), dtype=np.uint8))
    cap = bare_capture("wgc", target_fps=30, _wgc_session=session)
    times = iter([0.0])
    monkeypatch.setattr(capture_module.time, "perf_counter", lambda: next(times, 99.0))
    assert cap.get_latest_frame() is None  # première frame : horloge initialisée


def test_get_latest_frame_wgc_empty_frame_returns_none():
    session = types.SimpleNamespace(get_frame=lambda: np.zeros((0,), dtype=np.uint8))
    cap = bare_capture("wgc", _wgc_session=session)
    assert cap.get_latest_frame() is None


def test_get_latest_frame_window_mode_delegates(monkeypatch):
    calls = []
    frame = np.zeros((12, 24, 3), dtype=np.uint8)

    def fake_window_frame():
        calls.append(1)
        return frame

    cap = bare_capture("window", _capture_window_frame=fake_window_frame)
    result = cap.get_latest_frame()
    assert result is not None and result.shape == (12, 24, 3)
    assert calls == [1]


def test_get_latest_frame_dxcam_without_camera_returns_none():
    cap = bare_capture("dxcam")
    assert cap.get_latest_frame() is None


def test_get_latest_frame_imagegrab_with_region_uses_bbox(monkeypatch):
    from PIL import Image

    grabs = []

    def grab(all_screens=False, bbox=None):
        grabs.append(bbox or all_screens)
        return Image.new("RGB", (20, 10), (1, 2, 3))

    fake_pil = types.SimpleNamespace(grab=grab)
    monkeypatch.setattr(capture_module, "ImageGrab", fake_pil)

    cap = bare_capture("imagegrab", region=(5, 6, 25, 16))
    frame = cap.get_latest_frame()
    assert frame is not None and frame.shape == (10, 20, 3)
    assert grabs == [(5, 6, 25, 16)]


def test_get_latest_frame_unknown_mode_returns_none():
    cap = bare_capture("mystery-mode")
    assert cap.get_latest_frame() is None


def test_stop_with_wgc_session_stops_it():
    stopped = []
    session = types.SimpleNamespace(stop=lambda: stopped.append(1))
    cap = bare_capture("wgc", _wgc_session=session)
    cap.is_capturing = False
    cap.stop()
    assert stopped == [1]
    assert cap._wgc_session is None


def test_start_prefers_window_capture_when_enabled(monkeypatch):
    started_kwargs = {}

    class FakeDxcam:
        def grab(self, region=None):
            return np.zeros((5, 5, 3), dtype=np.uint8)

    monkeypatch.setattr(capture_module, "dxcam", types.SimpleNamespace(create=lambda output_color: FakeDxcam()))

    cap = ScreenCapture.__new__(ScreenCapture)
    cap.target_fps = 0
    cap.prefer_window_capture = True
    cap.backend = "dxcam"
    cap.capture_mode = "dxcam"
    cap.is_capturing = False
    cap.camera = None
    cap._wgc_session = None
    cap._wgc_failures = 0
    cap.window_hwnd = 7
    cap.region = (0, 0, 50, 50)

    # _try_start_wgc échoue -> repli dxcam avec région
    monkeypatch.setattr(cap, "_try_start_wgc", lambda hwnd: False)
    assert cap.start(region=(0, 0, 50, 50)) is True
    assert started_kwargs == {}  # pas utilisé dans ce chemin
