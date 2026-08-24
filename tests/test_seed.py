"""Tests Phase 3.5 — seed déterministe."""
import os
import random
import sys
import types
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.utils.seed import DEFAULT_SEED, seed_everything


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    monkeypatch.delenv("CUBLAS_WORKSPACE_CONFIG", raising=False)


def test_seed_default_is_42_and_sets_pythonhashseed():
    applied = seed_everything()
    assert applied == DEFAULT_SEED
    assert os.environ["PYTHONHASHSEED"] == str(DEFAULT_SEED)


def test_numpy_sequences_reproducible():
    seed_everything(1234)
    first = [float(np.random.random()) for _ in range(5)]

    seed_everything(1234)
    second = [float(np.random.random()) for _ in range(5)]

    assert first == second


def test_stdlib_random_reproducible():
    seed_everything(777)
    first = [random.random() for _ in range(8)]

    seed_everything(777)
    second = [random.random() for _ in range(8)]

    assert first == second


def test_torch_stub_seeded(monkeypatch):
    calls = []

    fake_torch = types.SimpleNamespace(
        manual_seed=lambda s: calls.append(("cpu", s)),
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            manual_seed_all=lambda s: calls.append(("cuda", s)),
        ),
        use_deterministic_algorithms=lambda flag, warn_only=False: calls.append(
            ("deterministic", flag)
        ),
    )
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            return fake_torch
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    seed_everything(99, deterministic_torch=True)

    assert ("cpu", 99) in calls
    assert ("cuda", 99) in calls
    assert ("deterministic", True) in calls
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"


def test_missing_optional_deps_do_not_crash(monkeypatch):
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def failing_import(name, *args, **kwargs):
        if name in {"numpy", "torch"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", failing_import)

    applied = seed_everything(7)
    assert applied == 7
