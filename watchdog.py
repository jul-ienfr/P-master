import subprocess
import time
import sys
import logging
import threading
import pyautogui

try:
    import keyboard
except ImportError:
    print("Veuillez installer le module 'keyboard' : pip install keyboard")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - WATCHDOG - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import json

# --- Configuration Fail-Safe ---
MAX_RESTARTS = 5
RESTART_DELAY_S = 3

# Lecture de la config pour trouver les coordonnees de Fallback (FOLD)
SIT_OUT_COORDS = (556, 649)
try:
    with open("config.json", "r") as f:
        conf = json.load(f)
        fold_coords = conf.get("fallback_coordinates", {}).get("FOLD")
        if fold_coords:
            SIT_OUT_COORDS = (fold_coords[0], fold_coords[1])
except Exception as e:
    logger.warning(f"Impossible de lire config.json, utilisation des coords Fold par defaut. {e}")

POKER_WINDOW_TITLE = "PokerStars"  # Adapter au nom exact de la fenêtre

class Watchdog:
    def __init__(self):
        self.bot_process = None
        self.running = True
        self.restart_count = 0

    def start_bot(self):
        logger.info("Lancement de main.py...")
        self.bot_process = subprocess.Popen([sys.executable, "main.py"])

    def trigger_fail_safe(self):
        """Active le mode survie: prend le focus et met en sit out"""
        logger.warning("Failsafe declenché. Verification de la fenetre Poker...")
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(POKER_WINDOW_TITLE)
            if windows:
                win = windows[0]
                try:
                    win.activate()
                except Exception:
                    pass
                time.sleep(0.5)
                # Clic d'urgence
                logger.warning(f"Clic d'urgence sur {SIT_OUT_COORDS}")
                pyautogui.click(SIT_OUT_COORDS[0], SIT_OUT_COORDS[1])
            else:
                logger.error("Fenetre poker introuvable. Impossible de clique Sit Out.")
        except ImportError:
            logger.error("Veuillez installer pygetwindow (pip install pygetwindow) pour le focus fenetre.")
            pyautogui.click(SIT_OUT_COORDS[0], SIT_OUT_COORDS[1])
        except Exception as e:
            logger.error(f"Erreur durant le failsafe: {e}")

    def kill_switch(self):
        """Coupe tout immediatement"""
        logger.critical("KILL SWITCH DECLENCHE (F12) ! Arret d'urgence du bot.")
        self.running = False
        if self.bot_process and self.bot_process.poll() is None:
            self.bot_process.kill()
        # On deplace la souris dans un coin inoffensif
        pyautogui.moveTo(0, 0, duration=0.1)
        # On quitte de maniere agressive
        import os
        os._exit(1)

    def monitor(self):
        # Activation du kill switch
        keyboard.add_hotkey('f12', self.kill_switch)
        logger.info("Kill Switch arme sur [F12] (requiert droits Admin).")

        self.start_bot()

        while self.running:
            time.sleep(1)
            if self.bot_process.poll() is not None:
                exit_code = self.bot_process.returncode
                logger.error(f"Le process bot s'est arrete avec le code {exit_code}")
                
                if exit_code != 0:
                    self.trigger_fail_safe()
                    
                if self.restart_count < MAX_RESTARTS and self.running:
                    self.restart_count += 1
                    logger.info(f"Redemarrage dans {RESTART_DELAY_S}s... (Tentative {self.restart_count}/{MAX_RESTARTS})")
                    time.sleep(RESTART_DELAY_S)
                    self.start_bot()
                else:
                    logger.critical("Nombre maximum de redemarrages atteint ou arret demande. Fin.")
                    self.running = False

if __name__ == "__main__":
    wd = Watchdog()
    try:
        wd.monitor()
    except KeyboardInterrupt:
        logger.info("Watchdog arrete proprement.")
        if wd.bot_process and wd.bot_process.poll() is None:
            wd.bot_process.terminate()
