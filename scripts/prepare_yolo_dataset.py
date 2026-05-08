from __future__ import annotations

import argparse
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.yolo_schema import YOLO_CLASS_NAMES, write_dataset_yaml


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass(frozen=True)
class LabeledSample:
    image_path: Path
    label_path: Path


def collect_labeled_samples(raw_dir: Path, labels_dir: Path) -> list[LabeledSample]:
    samples: list[LabeledSample] = []
    for image_path in sorted(raw_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        label_path = labels_dir / f"{image_path.stem}.txt"
        if label_path.is_file():
            # Les fichiers .txt vides sont des hard negatives valides et doivent rester dans les splits.
            samples.append(LabeledSample(image_path=image_path, label_path=label_path))
    return samples


def split_samples(samples: list[LabeledSample], train_ratio: float, val_ratio: float, seed: int) -> dict[str, list[LabeledSample]]:
    shuffled = list(samples)
    random.Random(seed).shuffle(shuffled)

    sample_count = len(shuffled)
    train_count = int(sample_count * train_ratio)
    val_count = int(sample_count * val_ratio)
    if sample_count >= 3:
        train_count = max(train_count, 1)
        val_count = max(val_count, 1)
    train_count = min(train_count, sample_count)
    val_count = min(val_count, max(0, sample_count - train_count))
    test_count = max(0, sample_count - train_count - val_count)

    train_samples = shuffled[:train_count]
    val_samples = shuffled[train_count:train_count + val_count]
    test_samples = shuffled[train_count + val_count:train_count + val_count + test_count]
    return {"train": train_samples, "val": val_samples, "test": test_samples}


def reset_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    for split in ("train", "val", "test"):
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)


def copy_split(samples_by_split: dict[str, list[LabeledSample]], output_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for split, samples in samples_by_split.items():
        for sample in samples:
            shutil.copy2(sample.image_path, output_dir / "images" / split / sample.image_path.name)
            shutil.copy2(sample.label_path, output_dir / "labels" / split / sample.label_path.name)
        counts[split] = len(samples)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Prépare un dataset YOLO train/val/test à partir des captures annotées.")
    parser.add_argument("--raw-dir", default="dataset/raw_images")
    parser.add_argument("--labels-dir", default="dataset/labels")
    parser.add_argument("--output-dir", default="dataset/yolo_pokerstars")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir).resolve()
    labels_dir = Path(args.labels_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not raw_dir.is_dir():
        raise SystemExit(f"Dossier brut introuvable: {raw_dir}")
    if not labels_dir.is_dir():
        raise SystemExit(f"Dossier labels introuvable: {labels_dir}")

    samples = collect_labeled_samples(raw_dir, labels_dir)
    if not samples:
        raise SystemExit("Aucune paire image/label trouvée. Lance d'abord l'auto-annotation ou ajoute des labels.")

    splits = split_samples(samples, train_ratio=args.train_ratio, val_ratio=args.val_ratio, seed=args.seed)
    reset_output_dir(output_dir)
    counts = copy_split(splits, output_dir)
    yaml_path = write_dataset_yaml(
        output_dir / "data.yaml",
        dataset_root=output_dir,
        train_images_dir=output_dir / "images" / "train",
        val_images_dir=output_dir / "images" / "val",
        test_images_dir=(output_dir / "images" / "test") if counts.get("test", 0) else None,
        class_names=YOLO_CLASS_NAMES,
    )

    print(
        "Dataset YOLO prêt: "
        f"train={counts.get('train', 0)}, val={counts.get('val', 0)}, test={counts.get('test', 0)} | "
        f"yaml={yaml_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
