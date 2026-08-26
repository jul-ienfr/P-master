"""Tests des stratégies d'injection (foreground vs ghost SendMessage)."""

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def install_fake_win32(monkeypatch, send_calls=None):
    calls = {"send": []}
    if send_calls is not None:
        calls = send_calls

    win32gui = types.SimpleNamespace(
        SendMessage=lambda hwnd, msg, wparam, lparam: calls["send"].append(
            (hwnd, msg, wparam, lparam)
        )
    )
    win32api = types.SimpleNamespace(
        SendMessage=lambda hwnd, msg, wparam, lparam: calls["send"].append(
            (hwnd, msg, wparam, lparam)
        )
    )

    class FakeWin32Con:
        MK_LBUTTON = 0x0001

    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(sys.modules, "win32con", FakeWin32Con)
    return calls


async def _fast_sleep(_delay):
    return None


def test_make_lparam_packs_coordinates():
    from src.bot.click_strategy import make_lparam

    assert make_lparam(320, 240) == (240 << 16) | (320 & 0xFFFF)


def test_ghost_click_without_hwnd_is_a_noop(monkeypatch):
    from src.bot.click_strategy import GhostClickStrategy

    install_fake_win32(monkeypatch)
    strategy = GhostClickStrategy(lambda: 0)

    async def scenario():
        clicked = await strategy.click_at(100, 200)
        await strategy.send_text("12.5")
        await strategy.press_return()
        return clicked

    assert asyncio.run(scenario()) is False


def test_ghost_click_sends_down_then_up_with_jitter(monkeypatch):
    from src.bot.click_strategy import WM_LBUTTONDOWN, WM_LBUTTONUP, GhostClickStrategy

    calls = install_fake_win32(monkeypatch)
    monkeypatch.setattr("src.bot.click_strategy.asyncio.sleep", _fast_sleep)
    strategy = GhostClickStrategy(lambda: 99)

    assert asyncio.run(strategy.click_at(100, 200)) is True
    assert len(calls["send"]) == 2
    down_hwnd, down_msg, down_wparam, down_lparam = calls["send"][0]
    up_hwnd, up_msg, _up_wparam, up_lparam = calls["send"][1]
    assert (down_msg, up_msg) == (WM_LBUTTONDOWN, WM_LBUTTONUP)
    assert down_wparam == 1  # MK_LBUTTON
    assert down_hwnd == up_hwnd == 99
    jitter_x = down_lparam & 0xFFFF
    jitter_y = (down_lparam >> 16) & 0xFFFF
    assert abs(jitter_x - 100) <= 2
    assert abs(jitter_y - 200) <= 2


def test_ghost_send_text_types_chars_and_return(monkeypatch):
    from src.bot.click_strategy import (
        VK_RETURN,
        WM_CHAR,
        WM_KEYDOWN,
        WM_KEYUP,
        GhostClickStrategy,
    )

    calls = install_fake_win32(monkeypatch)
    monkeypatch.setattr("src.bot.click_strategy.asyncio.sleep", _fast_sleep)
    strategy = GhostClickStrategy(lambda: 5)

    async def scenario():
        await strategy.send_text("12")
        await strategy.press_return()

    asyncio.run(scenario())

    char_messages = [msg for (_hwnd, msg, wparam, _l) in calls["send"] if msg == WM_CHAR]
    assert [wparam for (_h, m, wparam, _l) in calls["send"] if m == WM_CHAR] == [
        ord("1"),
        ord("2"),
    ]
    keydowns = [wparam for (_h, m, wparam, _l) in calls["send"] if m == WM_KEYDOWN]
    keyups = [wparam for (_h, m, wparam, _l) in calls["send"] if m == WM_KEYUP]
    assert len(char_messages) == 2
    assert VK_RETURN in keydowns and VK_RETURN in keyups


