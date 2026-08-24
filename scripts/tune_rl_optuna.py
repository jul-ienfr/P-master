#!/usr/bin/env python3
"""
Optuna hyperparameter tuning for the RL poker agent (Dueling DQN).

Tunes hyperparameters of RLAdapterAgent using Optuna with TPE sampler
and Median pruning. The search includes learning rate, gamma, batch size,
epsilon decay, buffer size, network architecture (fc units, dropout),
and gradient clipping.

Usage:
    python scripts/tune_rl_optuna.py [--trials 50] [--episodes 3000]
        [--storage sqlite:///models/rl/optuna_study.db]
"""

import argparse
import json
import logging
import os
import random
import sys
import types
import warnings

import numpy as np

# Add project root to sys.path for imports from src/ and scripts/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
_logs_dir = os.path.join(_project_root, "logs")
os.makedirs(_logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_logs_dir, "tune_rl_optuna.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure model directory exists
# ---------------------------------------------------------------------------
os.makedirs(os.path.join(_project_root, "models", "rl"), exist_ok=True)

# ---------------------------------------------------------------------------
# Optuna imports
# ---------------------------------------------------------------------------
try:
    import optuna
    from optuna.samplers import TPESampler
    from optuna.pruners import MedianPruner
    import optuna.trial
except ImportError:
    print("Optuna is required. Install it with: pip install optuna")
    sys.exit(1)

# ---------------------------------------------------------------------------
# PyTorch import (required by the RL agent)
# ---------------------------------------------------------------------------
try:
    import torch
    import torch.nn as nn
except ImportError:
    print("PyTorch is required. Install it with: pip install torch")
    sys.exit(1)


# ===================================================================
# Utility: dynamic network factory
# ===================================================================
def make_dynamic_exploit_network(fc1_units, fc2_units, fc3_units, dropout_rate):
    """
    Create a Dueling DQN network class with configurable hidden-layer sizes
    and dropout rate, matching the structure of ExploitValueNetwork but
    with user-defined dimensions.
    """
    class DynamicExploitValueNetwork(nn.Module):
        def __init__(self, state_dim, action_dim):
            super(DynamicExploitValueNetwork, self).__init__()
            self.fc1 = nn.Linear(state_dim, fc1_units)
            self.fc2 = nn.Linear(fc1_units, fc2_units)
            self.fc3 = nn.Linear(fc2_units, fc3_units)
            self.fc_val = nn.Linear(fc3_units, 1)
            self.fc_adv = nn.Linear(fc3_units, action_dim)
            self.relu = nn.ReLU()
            self.dropout = nn.Dropout(dropout_rate)

        def forward(self, x):
            x = self.relu(self.fc1(x))
            x = self.dropout(x)
            x = self.relu(self.fc2(x))
            x = self.dropout(x)
            x = self.relu(self.fc3(x))

            val = self.fc_val(x)
            adv = self.fc_adv(x)

            # Dueling DQN: Q(s,a) = V(s) + (A(s,a) - mean(A(s,a)))
            q_values = val + adv - adv.mean(dim=-1, keepdim=True)
            return q_values

    return DynamicExploitValueNetwork


# ===================================================================
# Patched train_step using agent.gradient_clip instead of hardcoded 1.0
# ===================================================================
def _patched_train_step(self):
    """
    Replacement for RLAdapterAgent.train_step that uses self.gradient_clip
    (set dynamically per trial) instead of the hardcoded value 1.0.
    """
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

    # Double DQN: selection with online network, evaluation with target network
    current_q_values = self.q_network(states).gather(1, actions)

    with torch.no_grad():
        next_q_values_online = self.q_network(next_states)
        next_q_values_online[next_masks == 0] = -float("inf")
        best_next_actions = next_q_values_online.max(1)[1].unsqueeze(1)
        next_q_values_target = self.target_network(next_states).gather(
            1, best_next_actions
        )
        target_q_values = (
            rewards + (1 - dones) * self.gamma * next_q_values_target
        )

    loss = self.loss_fn(current_q_values, target_q_values)

    self.optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(
        self.q_network.parameters(), self.gradient_clip
    )
    self.optimizer.step()

    self.step_count += 1
    if self.step_count % self.update_target_freq == 0:
        self.target_network.load_state_dict(self.q_network.state_dict())

    if self.epsilon > self.epsilon_min:
        self.epsilon *= self.epsilon_decay

    return loss.item()


# ===================================================================
# Optuna objective function
# ===================================================================
def objective(trial, episodes):
    """
    Optuna objective: sample hyperparameters, train agent for `episodes`
    steps, return average reward over the last 500 steps.

    Reports intermediate values every 500 episodes for MedianPruner.
    """
    # --- Suggest hyperparameters -------------------------------------------
    lr = trial.suggest_float("learning_rate", 1e-5, 1e-3, log=True)
    gamma = trial.suggest_float("gamma", 0.9, 0.999)
    batch_size = trial.suggest_categorical("batch_size", [32, 64, 128, 256])
    epsilon_decay = trial.suggest_float("epsilon_decay", 0.97, 0.999)
    buffer_size = trial.suggest_categorical(
        "buffer_size", [50000, 100000, 200000]
    )
    update_target_freq = trial.suggest_categorical(
        "update_target_freq", [500, 1000, 2000]
    )
    dropout = trial.suggest_float("dropout", 0.1, 0.4)
    fc1_units = trial.suggest_categorical("fc1_units", [128, 256, 512])
    fc2_units = trial.suggest_categorical("fc2_units", [128, 256])
    fc3_units = trial.suggest_categorical("fc3_units", [64, 128, 256])
    gradient_clip = trial.suggest_float("gradient_clip", 0.5, 5.0)

    logger.info(
        "Trial %3d: lr=%.6f  gamma=%.4f  batch=%d  eps_decay=%.4f  "
        "buf=%d  upd_freq=%d  drop=%.2f  fc1=%d  fc2=%d  fc3=%d  clip=%.2f",
        trial.number,
        lr,
        gamma,
        batch_size,
        epsilon_decay,
        buffer_size,
        update_target_freq,
        dropout,
        fc1_units,
        fc2_units,
        fc3_units,
        gradient_clip,
    )

    # --- Patch the network class in the module -----------------------------
    import src.bot.rl_agent as rl_agent_module

    DynamicNet = make_dynamic_exploit_network(
        fc1_units, fc2_units, fc3_units, dropout
    )
    DynamicNet.__name__ = "ExploitValueNetwork"
    DynamicNet.__qualname__ = "ExploitValueNetwork"
    rl_agent_module.ExploitValueNetwork = DynamicNet

    # --- Create agent ------------------------------------------------------
    from src.bot.rl_agent import RLAdapterAgent

    agent = RLAdapterAgent(
        state_dim=50,
        action_dim=5,
        learning_rate=lr,
        gamma=gamma,
        buffer_size=buffer_size,
    )

    # --- Patch extra instance attributes -----------------------------------
    agent.batch_size = batch_size
    agent.epsilon_decay = epsilon_decay
    agent.update_target_freq = update_target_freq
    agent.gradient_clip = gradient_clip

    # Replace train_step with the patched version so it uses gradient_clip
    agent.train_step = types.MethodType(_patched_train_step, agent)

    # --- Import training helpers -------------------------------------------
    try:
        from scripts.train_rl_selfplay import generate_synthetic_state, get_reward
    except ImportError as exc:
        logger.error(
            "Failed to import from scripts/train_rl_selfplay.py: %s", exc
        )
        raise

    # --- Training loop -----------------------------------------------------
    rewards_history = []
    logger.info(
        "Trial %d: starting training for %d episodes...",
        trial.number,
        episodes,
    )

    try:
        for episode in range(1, episodes + 1):
            is_fish = random.random() > 0.5
            state = generate_synthetic_state(is_fish)
            valid_mask = np.ones(agent.action_dim)

            action_idx = agent.select_action(state, valid_mask, exploit_mode=True)
            reward_val = get_reward(action_idx, state, is_fish)
            next_state = generate_synthetic_state(is_fish)
            done = True  # one-step episodes (bandit-like)

            agent.store_transition(
                state, action_idx, reward_val, next_state, done, valid_mask
            )
            agent.train_step()
            rewards_history.append(reward_val)

            # Report intermediate values at regular intervals for pruning
            if episode % 500 == 0:
                avg_reward = float(np.mean(rewards_history[-500:]))
                trial.report(avg_reward, episode)

                logger.info(
                    "Trial %d, episode %5d/%d: avg_reward (last 500) = %.4f",
                    trial.number,
                    episode,
                    episodes,
                    avg_reward,
                )

                if trial.should_prune():
                    logger.info(
                        "Trial %d pruned at episode %d (avg_reward=%.4f)",
                        trial.number,
                        episode,
                        avg_reward,
                    )
                    raise optuna.TrialPruned()

        final_avg_reward = float(np.mean(rewards_history[-500:]))
        logger.info(
            "Trial %d complete: final avg reward (last 500) = %.4f",
            trial.number,
            final_avg_reward,
        )
        return final_avg_reward

    finally:
        # Clean up GPU memory between trials (no-op on CPU)
        del agent
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# ===================================================================
# Main entry point
# ===================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Optuna hyperparameter tuning for the RL poker agent."
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=50,
        help="Number of Optuna trials (default: 50)",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=3000,
        help="Episodes per trial (default: 3000)",
    )
    parser.add_argument(
        "--storage",
        type=str,
        default="sqlite:///models/rl/optuna_study.db",
        help="Optuna storage URL (default: sqlite:///models/rl/optuna_study.db)",
    )
    args = parser.parse_args()

    logger.info(
        "Starting Optuna tuning: %d trials, %d episodes per trial",
        args.trials,
        args.episodes,
    )
    logger.info("Storage: %s", args.storage)

    # ------------------------------------------------------------------
    # Sampler & Pruner
    # ------------------------------------------------------------------
    sampler = TPESampler(n_startup_trials=10, seed=42)
    pruner = MedianPruner(n_startup_trials=10, n_warmup_steps=1000)

    # ------------------------------------------------------------------
    # Create or load study
    # ------------------------------------------------------------------
    try:
        study = optuna.create_study(
            study_name="rl_agent_tuning",
            storage=args.storage,
            sampler=sampler,
            pruner=pruner,
            direction="maximize",
        )
        logger.info("Created new study 'rl_agent_tuning'.")
    except optuna.exceptions.DuplicatedStudyError:
        logger.info(
            "Study 'rl_agent_tuning' already exists. Loading it (sampler/pruner "
            "will be ignored for existing trials)."
        )
        study = optuna.load_study(
            study_name="rl_agent_tuning",
            storage=args.storage,
            sampler=sampler,
            pruner=pruner,
        )

    # ------------------------------------------------------------------
    # Run optimisation
    # ------------------------------------------------------------------
    logger.info("Beginning optimisation...")
    study.optimize(
        lambda trial: objective(trial, args.episodes),
        n_trials=args.trials,
        show_progress_bar=True,
    )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    logger.info("Optimisation finished.")
    logger.info("Number of completed trials: %d", len(study.trials))

    best_trial = study.best_trial
    logger.info("=" * 60)
    logger.info("Best trial:")
    logger.info("  Trial number: %d", best_trial.number)
    logger.info("  Value (avg reward): %.6f", best_trial.value)
    logger.info("  Params:")
    for key, value in best_trial.params.items():
        logger.info("    %s: %s", key, value)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Save best hyperparameters to JSON
    # ------------------------------------------------------------------
    best_params_path = os.path.join(
        _project_root, "models", "rl", "best_params.json"
    )
    with open(best_params_path, "w") as f:
        json.dump(
            {
                "best_trial_number": best_trial.number,
                "best_value": best_trial.value,
                "params": best_trial.params,
            },
            f,
            indent=2,
        )
    logger.info("Best hyperparameters saved to: %s", best_params_path)

    # ------------------------------------------------------------------
    # Plot optimisation history (if visualisation dependencies exist)
    # ------------------------------------------------------------------
    try:
        import optuna.visualization as vis

        # Check that the required plotting backend is available
        fig = vis.plot_optimization_history(study)
        fig.write_html(
            os.path.join(_project_root, "models", "rl", "optuna_history.html")
        )
        logger.info(
            "Optimisation history plot saved to models/rl/optuna_history.html"
        )
    except Exception as exc:
        logger.warning(
            "Could not generate optimisation history plot: %s", exc
        )

    # Print a summary of how many trials were pruned
    n_pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
    if n_pruned > 0:
        logger.info("Pruned trials: %d / %d", n_pruned, len(study.trials))


if __name__ == "__main__":
    main()
