from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_capture_folder(source_dir: Path, destination_dir: Path, prefix: str = "capture") -> dict[str, int]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    existing_hashes = {}
    for existing in destination_dir.iterdir():
        if not existing.is_file() or existing.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            existing_hashes[file_sha1(existing)] = existing.name
        except OSError:
            continue

    imported = 0
    skipped = 0
    for source in sorted(source_dir.iterdir()):
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        file_hash = file_sha1(source)
        if file_hash in existing_hashes:
            skipped += 1
            continue

        target_name = f"{prefix}_{source.stem}{source.suffix.lower()}"
        target = destination_dir / target_name
        counter = 1
        while target.exists():
            target = destination_dir / f"{prefix}_{source.stem}_{counter}{source.suffix.lower()}"
            counter += 1
        shutil.copy2(source, target)
        existing_hashes[file_hash] = target.name
        imported += 1

    return {"imported": imported, "skipped": skipped}


def main() -> int:
    parser = argparse.ArgumentParser(description="Copie des captures PokerStars dans dataset/raw_images.")
    parser.add_argument("--source-dir", default="POKERSTAR CAPTURE")
    parser.add_argument("--destination-dir", default="dataset/raw_images")
    parser.add_argument("--prefix", default="pokerstars")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    destination_dir = Path(args.destination_dir).resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"Dossier source introuvable: {source_dir}")

    summary = import_capture_folder(source_dir, destination_dir, prefix=args.prefix)
    print(
        f"Import terminé: {summary['imported']} nouvelle(s) image(s), {summary['skipped']} doublon(s) ignoré(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
