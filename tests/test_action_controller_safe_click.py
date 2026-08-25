"""Tests des gardes de clic sûr de l'ActionController (sans interaction Windows réelle)."""

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.action_controller import ActionController
from src.bot.sanity_checker import ActionIntent


def make_controller(hwnd=0):
    controller = ActionController.__new__(ActionController)
    controller.hwnd = hwnd
    controller.window_title = "PokerStars"
    return controller


@pytest.fixture()
def fast_sleep(monkeypatch):
    async def _instant(_delay, *args, **kwargs):
        pass

    monkeypatch.setattr(asyncio, "sleep", _instant)


def run(coro):
    return asyncio.run(coro)


def test_execute_action_skips_fold_without_coords(fast_sleep):
    controller = make_controller()
    result = run(controller.execute_action({"action": "FOLD"}, coords_mapping={}))
    assert result == {"ok": False, "action": "FOLD", "reason": "missing_fold_coords"}


def test_execute_action_skips_call_without_coords(fast_sleep):
    controller = make_controller()
    result = run(controller.execute_action({"action": "CALL"}, coords_mapping={}))
    assert result == {"ok": False, "action": "CALL", "reason": "missing_call_coords"}


def test_execute_action_skips_bet_without_bet_box(fast_sleep):
    controller = make_controller()
    result = run(controller.execute_action({"action": "BET"}, coords_mapping={}))
    assert result == {"ok": False, "action": "BET", "reason": "missing_bet_box_coords"}


def test_execute_action_rejects_unsupported_action(fast_sleep):
    controller = make_controller()
    result = run(controller.execute_action({"action": "SMISE"}, coords_mapping={}))
    assert result == {"ok": False, "action": "SMISE", "reason": "unsupported_action"}


def test_click_at_aborts_when_window_rect_unavailable(monkeypatch, fast_sleep):
    controller = make_controller(hwnd=123)
    controller.get_window_rect = lambda refresh=False: None
    mouse_events = []
    monkeypatch.setattr(
        "src.bot.action_controller.win32api.mouse_event",
        lambda *args: mouse_events.append(args),
    )
    result = run(controller.click_at(10, 20))
    assert result is False
    assert mouse_events == []


def test_click_at_aborts_when_window_not_foreground(monkeypatch, fast_sleep):
    controller = make_controller(hwnd=123)
    controller.get_window_rect = lambda refresh=False: (100, 100, 900, 700)
    monkeypatch.setattr(ActionController, "_prepare_window_for_input", lambda self: False)
    mouse_events = []
    monkeypatch.setattr(
        "src.bot.action_controller.win32api.mouse_event",
        lambda *args: mouse_events.append(args),
    )
    result = run(controller.click_at(10, 20))
    assert result is False
    assert mouse_events == []


def test_click_at_happy_path_sends_down_and_up(monkeypatch, fast_sleep):
    controller = make_controller(hwnd=0)  # pas de fenêtre cible -> coordonnées écran directes
    cursor_positions = iter([(0, 0), (0, 0)])
    monkeypatch.setattr(
        "src.bot.action_controller.win32api.GetCursorPos", lambda: next(cursor_positions)
    )
    monkeypatch.setattr(
        "src.bot.action_controller.win32api.GetSystemMetrics",
        lambda index: 1920 if index == 0 else 1080,
    )
    monkeypatch.setattr(ActionController, "_prepare_window_for_input", lambda self: True)
    monkeypatch.setattr(ActionController, "_human_mouse_move", AsyncNoop())
    mouse_events = []
    monkeypatch.setattr(
        "src.bot.action_controller.win32api.mouse_event",
        lambda *args: mouse_events.append(args),
    )
    result = run(controller.click_at(320, 240))
    assert result is True
    flags = [args[0] for args in mouse_events]
    assert len(mouse_events) == 2  # LEFTDOWN puis LEFTUP
    assert flags[1] > flags[0]  # KEYUP contient le flag KEYDOWN + RELEASE


class AsyncNoop:
    """Callable awaitable-ish : retourne une coroutine no-op."""

    def __call__(self, *args, **kwargs):
        async def _noop():
            return None

        return _noop()


def test_action_intent_from_payload_defaults():
    intent = ActionIntent.from_payload({"action": "FOLD"})
    assert intent.action == "FOLD"
