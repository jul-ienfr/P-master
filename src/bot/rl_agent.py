import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
import random
import logging

logger = logging.getLogger(__name__)

class ExploitValueNetwork(nn.Module):
    """
    Réseau de neurones pour évaluer l'espérance de gain d'un état.
    Prend en entrée:
    - L'état brut du jeu (cartes en main, cartes communes, taille du pot, stack effectif)
    - Le profil de l'adversaire (VPIP, PFR, Agression Freq, Fold to CBet, etc.)
    """
    def __init__(self, state_dim, action_dim):
        super(ExploitValueNetwork, self).__init__()
        
        # Architecture profonde pour capturer les non-linéarités complexes du poker
        self.fc1 = nn.Linear(state_dim, 256)
        self.fc2 = nn.Linear(256, 256)
        self.fc3 = nn.Linear(256, 128)
        self.fc_val = nn.Linear(128, 1)          # Valeur de l'état (V)
        self.fc_adv = nn.Linear(128, action_dim) # Avantage des actions (A)
        
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.2)

    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.relu(self.fc2(x))
        x = self.dropout(x)
        x = self.relu(self.fc3(x))
        
        val = self.fc_val(x)
        adv = self.fc_adv(x)
        
        # Architecture Dueling DQN
        # Q(s, a) = V(s) + (A(s, a) - mean(A(s, a)))
        q_values = val + adv - adv.mean(dim=-1, keepdim=True)
        return q_values


class RLAdapterAgent:
    """
    Agent basé sur le Deep Reinforcement Learning (DQN/NFSP).
    Son but n'est pas d'être parfaitement GTO (le solver Rust s'en charge),
    mais de DÉVIER de la GTO pour exploiter les faiblesses d'un adversaire spécifique.
    """
    def __init__(self, state_dim=50, action_dim=5, learning_rate=1e-4, gamma=0.99, buffer_size=100000):
        self.state_dim = state_dim
        self.action_dim = action_dim # Ex: Fold, Check/Call, MinRaise, HalfPot, All-in
        self.gamma = gamma
        self.batch_size = 64
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"[RL_AGENT] Initialisation du réseau sur l'appareil : {self.device}")
        
        self.q_network = ExploitValueNetwork(state_dim, action_dim).to(self.device)
        self.target_network = ExploitValueNetwork(state_dim, action_dim).to(self.device)
        self.target_network.load_state_dict(self.q_network.state_dict())
        self.target_network.eval()
        
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=learning_rate)
        self.loss_fn = nn.MSELoss()
        
        self.memory = deque(maxlen=buffer_size)
        
        self.epsilon = 1.0       # Exploration rate
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.995
        self.update_target_freq = 1000
        self.step_count = 0
        
        # Assurer la création du dossier modèle
        os.makedirs("models/rl", exist_ok=True)

    def select_action(self, state_vector, valid_actions_mask, exploit_mode=True):
        """
        Choisit une action basée sur la politique e-greedy.
        """
        # epsilon-greedy pour l'exploration
        if exploit_mode and random.random() < self.epsilon:
            valid_indices = np.where(valid_actions_mask == 1)[0]
            if len(valid_indices) > 0:
                return np.random.choice(valid_indices)
            return 0 # Default (souvent Fold)
            
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state_vector).unsqueeze(0).to(self.device)
            q_values = self.q_network(state_tensor).cpu().numpy()[0]
            
            # Masquer les actions invalides (ex: impossible de checker si on fait face à une mise)
            q_values[valid_actions_mask == 0] = -np.inf
            
            return np.argmax(q_values)

    def store_transition(self, state, action, reward, next_state, done, valid_actions_mask_next):
        """Stocke l'expérience dans le replay buffer."""
        self.memory.append((state, action, reward, next_state, done, valid_actions_mask_next))

    def train_step(self):
        """Entraîne le réseau avec un mini-batch depuis la mémoire."""
        if len(self.memory) < self.batch_size:
            return 0.0
            
        batch = random.sample(self.memory, self.batch_size)
        states, actions, rewards, next_states, dones, next_masks = zip(*batch)
        
        states = torch.FloatTensor(np.array(states)).to(self.device)
        actions = torch.LongTensor(np.array(actions)).unsqueeze(1).to(self.device)
        rewards = torch.FloatTensor(np.array(rewards)).unsqueeze(1).to(self.device)
        next_states = torch.FloatTensor(np.array(next_states)).to(self.device)
        dones = torch.FloatTensor(np.array(dones)).unsqueeze(1).to(self.device)
        next_masks = torch.FloatTensor(np.array(next_masks)).to(self.device)
        
        # Double DQN : Sélection avec Q-net, Evaluation avec Target-net
        current_q_values = self.q_network(states).gather(1, actions)
        
        with torch.no_grad():
            next_q_values_online = self.q_network(next_states)
            next_q_values_online[next_masks == 0] = -float('inf')
            best_next_actions = next_q_values_online.max(1)[1].unsqueeze(1)
            
            next_q_values_target = self.target_network(next_states).gather(1, best_next_actions)
            target_q_values = rewards + (1 - dones) * self.gamma * next_q_values_target
            
        loss = self.loss_fn(current_q_values, target_q_values)
        
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0) # Prévenir l'explosion des gradients
        self.optimizer.step()
        
        self.step_count += 1
        if self.step_count % self.update_target_freq == 0:
            self.target_network.load_state_dict(self.q_network.state_dict())
            
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
            
        return loss.item()

    def save_model(self, filepath="models/rl/exploit_model.pth"):
        torch.save(self.q_network.state_dict(), filepath)
        logger.info(f"Modèle RL sauvegardé dans {filepath}")

    def load_model(self, filepath="models/rl/exploit_model.pth"):
        if os.path.exists(filepath):
            self.q_network.load_state_dict(torch.load(filepath, map_location=self.device))
            self.target_network.load_state_dict(self.q_network.state_dict())
            logger.info(f"Modèle RL chargé depuis {filepath}")
            self.epsilon = self.epsilon_min # Une fois chargé, on explore moins
        else:
            logger.warning(f"Aucun modèle trouvé à {filepath}, initialisation d'un nouveau modèle.")
