import asyncio
import logging
import os
import sys
import subprocess

# Auto-installation silencieuse de pynput au démarrage si manquant
try:
    from pynput import mouse
    PYNPUT_AVAILABLE = True
except ImportError:
    logging.info("Installation automatique de la dépendance manquante (pynput)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pynput", "--quiet"])
    try:
        from pynput import mouse
        PYNPUT_AVAILABLE = True
        logging.info("Installation réussie.")
    except ImportError:
        PYNPUT_AVAILABLE = False
        logging.warning("Échec de l'installation automatique. L'apprentissage des clics est désactivé.")

# Core Modules
from src.vision.capture import ScreenCapture
from src.vision.temporal_ocr import TemporalOCRFilter
from src.bot.table_tracker import TableTracker
from src.bot.decision_maker import DecisionMaker
from src.bot.bumhunter import Bumhunter
from src.bot.human_interaction import HumanInteractionController
from src.data.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MainLoop")

class SuperBotOrchestrator:
    """
    Le Chef d'Orchestre.
    Gère la boucle événementielle asynchrone pour ne jamais bloquer l'exécution.
    """
    def __init__(self):
        # Initialisation Base de Données
        self.db = DatabaseManager()
        
        # Modules Logiques
        self.tracker = TableTracker(self.db)
        self.decision_maker = DecisionMaker(self.db, create_rl_agent=True, enable_validated_rl=True)
        self.bumhunter = Bumhunter(self.db)
        self.action_controller = HumanInteractionController()
        
        # Modules Vision
        # Capture à 2 FPS (Une image toutes les 500ms, c'est l'optimum pour le poker)
        self.screen_capture = ScreenCapture(target_fps=2)
        self.ocr_filter = TemporalOCRFilter(history_size=3)
        
        self.is_running = False
        self.current_table_players = []
        
        # Variables GUI
        self.mode = "Observe"
        self.gui_callback = None
        
        # Learning coords
        self.learned_coords = {}
        self.awaiting_manual_click_for = None
        
        # Mouse listener pour capturer le clic de l'utilisateur
        self.mouse_listener = None
        if PYNPUT_AVAILABLE:
            self.mouse_listener = mouse.Listener(on_click=self._on_global_click)
            self.mouse_listener.start()

    def _on_global_click(self, x, y, button, pressed):
        """Callback asynchrone déclenché quand l'utilisateur clique n'importe où sur l'écran."""
        if pressed and button == mouse.Button.left:
            if self.awaiting_manual_click_for is not None:
                action = self.awaiting_manual_click_for
                # On enregistre la coordonnée du clic pour cette action
                self.learned_coords[action] = (int(x), int(y))
                self.awaiting_manual_click_for = None
                
                logger.info(f"Apprentissage réussi : L'action {action} est maintenant mappée aux coordonnées ({x}, {y})")
                if self.gui_callback:
                    # En environnement réel, ce callback enverra un event via Tauri vers React
                    self.gui_callback(f"✅ Position apprise pour '{action}' ({int(x)}, {int(y)}). Mode Autoplay activé pour cette action.")

    async def initialize(self):
        logger.info("Initialisation de l'infrastructure asynchrone...")
        await self.db.connect()
        self.screen_capture.start() # Démarre le thread DirectX en arrière-plan
        logger.info("Bot prêt.")

    async def shutdown(self):
        logger.info("Arrêt du Bot...")
        self.is_running = False
        self.screen_capture.stop()
        await self.db.close()

    async def _process_frame(self):
        """Analyse une image et met à jour l'état du jeu."""
        frame = self.screen_capture.get_latest_frame()
        if frame is None:
            await asyncio.sleep(0.05)
            return

        # Ici, dans un cas réel, on passerait la frame dans YOLO pour détecter les Bounding Boxes.
        # Pour l'architecture, on simule l'extraction de l'état "vision_state"
        # En production: vision_state = self.detector.process(frame, self.ocr_filter)
        
        # Simulation d'un état extrait par la vision (A remplacer par l'output YOLO réel)
        vision_state = {
            "street": "PREFLOP",
            "pot": 15.0, # Lissé par le TemporalOCRFilter
            "board": [],
            "hero_cards": ["Ah", "Kd"],
            "legal_actions": ["FOLD", "CALL", "RAISE"],
            "state_confidence": 0.95,
            "players": [
                {"name": "Hero", "is_hero": True, "active": True, "stack": 100.0},
                {"name": "Villain1", "is_hero": False, "active": True, "stack": 85.0}
            ]
        }

        # Mise à jour de la State Machine (TableTracker)
        await self.tracker.update_from_vision(vision_state)
        
        # Mise à jour de la liste des joueurs pour le Bumhunter
        self.current_table_players = [p.get("name") for p in vision_state.get("players", [])]

    async def _decision_loop(self):
        """Boucle de décision asynchrone."""
        while self.is_running:
            # 1. Vérification Bumhunting (Hit & Run)
            if self.current_table_players:
                should_leave = await self.bumhunter.check_leave_condition(self.current_table_players)
                if should_leave:
                    logger.warning("Bumhunter: Cible perdue. Départ de la table ordonné.")
                    # self.action_controller.execute_action("LEAVE_TABLE")
                    # Break ou Pause jusqu'à nouvelle table
                    await asyncio.sleep(5)
                    continue

            # 2. Vérifier si c'est à notre tour de jouer
            hero_seat = next((p for p in self.tracker.players.values() if p.is_hero), None)
            
            # Si nous avons des actions légales et que nous sommes actifs
            if self.tracker.legal_actions and hero_seat and hero_seat.is_active:
                logger.info(f"C'est à nous de jouer ! Actions légales: {self.tracker.legal_actions}")
                
                # Récupérer les infos nécessaires pour le solveur
                villain = self.tracker.get_primary_villain()
                villain_name = villain.name if villain else "Unknown"
                effective_stack = self.tracker.get_effective_stack()
                
                # Tournoi (MTT/SNG) : Données ICM
                # Si c'est du Cash Game, on laisse à None
                tournament_data = None 
                # tournament_data = {
                #     "hero_stack": hero_seat.current_stack,
                #     "villain_stack": villain.current_stack if villain else 0,
                #     "all_stacks": [p.current_stack for p in self.tracker.players.values() if p.is_active],
                #     "payouts": [1000, 500, 0] # Prix du tournoi (ex: Spin&Go ou bulle MTT)
                # }

                # Appel au Cerveau (GTO Rust + Exploitation RL + ICM)
                decision = await self.decision_maker.get_best_action(
                    hero_hand="".join(self.tracker.hero_cards),
                    board=self.tracker.current_board,
                    pot=self.tracker.pot_total,
                    effective_stack=effective_stack,
                    villain_name=villain_name,
                    legal_actions=self.tracker.legal_actions,
                    tournament_data=tournament_data
                )
                
                action = decision.get("action", "FOLD")
                bet_size = decision.get("bet_size")
                
                logger.info(f"Décision finale : {action} {bet_size if bet_size else ''} (Source: {decision.get('source')})")
                
                if self.mode == "Observe":
                    if self.gui_callback:
                        self.gui_callback("Mode Observe: Analyse en cours... Pas de clic automatique.")
                else:
                    # Mode Play
                    if action in self.learned_coords:
                        if self.gui_callback:
                            self.gui_callback("Auto-clic en cours...")
                        self.action_controller.execute_action(action, bet_size, coords=self.learned_coords)
                    else:
                        # On n'a pas encore appris les coordonnées pour cette action
                        self.awaiting_manual_click_for = action
                        if self.gui_callback:
                            self.gui_callback(f"⚠️ Veuillez cliquer MANUELLEMENT sur le bouton '{action}'. Le bot apprendra la position.")
                        
                        # Le bot se met en pause et attend que l'utilisateur clique.
                        # Le clic sera intercepté par `_on_global_click`.
                        while self.awaiting_manual_click_for is not None and self.is_running:
                            await asyncio.sleep(0.1)
                
                # Pause pour éviter d'agir 10 fois pendant que le client de poker traite l'action
                await asyncio.sleep(2)
            
            await asyncio.sleep(0.5)

    async def run(self):
        self.is_running = True
        
        # Lancement en parallèle de l'analyse visuelle et de la boucle de décision
        decision_task = asyncio.create_task(self._decision_loop())
        
        try:
            while self.is_running:
                await self._process_frame()
                # Libère le thread pour les autres tâches asynchrones (très important)
                await asyncio.sleep(0.01) 
        except KeyboardInterrupt:
            pass
        finally:
            await self.shutdown()

if __name__ == "__main__":
    bot = SuperBotOrchestrator()
    try:
        asyncio.run(bot.initialize())
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        asyncio.run(bot.shutdown())