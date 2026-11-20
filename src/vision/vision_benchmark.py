"""Harnais de mesure de la vision par site (spec 010, constat F-08).

La cible de l'audit §3.1 est « la précision de vision par site est mesurée sur un
jeu de fixtures et documentée ». Aucune fixture d'écran n'est committée dans ce
dépôt (données d'exploitation) : ce harnais mesure dès que l'opérateur fournit un
jeu de captures étiquetées, et — sans capture — produit un rapport **non mesuré**
plutôt qu'un taux inventé.

Principe honnête : un taux de réussite est ``None`` quand rien n'a été évalué.
``0.0`` signifierait « tout faux », ``1.0`` « tout juste » ; aucun des deux n'est
vrai pour un jeu vide.

Le harnais est indépendant du moteur OCR : il reçoit une fonction de lecture
(``reader(image_crop) -> float | None``), ce qui permet de le tester sans OCR.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UNMEASURED = "unmeasured"
MEASURED = "measured"


@dataclass(frozen=True)
class LabeledSample:
    """Une capture étiquetée : un crop, la valeur attendue, et le site."""

    image: Any
    expected: float | None
    site_key: str = ""
    field: str = "amount"


@dataclass(frozen=True)
class FieldMeasurement:
    field: str
    evaluated: int
    correct: int
    unreadable: int
    unevaluable: int
    accuracy: float | None
    latency_ms_median: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "evaluated": self.evaluated,
            "correct": self.correct,
            "unreadable": self.unreadable,
            "unevaluable": self.unevaluable,
            "accuracy": None if self.accuracy is None else round(self.accuracy, 4),
            "latency_ms_median": (
                None if self.latency_ms_median is None else round(self.latency_ms_median, 3)
            ),
        }


@dataclass
class VisionBenchmarkReport:
    site_key: str
    status: str
    samples: int
    fields: list[FieldMeasurement] = field(default_factory=list)
    generated_at: str = ""

    @property
    def measured(self) -> bool:
        return self.status == MEASURED

    @property
    def evaluated(self) -> int:
        return sum(item.evaluated for item in self.fields)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "vision_benchmark",
            "site_key": self.site_key,
            "status": self.status,
            "samples": self.samples,
            "evaluated": self.evaluated,
            "fields": [item.as_dict() for item in self.fields],
            "generated_at": self.generated_at,
        }


def _matches(actual: float | None, expected: float, tolerance: float) -> bool:
    if actual is None:
        return False
    return abs(float(actual) - float(expected)) <= tolerance


def run_vision_benchmark(
    samples: Sequence[LabeledSample],
    reader: Callable[[Any], float | None],
    *,
    site_key: str = "",
    tolerance: float = 0.01,
    clock: Callable[[], float] | None = None,
) -> VisionBenchmarkReport:
    """Mesure la précision et la latence par champ sur des captures étiquetées.

    ``reader`` reçoit un crop et retourne la valeur lue (ou ``None`` si illisible).
    Deux échecs sont distingués et **jamais exclus** :

    - ``unevaluable`` : étiquette absente, l'échantillon ne peut pas être jugé ;
    - ``unreadable`` : étiquette présente, lecteur muet — c'est un **échec de
      mesure**, compté dans le dénominateur de la précision.

    Sans échantillon évaluable, le statut est ``unmeasured`` et les taux sont
    ``None``.
    """
    clock = clock or time.perf_counter

    by_field: dict[str, dict[str, Any]] = {}
    for sample in samples:
        bucket = by_field.setdefault(
            sample.field,
            {"evaluated": 0, "correct": 0, "unreadable": 0, "unevaluable": 0, "lat": []},
        )
        if sample.expected is None:
            # Étiquette absente : non évaluable, mais tracé comme non mesuré.
            bucket["unevaluable"] += 1
            continue
        started = clock()
        try:
            actual = reader(sample.image)
        except Exception:
            actual = None
        bucket["lat"].append((clock() - started) * 1000.0)
        bucket["evaluated"] += 1
        if actual is None:
            bucket["unreadable"] += 1
        elif _matches(actual, sample.expected, tolerance):
            bucket["correct"] += 1

    measurements: list[FieldMeasurement] = []
    for field_name in sorted(by_field):
        bucket = by_field[field_name]
        evaluated = int(bucket["evaluated"])
        correct = int(bucket["correct"])
        latencies = list(bucket["lat"])
        measurements.append(
            FieldMeasurement(
                field=field_name,
                evaluated=evaluated,
                correct=correct,
                unreadable=int(bucket["unreadable"]),
                unevaluable=int(bucket["unevaluable"]),
                accuracy=(correct / evaluated) if evaluated > 0 else None,
                latency_ms_median=statistics.median(latencies) if latencies else None,
            )
        )

    evaluated_total = sum(item.evaluated for item in measurements)
    status = MEASURED if evaluated_total > 0 else UNMEASURED
    return VisionBenchmarkReport(
        site_key=site_key,
        status=status,
        samples=len(samples),
        fields=measurements,
        generated_at=datetime.now(UTC).isoformat(),
    )


def write_report(report: VisionBenchmarkReport, output: Path) -> Path:
    """Écrit le rapport JSON daté (artefact versionnable)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output
