from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.yolo_schema import YOLO_CLASS_NAMES


GENERIC_CARD_LABELS = {"board_card", "hero_card"}


def _empty_report(labels_dir: Path) -> dict[str, Any]:
    return {
        "labels_dir": labels_dir.as_posix(),
        "files": 0,
        "metadata_files": 0,
        "empty_files": 0,
        "nonempty_files": 0,
        "total_labels": 0,
        "generic_card_labels": 0,
        "generic_card_files": [],
        "invalid_labels": [],
        "class_counts": {},
    }


def parse_yolo_label_line(path: Path, line: str, line_number: int) -> tuple[str | None, str | None]:
    parts = line.split()
    if len(parts) != 5:
        return None, f"{path}:{line_number}: ligne YOLO invalide, attendu 5 champs"
    try:
        class_id = int(parts[0])
    except ValueError:
        return None, f"{path}:{line_number}: class id non entier {parts[0]!r}"
    if class_id < 0 or class_id >= len(YOLO_CLASS_NAMES):
        return None, f"{path}:{line_number}: class id hors schéma {class_id}"
    try:
        coords = [float(value) for value in parts[1:]]
    except ValueError:
        return None, f"{path}:{line_number}: coordonnées non numériques"
    if any(value < 0.0 or value > 1.0 for value in coords):
        return None, f"{path}:{line_number}: coordonnées hors intervalle [0, 1]"
    return YOLO_CLASS_NAMES[class_id], None


def inspect_labels(labels_dir: Path) -> dict[str, Any]:
    if not labels_dir.is_dir():
        raise SystemExit(f"Dossier labels introuvable: {labels_dir}")

    report = _empty_report(labels_dir)
    class_counts: Counter[str] = Counter()
    generic_card_files: defaultdict[str, int] = defaultdict(int)
    invalid_labels: list[str] = []

    label_paths = sorted(labels_dir.glob("*.txt"))
    report["files"] = len(label_paths)
    report["metadata_files"] = len(list(labels_dir.glob("*.json")))

    for label_path in label_paths:
        lines = [line.strip() for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            report["empty_files"] += 1
            continue
        report["nonempty_files"] += 1
        for line_number, line in enumerate(lines, start=1):
            class_name, error = parse_yolo_label_line(label_path, line, line_number)
            if error:
                invalid_labels.append(error)
                continue
            assert class_name is not None
            class_counts[class_name] += 1
            if class_name in GENERIC_CARD_LABELS:
                generic_card_files[label_path.name] += 1

    report["total_labels"] = sum(class_counts.values())
    report["generic_card_labels"] = sum(generic_card_files.values())
    report["generic_card_files"] = [
        {"file": file_name, "count": count}
        for file_name, count in sorted(generic_card_files.items())
    ]
    report["invalid_labels"] = invalid_labels
    report["class_counts"] = dict(class_counts.most_common())
    return report


def _filtered_label_lines(label_path: Path, *, drop_generic_cards: bool) -> tuple[list[str], int, int]:
    kept: list[str] = []
    dropped = 0
    original = 0
    for line_number, raw_line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        original += 1
        class_name, error = parse_yolo_label_line(label_path, line, line_number)
        if error:
            raise SystemExit(error)
        if drop_generic_cards and class_name in GENERIC_CARD_LABELS:
            dropped += 1
            continue
        kept.append(line)
    return kept, dropped, original


def write_validated_labels(
    labels_dir: Path,
    output_dir: Path,
    *,
    drop_generic_cards: bool,
    overwrite: bool,
    exclude_empty_after_drop: bool = False,
) -> dict[str, Any]:
    if output_dir.exists():
        if not overwrite:
            raise SystemExit(f"Dossier de sortie déjà existant: {output_dir}. Utilise --overwrite pour remplacer.")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    empty = 0
    dropped_generic = 0
    excluded_empty_after_drop = 0
    for label_path in sorted(labels_dir.glob("*.txt")):
        lines, dropped, original = _filtered_label_lines(label_path, drop_generic_cards=drop_generic_cards)
        dropped_generic += dropped
        metadata_path = label_path.with_suffix(".json")
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        else:
            metadata = {}
        if exclude_empty_after_drop and original > 0 and dropped == original and not lines:
            metadata.update(
                {
                    "status": "excluded_generic_only",
                    "source_label": label_path.name,
                    "dropped_generic_card_labels": dropped,
                    "requires_card_identity_review": True,
                    "empty": False,
                    "hard_negative": False,
                    "excluded": True,
                    "exclusion_reason": "only_generic_card_labels_after_filtering",
                }
            )
            (output_dir / f"{label_path.stem}.excluded.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            excluded_empty_after_drop += 1
            continue
        if not lines:
            empty += 1
        (output_dir / label_path.name).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        metadata.update(
            {
                "status": "validated_zones_only" if drop_generic_cards else "validated",
                "source_label": label_path.name,
                "dropped_generic_card_labels": dropped,
                "requires_card_identity_review": False if drop_generic_cards else dropped > 0,
                "empty": not lines,
                "hard_negative": not lines,
            }
        )
        (output_dir / metadata_path.name).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        copied += 1

    return {
        "output_dir": output_dir.as_posix(),
        "files": copied,
        "empty_files": empty,
        "dropped_generic_card_labels": dropped_generic,
        "excluded_empty_after_drop": excluded_empty_after_drop,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspecte et valide les labels YOLO proposés avant entraînement.")
    parser.add_argument("--labels-dir", default="dataset/proposed_labels")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--report-json", default=None)
    parser.add_argument("--allow-generic-cards", action="store_true")
    parser.add_argument("--drop-generic-cards", action="store_true")
    parser.add_argument("--exclude-empty-after-drop", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    labels_dir = Path(args.labels_dir).resolve()
    report = inspect_labels(labels_dir)

    if args.report_json:
        Path(args.report_json).resolve().write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))

    invalid_count = len(report["invalid_labels"])
    generic_count = int(report["generic_card_labels"])
    if invalid_count:
        raise SystemExit(f"Labels YOLO invalides: {invalid_count}")
    if generic_count and not args.allow_generic_cards and not args.drop_generic_cards:
        raise SystemExit(
            f"{generic_count} labels cartes génériques restent à corriger. "
            "Utilise --drop-generic-cards pour produire un dataset zones-only, ou --allow-generic-cards pour inspection seule."
        )

    if args.output_dir:
        summary = write_validated_labels(
            labels_dir,
            Path(args.output_dir).resolve(),
            drop_generic_cards=bool(args.drop_generic_cards),
            overwrite=bool(args.overwrite),
            exclude_empty_after_drop=bool(args.exclude_empty_after_drop),
        )
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
