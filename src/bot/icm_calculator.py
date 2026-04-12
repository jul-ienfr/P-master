import logging
from typing import List

logger = logging.getLogger(__name__)

class ICMCalculator:
    """
    Independent Chip Model (ICM)
    Convertit des jetons de tournoi (Chips) en Valeur Monétaire Réelle ($).
    Indispensable pour les bots de tournois (MTT / Sit&Go) à la bulle ou en Table Finale.
    """

    def __init__(self):
        pass

    def calculate_icm(self, stacks: List[float], payouts: List[float]) -> List[float]:
        """
        Calcule l'Equité Monétaire de chaque joueur (Algorithme de Malmuth-Harville).
        :param stacks: Liste des tapis (chips) de tous les joueurs restants.
        :param payouts: Structure des prix (ex: [1000, 500, 200] pour 1er, 2ème, 3ème).
        :return: Liste de la valeur en dollars du stack de chaque joueur.
        """
        if not stacks or not payouts:
            return []

        num_players = len(stacks)
        total_chips = sum(stacks)
        
        # S'il n'y a qu'un prix ou que c'est du Cash Game
        if len(payouts) == 1 or total_chips == 0:
            return [(s / total_chips) * payouts[0] if total_chips > 0 else 0 for s in stacks]

        # S'il y a plus de joueurs que de prix restants, on pad avec des 0
        padded_payouts = payouts + [0.0] * max(0, num_players - len(payouts))
        
        results = [0.0] * num_players

        # Optimisation récursive (Malmuth-Harville)
        def _calculate(remaining_stacks: List[float], depth: int, prob_path: float):
            nonlocal results
            
            if depth >= len(payouts) or sum(remaining_stacks) == 0:
                return

            current_total = sum(remaining_stacks)
            
            for i, stack in enumerate(remaining_stacks):
                if stack > 0:
                    prob_first = stack / current_total
                    # Le joueur i gagne la place 'depth'
                    results[i] += prob_path * prob_first * padded_payouts[depth]
                    
                    # On retire le joueur et on distribue la place suivante
                    new_stacks = list(remaining_stacks)
                    new_stacks[i] = 0 # Éliminé des places restantes
                    
                    _calculate(new_stacks, depth + 1, prob_path * prob_first)

        _calculate(stacks, 0, 1.0)
        return results

    def get_icm_risk_premium(self, hero_stack: float, villain_stack: float, all_stacks: List[float], payouts: List[float]) -> float:
        """
        Calcule le "Risk Premium" (La Prime de Risque).
        C'est le pourcentage de jetons supplémentaires qu'un All-In doit gagner par rapport à une situation 
        de Cash Game (ChipEV) pour que le All-In soit rentable en argent réel.
        """
        if not payouts or len(payouts) < 2:
            return 0.0 # Pas d'effet ICM en début de tournoi ou cash game
            
        # 1. Valeur de notre stack AVANT le coup
        icm_before = self.calculate_icm(all_stacks, payouts)[all_stacks.index(hero_stack)]
        
        # 2. Valeur de notre stack SI ON DOUBLE (Gagne le All-In)
        stacks_win = list(all_stacks)
        stacks_win[all_stacks.index(hero_stack)] += villain_stack
        stacks_win[all_stacks.index(villain_stack)] -= villain_stack
        icm_win = self.calculate_icm(stacks_win, payouts)[all_stacks.index(hero_stack)]
        
        # 3. Valeur de notre stack SI ON BUST (Perd le All-In)
        stacks_lose = list(all_stacks)
        chips_lost = min(hero_stack, villain_stack)
        stacks_lose[all_stacks.index(hero_stack)] -= chips_lost
        stacks_lose[all_stacks.index(villain_stack)] += chips_lost
        icm_lose = self.calculate_icm(stacks_lose, payouts)[all_stacks.index(hero_stack)]
        
        # Gain d'argent en cas de victoire vs Perte d'argent en cas de défaite
        monetary_gain = icm_win - icm_before
        monetary_loss = icm_before - icm_lose
        
        if monetary_gain == 0:
            return 1.0 # Le risque est infini si on ne peut rien gagner
            
        # Calcul du Risk Premium
        # En ChipEV (Cash Game), le rapport est 1:1. En ICM, perdre fait plus mal que gagner.
        risk_premium = (monetary_loss / monetary_gain) - 1.0
        
        return max(0.0, risk_premium)

    def adjust_gto_for_tournament(self, gto_action: str, hero_stack: float, villain_stack: float, all_stacks: List[float], payouts: List[float], pot_size: float) -> str:
        """
        Si le Risk Premium est trop élevé (ex: On est 2ème en jetons à la bulle et le 1er fait tapis),
        le bot refusera le GTO "CALL" et choisira "FOLD" pour survivre dans l'argent.
        """
        if gto_action != "CALL" and gto_action != "ALL_IN":
            return gto_action # L'ICM impacte surtout les gros calls et gros shoves

        risk_premium = self.get_icm_risk_premium(hero_stack, villain_stack, all_stacks, payouts)
        
        # Si la prime de risque est très élevée (> 15% de rentabilité supplémentaire exigée)
        if risk_premium > 0.15 and pot_size > (hero_stack * 0.4):
            logger.warning(f"🚨 [ICM SURVIE] Risk Premium extrême ({risk_premium:.2%}). Le bot OVERRIDE le GTO et FOLD pour sécuriser l'argent du tournoi.")
            return "FOLD"
            
        return gto_action
