import asyncio
import logging
import random
import win32api
import win32con
import win32gui
import math
import ctypes
from typing import Optional, Tuple

from src.bot.sanity_checker import ActionIntent

logger = logging.getLogger(__name__)

# --- CORRECTION DPI AWARENESS ---
# Empêche Windows de fausser les coordonnées (x,y) si l'utilisateur a un zoom écran > 100%
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception as e:
    logger.warning(f"Impossible de définir le DPI Awareness: {e}")

class ActionController:
    """
    Contrôleur d'actions conçu pour fonctionner DEPUIS l'hôte vers une Machine Virtuelle (VM)
    ou DANS une VM. Il simule des mouvements de souris humains (courbes de Bézier) pour 
    déjouer l'analyse heuristique des anti-cheats.
    """
    def __init__(self, window_title_keywords: str = "VirtualBox"):
        self.window_title_keywords = window_title_keywords
        self.hwnd = None
        self._find_window()

    def _find_window(self):
        """Cherche le handle (HWND) de la fenêtre cible (ex: VirtualBox Machine)."""
        def enum_windows_callback(hwnd, context):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if self.window_title_keywords.lower() in title.lower():
                    self.hwnd = hwnd
                    logger.info(f"Fenêtre cible trouvée: '{title}' (HWND: {hwnd})")
        
        win32gui.EnumWindows(enum_windows_callback, None)
        if not self.hwnd:
            logger.warning(f"Impossible de trouver une fenêtre contenant '{self.window_title_keywords}'")

    async def _human_mouse_move(self, start_x, start_y, target_x, target_y, duration=0.3):
        """
        Génère un mouvement de souris fluide entre deux points (approximation Bézier/Ease-out)
        au lieu d'une téléportation robotique. Asynchrone pour ne pas bloquer l'event loop.
        """
        steps = int(duration * 60) # 60 Hz
        if steps == 0: steps = 1
        
        # Ajout d'un léger over-shoot aléatoire pour simuler l'imperfection humaine
        control_x = (start_x + target_x) / 2 + random.randint(-50, 50)
        control_y = (start_y + target_y) / 2 + random.randint(-50, 50)

        for i in range(1, steps + 1):
            t = i / steps
            # Formule de Bézier quadratique
            x = int((1 - t)**2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            y = int((1 - t)**2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)
            
            # Déplacer physiquement la souris
            win32api.SetCursorPos((x, y))
            await asyncio.sleep(duration / steps)

    async def click_at(self, x: int, y: int, double_click: bool = False):
        """
        Effectue un clic PHYSIQUE (Hardware simulation) aux coordonnées absolues de l'écran.
        Recommandé si le bot tourne sur l'hôte et cible la fenêtre de la VM.
        """
        # Si on vise une fenêtre spécifique (VM), on décale les coordonnées relatives 
        # par rapport au coin de la fenêtre de la VM.
        if self.hwnd:
            rect = win32gui.GetWindowRect(self.hwnd)
            target_x = rect[0] + x # left + offset_x
            target_y = rect[1] + y # top + offset_y
        else:
            target_x, target_y = x, y
            
        # Obtenir la position actuelle pour démarrer le mouvement
        current_x, current_y = win32api.GetCursorPos()
        
        # Mouvement humain
        await self._human_mouse_move(current_x, current_y, target_x, target_y, duration=random.uniform(0.15, 0.4))
        
        # Micro-pause avant de cliquer
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Clic Hardware Down/Up
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, target_x, target_y, 0, 0)
        await asyncio.sleep(random.uniform(0.03, 0.08)) # Durée de la pression du clic
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, target_x, target_y, 0, 0)
        
        if double_click:
            await asyncio.sleep(random.uniform(0.05, 0.1))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, target_x, target_y, 0, 0)
            await asyncio.sleep(random.uniform(0.03, 0.08))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, target_x, target_y, 0, 0)
            
        logger.debug(f"Clic physique généré en ({target_x}, {target_y})")

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

    async def execute_action(self, action_request, coords_mapping: dict):
        if isinstance(action_request, ActionIntent):
            action_intent = action_request
        else:
            action_intent = ActionIntent.from_payload(action_request)

        action_name = action_intent.action
        
        # Délai de réflexion humain avant de jouer (très important pour les anti-cheats)
        think_time = random.uniform(1.2, 3.5)
        logger.info(f"Bot en réflexion ({think_time:.2f}s)...")
        await asyncio.sleep(think_time)
        
        if action_name == "FOLD":
            coords = coords_mapping.get("FOLD")
            if coords:
                await self.click_at(*coords)
                logger.info("-> Action exécutée : FOLD")
                
        elif action_name == "CALL" or action_name == "CHECK":
            coords = coords_mapping.get("CALL")
            if coords:
                await self.click_at(*coords)
                logger.info(f"-> Action exécutée : {action_name}")
                
        elif action_name == "ALL_IN" or "RAISE" in action_name or "BET" in action_name:
            text_box_coords = coords_mapping.get("BET_BOX")
            if text_box_coords:
                await self.click_at(*text_box_coords, double_click=True)
                
                amount_to_bet = str(action_intent.bet_size if action_intent.bet_size is not None else 5.50)
                await self.send_text(amount_to_bet)
                
                bet_btn_coords = coords_mapping.get("BET_BTN")
                if bet_btn_coords:
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    await self.click_at(*bet_btn_coords)
                    logger.info(f"-> Action exécutée : {action_name} ({amount_to_bet})")
