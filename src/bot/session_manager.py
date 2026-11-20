"""Disjoncteur de session — enveloppe du moteur de bankroll Rust (spec 004).

La décision d'arrêt (durée, plafond journalier, stop-loss, stop-win) est prise
par ``bankroll.session_verdict``, c'est-à-dire par le moteur Rust de
``src/bankroll.rs``. Cette classe ne garde que ce qui est intrinsèquement
Python : l'horloge de session, le suivi de la bankroll et les messages
opérateur.

Les seuils par défaut sont **identiques** à ceux de la version historique
(4 h, −3 caves, +10 caves), donc le comportement observable ne change pas ; ce
qui change est que la règle est désormais testée contre une forme fermée et
partagée avec le reste du système.
"""

import logging
from datetime import datetime, timedelta

from src.bot import bankroll

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Protège la Bankroll (le capital) du joueur et impose des règles de sécurité strictes.
    Agit comme un "Disjoncteur" si la variance est trop négative ou si le bot joue depuis trop longtemps.
    """

    def __init__(
        self,
        max_session_hours: float = bankroll.DEFAULT_MAX_HOURS,
        stop_loss_buyins: float = bankroll.DEFAULT_STOP_LOSS_BUYINS,
        stop_win_buyins: float = bankroll.DEFAULT_STOP_WIN_BUYINS,
        max_hands_per_day: int = bankroll.DEFAULT_MAX_HANDS_PER_DAY,
    ):
        self.limits = bankroll.SessionLimits(
            max_hours=max_session_hours,
            stop_loss_buyins=stop_loss_buyins,
            stop_win_buyins=stop_win_buyins,
            max_hands_per_day=max_hands_per_day,
        )
        self.start_time = datetime.now()
        self.max_session_duration = timedelta(hours=self.limits.max_hours)

        self.stop_loss_buyins = self.limits.stop_loss_buyins
        self.stop_win_buyins = self.limits.stop_win_buyins

        self.starting_bankroll = 0.0
        self.current_bankroll = 0.0
        self.big_blind_amount = 1.0  # Sera mis à jour dynamiquement

        self.hands_played = 0
        self.is_active = True
        self.shutdown_reason = ""

    def initialize_session(self, current_bankroll: float, big_blind: float):
        self.starting_bankroll = current_bankroll
        self.current_bankroll = current_bankroll
        self.big_blind_amount = big_blind
        self.start_time = datetime.now()
        self.hands_played = 0
        self.is_active = True
        logger.info(f"🛡️ Session Sécurisée démarrée. Bankroll initiale: {self.starting_bankroll}€")

    def update_bankroll(self, new_amount: float):
        self.current_bankroll = new_amount

    def record_hand(self):
        """Compte une main jouée (alimente le plafond journalier)."""
        self.hands_played += 1

    def _profit_loss_buyins(self) -> float:
        """Profit/perte de la session en caves. 1 cave = 100 grosses blindes."""
        buyin_amount = self.big_blind_amount * 100
        if buyin_amount <= 0:
            return 0.0
        return (self.current_bankroll - self.starting_bankroll) / buyin_amount

    def _stop_message(self, reason: str, pl_in_buyins: float) -> str:
        if reason == "max_duration":
            return f"Durée de session maximale atteinte ({datetime.now() - self.start_time})."
        if reason == "daily_hands":
            return f"Plafond de mains atteint ({self.hands_played} mains). Pause imposée."
        if reason == "stop_loss":
            return (
                f"Stop-Loss atteint (-{abs(pl_in_buyins):.1f} Caves). "
                "Protection du capital activée."
            )
        return (
            f"Stop-Win atteint (+{pl_in_buyins:.1f} Caves). Objectif rempli, on sécurise les gains."
        )

    def check_safety_limits(self) -> bool:
        """
        Vérifie si les limites de sécurité ont été franchies.
        Retourne True s'il faut forcer l'arrêt du Bot.
        """
        if not self.is_active:
            return True

        time_played = datetime.now() - self.start_time
        pl_in_buyins = self._profit_loss_buyins()

        reason = bankroll.session_verdict(
            self.limits,
            hours_played=time_played.total_seconds() / 3600.0,
            profit_loss_buyins=pl_in_buyins,
            hands_today=self.hands_played,
        )
        if reason is None:
            return False

        self.shutdown_reason = self._stop_message(reason, pl_in_buyins)
        self._trigger_shutdown()
        return True

    def _trigger_shutdown(self):
        self.is_active = False
        logger.error(f"🛑 DISJONCTEUR ACTIVÉ: {self.shutdown_reason}")
        logger.error("🛑 Le bot va se mettre en veille pour protéger votre Bankroll.")
