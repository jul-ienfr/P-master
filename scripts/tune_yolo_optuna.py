from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import optuna
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler
from ultralytics import YOLO

from src.vision.detector import resolve_model_path

DEFAULT_BASE_MODEL = "models/yolo11n.pt"
DEFAULT_DATA = "dataset/PokerStars_NLHE_6Max/dataset.yaml"
DEFAULT_STORAGE = "sqlite:///models/yolo_runs/optuna_study.db"
BEST_PARAMS_PATH = Path("models/yolo_runs/best_yolo_params.json")
LOG_DIR = Path("logs")
MODELS_YOLO_DIR = Path("models/yolo_runs")

# Disable wandb / comet logging from ultralytics settings
try:
    from ultralytics import settings as ultralytics_settings
    ultralytics_settings.update({"wandb": False, "comet": False, "mlflow": False})
except Exception:
    pass

logger = logging.getLogger("tune_yolo_optuna")


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_YOLO_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "tune_yolo_optuna.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def choose_base_model(requested: str) -> str:
    resolved = resolve_model_path(requested)
    if resolved is not None:
        return str(resolved)
    return requested


def suggest_hparams(trial: optuna.Trial) -> dict:
    """Define the Optuna hyperparameter search space."""
    return {
        "lr0": trial.suggest_float("lr0", 1e-4, 1e-2, log=True),
        "lrf": trial.suggest_float("lrf", 0.001, 0.1),
        "momentum": trial.suggest_float("momentum", 0.8, 0.98),
        "weight_decay": trial.suggest_float("weight_decay", 1e-5, 1e-3, log=True),
        "warmup_epochs": trial.suggest_int("warmup_epochs", 0, 10),
        "batch": trial.suggest_categorical("batch", [4, 8, 16, 32]),
        "imgsz": trial.suggest_categorical("imgsz", [640, 960, 1280]),
        "optimizer": trial.suggest_categorical("optimizer", ["SGD", "Adam", "AdamW"]),
        "cos_lr": trial.suggest_categorical("cos_lr", [True, False]),
        "close_mosaic": trial.suggest_int("close_mosaic", 0, 15),
    }


def _make_callback(trial: optuna.Trial):
    """Return a YOLO on_fit_epoch_end callback that reports metrics to Optuna."""

    def optuna_callback(trainer):
        epoch = trainer.epoch
        metrics = trainer.metrics
        if metrics and "metrics/mAP50(B)" in metrics:
            map50 = metrics["metrics/mAP50(B)"]
            trial.report(map50, epoch)
            if trial.should_prune():
                raise optuna.TrialPruned()

    return optuna_callback


def objective(trial: optuna.Trial, base_model: str, data_path: str, epochs: int) -> float:
    """Train a YOLO model with hyperparameters suggested by Optuna and return mAP@0.5."""
    hparams = suggest_hparams(trial)

    trial_id = trial.number
    run_name = f"trial_{trial_id:03d}"

    logger.info("Trial %03d starting with hparams: %s", trial_id, json.dumps(hparams, default=str))

    model = YOLO(choose_base_model(base_model))

    train_kwargs = {
        "data": data_path,
        "epochs": epochs,
        "device": "0",
        "project": str(MODELS_YOLO_DIR),
        "name": run_name,
        "exist_ok": True,
        "pretrained": True,
        "workers": 2,
        "verbose": False,
        **hparams,
    }

    # Attach pruning callback
    callback = _make_callback(trial)
    model.add_callback("on_fit_epoch_end", callback)

    t0 = time.time()
    try:
        train_result = model.train(**train_kwargs)
    except optuna.TrialPruned:
        logger.info("Trial %03d was pruned at epoch %d", trial_id, trial.last_reported_step or 0)
        raise
    duration = time.time() - t0

    # Extract metrics from the results object
    metrics = getattr(train_result, "metrics", None) or {}
    map50 = metrics.get("metrics/mAP50(B)", 0.0)
    map5095 = metrics.get("metrics/mAP50-95(B)", 0.0)
    precision = metrics.get("metrics/precision(B)", 0.0)
    recall = metrics.get("metrics/recall(B)", 0.0)

    # Log auxiliary metrics to Optuna
    trial.set_user_attr("mAP50-95", map5095)
    trial.set_user_attr("precision", precision)
    trial.set_user_attr("recall", recall)
    trial.set_user_attr("duration_sec", round(duration, 1))

    logger.info(
        "Trial %03d finished — mAP@0.5: %.4f, mAP@0.5:0.95: %.4f, precision: %.4f, recall: %.4f, "
        "duration: %.1fs",
        trial_id, map50, map5095, precision, recall, duration,
    )

    # Remove callback to avoid cross-trial contamination
    try:
        model._callbacks.pop("on_fit_epoch_end", None)
    except Exception:
        pass

    return map50


