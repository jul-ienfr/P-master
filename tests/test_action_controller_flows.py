"""Tests des chemins heureux d'execute_action (FOLD/CALL/BET) avec Win32 mocké."""
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
def controller(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = ActionController.__new__(ActionController)
    controller.hwnd = 0
    controller.window_title = "PokerStars NL2"
    # clics toujours "réussis", sans toucher à Windows
    async def fake_click(x, y, double_click=False):
        return True

    controller.click_at = fake_click
    return controller


@pytest.fixture()
def fast_sleep(monkeypatch):
    async def _instant(_delay, *args, **kwargs):
        pass

    monkeypatch.setattr(asyncio, "sleep", _instant)


def install_fake_keyboard(monkeypatch):
    key_events = []
    fake_win32api = types.SimpleNamespace(
        keybd_event=lambda vk, scan, flags, extra: key_events.append((vk, flags)),
        VkKeyScanEx=lambda char, layout: ord(char),
        GetKeyboardLayout=lambda: 0,
    )
    fake_win32con = types.SimpleNamespace(
        VK_RETURN=0x0D,
        KEYEVENTF_KEYUP=2,
        MOUSEEVENTF_ABSOLUTE=0x8000,
        MOUSEEVENTF_LEFTDOWN=0x0002,
        MOUSEEVENTF_LEFTUP=0x0004,
        SW_RESTORE=9,
    )
    monkeypatch.setattr("src.bot.action_controller.win32api", fake_win32api, raising=False)
    monkeypatch.setattr("src.bot.action_controller.win32con", fake_win32con, raising=False)
    return key_events


def run(coro):
    return asyncio.run(coro)


def test_execute_action_fold_clicks_fold_button(controller, fast_sleep):
    clicked = []

    async def fake_click(x, y, double_click=False):
        clicked.append((x, y))
        return True

    controller.click_at = fake_click
    result = run(controller.execute_action({"action": "FOLD"}, {"FOLD": (120, 300)}))
    assert result == {"ok": True, "action": "FOLD", "target": (120, 300)}
    assert clicked == [(120, 300)]


def test_execute_action_call_uses_call_coords(controller, fast_sleep):
    clicked = []

    async def fake_click(x, y, double_click=False):
        clicked.append((x, y))
        return True

    controller.click_at = fake_click
    result = run(controller.execute_action({"action": "CHECK"}, {"CALL": (200, 310)}))
    assert result["ok"] is True
    assert result["action"] == "CHECK"
    assert clicked == [(200, 310)]


def test_execute_action_bet_types_amount_and_presses_enter(controller, fast_sleep, monkeypatch):
    key_events = install_fake_keyboard(monkeypatch)
    sent_texts = []

    async def fake_send_text(text):
        sent_texts.append(text)

    controller.send_text = fake_send_text
    result = run(
        controller.execute_action(
            {"action": "BET", "bet_size": 125.0},
            {"BET_BOX": (340, 200), "BET_BTN": (460, 200)},
        )
    )
    assert result["ok"] is True
    assert result["target"] == "VK_RETURN+BET_BTN"
    # sans profil de site (config absent), BB par défaut = 200 : un sizing de
    # 125 < 1 BB est corrigé en 3 BB = 600 avant la frappe clavier
    assert sent_texts == ["600"]
    enter_downs = [vk for vk, _flags in key_events if vk == 0x0D]
    assert len(enter_downs) >= 2


def test_execute_action_fails_when_bet_box_click_fails(controller, fast_sleep, monkeypatch):
    async def failing_click(x, y, double_click=False):
        return False

    controller.click_at = failing_click
    result = run(controller.execute_action({"action": "RAISE"}, {"BET_BOX": (10, 10)}))
    assert result == {"ok": False, "action": "RAISE", "reason": "bet_box_click_failed"}


def test_execute_action_jit_abort_propagates_runtime_error(controller, fast_sleep):
    def jit_check(ignore_action_region=False):
        return False

    # le gate flow (appelant) intercepte "JIT Check Failed" ; ici on vérifie
    # que l'exception remonte bien depuis execute_action
    with pytest.raises(RuntimeError, match="JIT Check Failed"):
        run(
            controller.execute_action(
                {"action": "FOLD"}, {"FOLD": (5, 5)}, jit_check=jit_check
            )
        )
