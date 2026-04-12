import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SessionManager:
    """
    Protège la Bankroll (le capital) du joueur et impose des règles de sécurité strictes.
    Agit comme un "Disjoncteur" si la variance est trop négative ou si le bot joue depuis trop longtemps.
    """
    def __init__(self, max_session_hours: float = 4.0, stop_loss_buyins: float = 3.0, stop_win_buyins: float = 10.0):
        self.start_time = datetime.now()
        self.max_session_duration = timedelta(hours=max_session_hours)
        
        self.stop_loss_buyins = stop_loss_buyins
        self.stop_win_buyins = stop_win_buyins
        
        self.starting_bankroll = 0.0
        self.current_bankroll = 0.0
        self.big_blind_amount = 1.0 # Sera mis à jour dynamiquement
        
        self.is_active = True
        self.shutdown_reason = ""

    def initialize_session(self, current_bankroll: float, big_blind: float):
        self.starting_bankroll = current_bankroll
        self.current_bankroll = current_bankroll
        self.big_blind_amount = big_blind
        self.start_time = datetime.now()
        self.is_active = True
        logger.info(f"🛡️ Session Sécurisée démarrée. Bankroll initiale: {self.starting_bankroll}€")

    def update_bankroll(self, new_amount: float):
        self.current_bankroll = new_amount

    def check_safety_limits(self) -> bool:
        """
        Vérifie si les limites de sécurité ont été franchies.
        Retourne True s'il faut forcer l'arrêt du Bot.
        """
        if not self.is_active:
            return True

        # 1. Vérification du Temps (Fatigue / Sécurité algorithmique)
        time_played = datetime.now() - self.start_time
        if time_played > self.max_session_duration:
            self.shutdown_reason = f"Durée de session maximale atteinte ({time_played})."
            self._trigger_shutdown()
            return True

        # Calcul des profits en nombre de Caves (Buy-ins)
        # 1 Cave = 100 Big Blinds
        buyin_amount = self.big_blind_amount * 100
        if buyin_amount <= 0:
            return False

        profit_loss = self.current_bankroll - self.starting_bankroll
        pl_in_buyins = profit_loss / buyin_amount

        # 2. Vérification du Stop-Loss (Protection du capital)
        if pl_in_buyins <= -self.stop_loss_buyins:
            self.shutdown_reason = f"Stop-Loss atteint (-{abs(pl_in_buyins):.1f} Caves). Protection du capital activée."
            self._trigger_shutdown()
            return True

        # 3. Vérification du Stop-Win (Hit & Run sécurisé)
        if pl_in_buyins >= self.stop_win_buyins:
            self.shutdown_reason = f"Stop-Win atteint (+{pl_in_buyins:.1f} Caves). Objectif rempli, on sécurise les gains."
            self._trigger_shutdown()
            return True

        return False

    def _trigger_shutdown(self):
        self.is_active = False
        logger.error(f"🛑 DISJONCTEUR ACTIVÉ: {self.shutdown_reason}")
        logger.error("🛑 Le bot va se mettre en veille pour protéger votre Bankroll.")
