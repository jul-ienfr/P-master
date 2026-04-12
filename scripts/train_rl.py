import asyncio
import json
import logging
import os
import sys
import numpy as np
import torch
from pathlib import Path

# Ajouter le répertoire racine au PYTHONPATH
sys.path.append(str(Path(__file__).parent.parent))

from src.bot.rl_agent import RLAdapterAgent
from src.data.database import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("RL_Trainer")

# Mapping inversé pour parser les actions de la DB
ACTION_MAP = {"FOLD": 0, "CHECK": 1, "CALL": 1, "BET": 2, "RAISE": 2, "BET_50": 2, "BET_75": 3, "ALL_IN": 4}

def create_valid_mask(legal_actions: list) -> np.ndarray:
    mask = np.zeros(5) # 5 dimensions d'actions dans rl_agent.py
    for action in legal_actions:
        action_idx = ACTION_MAP.get(action.upper())
        if action_idx is not None:
            mask[action_idx] = 1
    # Toujours autoriser fold (0)
    mask[0] = 1
    return mask

def mock_state_vector(pot_size, effective_stack):
    # Vecteur d'état temporaire (50 dimensions pour matcher rl_agent.py)
    # L'implémentation finale devra utiliser exactement la même fonction d'encodage que dans decision_maker.py
    state = np.zeros(50)
    state[0] = float(pot_size) / max(float(effective_stack), 1.0)
    state[1] = float(effective_stack) / 100.0
    # Simulate some opponent stats (VPIP, PFR, AF)
    state[2] = 0.25 
    state[3] = 0.18
    state[4] = 2.0
    return state

async def train_from_database():
    """Entraîne l'agent RL à partir de l'historique des mains stocké dans PostgreSQL."""
    logger.info("Initialisation de l'entraînement de l'agent RL...")
    
    db = DatabaseManager()
    await db.connect()
    
    agent = RLAdapterAgent()
    agent.load_model()
    
    if not db.pool and db.mode != "memory":
        logger.error("Impossible de se connecter à la base de données. Vérifiez POKER_DB_MODE ou les identifiants.")
        return

    logger.info("Extraction des historiques de mains...")
    
    hands = []
    if db.pool:
        async with db.pool.acquire() as conn:
            # On récupère toutes les mains avec des actions
            rows = await conn.fetch("SELECT * FROM hands_history ORDER BY timestamp ASC")
            hands = [dict(row) for row in rows]
    elif db.mode == "memory":
        hands = db.hands_history_memory
        
    if not hands:
        logger.warning("Aucune main trouvée dans la base de données. Simulation d'entraînement avec des données fictives pour validation du pipeline...")
        # Données fictives pour s'assurer que le pipeline d'entraînement ne crash pas
        hands = [
            {
                "board": "AhKd2c",
                "actions": json.dumps([
                    {"player": "Hero", "action": "BET", "amount": 5.0, "pot_size": 10.0, "street": "FLOP"},
                    {"player": "Villain", "action": "CALL", "amount": 5.0, "pot_size": 15.0, "street": "FLOP"},
                    {"player": "Hero", "action": "RAISE", "amount": 15.0, "pot_size": 25.0, "street": "TURN"},
                    {"player": "Villain", "action": "FOLD", "amount": 0.0, "pot_size": 40.0, "street": "TURN"},
                ])
            } for _ in range(50) # Simuler 50 mains
        ]

    logger.info(f"{len(hands)} mains récupérées. Début de l'Experience Replay.")
    
    total_loss = 0
    transitions_added = 0
    
    # Étape 1 : Remplir le Replay Buffer
    for hand in hands:
        actions_raw = hand.get("actions", "[]")
        if isinstance(actions_raw, str):
            try:
                actions = json.loads(actions_raw)
            except json.JSONDecodeError:
                continue
        else:
            actions = actions_raw
            
        if not actions or not isinstance(actions, list):
            continue
            
        # Reconstruire les transitions (État, Action, Récompense, Nouvel État)
        # Simplification: on associe la récompense finale aux actions du Hero
        
        # Déterminer si le Hero a gagné le pot (simpliste: si le villain a FOLD, hero gagne)
        hero_won = any(a.get("player") != "Hero" and a.get("action") == "FOLD" for a in actions)
        final_pot = float(actions[-1].get("pot_size", 0.0)) if actions else 0.0
        reward = final_pot if hero_won else -float(sum(a.get("amount", 0.0) for a in actions if a.get("player") == "Hero"))

        current_state = None
        current_action_idx = None
        
        for i, action_data in enumerate(actions):
            if not isinstance(action_data, dict):
                continue
                
            player = action_data.get("player", "")
            action_type = action_data.get("action", "")
            pot = float(action_data.get("pot_size", 10.0))
            
            if player == "Hero":
                # L'état AU MOMENT de la décision
                state = mock_state_vector(pot, effective_stack=100.0)
                action_idx = ACTION_MAP.get(action_type, 0) # FOLD par defaut
                
                if current_state is not None and current_action_idx is not None:
                    # Transition N-1 -> N
                    # Puisqu'on est au milieu de la main, la récompense intermédiaire est 0, 
                    # et l'épisode n'est pas terminé (done=False)
                    valid_mask_next = create_valid_mask(["FOLD", "CALL", "BET", "RAISE", "ALL_IN"])
                    agent.store_transition(
                        state=current_state,
                        action=current_action_idx,
                        reward=0.0,
                        next_state=state,
                        done=False,
                        valid_actions_mask_next=valid_mask_next
                    )
                    transitions_added += 1
                
                current_state = state
                current_action_idx = action_idx
                
        # Fin de la main (Transition finale)
        if current_state is not None and current_action_idx is not None:
            # État terminal (vecteur de 0)
            terminal_state = np.zeros(50)
            terminal_mask = np.zeros(5)
            
            agent.store_transition(
                state=current_state,
                action=current_action_idx,
                reward=reward, # La récompense finale (le pot gagné ou l'argent perdu)
                next_state=terminal_state,
                done=True,
                valid_actions_mask_next=terminal_mask
            )
            transitions_added += 1

    logger.info(f"Replay Buffer rempli avec {transitions_added} transitions.")
    
    # Étape 2 : Entraîner le réseau (Mini-batches)
    training_steps = min(transitions_added, 2000) # Limiter pour ne pas boucler indéfiniment
    
    if training_steps >= agent.batch_size:
        logger.info(f"Lancement de {training_steps} cycles d'optimisation (Backpropagation)...")
        for step in range(training_steps):
            loss = agent.train_step()
            total_loss += loss
            
            if (step + 1) % 100 == 0:
                logger.info(f"Step {step + 1}/{training_steps} - Loss: {loss:.4f} - Epsilon: {agent.epsilon:.3f}")
                
        # Sauvegarde des nouveaux poids synaptiques
        agent.save_model()
        logger.info(f"Entraînement terminé. Loss moyenne : {total_loss / training_steps:.4f}")
    else:
        logger.warning(f"Pas assez de transitions en mémoire ({transitions_added} < {agent.batch_size}) pour lancer le Deep Learning.")
        
    await db.close()

if __name__ == "__main__":
    # Exécution asynchrone de la boucle d'entraînement
    try:
        asyncio.run(train_from_database())
    except KeyboardInterrupt:
        logger.info("Entraînement interrompu par l'utilisateur.")
    except Exception as e:
        logger.error(f"Erreur critique lors de l'entraînement : {e}", exc_info=True)