def test_action_controller_routes_ghost_mode(monkeypatch):
    from src.bot.action_controller import ActionController
    from src.bot.click_strategy import WM_LBUTTONDOWN, GhostClickStrategy

    calls = install_fake_win32(monkeypatch)
    monkeypatch.setattr("src.bot.click_strategy.asyncio.sleep", _fast_sleep)

    controller = ActionController.__new__(ActionController)
    controller.hwnd = 77
    controller.window_title = "NLHE Test"
    controller.ghost_clicks_enabled = True
    controller._ghost_strategy = None

    assert isinstance(controller.click_strategy, GhostClickStrategy)
    assert asyncio.run(controller.click_at(50, 60)) is True
    messages = [msg for (_hwnd, msg, _w, _l) in calls["send"]]
    assert WM_LBUTTONDOWN in messages


def test_action_controller_foreground_uses_client_origin(monkeypatch):
    """Le clic doit partir de l'origine CLIENT (repère capture), pas fenêtre."""
    from src.bot.action_controller import ActionController

    controller = ActionController.__new__(ActionController)
    controller.hwnd = 4242
    controller.window_title = "NLHE Test"
    # Origine fenêtre décalée de (-8, -31) vs origine client (barre de titre).
    controller._get_client_origin = lambda: (100, 200)
    controller.get_window_rect = lambda refresh=False: (92, 169, 1100, 900)
    controller._prepare_window_for_input = lambda: True

    moves = []

    async def fake_mouse_move(start_x, start_y, target_x, target_y):
        moves.append((target_x, target_y))

    clicks = []

    class FakeBackend:
        async def get_cursor_pos(self):
            return (0, 0)

        async def mouse_down_abs(self, abs_x, abs_y):
            clicks.append(("down", abs_x, abs_y))

        async def mouse_up_abs(self, abs_x, abs_y):
            clicks.append(("up", abs_x, abs_y))

    controller._human_mouse_move = fake_mouse_move
    controller.backend = FakeBackend()

    monkeypatch.setattr("src.bot.action_controller.win32api.GetSystemMetrics", lambda index: 1920 if index == 0 else 1080)
    monkeypatch.setattr("src.bot.action_controller.win32gui.SetForegroundWindow", lambda hwnd: None)
    monkeypatch.setattr("src.bot.action_controller.asyncio.sleep", _fast_sleep)
    monkeypatch.setattr(
        "src.bot.action_controller.ActionController._log_click_reference_offset",
        lambda self: None,
    )

    result = asyncio.run(controller.click_at(10, 20))

    assert result is True
    # Cible écran = origine client (100,200) + coords frame (10,20) => (110,220),
    # et surtout PAS l'origine fenêtre (92,169) qui donnerait (102,189).
    assert moves == [(110, 220)]
    screen_width, screen_height = 1920, 1080
    expected_abs_x = int(110 * 65535 / screen_width)
    expected_abs_y = int(220 * 65535 / screen_height)
    assert clicks[0] == ("down", expected_abs_x, expected_abs_y)


def test_client_window_rect_consistency(monkeypatch):
    """ClientToScreen et GetWindowRect divergent de l'offset titre+bordures."""
    from src.bot.action_controller import ActionController

    def fake_client_to_screen(hwnd, point):
        # Origine fenêtre (84,168) + bordure 16px + barre de titre 32px.
        return (100, 200)

    def fake_get_client_rect(hwnd):
        return (0, 0, 920, 704)

    def fake_get_window_rect(hwnd):
        return (84, 168, 1016, 803)

    monkeypatch.setattr(
        "src.bot.action_controller.win32gui.ClientToScreen", fake_client_to_screen
    )
    monkeypatch.setattr(
        "src.bot.action_controller.win32gui.GetClientRect", fake_get_client_rect
    )
    monkeypatch.setattr(
        "src.bot.action_controller.win32gui.GetWindowRect", fake_get_window_rect
    )

    controller = ActionController.__new__(ActionController)
    controller.hwnd = 10
    controller.window_title = "NLHE Test"

    client_rect = controller.get_client_rect()
    window_rect = controller.get_window_rect()
    origin = controller._get_client_origin()

    assert client_rect == (100, 200, 1020, 904)
    assert window_rect == (84, 168, 1016, 803)
    # L'origine client n'est PAS l'origine fenêtre : écart titre+bordures.
    assert origin != (window_rect[0], window_rect[1])
    assert origin == (100, 200)
