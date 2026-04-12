import asyncio
import logging
import random
import time
from typing import List, Dict, Optional

# On simule l'utilisation de l'OCR pour lire le lobby
from src.vision.ocr import PokerOCR
from src.data.database import DatabaseManager

logger = logging.getLogger(__name__)

class Bumhunter:
    """
    Système de Bumhunting automatisé.
    Le Bumhunting (littéralement "chasse aux clochards" au poker) consiste à refuser 
    de jouer contre de bons joueurs (Regs) et à cibler exclusivement les joueurs récréatifs (Whales/Fish).
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
        # Configuration des seuils de "Chasse"
        self.WHALE_VPIP_THRESHOLD = 0.40  # S'il joue plus de 40% des mains, c'est un joueur très rentable
        self.NIT_VPIP_THRESHOLD = 0.16    # S'il joue moins de 16% des mains, c'est un joueur serré/reg
        
        # Le bot ne s'assoit que s'il y a un certain "Profit Score" à la table
        self.MIN_TABLE_SCORE_TO_JOIN = 8 
        
        # On évite de s'asseoir s'il y a trop de regs (joueurs réguliers)
        self.MAX_REGS_ALLOWED = 2

    async def evaluate_table(self, table_name: str, players_at_table: List[str]) -> Dict:
        """
        Analyse les noms des joueurs présents à une table (lus par l'OCR dans le lobby).
        Interroge la base de données pour calculer le score de rentabilité de la table.
        """
        table_score = 0
        regs_count = 0
        whales_count = 0
        unknown_players = 0
        
        logger.info(f"Analyse de la table {table_name} avec {len(players_at_table)} joueurs...")
        
        for player_name in players_at_table:
            # Récupère le profil du joueur dans notre base de données
            profile = await self.db.get_player_profile(player_name)
            
            if not profile or profile.get('hands_played', 0) < 20:
                # Un joueur inconnu est généralement considéré comme un joueur récréatif (fish)
                # jusqu'à preuve du contraire
                table_score += 2
                unknown_players += 1
                continue
                
            # Extraction des stats
            derived = profile.get("derived_profile", {})
            vpip = derived.get("vpip_rate", 0.0)
            pfr = derived.get("pfr_rate", 0.0)
            
            # Classification simple pour le Bumhunting
            if vpip > self.WHALE_VPIP_THRESHOLD:
                # C'est une Baleine ! Jackpot !
                table_score += 15
                whales_count += 1
                logger.info(f"🐳 Baleine détectée à la table {table_name}: {player_name} (VPIP: {vpip*100:.1f}%)")
                
            elif vpip < self.NIT_VPIP_THRESHOLD or (vpip < 0.25 and pfr > 0.18):
                # C'est un "Reg" (Joueur Régulier solide)
                table_score -= 5
                regs_count += 1
                logger.debug(f"🦈 Reg détecté : {player_name}")
                
            elif vpip > 0.30 and pfr < 0.10:
                # Calling station (mauvais joueur passif)
                table_score += 8
                whales_count += 1
                
        decision = "SKIP"
        reason = ""
        
        if whales_count >= 1 or (table_score >= self.MIN_TABLE_SCORE_TO_JOIN and regs_count <= self.MAX_REGS_ALLOWED):
            decision = "JOIN"
            reason = f"Table très rentable (Score: {table_score}, Whales: {whales_count})"
        elif regs_count > self.MAX_REGS_ALLOWED:
            reason = f"Trop de Regs à table ({regs_count})"
        else:
            reason = f"Table pas assez rentable (Score: {table_score})"
            
        return {
            "table_name": table_name,
            "score": table_score,
            "whales_count": whales_count,
            "regs_count": regs_count,
            "decision": decision,
            "reason": reason
        }

    async def check_leave_condition(self, current_table_players: List[str]) -> bool:
        """
        Le "Hit and Run" ou la condition de départ.
        On vérifie si la table est devenue trop difficile.
        Retourne True s'il faut quitter la table.
        """
        # Si on a évalué que la table n'a plus de mauvais joueurs, on part.
        evaluation = await self.evaluate_table("CurrentTable", current_table_players)
        
        if evaluation["decision"] == "SKIP":
            logger.warning(f"La table n'est plus rentable ({evaluation['reason']}). Préparation au départ.")
            return True
            
        return False
