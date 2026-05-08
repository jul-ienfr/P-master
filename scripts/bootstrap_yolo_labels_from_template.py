from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.detector import PokerDetector, DetectionResult
from src.vision.yolo_schema import YOLO_CLASS_MAP, YOLO_CLASS_NAMES


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def normalize_bbox(det: DetectionResult, width: int, height: int) -> str | None:
    x1, y1, x2, y2 = det.bbox
    x1 = max(0, min(x1, width))
    x2 = max(0, min(x2, width))
    y1 = max(0, min(y1, height))
    y2 = max(0, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        return None

    abs_w = x2 - x1
    abs_h = y2 - y1
    center_x = x1 + (abs_w / 2.0)
    center_y = y1 + (abs_h / 2.0)
    return f"{center_x / width:.6f} {center_y / height:.6f} {abs_w / width:.6f} {abs_h / height:.6f}"


def generic_label_for_detection(group_name: str, det: DetectionResult) -> str | None:
    if group_name == "board_cards":
        return "board_card"
    if group_name == "hero_cards":
        return "hero_card"
    if group_name == "pots":
        return "pot_area"
    if group_name == "stacks":
        return "stack_area"
    if group_name == "player_names":
        return "player_name_area"
    if group_name == "dealer_button":
        return "dealer_button"
    if group_name == "action_buttons":
        return det.class_name if det.class_name in YOLO_CLASS_MAP else None
    return None


def state_to_yolo_lines(state, width: int, height: int) -> list[str]:
    lines: list[str] = []
    grouped = {
        "board_cards": list(state.board_cards),
        "hero_cards": list(state.hero_cards),
        "pots": list(state.pots),
        "stacks": list(state.stacks),
        "player_names": list(state.player_names),
        "action_buttons": list(state.action_buttons),
    }
    if state.dealer_button is not None:
        grouped["dealer_button"] = [state.dealer_button]

    for group_name, detections in grouped.items():
        for det in detections:
            label = generic_label_for_detection(group_name, det)
            if label is None:
                continue
            normalized = normalize_bbox(det, width, height)
            if normalized is None:
                continue
            cls_id = YOLO_CLASS_MAP[label]
            lines.append(f"{cls_id} {normalized}")

    return lines


def metadata_for_image(image_path: Path, width: int, height: int, lines: list[str], status: str) -> dict[str, object]:
    counts: dict[str, int] = {}
    for line in lines:
        cls_id = int(line.split(maxsplit=1)[0])
        cls_name = YOLO_CLASS_NAMES[cls_id]
        counts[cls_name] = counts.get(cls_name, 0) + 1

    return {
        "source": "template_bootstrap",
        "status": status,
        "image": image_path.name,
        "image_size": {"width": width, "height": height},
        "counts": counts,
        "empty": not lines,
        "hard_negative": not lines,
    }


def bootstrap_labels(
    raw_dir: Path,
    labels_dir: Path,
    overwrite: bool = False,
    status: str = "proposed",
    write_metadata: bool = True,
) -> dict[str, int]:
    detector = PokerDetector()
    labels_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    empty = 0

    for image_path in sorted(raw_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue

        label_path = labels_dir / f"{image_path.stem}.txt"
        metadata_path = labels_dir / f"{image_path.stem}.json"
        if label_path.exists() and not overwrite:
            skipped += 1
            continue

        frame = cv2.imread(str(image_path))
        if frame is None:
            skipped += 1
            continue

        state = detector.analyze_frame(frame)
        height, width = frame.shape[:2]
        lines = state_to_yolo_lines(state, width, height)
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if write_metadata:
            metadata = metadata_for_image(image_path, width, height, lines, status=status)
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written += 1
        if not lines:
            empty += 1

    return {"written": written, "skipped": skipped, "empty": empty}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap des labels YOLO depuis le backend template PokerMaster.")
    parser.add_argument("--raw-dir", default="dataset/raw_images")
    parser.add_argument("--labels-dir", default=None, help="Dossier de sortie explicite (compatibilité: ex. dataset/labels).")
    parser.add_argument("--proposed-labels-dir", default="dataset/proposed_labels")
    parser.add_argument("--status", choices=("proposed", "validated"), default="proposed")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-metadata", action="store_true")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir).resolve()
    if args.labels_dir is not None:
        labels_dir = Path(args.labels_dir).resolve()
    elif args.status == "proposed":
        labels_dir = Path(args.proposed_labels_dir).resolve()
    else:
        labels_dir = Path("dataset/labels").resolve()
    if not raw_dir.is_dir():
        raise SystemExit(f"Dossier brut introuvable: {raw_dir}")

    summary = bootstrap_labels(
        raw_dir,
        labels_dir,
        overwrite=args.overwrite,
        status=args.status,
        write_metadata=not args.no_metadata,
    )
    print(
        "Bootstrap labels terminé: "
        f"status={args.status}, sortie={labels_dir}, "
        f"{summary['written']} fichier(s) écrit(s), "
        f"{summary['empty']} vide(s), "
        f"{summary['skipped']} ignoré(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
