"""Stratégies d'injection d'entrées : foreground humanisé vs ghost SendMessage.

Unifie les deux contrôleurs historiques (`ActionController` foreground et
`Win32GhostController` SendMessage) derrière un contrat unique `ClickStrategy`.
Le mode ghost (clics en arrière-plan) est désactivé par défaut
(`bot.ghost_clicks_enabled=false`) : certains clients DirectUI ignorent les
messages WM_LBUTTONDOWN et le pattern est détectable.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_RETURN = 0x0D
MK_LBUTTON = 0x0001


def make_lparam(x: int, y: int) -> int:
    """Encode une paire (x, y) coordonnées client en LPARAM Win32."""
    return (int(y) << 16) | (int(x) & 0xFFFF)


@runtime_checkable
class ClickStrategy(Protocol):
    """Contrat commun des stratégies d'exécution d'action."""

    async def click_at(self, x: int, y: int, double_click: bool = False) -> bool:
        """Clique au point (x, y) en coordonnées client de la fenêtre cible."""
        raise NotImplementedError

    async def send_text(self, text: str) -> bool:
        """Frappe le texte caractère par caractère."""
        raise NotImplementedError

    async def press_return(self) -> None:
        """Valide avec la touche Entrée."""
        raise NotImplementedError


class ForegroundClickStrategy:
    """Délègue au ActionController : mouvement humain + focus fenêtre."""

    def __init__(self, controller):
        self.controller = controller

    async def click_at(self, x: int, y: int, double_click: bool = False) -> bool:
        return await self.controller._foreground_click_at(
            x, y, double_click=double_click
        )

    async def send_text(self, text: str) -> bool:
        await self.controller._humanized_send_text(text)
        return True

    async def press_return(self) -> None:
        await self.controller._humanized_press_return()


class GhostClickStrategy:
    """Clics et frappes en arrière-plan via SendMessage (coordonnées client)."""

    def __init__(
        self,
        hwnd_provider,
        *,
        click_jitter_px: int = 2,
        down_delay_range_s: tuple[float, float] = (0.03, 0.08),
        key_delay_range_s: tuple[float, float] = (0.01, 0.03),
    ):
        self._hwnd_provider = hwnd_provider
        self.click_jitter_px = max(0, int(click_jitter_px))
        self.down_delay_range_s = down_delay_range_s
        self.key_delay_range_s = key_delay_range_s

    @property
    def hwnd(self) -> int:
        try:
            return int(self._hwnd_provider() or 0)
        except Exception:
            return 0

    def _win32gui(self):
        import win32gui

        return win32gui

    def _win32api(self):
        import win32api

        return win32api

    def _jitter(self, value: int) -> int:
        if self.click_jitter_px <= 0:
            return int(value)
        return int(value) + random.randint(-self.click_jitter_px, self.click_jitter_px)

    def _send_click(self, hwnd: int, x: int, y: int) -> None:
        win32gui = self._win32gui()
        jx, jy = self._jitter(x), self._jitter(y)
        lparam = make_lparam(jx, jy)
        win32gui.SendMessage(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(random.uniform(*self.down_delay_range_s))
        win32gui.SendMessage(hwnd, WM_LBUTTONUP, 0, lparam)
        logger.debug("GHOST_CLICK | hwnd=%s client=(%s,%s)", hwnd, jx, jy)

    async def click_at(self, x: int, y: int, double_click: bool = False) -> bool:
        hwnd = self.hwnd
        if not hwnd:
            logger.warning("GHOST_CLICK | fenêtre cible indisponible, clic annulé.")
            return False
        self._send_click(hwnd, x, y)
        if double_click:
            await asyncio.sleep(random.uniform(*self.down_delay_range_s))
            self._send_click(hwnd, x, y)
        return True

    async def _type_char(self, hwnd: int, char: str) -> None:
        win32api = self._win32api()
        vk_code = ord(char.upper())
        win32api.SendMessage(hwnd, WM_KEYDOWN, vk_code, 0)
        win32api.SendMessage(hwnd, WM_CHAR, ord(char), 0)
        win32api.SendMessage(hwnd, WM_KEYUP, vk_code, 0)

    async def send_text(self, text: str) -> bool:
        hwnd = self.hwnd
        if not hwnd:
            return False
        for char in str(text):
            await self._type_char(hwnd, char)
            await asyncio.sleep(random.uniform(*self.key_delay_range_s))
        return True

    async def press_key(self, vk_code: int) -> None:
        hwnd = self.hwnd
        if not hwnd:
            return
        win32api = self._win32api()
        win32api.SendMessage(hwnd, WM_KEYDOWN, int(vk_code), 0)
        win32api.SendMessage(hwnd, WM_KEYUP, int(vk_code), 0)

    async def press_return(self) -> None:
        await self.press_key(VK_RETURN)
