"""Mesure de la vision par site sur des captures étiquetées (spec 010, F-08).

Le harnais `src/vision/vision_benchmark.py` mesure, mais rien ne l'alimentait :
aucune capture n'est committée (données d'exploitation), donc la précision par
site n'était pas mesurable. Ce script est le point d'entrée opérateur : il lit un
dossier de captures étiquetées, appelle l'OCR du site, et écrit un artefact JSON
daté dans `research/results/`.

Sans capture fournie, il n'invente rien : il écrit un rapport `unmeasured` avec
des taux `None` et le dit explicitement en sortie.

Format des étiquettes (`labels.json` dans le dossier de captures) :

    {
      "site_key": "pokerstars",
      "samples": [
        {"path": "sample_000.png", "field": "pot", "expected": 12345.0},
        {"path": "sample_001.png", "field": "stack", "expected": null}
      ]
    }

`expected: null` marque un échantillon non évaluable (étiquette absente) ; il est
compté comme tel, jamais exclu silencieusement.

Usage :

    python scripts/vision_benchmark.py --captures captures/pokerstars
    python scripts/vision_benchmark.py --captures captures/winamax --site winamax
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.ocr import PokerOCR  # noqa: E402
from src.vision.vision_benchmark import (  # noqa: E402
    LabeledSample,
    run_vision_benchmark,
    write_report,
)

DEFAULT_OUTPUT_DIR = ROOT / "research" / "results"


def load_labels(captures_dir: Path) -> dict[str, Any]:
    """Lit `labels.json` et vérifie sa forme minimale."""
    labels_path = captures_dir / "labels.json"
    if not labels_path.is_file():
        raise FileNotFoundError(f"Étiquettes absentes : {labels_path}")
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError(f"labels.json mal formé (clé 'samples' attendue) : {labels_path}")
    return payload


def build_samples(captures_dir: Path, payload: dict[str, Any]) -> list[LabeledSample]:
    """Construit les échantillons, une capture absente devenant non évaluable.

    Une capture manquante n'est pas une erreur fatale : l'échantillon est marqué
    non évaluable (``expected=None``) et le rapport le dit. Faire échouer tout le
    run sur un fichier manquant masquerait la mesure des autres.
    """
    samples: list[LabeledSample] = []
    for entry in payload["samples"]:
        if not isinstance(entry, dict):
            continue
        field = str(entry.get("field") or "amount")
        expected_raw = entry.get("expected")
        expected = None if expected_raw is None else float(expected_raw)
        image_path = captures_dir / str(entry.get("path") or "")
        if expected is not None and image_path.is_file():
            image = cv2.imread(str(image_path))
            if image is None:
                expected = None
        else:
            image = None
            if expected is not None:
                expected = None
        samples.append(LabeledSample(image=image, expected=expected, field=field))
    return samples


def build_reader(ocr: PokerOCR):
    """Lecteur de montant branché sur l'OCR du site (pré-traitement inclus)."""

    def reader(image) -> float | None:
        return ocr.read_and_parse_amount(image)

    return reader


def main() -> int:
    parser = argparse.ArgumentParser(description="Mesure de vision par site (F-08)")
    parser.add_argument("--captures", required=True, help="Dossier de captures étiquetées")
    parser.add_argument("--site", default=None, help="Clé de site (défaut : labels.json)")
    parser.add_argument("--output", default=None, help="Chemin du rapport JSON de sortie")
    parser.add_argument("--tolerance", type=float, default=0.01, help="Tolérance de montant")
    args = parser.parse_args()

    captures_dir = Path(args.captures)
    if not captures_dir.is_dir():
        print(f"Dossier de captures introuvable : {captures_dir}")
        return 1

    try:
        payload = load_labels(captures_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{exc}")
        print("Rapport non produit : aucune mesure inventée.")
        return 1

    site_key = str(args.site or payload.get("site_key") or "default")
    samples = build_samples(captures_dir, payload)

    if not samples:
        # Aucune capture : on produit quand même le rapport « non mesuré ».
        report = run_vision_benchmark([], lambda _image: None, site_key=site_key)
    else:
        ocr = PokerOCR.from_config(
            {"enabled_engines": ["rapidocr", "tesseract"], "mode": "fallback", "parallel": False},
            site_key=site_key,
        )
        report = run_vision_benchmark(
            samples, build_reader(ocr), site_key=site_key, tolerance=args.tolerance
        )

    output = (
        Path(args.output)
        if args.output
        else DEFAULT_OUTPUT_DIR / f"vision_benchmark_{site_key}.json"
    )
    write_report(report, output)

    print(f"Rapport écrit : {output}")
    print(f"Site : {report.site_key} | statut : {report.status} | échantillons : {report.samples}")
    if not report.measured:
        print(
            "Non mesuré : aucune capture évaluable. "
            "Les taux sont absents (None), aucun taux n'est inventé."
        )
    else:
        for field in report.fields:
            accuracy = "n/a" if field.accuracy is None else f"{field.accuracy:.4f}"
            latency = (
                "n/a" if field.latency_ms_median is None else f"{field.latency_ms_median:.1f} ms"
            )
            print(
                f"  {field.field}: précision {accuracy} "
                f"({field.correct}/{field.evaluated}, {field.unreadable} illisibles, "
                f"{field.unevaluable} non évaluables) | médiane {latency}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
