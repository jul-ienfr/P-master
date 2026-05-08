from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultralytics import YOLO

from src.vision.detector import resolve_model_path
from src.vision.yolo_schema import YoloDatasetSchemaError, validate_dataset_yaml_schema


DEFAULT_BASE_MODEL = "yolo11n.pt"


def choose_base_model(requested: str) -> str:
    resolved = resolve_model_path(requested)
    if resolved is not None:
        return str(resolved)
    return requested


def cuda_device_summary() -> list[str]:
    try:
        import torch
    except Exception:
        return []
    if not torch.cuda.is_available():
        return []
    return [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())]


def resolve_training_device(requested: str) -> str:
    value = str(requested or "auto").strip().lower()
    if value == "auto":
        return "0" if cuda_device_summary() else "cpu"
    if value in {"cpu", "mps"}:
        return value
    if value in {"gpu", "cuda"}:
        devices = cuda_device_summary()
        if not devices:
            raise SystemExit("GPU CUDA demandé mais indisponible pour PyTorch. Utilise --device cpu ou vérifie l'installation CUDA.")
        return "0"
    if value.startswith("cuda:"):
        device_index = value.split(":", 1)[1]
        if not device_index.isdigit():
            raise SystemExit(f"Device CUDA invalide: {requested}")
        devices = cuda_device_summary()
        if int(device_index) >= len(devices):
            raise SystemExit(f"Device CUDA {device_index} indisponible; {len(devices)} GPU détecté(s).")
        return device_index
    if value.isdigit():
        devices = cuda_device_summary()
        if int(value) >= len(devices):
            raise SystemExit(f"Device GPU {value} indisponible; {len(devices)} GPU détecté(s).")
        return value
    return requested


def main() -> int:
    parser = argparse.ArgumentParser(description="Entraîne et exporte un détecteur YOLO PokerMaster.")
    parser.add_argument("--data", default="dataset/runtime_observation/dataset.yaml")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="auto", help="auto, cpu, gpu/cuda, cuda:0, ou index GPU comme 0.")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--project", default="models/yolo_runs")
    parser.add_argument("--name", default="pokerstars_v1")
    parser.add_argument("--export-onnx", action="store_true")
    parser.add_argument("--export-engine", action="store_true")
    parser.add_argument("--warmup-epochs", type=float, default=None)
    parser.add_argument("--skip-canonical-copy", action="store_true")
    args = parser.parse_args()

    devices = cuda_device_summary()
    if args.list_devices:
        if devices:
            for index, name in enumerate(devices):
                print(f"gpu:{index} {name}")
        else:
            print("Aucun GPU CUDA disponible pour PyTorch; CPU disponible.")
        return 0
    training_device = resolve_training_device(args.device)
    print(f"Device entraînement sélectionné: {training_device}")

    data_path = Path(args.data).resolve()
    if not data_path.is_file():
        raise SystemExit(f"Dataset YAML introuvable: {data_path}")
    try:
        validate_dataset_yaml_schema(data_path)
    except YoloDatasetSchemaError as exc:
        raise SystemExit(str(exc)) from exc

    train_kwargs = {
        "data": str(data_path),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": training_device,
        "project": args.project,
        "name": args.name,
        "exist_ok": True,
        "pretrained": True,
    }
    if args.warmup_epochs is not None:
        train_kwargs["warmup_epochs"] = args.warmup_epochs

    model = YOLO(choose_base_model(args.base_model))
    train_result = model.train(**train_kwargs)

    best_weights = Path(getattr(train_result, "save_dir", Path(args.project) / args.name)) / "weights" / "best.pt"
    if not best_weights.is_file():
        raise SystemExit(f"Poids best.pt introuvables après entraînement: {best_weights}")

    export_source = best_weights
    if args.skip_canonical_copy:
        print(f"Poids entraînés conservés dans le run: {best_weights}")
    else:
        models_dir = Path("models").resolve()
        models_dir.mkdir(parents=True, exist_ok=True)
        canonical_pt = models_dir / "poker_yolo_v11.pt"
        shutil.copy2(best_weights, canonical_pt)
        export_source = canonical_pt
        print(f"Poids entraînés copiés vers {canonical_pt}")

    if args.export_onnx:
        exported = YOLO(str(export_source)).export(format="onnx", imgsz=args.imgsz)
        exported_path = Path(exported).resolve()
        if args.skip_canonical_copy:
            print(f"Modèle ONNX prêt dans le run: {exported_path}")
        else:
            canonical_onnx = Path("models").resolve() / "poker_yolo_v11.onnx"
            if exported_path != canonical_onnx:
                shutil.copy2(exported_path, canonical_onnx)
            print(f"Modèle ONNX prêt: {canonical_onnx}")

    if args.export_engine:
        exported = YOLO(str(export_source)).export(format="engine", imgsz=args.imgsz)
        exported_path = Path(exported).resolve()
        if args.skip_canonical_copy:
            print(f"Modèle TensorRT prêt dans le run: {exported_path}")
        else:
            canonical_engine = Path("models").resolve() / "poker_yolo_v11.engine"
            if exported_path != canonical_engine:
                shutil.copy2(exported_path, canonical_engine)
            print(f"Modèle TensorRT prêt: {canonical_engine}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
