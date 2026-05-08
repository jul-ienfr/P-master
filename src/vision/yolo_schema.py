from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


YOLO_CLASS_NAMES: list[str] = [
    # --- 1. Cartes (52 classiques + dos) ---
    "2h", "3h", "4h", "5h", "6h", "7h", "8h", "9h", "Th", "Jh", "Qh", "Kh", "Ah",
    "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s", "Ts", "Js", "Qs", "Ks", "As",
    "2c", "3c", "4c", "5c", "6c", "7c", "8c", "9c", "Tc", "Jc", "Qc", "Kc", "Ac",
    "2d", "3d", "4d", "5d", "6d", "7d", "8d", "9d", "Td", "Jd", "Qd", "Kd", "Ad",
    "card_facedown",
    # Maintien des anciens labels génériques pour compatibilité / fallback
    "board_card",
    "hero_card",
    
    # --- 2. Zones Textuelles (OCR) et Boutons ---
    "pot_area",
    "stack_area",
    "player_name_area",
    "dealer_button",
    
    # --- 3. Actions ---
    "fold_button",
    "call_button",
    "check_button",
    "bet_button",
    "raise_button",
    
    # --- 4. Validation Visuelle (Anti-Hallucination OCR) ---
    "chip_stack_red",
    "chip_stack_blue",
    "chip_stack_green",
    "chip_stack_black",
    "chip_stack_gold",
]

YOLO_CLASS_MAP: dict[str, int] = {name: index for index, name in enumerate(YOLO_CLASS_NAMES)}


class YoloDatasetSchemaError(ValueError):
    """Raised when a YOLO dataset YAML does not match PokerMaster classes."""


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.isdigit():
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].strip()
        if not items:
            return []
        return [_parse_scalar(item.strip()) for item in items.split(",")]
    return value


def _parse_dataset_yaml_minimal(content: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        index += 1
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = _parse_scalar(value)
            continue
        block: dict[int, str] = {}
        items: list[str] = []
        while index < len(lines) and (lines[index].startswith(" ") or lines[index].startswith("\t")):
            child = lines[index].strip()
            index += 1
            if not child or child.startswith("#"):
                continue
            if child.startswith("-"):
                items.append(str(_parse_scalar(child[1:].strip())))
            elif ":" in child:
                child_key, child_value = child.split(":", 1)
                try:
                    block[int(child_key.strip())] = str(_parse_scalar(child_value.strip()))
                except ValueError as exc:
                    raise YoloDatasetSchemaError(f"Clé names invalide dans le YAML YOLO: {child_key.strip()!r}") from exc
        data[key] = items if items else block
    return data


def read_dataset_yaml_schema(data_yaml_path: Path) -> dict[str, Any]:
    """Read a YOLO dataset YAML using PyYAML when available, otherwise a local parser."""
    content = data_yaml_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _parse_dataset_yaml_minimal(content)

    loaded = yaml.safe_load(content)
    if not isinstance(loaded, dict):
        raise YoloDatasetSchemaError(f"YAML dataset YOLO invalide: {data_yaml_path}")
    return loaded


def normalize_dataset_names(raw_names: Any) -> list[str]:
    if isinstance(raw_names, list):
        return [str(name) for name in raw_names]
    if isinstance(raw_names, dict):
        try:
            ordered_indexes = sorted(int(index) for index in raw_names)
            return [str(raw_names[index] if index in raw_names else raw_names[str(index)]) for index in ordered_indexes]
        except (TypeError, ValueError, KeyError) as exc:
            raise YoloDatasetSchemaError("Le champ names du YAML YOLO doit utiliser des index entiers.") from exc
    raise YoloDatasetSchemaError("Le champ names du YAML YOLO doit être une liste ou un dictionnaire index->nom.")


def validate_dataset_yaml_schema(
    data_yaml_path: Path,
    *,
    expected_class_names: Iterable[str] = YOLO_CLASS_NAMES,
) -> list[str]:
    """Validate nc/names from a YOLO dataset YAML against PokerMaster classes."""
    expected_names = list(expected_class_names)
    schema = read_dataset_yaml_schema(data_yaml_path)
    if "nc" not in schema:
        raise YoloDatasetSchemaError(f"YAML dataset YOLO invalide ({data_yaml_path}): champ nc manquant.")
    if "names" not in schema:
        raise YoloDatasetSchemaError(f"YAML dataset YOLO invalide ({data_yaml_path}): champ names manquant.")

    try:
        nc = int(schema["nc"])
    except (TypeError, ValueError) as exc:
        raise YoloDatasetSchemaError(f"YAML dataset YOLO invalide ({data_yaml_path}): nc doit être un entier.") from exc

    names = normalize_dataset_names(schema["names"])
    expected_nc = len(expected_names)
    if nc != expected_nc:
        raise YoloDatasetSchemaError(
            f"Schéma YOLO incompatible pour {data_yaml_path}: nc={nc}, attendu {expected_nc}."
        )
    if len(names) != expected_nc:
        raise YoloDatasetSchemaError(
            f"Schéma YOLO incompatible pour {data_yaml_path}: names contient {len(names)} classes, attendu {expected_nc}."
        )
    if names != expected_names:
        first_mismatch = next(
            (index for index, (actual, expected) in enumerate(zip(names, expected_names)) if actual != expected),
            None,
        )
        if first_mismatch is None:
            raise YoloDatasetSchemaError(f"Schéma YOLO incompatible pour {data_yaml_path}: ordre des classes invalide.")
        raise YoloDatasetSchemaError(
            "Schéma YOLO incompatible pour "
            f"{data_yaml_path}: classe #{first_mismatch}={names[first_mismatch]!r}, "
            f"attendu {expected_names[first_mismatch]!r}."
        )
    return names


def write_dataset_yaml(
    output_path: Path,
    *,
    dataset_root: Path,
    train_images_dir: Path,
    val_images_dir: Path,
    test_images_dir: Path | None = None,
    class_names: Iterable[str] = YOLO_CLASS_NAMES,
) -> Path:
    names = list(class_names)
    lines = [
        f"path: {dataset_root.as_posix()}",
        f"train: {train_images_dir.relative_to(dataset_root).as_posix()}",
        f"val: {val_images_dir.relative_to(dataset_root).as_posix()}",
    ]
    if test_images_dir is not None:
        lines.append(f"test: {test_images_dir.relative_to(dataset_root).as_posix()}")
    lines.append(f"nc: {len(names)}")
    lines.append("names:")
    lines.extend(f"  {index}: {name}" for index, name in enumerate(names))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
