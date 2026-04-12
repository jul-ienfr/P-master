import ctypes
import time
import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

# Constantes de l'API Windows (Win32)
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_RETURN = 0x0D

class Win32GhostController:
    """
    Contrôleur Fantôme (API Win32).
    Permet d'envoyer des clics et des touches clavier directement à une fenêtre spécifique (ex: PokerStars)
    en arrière-plan (sans bouger le curseur physique de la souris de l'utilisateur).
    Zéro latence, 100% scalable pour le multi-tabling.
    """
    def __init__(self, window_title: str = "PokerStars"):
        self.window_title = window_title
        self.hwnd = self._find_window(window_title)
        
        if not self.hwnd:
            logger.warning(f"Fenêtre '{window_title}' introuvable. Le mode Fantôme Win32 sera inactif.")

    def _find_window(self, title: str) -> int:
        """Trouve le Handle (HWND) de la fenêtre par son titre."""
        try:
            import win32gui
            # Recherche partielle du titre (ex: "PokerStars Lobby" matchera "PokerStars")
            hwnd = win32gui.FindWindow(None, title)
            if hwnd == 0:
                # Fallback: énumération de toutes les fenêtres pour un match partiel
                def callback(h, hwnds):
                    if win32gui.IsWindowVisible(h) and title.lower() in win32gui.GetWindowText(h).lower():
                        hwnds.append(h)
                    return True
                hwnds = []
                win32gui.EnumWindows(callback, hwnds)
                if hwnds:
                    hwnd = hwnds[0]
            return hwnd
        except ImportError:
            logger.error("Le module pywin32 n'est pas installé. (pip install pywin32)")
            return 0

    def refresh_window_handle(self):
        """Utile en MTT quand on change de table automatiquement."""
        self.hwnd = self._find_window(self.window_title)

    def make_lparam(self, x: int, y: int) -> int:
        """Convertit les coordonnées X,Y en format LPARAM pour l'API Windows."""
        return (y << 16) | (x & 0xFFFF)

    def ghost_click(self, x: int, y: int):
        """Envoie un clic gauche virtuel aux coordonnées X, Y de la fenêtre cible."""
        if not self.hwnd:
            return

        try:
            import win32gui
            import win32api
            import win32con
            
            # On ajoute un micro-jitter (1-2 pixels) pour éviter un clic robotique parfait
            jitter_x = x + random.randint(-2, 2)
            jitter_y = y + random.randint(-2, 2)
            lparam = self.make_lparam(jitter_x, jitter_y)

            # Envoi du message DOWN (pression)
            win32gui.SendMessage(self.hwnd, WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            
            # Délai microscopique humain entre l'appui et le relâchement du clic (30 à 80ms)
            time.sleep(random.uniform(0.03, 0.08))
            
            # Envoi du message UP (relâchement)
            win32gui.SendMessage(self.hwnd, WM_LBUTTONUP, 0, lparam)
            logger.debug(f"Clic fantôme envoyé à {jitter_x},{jitter_y} sur HWND {self.hwnd}")
            
        except Exception as e:
            logger.error(f"Erreur lors du clic Win32 : {e}")

    def ghost_type_amount(self, amount: float):
        """Envoie des frappes de clavier virtuelles à la fenêtre pour saisir le montant."""
        if not self.hwnd:
            return
            
        try:
            import win32gui
            import win32api
            
            amount_str = str(amount)
            for char in amount_str:
                # Convertir le caractère en code ASCII/Virtual Key
                vk_code = ord(char.upper())
                
                # Message KeyDown
                win32api.SendMessage(self.hwnd, WM_KEYDOWN, vk_code, 0)
                # Message d'impression du caractère
                win32api.SendMessage(self.hwnd, WM_CHAR, ord(char), 0)
                # Message KeyUp
                win32api.SendMessage(self.hwnd, WM_KEYUP, vk_code, 0)
                
                # Délai de frappe humain ultra rapide (10-30ms)
                time.sleep(random.uniform(0.01, 0.03))
                
            # Appuyer sur Entrée pour valider (optionnel, selon le casino)
            win32api.SendMessage(self.hwnd, WM_KEYDOWN, VK_RETURN, 0)
            win32api.SendMessage(self.hwnd, WM_KEYUP, VK_RETURN, 0)
            
        except Exception as e:
            logger.error(f"Erreur lors de la frappe Win32 : {e}")

    def execute_action(self, action: str, amount: Optional[float], coords_dict: dict):
        """Exécute l'action de poker instantanément en arrière-plan."""
        action = action.upper()
        
        # 1. Saisie du montant si c'est une mise
        if amount is not None and action in ["BET", "RAISE", "ALL_IN"]:
            if "BET_BOX" in coords_dict:
                box_x, box_y = coords_dict["BET_BOX"]
                self.ghost_click(box_x, box_y)
                time.sleep(0.05)
                # Optionnel: Ctrl+A pour tout sélectionner avant de taper
                self.ghost_type_amount(amount)
        
        # 2. Clic sur le bouton d'action (Fold, Call, Bet)
        if action in coords_dict:
            btn_x, btn_y = coords_dict[action]
            self.ghost_click(btn_x, btn_y)
            logger.info(f"Action '{action}' exécutée en mode FANTÔME (Zéro Latence).")
        else:
            logger.warning(f"Coordonnées pour '{action}' introuvables pour le mode Fantôme.")
