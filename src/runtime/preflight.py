from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Optional

MODEL_PATH_CANDIDATE_SUFFIXES = (".engine", ".onnx", ".pt")


class PreflightError(RuntimeError):
    pass


class Preflight:
    def __init__(self, root: Path, *, config_path: Optional[Path] = None) -> None:
        self.root = Path(root)
        self.config_path = Path(config_path or (self.root / "config.json"))

    def _load_config(self) -> dict:
        if not self.config_path.is_file():
            raise PreflightError(f"Configuration introuvable: {self.config_path}")
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            raise PreflightError(f"Configuration illisible: {self.config_path} ({exc})") from exc
        return dict(payload) if isinstance(payload, dict) else {}

    def _resolve_model_path(self, model_path: str) -> Optional[Path]:
        requested = Path(model_path)
        if not requested.is_absolute():
            requested = (self.root / requested).resolve()

        if requested.is_file():
            return requested

        stem = requested.with_suffix("")
        for suffix in MODEL_PATH_CANDIDATE_SUFFIXES:
            candidate = stem.with_suffix(suffix)
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _assert_writable_path(path: Path, label: str) -> None:
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / f".{path.stem or 'preflight'}_write_probe.tmp"
        try:
            with probe.open("w", encoding="utf-8") as handle:
                handle.write("ok")
        except Exception as exc:
            raise PreflightError(f"{label} non inscriptible: {path} ({exc})") from exc
        finally:
            try:
                probe.unlink(missing_ok=True)
            except Exception:
                pass

    def run(self) -> dict:
        config = self._load_config()

        runtime_bridge_dir = Path(os.getenv("POKER_RUNTIME_BRIDGE_DIR") or (self.root / "log" / "runtime_bridge"))
        runtime_history_path = Path(
            os.getenv("POKER_RUNTIME_HISTORY_PATH")
            or self.root / "log" / "runtime_history.jsonl"
        )
        observation_store_path = Path(
            (config.get("database", {}) or {}).get("observation_persistence_path", "log/observation_store.json")
        )
        if not observation_store_path.is_absolute():
            observation_store_path = self.root / observation_store_path

        yolo_cfg = config.get("yolo", {}) or {}
        requested_yolo_model_path = Path(yolo_cfg.get("model_path", "models/poker_yolo_v11.engine"))
        resolved_yolo_model_path = self._resolve_model_path(str(requested_yolo_model_path))

        if resolved_yolo_model_path is None:
            if requested_yolo_model_path.is_absolute():
                missing_path = requested_yolo_model_path
            else:
                missing_path = (self.root / requested_yolo_model_path).resolve()
            raise PreflightError(
                f"Modele YOLO introuvable: {missing_path}. Installe les assets avant de lancer le runtime V2."
            )

        self._assert_writable_path(runtime_bridge_dir / "runtime_state.json", "Runtime bridge")
        self._assert_writable_path(runtime_history_path, "Historique runtime")
        self._assert_writable_path(observation_store_path, "Persistance observation")

        native_solver_available = importlib.util.find_spec("postflop_solver_py") is not None
        http_solver_url = str(os.getenv("POKER_GTO_SERVER_URL") or "http://127.0.0.1:8765/v2/solve").strip()
        fallback_only = not native_solver_available and not http_solver_url

        if fallback_only:
            raise PreflightError(
                "Aucun backend solveur configure. Configure postflop_solver_py ou POKER_GTO_SERVER_URL avant le lancement."
            )

        return {
            "config_path": str(self.config_path),
            "runtime_bridge_dir": str(runtime_bridge_dir),
            "runtime_history_path": str(runtime_history_path),
            "observation_store_path": str(observation_store_path),
            "yolo_model_path": str(resolved_yolo_model_path),
            "native_solver_available": native_solver_available,
            "http_solver_url": http_solver_url,
        }
