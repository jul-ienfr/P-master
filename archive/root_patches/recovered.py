import asyncio
import logging
import random
import win32api
import win32con
import win32gui
import math
import ctypes
from typing import List, Optional, Tuple

from src.bot.sanity_checker import ActionIntent

logger = logging.getLogger(__name__)
DEFAULT_POKER_WINDOW_KEYWORDS = ("NLHE", "Hold'em No Limit", "PokerStars")
MIN_THINK_TIME_S = 0.18
MAX_THINK_TIME_S = 0.55
MIN_MOVE_DURATION_S = 0.08
MAX_MOVE_DURATION_S = 0.18

# --- CORRECTION DPI AWARENESS ---
# Emp├¬che Windows de fausser les coordonn├®es (x,y) si l'utilisateur a un zoom ├®cran > 100%
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception as e:
    logger.warning(f"Impossible de d├®finir le DPI Awareness: {e}")


def _parse_window_title_keywords(raw_value: str) -> List[str]:
    tokens = str(raw_value or "").replace(",", "|").replace(";", "|").split("|")
    return [token.strip() for token in tokens if token and token.strip()]

class ActionController:
    """
    Contr├┤leur d'actions con├ºu pour fonctionner DEPUIS l'h├┤te vers une Machine Virtuelle (VM)
    ou DANS une VM. Il simule des mouvements de souris humains (courbes de B├®zier) pour 
    d├®jouer l'analyse heuristique des anti-cheats.
    """
    def __init__(self, window_title_keywords: str = "VirtualBox"):
        self.window_title_keywords = window_title_keywords
        self.hwnd = None
        self.window_title = ""
        self._find_window()

    def _candidate_windows(self) -> List[Tuple[int, str, Tuple[int, int, int, int]]]:
        candidates: List[Tuple[int, str, Tuple[int, int, int, int]]] = []

        def enum_windows_callback(hwnd, context):
            if not win32gui.IsWindowVisible(hwnd):
                return

            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                return

            try:
                rect = win32gui.GetWindowRect(hwnd)
            except Exception:
                return
            candidates.append((hwnd, title, rect))

        win32gui.EnumWindows(enum_windows_callback, None)
        return candidates

    @staticmethod
    def _score_window_title(title: str, keywords: List[str]) -> int:
        normalized_title = title.lower()
        score = sum(3 for keyword in keywords if keyword.lower() in normalized_title)
        if "lobby" in normalized_title:
            score -= 3
        return score

    def _select_best_window(
        self,
        keywords: List[str],
    ) -> Optional[Tuple[int, str, Tuple[int, int, int, int]]]:
        if not keywords:
            return None

        matches = []
        for hwnd, title, rect in self._candidate_windows():
            score = self._score_window_title(title, keywords)
            if score <= 0:
                continue
            width = max(0, rect[2] - rect[0])
            height = max(0, rect[3] - rect[1])
            matches.append((score, width * height, hwnd, title, rect))

        if not matches:
            return None

        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _, _, hwnd, title, rect = matches[0]
        return hwnd, title, rect

    def _find_window(self):
        """Cherche le handle (HWND) de la fen├¬tre cible."""
        previous_hwnd = self.hwnd
        previous_title = self.window_title
        primary_keywords = _parse_window_title_keywords(self.window_title_keywords)
        best_match = self._select_best_window(primary_keywords)

        if best_match is None:
            fallback_keywords = [
                keyword for keyword in DEFAULT_POKER_WINDOW_KEYWORDS if keyword not in primary_keywords
            ]
            best_match = self._select_best_window(fallback_keywords)

        if best_match is None:
            self.hwnd = None
            self.window_title = ""
            if previous_hwnd is not None or previous_title:
                logger.warning(f"Impossible de trouver une fen├¬tre contenant '{self.window_title_keywords}'")
            return

        self.hwnd, self.window_title, _ = best_match
        if self.hwnd != previous_hwnd or self.window_title != previous_title:
            logger.info(f"Fen├¬tre cible trouv├®e: '{self.window_title}' (HWND: {self.hwnd})")

    def refresh_window(self):
        self._find_window()
        return self.hwnd

    def get_window_rect(self, refresh: bool = False) -> Optional[Tuple[int, int, int, int]]:
        if refresh or not self.hwnd:
            self._find_window()
        if not self.hwnd:
            return None
        try:
            return win32gui.GetWindowRect(self.hwnd)
        except Exception:
            self.hwnd = None
            self.window_title = ""
            return None

    def get_client_rect(self, refresh: bool = False) -> Optional[Tuple[int, int, int, int]]:
        if refresh or not self.hwnd:
            self._find_window()
        if not self.hwnd:
            return None
        try:
            left, top = win32gui.ClientToScreen(self.hwnd, (0, 0))
            _, _, right, bottom = win32gui.GetClientRect(self.hwnd)
            return (left, top, left + right, top + bottom)
        except Exception:
            self.hwnd = None
            self.window_title = ""
            return None

    def _get_client_origin(self) -> Optional[Tuple[int, int]]:
        if not self.hwnd:
            return None
        try:
            return win32gui.ClientToScreen(self.hwnd, (0, 0))
        except Exception:
            return None

    @staticmethod
    def _get_foreground_window() -> Optional[int]:
        try:
            hwnd = int(win32gui.GetForegroundWindow())
        except Exception:
            return None
        return hwnd if hwnd > 0 else None

    def _force_window_foreground(self) -> bool:
        if not self.hwnd:
            return False

        target_hwnd = int(self.hwnd)
        foreground_before = self._get_foreground_window()
        attached_threads: List[int] = []
        user32 = getattr(getattr(ctypes, "windll", None), "user32", None)
        kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
        current_thread_id = 0

        try:
            if kernel32 is not None:
                try:
                    current_thread_id = int(kernel32.GetCurrentThreadId())
                except Exception:
                    current_thread_id = 0

            if user32 is not None and current_thread_id:
                target_thread_id = int(user32.GetWindowThreadProcessId(target_hwnd, 0) or 0)
                foreground_thread_id = (
                    int(user32.GetWindowThreadProcessId(int(foreground_before), 0) or 0)
                    if foreground_before
                    else 0
                )
                for thread_id in {target_thread_id, foreground_thread_id}:
                    if thread_id and thread_id != current_thread_id:
                        try:
                            attached = bool(user32.AttachThreadInput(current_thread_id, thread_id, True))
                        except Exception:
                            attached = False
                        if attached:
                            attached_threads.append(thread_id)

            for operation in (
                lambda: win32gui.BringWindowToTop(target_hwnd),
                lambda: win32gui.SetWindowPos(
                    target_hwnd,
                    win32con.HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                ),
                lambda: win32gui.SetWindowPos(
                    target_hwnd,
                    win32con.HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                ),
                lambda: win32gui.SetForegroundWindow(target_hwnd),
            ):
                try:
                    operation()
                except Exception:
                    pass

            if user32 is not None:
                for operation in (
                    lambda: user32.SetForegroundWindow(target_hwnd),
                    lambda: user32.SetActiveWindow(target_hwnd),
                    lambda: user32.SetFocus(target_hwnd),
                ):
                    try:
                        operation()
                    except Exception:
                        pass

            foreground_after = self._get_foreground_window()
            if foreground_after == target_hwnd:
                return True

            try:
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass

            try:
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception:
                pass

            return self._get_foreground_window() == target_hwnd
        finally:
            if user32 is not None and current_thread_id:
                for thread_id in reversed(attached_threads):
                    try:
                        user32.AttachThreadInput(current_thread_id, thread_id, False)
                    except Exception:
                        pass

    def _prepare_window_for_input(self) -> bool:
        if not self.hwnd:
            return True
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        except Exception:
            pass
        focused = self._force_window_foreground()
        logger.info(
            "INPUT_PREPARE | hwnd=%s focused=%s title=%s",
            self.hwnd,
            "yes" if focused else "no",
            self.window_title,
        )
        return focused

    async def _human_mouse_move(self, start_x, start_y, target_x, target_y, duration=0.3):
        """
        G├®n├¿re un mouvement de souris fluide entre deux points (approximation B├®zier/Ease-out)
        au lieu d'une t├®l├®portation robotique. Asynchrone pour ne pas bloquer l'event loop.
        """
        steps = int(duration * 60) # 60 Hz
        if steps == 0: steps = 1
        
        # Ajout d'un l├®ger over-shoot al├®atoire pour simuler l'imperfection humaine
        control_x = (start_x + target_x) / 2 + random.randint(-50, 50)
        control_y = (start_y + target_y) / 2 + random.randint(-50, 50)

        for i in range(1, steps + 1):
            t = i / steps
            # Formule de B├®zier quadratique
            x = int((1 - t)**2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            y = int((1 - t)**2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)
            
            # D├®placer physiquement la souris
            win32api.SetCursorPos((x, y))
            await asyncio.sleep(duration / steps)

    async def click_at(self, x: int, y: int, double_click: bool = False):
        """
        Effectue un clic PHYSIQUE (Hardware simulation) aux coordonn├®es absolues de l'├®cran.
        Recommand├® si le bot tourne sur l'h├┤te et cible la fen├¬tre de la VM.
        """
        # Si on vise une fen├¬tre sp├®cifique (VM), on d├®cale les coordonn├®es relatives 
        # par rapport au coin de la fen├¬tre de la VM.
        if self.hwnd:
            client_origin = self._get_client_origin()
            if client_origin is None:
                logger.error("CLICK_ATTEMPT | impossible de convertir les coordonnees client pour la fenetre cible.")
                return False
            target_x = client_origin[0] + x
            target_y = client_origin[1] + y
        else:
            target_x, target_y = x, y

        if not self._prepare_window_for_input():
            logger.error(
                "CLICK_ATTEMPT | aborted reason=window_not_foreground hwnd=%s title=%s",
                self.hwnd,
                self.window_title,
            )
            return False
        logger.info(
            "CLICK_ATTEMPT | client=(%s,%s) screen=(%s,%s) hwnd=%s title=%s",
            x,
            y,
            target_x,
            target_y,
            self.hwnd,
            self.window_title,
        )
            
        # Obtenir la position actuelle pour d├®marrer le mouvement
        current_x, current_y = win32api.GetCursorPos()
        
        # Mouvement humain
        await self._human_mouse_move(current_x, current_y, target_x, target_y, duration=random.uniform(MIN_MOVE_DURATION_S, MAX_MOVE_DURATION_S))

        # Micro-pause avant de cliquer
        await asyncio.sleep(random.uniform(0.02, 0.05))

        # Clic Hardware Down/Up
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, target_x, target_y, 0, 0)
        await asyncio.sleep(random.uniform(0.02, 0.05)) # Dur├®e de la pression du clic
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, target_x, target_y, 0, 0)
        
        if double_click:
            await asyncio.sleep(random.uniform(0.03, 0.06))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, target_x, target_y, 0, 0)
            await asyncio.sleep(random.uniform(0.02, 0.05))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, target_x, target_y, 0, 0)
            
        logger.debug(f"Clic physique g├®n├®r├® en ({target_x}, {target_y})")
        return True

    async def send_text(self, text: str):
        """Tape le texte avec un d├®lai al├®atoire entre chaque touche (Human-like)."""
        for char in text:
            # Map le caract├¿re au Virtual Key Code correspondant
            vk_code = win32api.VkKeyScanEx(char, win32api.GetKeyboardLayout())
            # Touche enfonc├®e
            win32api.keybd_event(vk_code & 0xFF, 0, 0, 0)
            await asyncio.sleep(random.uniform(0.01, 0.04))
            # Touche rel├óch├®e
            win32api.keybd_event(vk_code & 0xFF, 0, win32con.KEYEVENTF_KEYUP, 0)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    async def execute_action(self, action_request, coords_mapping: dict):
        if isinstance(action_request, ActionIntent):
            action_intent = action_request
        else:
            action_intent = ActionIntent.from_payload(action_request)

        action_name = action_intent.action
        logger.info(
            "ACTION_REQUEST | action=%s bet_size=%s targets=%s",
            action_name,
            action_intent.bet_size,
            sorted(key for key, value in (coords_mapping or {}).items() if value),
        )
        
        # D├®lai de r├®flexion humain avant de jouer (tr├¿s important pour les anti-cheats)
        think_time = random.uniform(MIN_THINK_TIME_S, MAX_THINK_TIME_S)
        logger.info(f"Bot en r├®flexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)
        
        if action_name == "FOLD":
            coords = coords_mapping.get("FOLD")
            if coords:
                clicked = await self.click_at(*coords)
                if clicked:
                    logger.info("-> Action ex├®cut├®e : FOLD")
                    return {"ok": True, "action": "FOLD", "target": tuple(coords)}
                logger.error("CLICK_RESULT | action=FOLD status=failed reason=fold_click_failed")
                return {"ok": False, "action": "FOLD", "reason": "fold_click_failed", "target": tuple(coords)}
            logger.warning("CLICK_RESULT | action=FOLD status=skipped reason=missing_fold_coords")
            return {"ok": False, "action": "FOLD", "reason": "missing_fold_coords"}
                
        elif action_name == "CALL" or action_name == "CHECK":
            coords = coords_mapping.get("CALL")
            if coords:
                clicked = await self.click_at(*coords)
                if clicked:
                    logger.info(f"-> Action ex├®cut├®e : {action_name}")
                    return {"ok": True, "action": action_name, "target": tuple(coords)}
                logger.error("CLICK_RESULT | action=%s status=failed reason=call_click_failed", action_name)
                return {"ok": False, "action": action_name, "reason": "call_click_failed", "target": tuple(coords)}
            logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_call_coords", action_name)
            return {"ok": False, "action": action_name, "reason": "missing_call_coords"}
                
        elif action_name == "ALL_IN" or "RAISE" in action_name or "BET" in action_name:
            text_box_coords = coords_mapping.get("BET_BOX")
            if text_box_coords:
                clicked = await self.click_at(*text_box_coords, double_click=True)
                if not clicked:
                    logger.error("CLICK_RESULT | action=%s status=failed reason=bet_box_click_failed", action_name)
                    return {"ok": False, "action": action_name, "reason": "bet_box_click_failed"}
                
                amount_to_bet = str(action_intent.bet_size if action_intent.bet_size is not None else 5.50)
                await self.send_text(amount_to_bet)
                
                bet_btn_coords = coords_mapping.get("BET_BTN")
                if bet_btn_coords:
                    await asyncio.sleep(random.uniform(0.08, 0.16))
                    clicked = await self.click_at(*bet_btn_coords)
                    if clicked:
                        logger.info(f"-> Action ex├®cut├®e : {action_name} ({amount_to_bet})")
                        return {
                            "ok": True,
                            "action": action_name,
                            "target": tuple(bet_btn_coords),
                            "bet_size": amount_to_bet,
                        }
                    logger.error("CLICK_RESULT | action=%s status=failed reason=bet_button_click_failed", action_name)
                    return {
                        "ok": False,
                        "action": action_name,
                        "reason": "bet_button_click_failed",
                        "target": tuple(bet_btn_coords),
                        "bet_size": amount_to_bet,
                    }
                logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_bet_button_coords", action_name)
                return {"ok": False, "action": action_name, "reason": "missing_bet_button_coords"}
            logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_bet_box_coords", action_name)
            return {"ok": False, "action": action_name, "reason": "missing_bet_box_coords"}

        logger.warning("CLICK_RESULT | action=%s status=skipped reason=unsupported_action", action_name)
        return {"ok": False, "action": action_name, "reason": "unsupported_action"}
