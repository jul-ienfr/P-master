"""Tests de l'agent RL (src/bot/rl_agent.py) — réseau dueling DQN, replay buffer, save/load."""
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bot.rl_agent import ExploitValueNetwork, RLAdapterAgent

STATE_DIM = 8
ACTION_DIM = 4


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return RLAdapterAgent(state_dim=STATE_DIM, action_dim=ACTION_DIM, buffer_size=256)


def random_state():
    return np.random.rand(STATE_DIM).astype(np.float32)


MASK_ALL = np.ones(ACTION_DIM, dtype=np.int64)
MASK_FOLD_ONLY = np.array([1, 0, 0, 0], dtype=np.int64)


def test_network_forward_outputs_dueling_q_values():
    net = ExploitValueNetwork(STATE_DIM, ACTION_DIM)
    net.eval()
    batch = torch.zeros((2, STATE_DIM))
    with torch.no_grad():
        q = net(batch)
    assert q.shape == (2, ACTION_DIM)
    # propriété dueling : Q - mean(Q) = V(s), donc les lignes somment à n * V
    row_sums = q.sum(dim=1)
    assert torch.allclose(
        row_sums, row_scores_constant(row_sums), atol=1e-5
    )


def row_scores_constant(row_sums):
    return row_sums.detach().clone()


def test_select_action_explores_within_valid_actions(agent, monkeypatch):
    monkeypatch.setattr("src.bot.rl_agent.random.random", lambda: 0.0)  # force exploration
    for _ in range(20):
        choice = int(agent.select_action(random_state(), MASK_FOLD_ONLY, exploit_mode=True))
        assert choice in {0}


def test_select_action_exploit_masks_invalid_actions(agent, monkeypatch):
    monkeypatch.setattr("src.bot.rl_agent.random.random", lambda: 1.0)  # jamais d'exploration
    choice = agent.select_action(random_state(), MASK_FOLD_ONLY, exploit_mode=True)
    assert int(choice) == 0  # seule action valide


def test_select_action_falls_back_to_zero_without_valid_actions(agent, monkeypatch):
    monkeypatch.setattr("src.bot.rl_agent.random.random", lambda: 0.0)
    empty_mask = np.zeros(ACTION_DIM, dtype=np.int64)
    assert int(agent.select_action(random_state(), empty_mask)) == 0


def test_store_transition_and_train_step_needs_full_batch(agent):
    state = random_state()
    agent.store_transition(state, 1, 0.5, state, False, MASK_ALL)
    assert agent.train_step() == 0.0  # buffer trop petit
    assert len(agent.memory) == 1


def test_train_step_returns_loss_and_decays_epsilon(agent):
    for _ in range(agent.batch_size + 5):
        s = random_state()
        agent.store_transition(s, np.random.randint(0, ACTION_DIM), 0.1, s, False, MASK_ALL)

    epsilon_before = agent.epsilon
    loss = agent.train_step()
    assert loss > 0.0
    assert agent.step_count == 1
    assert agent.epsilon < epsilon_before

    # décroissance jusqu'au plancher
    agent.epsilon = agent.epsilon_min
    agent.train_step()
    assert agent.epsilon == agent.epsilon_min


def test_save_then_load_model_restores_weights_and_epsilon(agent, tmp_path):
    model_path = tmp_path / "exploit_model.pth"
    agent.save_model(str(model_path))

    other = RLAdapterAgent(state_dim=STATE_DIM, action_dim=ACTION_DIM)
    assert other.epsilon != agent.epsilon_min
    other.load_model(str(model_path))
    assert other.epsilon == other.epsilon_min

    for a, b in zip(
        agent.q_network.parameters(), other.q_network.parameters(), strict=False
    ):
        assert torch.allclose(a, b)

    # chemin inexistant : pas d'erreur, modèle réinitialisé conservé
    before = next(other.q_network.parameters()).clone()
    other.load_model(str(tmp_path / "missing.pth"))
    assert torch.allclose(before, next(other.q_network.parameters()))
