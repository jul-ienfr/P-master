"""Seed déterministe — Phase 3.5

Une seule source de vérité pour la reproductibilité : random, NumPy,
PyTorch (+CUDA), PYTHONHASHSEED et CUBLAS_WORKSPACE_CONFIG.

À appeler en tête de src/main.py et de tout script d'entraînement/eval.
"""
from __future__ import annotations

import logging
import os
import random

logger = logging.getLogger(__name__)

DEFAULT_SEED = 42


def seed_everything(seed: int = DEFAULT_SEED, *, deterministic_torch: bool = False) -> int:
    """Initialise tous les RNG. Retourne le seed appliqué."""
    seed = int(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)

    try:
        import numpy as np

        np.random.seed(seed % (2**32))
    except ImportError:
        pass

    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        if deterministic_torch:
            # Exige CUBLAS_WORKSPACE_CONFIG pour les GEMM déterministes sur CUDA.
            os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
            torch.use_deterministic_algorithms(True, warn_only=True)
    except ImportError:
        pass

    logger.info("Seed global appliqué : %d (deterministic_torch=%s)", seed, deterministic_torch)
    return seed
