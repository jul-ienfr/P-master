from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.preflight import Preflight, PreflightError


def test_preflight_accepts_existing_runtime_paths(tmp_path, monkeypatch):
    model_path = tmp_path / "models" / "poker_yolo_v11.engine"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("stub", encoding="utf-8")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database": {
                    "observation_persistence_path": "log/observation_store.json",
                },
                "yolo": {
                    "model_path": str(model_path),
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.runtime.preflight.importlib.util.find_spec", lambda name: object() if name == "postflop_solver_py" else None)

    result = Preflight(tmp_path, config_path=config_path).run()

    assert result["native_solver_available"] is True
    assert result["yolo_model_path"] == str(model_path)


def test_preflight_resolves_onnx_when_engine_path_is_requested(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = models_dir / "poker_yolo_v11.onnx"
    onnx_path.write_bytes(b"dummy")

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database": {
                    "observation_persistence_path": "log/observation_store.json",
                },
                "yolo": {
                    "model_path": "models/poker_yolo_v11.engine",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.runtime.preflight.importlib.util.find_spec", lambda name: object() if name == "postflop_solver_py" else None)

    result = Preflight(tmp_path, config_path=config_path).run()

    assert result["yolo_model_path"] == str(onnx_path)


def test_preflight_fails_when_yolo_model_is_missing(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "database": {
                    "observation_persistence_path": "log/observation_store.json",
                },
                "yolo": {
                    "model_path": "models/missing.engine",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        Preflight(tmp_path, config_path=config_path).run()
    except PreflightError as exc:
        assert "Modele YOLO introuvable" in str(exc)
    else:
        raise AssertionError("Preflight should fail when the YOLO model is missing")
