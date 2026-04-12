import time
import random
import pyautogui
import pydirectinput
import logging

logger = logging.getLogger(__name__)

class HumanInteractionController:
    """
    Système de contrôle d'entrées hautement indétectable pour éviter les systèmes anti-bot.
    Mélange le contrôle de la souris avec des courbes de Bézier (mouvements humains)
    et les raccourcis claviers (pydirectinput) de manière probabiliste.
    """
    
    def __init__(self):
        # Configuration de sécurité PyAutoGUI
        pyautogui.FAILSAFE = True
        pyautogui.MINIMUM_DURATION = 0.1
        pyautogui.MINIMUM_SLEEP = 0.05
        
        # Mapping clavier typique (à adapter selon les raccourcis PokerStars)
        self.keybinds = {
            "FOLD": "f",
            "CHECK": "c",
            "CALL": "c",
            "BET": "b",
            "RAISE": "r",
            "ALL_IN": "a"
        }

    def _human_sleep(self, base_duration: float):
        """Pause avec une petite variation aléatoire (jitter)."""
        time.sleep(base_duration + random.uniform(0.01, 0.15))

    def _ease_out_quad(self, t):
        """Fonction d'easing pour ralentir la souris à l'approche de la cible."""
        return t * (2 - t)

    def _move_mouse_human_like(self, x: int, y: int):
        """
        Déplace la souris vers une cible en simulant une courbe et une vitesse humaine.
        """
        current_x, current_y = pyautogui.position()
        
        # Ajout d'une marge d'erreur pour ne pas cliquer au pixel exact à chaque fois (offset)
        target_x = x + random.randint(-4, 4)
        target_y = y + random.randint(-4, 4)
        
        # Durée de trajet aléatoire basée sur la distance
        distance = ((target_x - current_x) ** 2 + (target_y - current_y) ** 2) ** 0.5
        duration = min(max(distance / random.uniform(800, 1500), 0.2), 0.8) # Entre 0.2s et 0.8s
        
        # Déplacement avec un tweening pour simuler l'inertie humaine
        pyautogui.moveTo(
            target_x, 
            target_y, 
            duration=duration, 
            tween=self._ease_out_quad
        )
        self._human_sleep(0.05) # Micro pause avant le clic comme un vrai humain

    def execute_action(self, action: str, amount: float = None, coords: dict = None):
        """
        Exécute l'action demandée en alternant aléatoirement entre:
        1. Mouvement de souris + Clic
        2. Raccourci Clavier
        """
        action = action.upper()
        use_keyboard = random.random() < 0.35 # 35% de chances d'utiliser le clavier
        
        # Gérer la saisie du montant de mise si applicable
        if amount is not None and action in ["BET", "RAISE", "ALL_IN"]:
            self._enter_bet_amount(amount, coords.get("BET_BOX") if coords else None)
            
        if use_keyboard and action in self.keybinds:
            logger.info(f"Exécution indétectable ({action}) : Raccourci Clavier '{self.keybinds[action]}'")
            pydirectinput.press(self.keybinds[action])
            self._human_sleep(random.uniform(0.1, 0.3))
        else:
            # S'il n'y a pas de coords, on ne peut pas cliquer, on fallback sur le clavier
            if not coords or action not in coords:
                logger.warning(f"Coordonnées manquantes pour l'action souris {action}, fallback clavier.")
                if action in self.keybinds:
                    pydirectinput.press(self.keybinds[action])
                return

            target = coords[action]
            logger.info(f"Exécution indétectable ({action}) : Mouvement Souris vers {target}")
            
        # Temps de réaction avant de bouger la souris (0.8 à 2.5 secondes - plus naturel)
        self._human_sleep(random.uniform(0.8, 2.5)) 
        
        self._move_mouse_human_like(target[0], target[1])
        # Petit délai aléatoire une fois sur le bouton avant d'appuyer (comportement très humain)
        self._human_sleep(random.uniform(0.05, 0.2))
        pyautogui.click()
        
        # Parfois on retire la souris du bouton après le clic (50% du temps)
        if random.random() < 0.5:
            self._human_sleep(random.uniform(0.1, 0.3))
            pyautogui.moveRel(random.randint(-100, 100), random.randint(-100, 100), duration=random.uniform(0.2, 0.5))

    def _enter_bet_amount(self, amount: float, bet_box_coords: tuple = None):
        """Saisit un montant en simulant les frappes au clavier."""
        if bet_box_coords:
            self._move_mouse_human_like(bet_box_coords[0], bet_box_coords[1])
            pyautogui.click(clicks=2, interval=0.1) # Double clic pour sélectionner le texte existant
            self._human_sleep(0.1)
            
        amount_str = str(amount)
        for char in amount_str:
            pydirectinput.press(char)
            self._human_sleep(random.uniform(0.05, 0.15)) # Typo delay aléatoire
        self._human_sleep(0.2)
