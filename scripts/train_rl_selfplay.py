import os
import sys
import numpy as np
import random
import logging
from tqdm import tqdm

# Ajouter le répertoire racine au PYTHONPATH pour importer src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot.rl_agent import RLAdapterAgent

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_synthetic_state(is_fish=False):
    """
    Génère un état de jeu synthétique (vecteur de 50 dimensions) pour l'entraînement.
    Si is_fish est True, on simule un adversaire très large/passif.
    """
    state = np.zeros(50)
    
    # 0: Pot odds / Pot ratio (0.0 to 1.0)
    state[0] = random.uniform(0.1, 0.9)
    # 1: Effective stack / 100 (0.1 to 2.0)
    state[1] = random.uniform(0.1, 2.0)
    
    if is_fish:
        state[2] = random.uniform(0.40, 0.80) # VPIP très haut
        state[3] = random.uniform(0.05, 0.15) # PFR très bas
        state[4] = random.uniform(0.5, 1.0)   # AF faible
    else:
        state[2] = random.uniform(0.15, 0.25) # VPIP régulier
        state[3] = random.uniform(0.10, 0.20) # PFR régulier
        state[4] = random.uniform(2.0, 3.5)   # AF agressif
        
    # Simulation des cartes (random noise pour l'entraînement synthétique)
    for i in range(5, 50):
        state[i] = random.choice([0, 1])
        
    return state

def get_reward(action_idx, state, is_fish):
    """
    Fonction de récompense simulée.
    But: Apprendre au bot à faire des actions exploitatives contre les fishs.
    """
    # Actions: 0: FOLD, 1: CHECK/CALL, 2: RAISE_HALF, 3: RAISE_POT, 4: ALL_IN
    vpip = state[2]
    pot_size = state[0]
    
    reward = 0.0
    
    if is_fish:
        # Contre un fish, la Value (bet fort) est récompensée si on a une "bonne main" (simulée par pot_size)
        if action_idx in [2, 3]: # Bet/Raise
            reward = 1.0 if random.random() > 0.4 else -0.5
        elif action_idx == 1: # Call
            reward = 0.5 if random.random() > 0.5 else -0.2
        elif action_idx == 0: # Fold
            reward = -0.1
    else:
        # Contre un régulier, le bluff (Fold equity) ou le jeu standard est récompensé
        if action_idx == 0:
            reward = 0.0
        elif action_idx == 1:
            reward = 0.1 if random.random() > 0.6 else -0.5
        elif action_idx in [2, 3]:
            reward = 0.5 if random.random() > 0.7 else -1.0
            
    return reward

def train_self_play(episodes=10000):
    """
    Boucle d'entraînement Self-Play / Synthétique.
    L'agent joue contre des profils simulés (Fish/Reg) pour apprendre à dévier de la GTO.
    """
    logger.info(f"Démarrage de l'entraînement RL sur {episodes} épisodes...")
    
    agent = RLAdapterAgent(state_dim=50, action_dim=5)
    
    # Charger le modèle existant si disponible
    agent.load_model()
    
    batch_losses = []
    rewards_history = []
    
    for episode in tqdm(range(episodes), desc="Training Episodes"):
        # 1. Générer le profil de l'adversaire (50% Fish, 50% Reg)
        is_fish = random.random() > 0.5
        state = generate_synthetic_state(is_fish)
        
        # Masque d'actions (toutes valides pour la simulation)
        valid_mask = np.ones(agent.action_dim)
        
        # 2. L'agent choisit une action
        action_idx = agent.select_action(state, valid_mask, exploit_mode=True)
        
        # 3. L'environnement renvoie une récompense (simulée)
        reward = get_reward(action_idx, state, is_fish)
        
        # 4. Générer l'état suivant
        next_state = generate_synthetic_state(is_fish)
        done = True # On simule des épisodes à 1 seule étape pour simplifier (Bandit-like)
        
        # 5. Stocker dans le replay buffer
        agent.store_transition(state, action_idx, reward, next_state, done, valid_mask)
        
        # 6. Entraîner le réseau
        loss = agent.train_step()
        if loss:
            batch_losses.append(loss)
            
        rewards_history.append(reward)
        
        # Sauvegarder périodiquement
        if (episode + 1) % 1000 == 0:
            avg_loss = np.mean(batch_losses[-1000:]) if batch_losses else 0
            avg_reward = np.mean(rewards_history[-1000:])
            logger.info(f"Episode {episode + 1}/{episodes} - Loss: {avg_loss:.4f} - Avg Reward: {avg_reward:.4f} - Epsilon: {agent.epsilon:.3f}")
            agent.save_model()
            
    logger.info("Entraînement terminé avec succès.")
    agent.save_model()

if __name__ == "__main__":
    # Lancer l'entraînement par défaut sur 50 000 épisodes
    train_self_play(episodes=50000)