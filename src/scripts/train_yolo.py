import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from ultralytics import YOLO
except ImportError:
    print("❌ Erreur: 'ultralytics' n'est pas installe. Lancez 'pip install ultralytics'.")
    sys.exit(1)

from src.vision.yolo_schema import YOLO_CLASS_NAMES


def _parse_bool_flag(value: object) -> bool:
    normalized = str(value or "true").strip().lower()
    return normalized not in {"0", "false", "no", "off"}


def _parse_simple_dataset_yaml(dataset_yaml: Path) -> dict:
    parsed: dict[str, str] = {}
    with open(dataset_yaml, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line == "names:":
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in {"path", "train", "val", "test"} and value:
                parsed[key] = value
    return parsed


def _resolve_dataset_entry(dataset_root: Path, value: str, default: str) -> Path:
    target = Path(value or default)
    if target.is_absolute():
        return target
    return (dataset_root / target).resolve()


def _count_labeled_samples(images_dir: Path, labels_dir: Path) -> tuple[int, int]:
    if not images_dir.exists():
        return 0, 0
    image_count = 0
    labeled_count = 0
    for image_path in images_dir.iterdir():
        if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        image_count += 1
        if (labels_dir / f"{image_path.stem}.txt").exists():
            labeled_count += 1
    return image_count, labeled_count


def _stage_labeled_observation_dataset(images_dir: Path, labels_dir: Path) -> tuple[Path, int]:
    staged_root = ROOT / "dataset" / "_runtime_augmented" / "observation_runtime"
    staged_images_dir = staged_root / "images"
    staged_labels_dir = staged_root / "labels"
    staged_images_dir.mkdir(parents=True, exist_ok=True)
    staged_labels_dir.mkdir(parents=True, exist_ok=True)

    for directory in (staged_images_dir, staged_labels_dir):
        for entry in directory.iterdir():
            if entry.is_file():
                entry.unlink()

    copied_count = 0
    for image_path in images_dir.iterdir():
        if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        label_path = labels_dir / f"{image_path.stem}.txt"
        if not label_path.exists():
            continue
        shutil.copy2(image_path, staged_images_dir / image_path.name)
        shutil.copy2(label_path, staged_labels_dir / label_path.name)
        copied_count += 1

    return staged_root, copied_count


def _write_augmented_dataset_yaml(output_path: Path, train_dirs: list[Path], val_dirs: list[Path]) -> Path:
    lines = [f"path: {ROOT.resolve().as_posix()}", "train:"]
    lines.extend(f"  - {directory.resolve().as_posix()}" for directory in train_dirs)
    lines.append("val:")
    lines.extend(f"  - {directory.resolve().as_posix()}" for directory in val_dirs)
    lines.append(f"nc: {len(YOLO_CLASS_NAMES)}")
    lines.append("names:")
    lines.extend(f"  {index}: {name}" for index, name in enumerate(YOLO_CLASS_NAMES))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _build_training_dataset_yaml(base_dataset_yaml: Path, observation_dataset_dir: Path, include_observation: bool) -> Path:
    if not include_observation:
        return base_dataset_yaml

    dataset_config = _parse_simple_dataset_yaml(base_dataset_yaml)
    dataset_root_value = dataset_config.get("path", ".")
    dataset_root = Path(dataset_root_value)
    if not dataset_root.is_absolute():
        dataset_root = (base_dataset_yaml.parent / dataset_root).resolve()

    base_train_dir = _resolve_dataset_entry(dataset_root, dataset_config.get("train", "images"), "images")
    base_val_dir = _resolve_dataset_entry(dataset_root, dataset_config.get("val", dataset_config.get("train", "images")), "images")
    train_dirs = [base_train_dir]
    val_dirs = [base_val_dir]

    observation_images_dir = observation_dataset_dir / "images"
    observation_labels_dir = observation_dataset_dir / "labels"
    observation_images, observation_labeled = _count_labeled_samples(observation_images_dir, observation_labels_dir)
    observation_unlabeled = max(0, observation_images - observation_labeled)

    if observation_images and not observation_labeled:
        print(
            f"ℹ️ {observation_images} captures runtime observation trouvées, mais aucune n'est encore annotée."
        )
        print(
            "   Lancez: python src/vision/auto_annotator.py --raw-dir dataset/runtime_observation/images --labels-dir dataset/runtime_observation/labels"
        )

    if observation_labeled:
        staged_observation_root, staged_labeled = _stage_labeled_observation_dataset(
            observation_images_dir,
            observation_labels_dir,
        )
        train_dirs.append((staged_observation_root / "images").resolve())
        augmented_yaml = ROOT / "dataset" / "_runtime_augmented" / "dataset.yaml"
        _write_augmented_dataset_yaml(augmented_yaml, train_dirs, val_dirs)
        print(
            f"✅ Dataset d'entrainement enrichi avec {staged_labeled} samples runtime observation labels."
        )
        if observation_unlabeled:
            print(
                f"ℹ️ {observation_unlabeled} captures runtime observation non annotees ont ete ignorees pour cet entrainement."
            )
        return augmented_yaml

    return base_dataset_yaml

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="dataset/PokerStars_NLHE_6Max/dataset.yaml", help="Chemin vers le fichier dataset.yaml")
    parser.add_argument("--epochs", type=int, default=50, help="Nombre d'epochs")
    parser.add_argument(
        "--include-observation",
        type=str,
        default="true",
        help="Inclure automatiquement dataset/runtime_observation s'il contient des labels",
    )
    parser.add_argument(
        "--observation-dataset-dir",
        type=str,
        default="dataset/runtime_observation",
        help="Dossier contenant images/labels des captures runtime",
    )
    args = parser.parse_args()

    print("=== Fine-tuning YOLOv11 pour Poker Bot ===")
    
    # 1. Verification du Dataset
    dataset_yaml = ROOT / args.data
    if not dataset_yaml.exists():
        print(f"❌ Fichier dataset introuvable : {dataset_yaml}")
        print("Assurez-vous d'avoir cree le dataset via auto_annotate_templates.py")
        sys.exit(1)

    observation_dataset_dir = (ROOT / args.observation_dataset_dir).resolve()
    dataset_yaml = _build_training_dataset_yaml(
        dataset_yaml,
        observation_dataset_dir=observation_dataset_dir,
        include_observation=_parse_bool_flag(args.include_observation),
    )
    print(f"📚 Dataset utilise pour l'entrainement : {dataset_yaml}")
        
    # 2. Chargement du Modele Existant
    # On fine-tune le modele actuel s'il existe, sinon on prend un modele pre-entraine global.
    existing_model_path = ROOT / "models" / "poker_yolo_v11.pt"  
    # Ultralytics a besoin du .pt pour entrainer, pas du .onnx
    
    if existing_model_path.exists():
        print(f"✅ Chargement du modele existant : {existing_model_path}")
        model = YOLO(str(existing_model_path))
    else:
        print("⚠️ Modele global introuvable. Telechargement d'un modele yolov11n de base.")
        model = YOLO("yolo11n.pt")  

    print("\n🚀 Demarrage de l'entrainement...")
    
    # 3. Lancement de l'entrainement
    results = model.train(
        data=str(dataset_yaml),
        epochs=args.epochs,
        imgsz=640,
        batch=16,
        name="poker_yolo_finetune",
        device="0" # Utilise le GPU
    )
    
    # 4. Exportation ONNX
    print("\n📦 Exportation du nouveau modele en ONNX pour des performances max...")
    success = model.export(format="onnx", int8=False, dynamic=False)
    
    print("\n✅ Entrainement et export terminés !")
    print("-> Pour l'utiliser, deplacez le nouveau fichier .onnx dans le dossier 'models/'")
    print("-> et mettez a jour 'config.json' : 'yolo.model_path'")

if __name__ == "__main__":
    main()
