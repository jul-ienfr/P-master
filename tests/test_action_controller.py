import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.bot.action_controller import ActionController
from src.bot.sanity_checker import ActionIntent


def test_action_controller_prefers_table_window_over_lobby(monkeypatch):
    windows = {
        1: ("PokerStars Lobby", (2200, 100, 3500, 900)),
        2: ("NLHE 100/200 6 Max - Hold'em No Limit 100/200 Argent fictif", (680, 150, 1818, 966)),
    }

    def fake_enum_windows(callback, context):
        for hwnd in windows:
            callback(hwnd, context)

    monkeypatch.setattr("src.bot.action_controller.win32gui.EnumWindows", fake_enum_windows)
    monkeypatch.setattr("src.bot.action_controller.win32gui.IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr("src.bot.action_controller.win32gui.GetWindowText", lambda hwnd: windows[hwnd][0])
    monkeypatch.setattr("src.bot.action_controller.win32gui.GetWindowRect", lambda hwnd: windows[hwnd][1])

    controller = ActionController(window_title_keywords="VirtualBox")

    assert controller.window_title.startswith("NLHE 100/200 6 Max")
    assert controller.get_window_rect() == (680, 150, 1818, 966)


def test_prepare_window_for_input_restores_and_focuses_window(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "src.bot.action_controller.win32gui.ShowWindow",
        lambda hwnd, mode: calls.append(("show", hwnd, mode)),
    )

    controller = ActionController.__new__(ActionController)
    controller.hwnd = 4242
    controller.window_title = "NLHE Test"
    controller._force_window_foreground = lambda: calls.append(("focus", controller.hwnd)) or True

    assert controller._prepare_window_for_input() is True
    assert calls[0][0] == "show"
    assert calls[1] == ("focus", 4242)


def test_click_at_aborts_when_window_cannot_be_focused():
    controller = ActionController.__new__(ActionController)
    controller.hwnd = 4242
    controller.window_title = "NLHE Test"
    controller._get_client_origin = lambda: (100, 200)
    controller._prepare_window_for_input = lambda: False

    result = asyncio.run(controller.click_at(10, 20))

    assert result is False


def test_execute_action_bet_relaxes_final_jit_check(monkeypatch):
    controller = ActionController.__new__(ActionController)
    controller.hwnd = None
    controller.window_title = "NLHE Test"

    jit_calls = []

    async def fake_jit_check(ignore_action_region=False):
        jit_calls.append(ignore_action_region)
        return True

    async def fake_click_at(x, y, double_click=False):
        return True

    async def fake_send_text(text):
        return None

    async def _fast_sleep(_delay):
        return None

    controller.click_at = fake_click_at
    controller.send_text = fake_send_text

    monkeypatch.setattr("src.bot.action_controller.asyncio.sleep", _fast_sleep)
    monkeypatch.setattr("src.bot.action_controller.random.uniform", lambda a, b: 0.0)

    result = asyncio.run(
        controller.execute_action(
            ActionIntent(action="BET", bet_size=1.0),
            {"BET_BOX": (10, 10), "BET_BTN": (20, 20)},
            jit_check=fake_jit_check,
        )
    )

    assert result["ok"] is True
    assert jit_calls == [False, True]


def test_execute_action_uses_single_click_for_fold_and_call(monkeypatch):
    controller = ActionController.__new__(ActionController)
    controller.hwnd = None
    controller.window_title = "NLHE Test"

    click_calls = []

    async def fake_click_at(x, y, double_click=False):
        click_calls.append({"x": x, "y": y, "double_click": double_click})
        return True

    async def _fast_sleep(_delay):
        return None

    controller.click_at = fake_click_at

    monkeypatch.setattr("src.bot.action_controller.asyncio.sleep", _fast_sleep)
    monkeypatch.setattr("src.bot.action_controller.random.uniform", lambda a, b: 0.0)

    fold_result = asyncio.run(
        controller.execute_action(
            ActionIntent(action="FOLD"),
            {"FOLD": (10, 10)},
        )
    )
    call_result = asyncio.run(
        controller.execute_action(
            ActionIntent(action="CALL"),
            {"CALL": (20, 20)},
        )
    )

    assert fold_result["ok"] is True
    assert call_result["ok"] is True
    assert click_calls == [
        {"x": 10, "y": 10, "double_click": False},
        {"x": 20, "y": 20, "double_click": False},
    ]
