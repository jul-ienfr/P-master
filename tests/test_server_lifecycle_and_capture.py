"""Tests du lifecycle BotAPI (start/stop) et des branches de capture restantes."""
import asyncio
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "aiohttp_cors" not in sys.modules:

    class _StubResourceOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _StubCors:
        def add(self, route):
            return route

    def _stub_setup(app, defaults=None):
        return _StubCors()

    sys.modules["aiohttp_cors"] = types.SimpleNamespace(
        setup=_stub_setup,
        ResourceOptions=_StubResourceOptions,
    )

from src.api.server import BotAPI  # noqa: E402
from src.vision import capture as capture_module  # noqa: E402
from src.vision.capture import ScreenCapture  # noqa: E402


class StubHITL:
    annotations_count = 0
    target_dataset_size = 1
    is_waiting_for_human = False
    current_issue = None

    def check_convergence(self):
        return False

    def resolve_human_intervention(self, boxes):
        pass


def run(coro):
    return asyncio.run(coro)


def test_botapi_stop_is_idempotent_without_start():
    # stop() sans start() : aucun runner/site -> no-op silencieux
    async def scenario():
        api = BotAPI(StubHITL(), runtime_status_provider=lambda: {})
        await api.stop()
        await api.stop()
        return api

    api = run(scenario())
    assert api.runner is None
    assert api.site is None


def test_screen_capture_imagegrab_fallback(monkeypatch):
    from PIL import Image

    calls = []

    def grab(all_screens=False, bbox=None):
        calls.append((all_screens, bbox))
        return Image.new("RGB", (60, 30), (200, 200, 200))

    fake_pil = types.SimpleNamespace(grab=grab)
    monkeypatch.setattr(capture_module, "ImageGrab", fake_pil)
    monkeypatch.setattr(capture_module, "dxcam", None)

    cap = ScreenCapture.__new__(ScreenCapture)
    cap.target_fps = 0
    cap.prefer_window_capture = False
    cap.region = None
    cap.window_hwnd = None
    cap.backend = "imagegrab"
    cap.capture_mode = "imagegrab"
    cap.is_capturing = True
    cap.camera = None
    cap._wgc_session = None
    cap._wgc_failures = 0

    frame = cap.get_latest_frame()
    assert frame is not None
    assert frame.shape == (30, 60, 3)


def test_screen_capture_wgc_frame_path():
    frames = iter([np.zeros((20, 20, 3), dtype=np.uint8), None])
    session = types.SimpleNamespace(get_frame=lambda: next(frames), stop=lambda: None)

    cap = ScreenCapture.__new__(ScreenCapture)
    cap.target_fps = 0
    cap.is_capturing = True
    cap.capture_mode = "wgc"
    cap._wgc_session = session
    cap.camera = None
    cap.region = None

    first = cap.get_latest_frame()
    assert first is not None and first.shape == (20, 20, 3)
    # frame vide/None -> None (fenêtre non rendue)
    assert cap.get_latest_frame() is None


def test_screen_capture_dxcam_grab_failure_returns_none(monkeypatch):
    class BrokenCamera:
        def grab(self, region=None):
            raise RuntimeError("gpu gone")

    cap = ScreenCapture.__new__(ScreenCapture)
    cap.target_fps = 0
    cap.is_capturing = True
    cap.capture_mode = "dxcam"
    cap.camera = BrokenCamera()
    cap.region = None

    assert cap.get_latest_frame() is None