def create_study(storage: str, study_name: str) -> optuna.Study:
    """Create or load an Optuna study."""
    sampler = TPESampler(n_startup_trials=5)
    pruner = MedianPruner(n_startup_trials=5, n_warmup_steps=3)
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
        load_if_exists=True,
    )
    return study


def save_best_params(study: optuna.Study) -> None:
    """Save the best trial parameters to a JSON file."""
    best_trial = study.best_trial
    params = {
        "best_trial_number": best_trial.number,
        "best_value": best_trial.value,
        "params": best_trial.params,
        "user_attrs": best_trial.user_attrs,
    }
    BEST_PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BEST_PARAMS_PATH.write_text(json.dumps(params, indent=2, default=str), encoding="utf-8")
    logger.info("Best trial params saved to %s", BEST_PARAMS_PATH)
    logger.info("Best trial #%d — mAP@0.5: %.4f", best_trial.number, best_trial.value)
    logger.info("Best hyperparameters: %s", json.dumps(best_trial.params, default=str))


def train_final_model(best_params: dict, base_model: str, data_path: str, device: str) -> None:
    """Train a final model with best found hyperparameters for the full epoch budget."""
    logger.info("Training final model with best hyperparameters for %d epochs...", 40)

    model = YOLO(choose_base_model(base_model))
    train_kwargs = {
        "data": data_path,
        "epochs": 40,
        "device": device,
        "project": str(MODELS_YOLO_DIR),
        "name": "best_tuned",
        "exist_ok": True,
        "pretrained": True,
        "workers": 2,
        **best_params,
    }
    model.train(**train_kwargs)
    logger.info("Final model training complete — saved to %s/best_tuned", MODELS_YOLO_DIR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optuna hyperparameter tuning for YOLO poker table detector."
    )
    parser.add_argument("--trials", type=int, default=20, help="Number of Optuna trials (default: 20)")
    parser.add_argument("--epochs", type=int, default=20, help="Epochs per trial (default: 20)")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL, help="Base YOLO model (default: models/yolo11n.pt)")
    parser.add_argument(
        "--data", default=DEFAULT_DATA, help="Dataset YAML path (default: dataset/PokerStars_NLHE_6Max/dataset.yaml)"
    )
    parser.add_argument("--storage", default=DEFAULT_STORAGE, help="Optuna storage URL (default: sqlite:///models/yolo_runs/optuna_study.db)")
    parser.add_argument("--device", default="0", help="Device for training (default: 0)")
    parser.add_argument(
        "--no-final-train", action="store_true",
        help="Skip final model training after tuning (default: False)"
    )
    parser.add_argument(
        "--study-name", default="yolo_detector_tuning",
        help="Optuna study name (default: yolo_detector_tuning)"
    )
    return parser.parse_args(argv)


def main() -> int:
    _setup_logging()
    args = parse_args()
    from src.utils.seed import seed_everything

    seed_everything(args.seed if hasattr(args, "seed") else 42)

    data_path = Path(args.data).resolve()
    if not data_path.is_file():
        logger.error("Dataset YAML not found: %s", data_path)
        print(f"Dataset YAML introuvable: {data_path}", file=sys.stderr)
        return 1

    logger.info("Starting Optuna tuning for YOLO detector")
    logger.info("Trials: %d | Epochs per trial: %d | Base model: %s", args.trials, args.epochs, args.base_model)
    logger.info("Data: %s | Device: %s", data_path, args.device)
    logger.info("Storage: %s", args.storage)

    study = create_study(storage=args.storage, study_name=args.study_name)

    study.optimize(
        lambda trial: objective(trial, args.base_model, str(data_path), args.epochs),
        n_trials=args.trials,
        show_progress_bar=True,
    )

    logger.info("Optimization finished. Best trial: #%d — mAP@0.5: %.4f", study.best_trial.number, study.best_trial.value)
    save_best_params(study)

    if not args.no_final_train:
        train_final_model(
            best_params=study.best_trial.params,
            base_model=args.base_model,
            data_path=str(data_path),
            device=args.device,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
