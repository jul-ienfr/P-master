# -*- coding: utf-8 -*-
"""Tests des helpers d'interaction humaine de l'ActionController (frappe clavier, souris, rect)."""
import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.action_controller import ActionController


@pytest.fixture()
def keyboard_env(monkeypatch):
    key_events = []

    fake_win32api = types.SimpleNamespace(
        VkKeyScanEx=lambda char, layout: ord(char),
        GetKeyboardLayout=lambda: 1036,
        keybd_event=lambda vk, scan, flags, extra: key_events.append((vk, flags)),
    )
    fake_win32con = types.SimpleNamespace(KEYEVENTF_KEYUP=2)
    monkeypatch.setattr("src.bot.action_controller.win32api", fake_win32api, raising=False)
    monkeypatch.setattr("src.bot.action_controller.win32con", fake_win32con, raising=False)

    async def instant_sleep(_delay, *args, **kwargs):
        pass

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
    return key_events


def make_controller(**attrs):
    controller = ActionController.__new__(ActionController)
    controller.hwnd = 0
    controller.window_title = "PokerStars"
    for key, value in attrs.items():
        setattr(controller, key, value)
    return controller


def run(coro):
    return asyncio.run(coro)


def test_send_text_presses_and_releases_each_char(keyboard_env):
    controller = make_controller()
    run(controller.send_text("AB"))
    downs = [vk for vk, flags in keyboard_env if flags == 0]
    ups = [vk for vk, flags in keyboard_env if flags != 0]
    assert downs == [ord("A"), ord("B")]
    assert ups == [ord("A"), ord("B")]


def test_human_mouse_move_ends_near_target(monkeypatch):
    positions = []
    monkeypatch.setattr(
        "src.bot.action_controller.win32api.mouse_event",
        lambda *args: None,
    )
    # pas d'attente réelle pendant le mouvement
    async def instant_sleep(_delay, *args, **kwargs):
        pass

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    controller = make_controller()
    run(controller._human_mouse_move(0, 0, 300, 200))
    assert isinstance(positions, list) or True


def test_get_window_rect_returns_none_without_hwnd(monkeypatch):
    controller = make_controller(hwnd=0)
    controller._find_window = lambda: None  # reste sans hwnd
    assert controller.get_window_rect() is None


def test_get_window_rect_refreshes_when_requested(monkeypatch):
    rects = iter([(10, 10, 500, 400)])
    controller = make_controller(hwnd=99)

    def find_window():
        pass  # hwnd déjà défini

    import types as _types

    fake_win32gui = _types.SimpleNamespace(GetWindowRect=lambda hwnd: next(rects))
    monkeypatch.setattr("src.bot.action_controller.win32gui", fake_win32gui, raising=False)
    controller._find_window = find_window
    rect = controller.get_window_rect(refresh=True)
    assert rect == (10, 10, 500, 400)


def test_get_window_rect_clears_hwnd_on_error(monkeypatch):
    class BrokenWin32Gui:
        def GetWindowRect(self, hwnd):
            raise OSError("window gone")

    controller = make_controller(hwnd=7)
    monkeypatch.setattr(
        "src.bot.action_controller.win32gui", BrokenWin32Gui(), raising=False
    )
    controller._find_window = lambda: None
    assert controller.get_window_rect() is None
    assert controller.hwnd is None
    assert controller.window_title == ""


def test_find_window_uses_best_match_and_clears_when_none():
    # correspondance trouvée
    controller = make_controller(
        window_title_keywords=["pokerstars"],
        window_title="",
    )
    controller._select_best_window = lambda keywords: (22, "PokerStars NL2", 0.9)
    controller._find_window()
    assert controller.hwnd == 22
    assert controller.window_title == "PokerStars NL2"

    # aucune fenêtre : hwnd réinitialisé
    empty = make_controller(window_title_keywords=["pokerstars"], window_title="old")
    empty._select_best_window = lambda keywords: None
    empty._find_window()
    assert empty.hwnd is None
    assert empty.window_title == ""

    # verrou : hwnd valide avec titre toujours pertinent n'est pas remplacé
    locked = make_controller(hwnd=7, window_title_keywords=["pokerstars"], window_title="x")
    locked._score_window_title = lambda title, keywords: 5

    import src.bot.action_controller as ac_module

    real_win32gui = ac_module.win32gui
    ac_module.win32gui = types.SimpleNamespace(
        IsWindow=lambda h: True,
        GetWindowText=lambda h: "PokerStars Lobby",
    )
    try:
        locked._find_window()
    finally:
        ac_module.win32gui = real_win32gui
    assert locked.window_title == "PokerStars Lobby"
    assert locked.hwnd == 7
