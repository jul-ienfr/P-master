"""Tests du contrôleur fantôme Win32 avec modules win32 mockés."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def install_fake_win32(monkeypatch, find_window_result=0, enum_windows_hits=None):
    calls = {"send": [], "enum_windows": 0}

    win32gui = types.SimpleNamespace()
    win32gui.FindWindow = lambda cls, title: find_window_result
    win32gui.IsWindowVisible = lambda h: True

    def get_window_text(h):
        return "PokerStars Lobby" if h == 42 else ""

    win32gui.GetWindowText = get_window_text

    def enum_windows(callback, hwnds):
        calls["enum_windows"] += 1
        for h in enum_windows_hits or []:
            callback(h, hwnds)
        return hwnds

    win32gui.EnumWindows = enum_windows
    win32gui.SendMessage = lambda hwnd, msg, wparam, lparam: calls["send"].append((hwnd, msg, wparam, lparam))

    win32api = types.SimpleNamespace(SendMessage=lambda *a: None)

    class FakeWin32Con:
        MK_LBUTTON = 0x0001

    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(sys.modules, "win32con", FakeWin32Con)
    return calls


def test_find_window_uses_partial_match_enumeration(monkeypatch):
    from src.bot.win32_controller import Win32GhostController

    install_fake_win32(monkeypatch, find_window_result=0, enum_windows_hits=[7, 42])
    controller = Win32GhostController("PokerStars")
    assert controller.hwnd == 42


def test_ghost_click_without_hwnd_is_a_noop(monkeypatch):
    from src.bot.win32_controller import Win32GhostController

    calls = install_fake_win32(monkeypatch, find_window_result=0, enum_windows_hits=[])
    controller = Win32GhostController("PokerStars")
    assert controller.hwnd == 0
    controller.ghost_click(100, 200)
    controller.ghost_type_amount(12.5)
    assert calls["send"] == []


def test_make_lparam_packs_coordinates():
    from src.bot.win32_controller import Win32GhostController

    controller = Win32GhostController.__new__(Win32GhostController)
    lparam = controller.make_lparam(320, 240)
    assert lparam == (240 << 16) | (320 & 0xFFFF)


def test_ghost_click_sends_down_then_up_with_jitter(monkeypatch):
    from src.bot.win32_controller import WM_LBUTTONDOWN, WM_LBUTTONUP, Win32GhostController

    calls = install_fake_win32(monkeypatch, find_window_result=99)
    controller = Win32GhostController("PokerStars")
    assert controller.hwnd == 99
    controller.ghost_click(100, 200)
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


def test_execute_action_without_matching_coords_does_not_click(monkeypatch):
    from src.bot.win32_controller import Win32GhostController

    calls = install_fake_win32(monkeypatch, find_window_result=5)
    controller = Win32GhostController("PokerStars")
    controller.execute_action("CHECK", None, coords_dict={"FOLD_BUTTON_XY": (10, 20)})
    assert calls["send"] == []


def test_execute_action_clicks_action_button_and_types_bet_amount(monkeypatch):
    from src.bot.win32_controller import WM_CHAR, WM_KEYDOWN, WM_KEYUP, Win32GhostController

    key_calls = []
    fake_api = types.SimpleNamespace(
        SendMessage=lambda hwnd, msg, wparam, lparam: key_calls.append((msg, wparam))
    )
    calls = install_fake_win32(monkeypatch, find_window_result=5)
    # remplace win32api après installation pour capturer les frappes
    sys.modules["win32api"] = fake_api

    controller = Win32GhostController("PokerStars")
    controller.execute_action(
        "BET", 12.5, coords_dict={"BET_BOX": (400, 500), "BET": (600, 520)}
    )

    clicked_messages = [msg for (_hwnd, msg, _w, _l) in calls["send"]]
    assert len(clicked_messages) >= 4  # clic BET_BOX + clic bouton BET (DOWN/UP x2)
    assert any(wparam == ord("1") for msg, wparam in key_calls if msg == WM_CHAR)
    assert any(msg == WM_KEYDOWN and wparam == 0x0D for msg, wparam in key_calls)
