#!/usr/bin/env python3
"""
Optuna-based hyperparameter tuning for Player Clustering (K-Means).

Modes:
  - DB mode: connect to PostgreSQL, fetch real player data (default)
  - Synthetic mode: generate synthetic player data for testing (--synthetic or fallback)

Usage:
    python scripts/tune_clustering_optuna.py [--trials 30]
        [--objective silhouette|davies_bouldin|calinski_harabasz]
        [--storage sqlite:///models/clustering/optuna_study.db]
        [--synthetic] [--study-name player_clustering_tuning]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import warnings

import numpy as np

# Ajouter le repertoire racine au PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import (
        silhouette_score,
        davies_bouldin_score,
        calinski_harabasz_score,
    )
except ImportError:
    raise ImportError("scikit-learn is required. Run: pip install scikit-learn")

try:
    import optuna
    from optuna.samplers import TPESampler, GridSampler
except ImportError:
    raise ImportError("optuna is required. Run: pip install optuna")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ClusterTuning")

OBJECTIVES = {
    "silhouette": {"func": silhouette_score, "direction": "maximize"},
    "davies_bouldin": {"func": davies_bouldin_score, "direction": "minimize"},
    "calinski_harabasz": {"func": calinski_harabasz_score, "direction": "maximize"},
}

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def generate_synthetic_data(n_players: int = 300) -> np.ndarray:
    """Generate synthetic poker-player stats for testing without a DB.

    Returns
        shape (n_players, 4) with columns [VPIP, PFR, GAP, AFq].
    """
    np.random.seed(42)
    # VPIP ~ beta(2,5) * 0.5  clamped to [0, 1]
    vpip = np.random.beta(2, 5, n_players) * 0.5
    vpip = np.clip(vpip, 0.0, 1.0)

    # PFR ~ beta(1.5,6) * 0.35  clamped to [0, 1]
    pfr = np.random.beta(1.5, 6, n_players) * 0.35
    pfr = np.clip(pfr, 0.0, 1.0)

    # PFR can never exceed VPIP in practice
    pfr = np.minimum(pfr, vpip)

    gap = np.maximum(0.0, vpip - pfr)

    # AFq ~ beta(2, 3)
    afq = np.random.beta(2, 3, n_players)
    afq = np.clip(afq, 0.0, 1.0)

    return np.column_stack([vpip, pfr, gap, afq])


async def load_db_data() -> np.ndarray | None:
    """Fetch real player data from PostgreSQL.

    Returns
        shape (N, 4) with columns [VPIP, PFR, GAP, AFq] or None on failure.
    """
    from src.data.database import DatabaseManager

    db = DatabaseManager()
    await db.connect()

    if not db.pool:
        logger.warning("PostgreSQL connection not available.")
        await db.close()
        return None

    try:
        query = """
            SELECT player_name, hands_played, observed_hands,
                   vpip_count, pfr_count, raw_stats
            FROM players
            WHERE (hands_played > 50 OR observed_hands > 50)
        """
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(query)

        if len(rows) < 10:
            logger.warning(f"Not enough qualified players ({len(rows)} < 10).")
            return None

        features = []
        for row in rows:
            sample_size = max(row["observed_hands"], row["hands_played"])
            vpip = float(row["vpip_count"]) / sample_size if sample_size > 0 else 0.0
            pfr = float(row["pfr_count"]) / sample_size if sample_size > 0 else 0.0
            gap = max(0.0, vpip - pfr)

            raw_stats = row["raw_stats"] if isinstance(row["raw_stats"], dict) else {}
            agg_actions = int(raw_stats.get("aggressive_actions", 0))
            pass_actions = int(raw_stats.get("passive_actions", 0))
            total_actions = agg_actions + pass_actions
            afq = float(agg_actions) / total_actions if total_actions > 0 else 0.0

            features.append([vpip, pfr, gap, afq])

        return np.array(features, dtype=np.float64)
    except Exception as exc:
        logger.warning(f"DB query failed: {exc}")
        return None
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Feature selection
# ---------------------------------------------------------------------------


def build_feature_matrix(
    full_features: np.ndarray, use_gap: bool, use_afq: bool
) -> np.ndarray:
    """Select feature columns based on boolean flags.

    Base columns are always [VPIP=0, PFR=1].
    Optionally adds [GAP=2] and/or [AFq=3].
    """
    cols = [0, 1]
    if use_gap:
        cols.append(2)
    if use_afq:
        cols.append(3)
    return full_features[:, cols]


# ---------------------------------------------------------------------------
# Optuna objective
# ---------------------------------------------------------------------------


def objective(
    trial: optuna.Trial,
    X_full: np.ndarray,
    metric_func: callable,
    metric_direction: str,
) -> float:
    """Optuna objective: suggest params, run K-Means, return metric score."""
    n_clusters = trial.suggest_int("n_clusters", 2, 12)
    n_init = trial.suggest_categorical("n_init", [5, 10, 15, 20])
    algorithm = trial.suggest_categorical("algorithm", ["lloyd", "elkan"])
    use_gap = trial.suggest_categorical("use_gap", [True, False])
    use_afq = trial.suggest_categorical("use_afq", [True, False])

    X = build_feature_matrix(X_full, use_gap, use_afq)
    n_samples = X.shape[0]

    # Sanity checks
    if n_clusters > n_samples or n_clusters < 2:
        return _penalty(metric_direction)

    # Normalise
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Fit K-Means
    kmeans = KMeans(
        n_clusters=n_clusters,
        n_init=n_init,
        algorithm=algorithm,
        random_state=42,
    )
    labels = kmeans.fit_predict(X_scaled)

    # Ensure at least 2 non-empty clusters
    if len(set(labels)) < 2:
        return _penalty(metric_direction)

    return float(metric_func(X_scaled, labels))


def _penalty(direction: str) -> float:
    """Return a penalised value that will be rejected by the sampler."""
    return -1e9 if direction == "maximize" else 1e9


# ---------------------------------------------------------------------------
# Final clustering
# ---------------------------------------------------------------------------


def run_final_clustering(X_full: np.ndarray, best_params: dict) -> None:
    """Re-fit with best params and print cluster distribution & centroids."""
    X = build_feature_matrix(X_full, best_params["use_gap"], best_params["use_afq"])

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(
        n_clusters=int(best_params["n_clusters"]),
        n_init=int(best_params["n_init"]),
        algorithm=best_params["algorithm"],
        random_state=42,
    )
    labels = kmeans.fit_predict(X_scaled)

    # Distribution
    unique, counts = np.unique(labels, return_counts=True)
    distribution = {int(u): int(c) for u, c in zip(unique, counts)}

    # Centroids back to original scale
    centroids_orig = scaler.inverse_transform(kmeans.cluster_centers_)

    # Feature names for display
    fnames = ["VPIP", "PFR"]
    if best_params["use_gap"]:
        fnames.append("GAP")
    if best_params["use_afq"]:
        fnames.append("AFq")

    print()
    print("=" * 60)
    print("FINAL CLUSTERING RESULTS")
    print("=" * 60)
    print(
        f"Parameters: n_clusters={best_params['n_clusters']}, "
        f"n_init={best_params['n_init']}, "
        f"algorithm={best_params['algorithm']}"
    )
    print(f"Features used: {', '.join(fnames)}")
    print(f"\nCluster distribution: {distribution}")
    print(f"\nCentroids (original scale):")
    for i, centroid in enumerate(centroids_orig):
        vals = ", ".join(f"{v:.4f}" for v in centroid)
        print(f"  Cluster {i}: [{vals}]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tune K-Means clustering for poker players using Optuna"
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=30,
        help="Number of Optuna trials (default: 30)",
    )
    parser.add_argument(
        "--objective",
        type=str,
        default="silhouette",
        choices=list(OBJECTIVES.keys()),
        help="Objective metric to optimise (default: silhouette)",
    )
    parser.add_argument(
        "--storage",
        type=str,
        default="sqlite:///models/clustering/optuna_study.db",
        help="Optuna storage URL (default: sqlite:///models/clustering/optuna_study.db)",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Force synthetic data mode (skip DB connection attempt)",
    )
    parser.add_argument(
        "--study-name",
        type=str,
        default="player_clustering_tuning",
        help="Optuna study name (default: player_clustering_tuning)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()

    from src.utils.seed import seed_everything

    seed_everything(args.seed)

    # -----------------------------------------------------------------------
    # 1. Data loading
    # -----------------------------------------------------------------------
    if args.synthetic:
        logger.info("Using synthetic data (--synthetic flag set).")
        X_full = generate_synthetic_data()
    else:
        logger.info("Attempting to load data from PostgreSQL ...")
        X_full = asyncio.run(load_db_data())
        if X_full is None:
            logger.warning(
                "DB load failed or no data. Falling back to synthetic data."
            )
            X_full = generate_synthetic_data()

    logger.info(
        f"Loaded data: {X_full.shape[0]} samples, {X_full.shape[1]} features"
    )

    # -----------------------------------------------------------------------
    # 2. Objective configuration
    # -----------------------------------------------------------------------
    obj_config = OBJECTIVES[args.objective]
    metric_func = obj_config["func"]
    direction = obj_config["direction"]

    logger.info(f"Objective: {args.objective} (direction: {direction})")
    logger.info(f"Trials: {args.trials}")

    # -----------------------------------------------------------------------
    # 3. Optuna study
    # -----------------------------------------------------------------------
    # Resolve relative SQLite paths against the project root
    storage_url = args.storage
    if storage_url.startswith("sqlite:///"):
        rel = storage_url[len("sqlite:///"):]
        if not os.path.isabs(rel):
            proj_root = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            abs_path = os.path.join(proj_root, rel)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            storage_url = f"sqlite:///{abs_path}"

    sampler = TPESampler(seed=args.seed)
    study = optuna.create_study(
        study_name=args.study_name,
        storage=storage_url,
        load_if_exists=True,
        direction=direction,
        sampler=sampler,
    )
    # No pruning -- unsupervised and fast.

    logger.info("Starting optimisation ...")
    study.optimize(
        lambda t: objective(t, X_full, metric_func, direction),
        n_trials=args.trials,
        n_jobs=1,
    )

    # -----------------------------------------------------------------------
    # 4. Report
    # -----------------------------------------------------------------------
    best_trial = study.best_trial
    print()
    print("=" * 60)
    print("OPTUNA TUNING RESULTS")
    print("=" * 60)
    print(f"Number of finished trials: {len(study.trials)}")
    print(f"Best trial: #{best_trial.number}")
    print(f"Best {args.objective} score: {best_trial.value:.6f}")
    print("Best hyperparameters:")
    for key, value in best_trial.params.items():
        print(f"  {key}: {value}")

    # -----------------------------------------------------------------------
    # 5. Save best parameters
    # -----------------------------------------------------------------------
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(proj_root, "models", "clustering")
    os.makedirs(output_dir, exist_ok=True)

    best_params_path = os.path.join(output_dir, "best_cluster_params.json")
    with open(best_params_path, "w") as f:
        json.dump(best_trial.params, f, indent=2)
    logger.info(f"Best params saved to {best_params_path}")

    # -----------------------------------------------------------------------
    # 6. Final clustering with best params
    # -----------------------------------------------------------------------
    run_final_clustering(X_full, best_trial.params)


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
    main()
