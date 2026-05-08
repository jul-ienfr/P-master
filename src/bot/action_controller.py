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
# Empêche Windows de fausser les coordonnées (x,y) si l'utilisateur a un zoom écran > 100%
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception as e:
    logger.warning(f"Impossible de définir le DPI Awareness: {e}")


def _parse_window_title_keywords(raw_value: str) -> List[str]:
    tokens = str(raw_value or "").replace(",", "|").replace(";", "|").split("|")
    return [token.strip() for token in tokens if token and token.strip()]

class ActionController:
    """
    Contrôleur d'actions conçu pour fonctionner DEPUIS l'hôte vers une Machine Virtuelle (VM)
    ou DANS une VM. Il simule des mouvements de souris humains (courbes de Bézier) pour 
    déjouer l'analyse heuristique des anti-cheats.
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
        """Cherche le handle (HWND) de la fenêtre cible."""
        primary_keywords = _parse_window_title_keywords(self.window_title_keywords)
        
        # LOCK HWND: Empêcher de sauter sur une autre fenêtre si celle-ci est toujours valide
        if getattr(self, 'hwnd', None) and win32gui.IsWindow(self.hwnd):
            try:
                current_title = win32gui.GetWindowText(self.hwnd)
                if self._score_window_title(current_title, primary_keywords) > 0:
                    self.window_title = current_title
                    return
            except Exception:
                pass

        previous_hwnd = self.hwnd
        previous_title = self.window_title
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
                logger.warning(f"Impossible de trouver une fenêtre contenant '{self.window_title_keywords}'")
            return

        self.hwnd, self.window_title, _ = best_match
        if self.hwnd != previous_hwnd or self.window_title != previous_title:
            logger.info(f"Fenêtre cible trouvée: '{self.window_title}' (HWND: {self.hwnd})")

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

    def _ease_out_quad(self, t):
        return t * (2 - t)

    async def _human_mouse_move(self, start_x, start_y, target_x, target_y, duration=None):
        """
        Génère un mouvement de souris fluide basé sur la loi de Fitts et Bézier, 
        avec un potentiel dépassement (overshoot) pour leurrer les anti-cheats.
        """
        distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5
        if duration is None:
            duration = min(max(distance / random.uniform(800, 1500), 0.2), 0.8)
        
        steps = max(5, int(duration * 60))
        
        control_x = start_x + (target_x - start_x) * random.uniform(0.3, 0.7) + random.randint(-150, 150)
        control_y = start_y + (target_y - start_y) * random.uniform(0.3, 0.7) + random.randint(-150, 150)

        for i in range(1, steps + 1):
            t = i / steps
            x = int((1 - t)**2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            y = int((1 - t)**2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)
            win32api.SetCursorPos((x, y))
            await asyncio.sleep(duration / steps)
            
        if random.random() < 0.40:
            ox = target_x + random.randint(-15, 15)
            oy = target_y + random.randint(-15, 15)
            
            o_steps = max(3, int(0.12 * 60))
            for i in range(1, o_steps + 1):
                t = self._ease_out_quad(i / o_steps)
                x = int(target_x + (ox - target_x) * t)
                y = int(target_y + (oy - target_y) * t)
                win32api.SetCursorPos((x, y))
                await asyncio.sleep(0.12 / o_steps)
                
            for i in range(1, o_steps + 1):
                t = self._ease_out_quad(i / o_steps)
                x = int(ox + (target_x - ox) * t)
                y = int(oy + (target_y - oy) * t)
                win32api.SetCursorPos((x, y))
                await asyncio.sleep(0.12 / o_steps)

    async def click_at(self, x: int, y: int, double_click: bool = False):
        """
        Effectue un clic PHYSIQUE (Hardware simulation) aux coordonnées absolues de l'écran.
        Recommandé si le bot tourne sur l'hôte et cible la fenêtre de la VM.
        """
        # Si on vise une fenêtre spécifique (VM), on décale les coordonnées relatives 
        # par rapport au coin de la fenêtre de la VM.
        if self.hwnd:
            rect_origin = self.get_window_rect()
            if rect_origin is None:
                logger.error("CLICK_ATTEMPT | impossible de recuperer le rect origin pour la fenetre cible.")
                return False
            target_x = rect_origin[0] + x
            target_y = rect_origin[1] + y
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
            
        # Obtenir la position actuelle pour démarrer le mouvement
        current_x, current_y = win32api.GetCursorPos()
        
        # Mouvement humain
        await self._human_mouse_move(current_x, current_y, target_x, target_y, duration=random.uniform(MIN_MOVE_DURATION_S, MAX_MOVE_DURATION_S))

        # Micro-pause avant de cliquer
        await asyncio.sleep(random.uniform(0.02, 0.05))

        # On rajoute un focus manuel de la fenêtre pour s'assurer que c'est bien elle qui reçoit le clic
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass

        # Clic Hardware Down/Up avec coordonnée physique absolue
        screen_width = win32api.GetSystemMetrics(0)
        screen_height = win32api.GetSystemMetrics(1)
        abs_x = int(target_x * 65535 / screen_width)
        abs_y = int(target_y * 65535 / screen_height)

        win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTDOWN, abs_x, abs_y, 0, 0)
        await asyncio.sleep(random.uniform(0.02, 0.05))
        win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTUP, abs_x, abs_y, 0, 0)
        
        if double_click:
            await asyncio.sleep(random.uniform(0.03, 0.06))
            win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTDOWN, abs_x, abs_y, 0, 0)
            await asyncio.sleep(random.uniform(0.02, 0.05))
            win32api.mouse_event(win32con.MOUSEEVENTF_ABSOLUTE | win32con.MOUSEEVENTF_LEFTUP, abs_x, abs_y, 0, 0)
            
        logger.debug(f"Clic physique généré ABSOLUTEMENT en ({target_x}, {target_y})")
        return True

    async def send_text(self, text: str):
        """Tape le texte avec un délai aléatoire entre chaque touche (Human-like)."""
        for char in text:
            # Map le caractère au Virtual Key Code correspondant
            vk_code = win32api.VkKeyScanEx(char, win32api.GetKeyboardLayout())
            # Touche enfoncée
            win32api.keybd_event(vk_code & 0xFF, 0, 0, 0)
            await asyncio.sleep(random.uniform(0.01, 0.04))
            # Touche relâchée
            win32api.keybd_event(vk_code & 0xFF, 0, win32con.KEYEVENTF_KEYUP, 0)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    async def execute_action(self, action_request, coords_mapping: dict, **kwargs):
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
        
        # Délai de réflexion humain proportionnel à l'action
        if action_name == "FOLD":
            think_time = random.uniform(1.0, 2.5)
        elif action_name in ["CHECK", "CALL"] and action_intent.bet_size is None:
            think_time = random.uniform(2.0, 4.5)
        else:
            think_time = random.uniform(4.0, 12.0)
            
        logger.info(f"Bot en réflexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)
        
        if action_name == "FOLD":
            coords = coords_mapping.get("FOLD")
            if coords:
                clicked = await self.click_at(*coords)
                if clicked:
                    logger.info("-> Action exécutée : FOLD")
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
                    logger.info(f"-> Action exécutée : {action_name}")
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
                
                # --- Dynamic BB Parsing for resilient betting ---
                import re, json, os
                bb_size = 200  # Fallback par defaut absolu
                active_regex = r'\d+[/,](\d+)\b'
                
                # 1. Selection automatique du profil du site depuis config.json
                if self.window_title:
                    try:
                        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')
                        with open(config_path, 'r') as f:
                            cfg = json.load(f)
                            profiles = cfg.get('bot', {}).get('site_profiles', {})
                            
                            # On cherche quel site correspond au titre de la fenetre actuelle
                            for site_name, profile in profiles.items():
                                if site_name.lower() in self.window_title.lower():
                                    bb_size = int(profile.get('default_bb', bb_size))
                                    active_regex = profile.get('stake_regex', active_regex)
                                    break
                    except Exception:
                        pass

                # 2. Extraction dynamique depuis le titre de la fenetre actuelle avec la regex du site
                if self.window_title:
                    match = re.search(active_regex, self.window_title)
                    if match:
                        try:
                            bb_size = int(match.group(1))
                        except ValueError:
                            pass
                            
                target_amount = action_intent.bet_size if action_intent.bet_size is not None else float(3 * bb_size)
                
                # Si le calcul OCR a fail (pot=0) et crashé à 1.0, on force une relance standard GTO (3 BB)
                if target_amount < bb_size:
                    logger.warning(f"Correction Sizing: {target_amount} est inférieur à 1 BB ({bb_size}). Forcé à 3 BB.")
                    target_amount = float(3 * bb_size)
                
                # Formatage du nombre (Entier si Play Money, Décimal sinon)
                if bb_size >= 10:
                    amount_to_bet = str(int(target_amount))
                else:
                    amount_to_bet = f"{target_amount:.2f}".rstrip('0').rstrip('.')
                    
                logger.info(f"=========== HISTORIQUE MISE ===========")
                logger.info(f"  Action Requise    : {action_name}")
                logger.info(f"  BB détectée       : {bb_size}")
                logger.info(f"  Calcul IA brut    : {action_intent.bet_size}")
                logger.info(f"  Montant Final     : {amount_to_bet}")
                logger.info(f"=======================================")
                
                await self.send_text(amount_to_bet)
                
                await asyncio.sleep(random.uniform(0.08, 0.16))
                
                # Double frappe ENTER pour valider sur les clients récalcitrants
                for _ in range(2):
                    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
                    await asyncio.sleep(random.uniform(0.03, 0.07))
                    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
                    await asyncio.sleep(random.uniform(0.1, 0.2))
                
                # ET on clique le bouton physiques BET_BTN pour valider (Indispensable sur PokerStars récent)
                bet_btn_coords = coords_mapping.get("BET_BTN")
                if bet_btn_coords:
                    logger.info(f"CLICK_ATTEMPT | Clic de sécurité sur le bouton BET_BTN en coords {bet_btn_coords}...")
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                    clicked_btn = await self.click_at(*bet_btn_coords, double_click=False)
                    if not clicked_btn:
                        logger.warning("CLICK_RESULT | Impossible de cliquer BET_BTN en cascade, validation incertaine.")
                    else:
                        logger.info("CLICK_RESULT | Bouton BET_BTN cliqué avec succès.")
                else:
                    logger.warning("CLICK_RESULT | AUCUNE coordonnée pour BET_BTN. L'IA n'a pas vu le bouton final ! Seul ENTER a été pressé.")
                
                logger.info(f"-> Action exécutée : {action_name} ({amount_to_bet}) validé")
                return {
                    "ok": True,
                    "action": action_name,
                    "target": "VK_RETURN+BET_BTN",
                    "bet_size": amount_to_bet,
                }
            logger.warning("CLICK_RESULT | action=%s status=skipped reason=missing_bet_box_coords", action_name)
            return {"ok": False, "action": action_name, "reason": "missing_bet_box_coords"}

        logger.warning("CLICK_RESULT | action=%s status=skipped reason=unsupported_action", action_name)
        return {"ok": False, "action": action_name, "reason": "unsupported_action"}
