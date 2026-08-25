"""Tests Phase 2.2 — capture hybride WGC avec fallback."""
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.vision.capture import (
    WINDOWS_CAPTURE_AVAILABLE,
    ScreenCapture,
    WgcWindowCapture,
)


class FakeWgcSession:
    def __init__(self, frames):
        self._frames = list(frames)
        self.stopped = False

    def get_frame(self):
        if self._frames:
            return self._frames.pop(0)
        return None

    def stop(self):
        self.stopped = True


@pytest.fixture
def capture():
    cap = ScreenCapture(target_fps=0)  # pas de throttle pour les tests
    yield cap
    cap.stop()


def test_wgc_selected_when_session_produces_frame(monkeypatch, capture):
    # La première frame est consommée par la sonde de démarrage.
    frames = [np.zeros((4, 4, 3), dtype=np.uint8), np.full((4, 4, 3), 7, dtype=np.uint8)]
    monkeypatch.setattr(
        "src.vision.capture.WgcWindowCapture", lambda hwnd: FakeWgcSession(frames)
    )

    assert capture.start(region=(10, 10, 100, 100), hwnd=12345) is True
    assert capture.capture_mode == "wgc"
    got = capture.get_latest_frame()
    assert got is not None and got.shape == (4, 4, 3)


def test_fallback_to_window_mode_when_wgc_never_frames(monkeypatch, capture):
    monkeypatch.setattr(
        "src.vision.capture.WgcWindowCapture",
        lambda hwnd: FakeWgcSession([]),  # aucune frame sous 1s
    )

    assert capture.start(hwnd=12345) is True
    assert capture.capture_mode != "wgc"


def test_fallback_to_window_mode_when_wgc_init_raises(monkeypatch, capture):
    def boom(hwnd):
        raise RuntimeError("pas de session")

    monkeypatch.setattr("src.vision.capture.WgcWindowCapture", boom)

    assert capture.start(hwnd=12345) is True
    assert capture.capture_mode == "window"


def test_no_hwnd_keeps_existing_backend(capture):
    if capture.backend != "dxcam":
        pytest.skip("dxcam indisponible sur cette machine")
    assert capture.start() is True
    assert capture.capture_mode == "dxcam"


def test_stop_closes_wgc_session(monkeypatch, capture):
    session = FakeWgcSession([np.zeros((2, 2, 3), dtype=np.uint8)])
    monkeypatch.setattr("src.vision.capture.WgcWindowCapture", lambda hwnd: session)

    capture.start(hwnd=999)
    assert capture.capture_mode == "wgc"

    capture.stop()
    assert session.stopped is True
    assert capture._wgc_session is None


def test_wgc_consumes_each_frame_once(monkeypatch, capture):
    # 1 pour la sonde + 2 pour le pipeline.
    frames = [
        np.zeros((3, 3, 3), dtype=np.uint8),
        np.full((3, 3, 3), 1, dtype=np.uint8),
        np.full((3, 3, 3), 2, dtype=np.uint8),
    ]
    monkeypatch.setattr(
        "src.vision.capture.WgcWindowCapture", lambda hwnd: FakeWgcSession(frames)
    )

    capture.start(hwnd=42)
    first = capture.get_latest_frame()[0, 0, 0]
    second = capture.get_latest_frame()[0, 0, 0]
    third = capture.get_latest_frame()

    assert first == 1
    assert second == 2
    assert third is None  # consommée : pas de re-lecture


@pytest.mark.integration
def test_wgc_real_smoke_local():
    """Smoke réel optionnel : nécessite une fenêtre visible et un bureau."""
    if not WINDOWS_CAPTURE_AVAILABLE:
        pytest.skip("windows-capture non installé")
    try:
        import win32gui

        hwnds = []

        def enum_cb(hwnd, acc):
            title = win32gui.GetWindowText(hwnd)
            if win32gui.IsWindowVisible(hwnd) and title and "Visual Studio Code" in title:
                acc.append(hwnd)

        win32gui.EnumWindows(enum_cb, hwnds)
    except Exception:
        pytest.skip("win32gui indisponible")
    if not hwnds:
        pytest.skip("aucune fenêtre VS Code visible")

    session = WgcWindowCapture(hwnds[0])
    deadline = time.perf_counter() + 3.0
    frame = None
    while time.perf_counter() < deadline:
        frame = session.get_frame()
        if frame is not None:
            break
        time.sleep(0.05)
    session.stop()

    assert frame is not None and frame.ndim == 3 and frame.shape[2] == 3
