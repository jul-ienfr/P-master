"""Mesure du temps par étage de décision (constat F-10, spec 008).

Une décision traverse une dizaine d'étages (profil villain, ranges, RL, appel
solveur, exploitation, assemblage), mais seule la latence **totale** est
enregistrée. Quand une décision est lente, rien ne dit *quel* étage l'est : le
seul recours est d'instrumenter à la main.

Ce module fournit l'accumulateur d'étages et l'agrégation par percentile. Il ne
connaît ni le solveur ni le gate : il reçoit des noms d'étages et rend des
durées. Les étages imbriqués sont autorisés et leur somme est rapportée **telle
quelle**, jamais recadrée à la latence totale (une mesure qui se recadre
elle-même masquerait justement ce qu'elle doit révéler).

Le coût est un ``time.perf_counter`` par étage, mesuré par test — jamais supposé
négligeable.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

DEFAULT_STAGE_PERCENTILES = (0.5, 0.95, 0.99)


def percentile(sorted_values: list[float], ratio: float) -> float:
    """Percentile par rang le plus proche d'une liste **triée**.

    ``0.0`` sur liste vide, jamais d'exception. Le rang est ``ceil(ratio * n)``
    (méthode « nearest-rank ») : c'est le rang qui garantit qu'un p95 sur quatre
    mesures vaut bien le maximum observé, et non la troisième valeur — un p95
    qui sous-estime la queue est un p95 qui ment sur la latence.
    """
    if not sorted_values:
        return 0.0
    bounded = min(1.0, max(0.0, float(ratio)))
    rank = math.ceil(bounded * len(sorted_values))
    index = min(len(sorted_values) - 1, max(0, rank - 1))
    return float(sorted_values[index])


class StageTimer:
    """Accumulateur ordonné de durées par étage.

    ``start``/``stop`` se réutilisent par paire ; ``stage`` est la variante
    contextuelle. Un ``stop`` sans ``start`` correspondant est ignoré (jamais une
    exception dans un chemin chaud) ; une durée négative (horloge non monotone)
    est ramenée à zéro plutôt que rapportée.
    """

    def __init__(self, *, clock: Any = time.perf_counter) -> None:
        self._clock = clock
        self._started_at = float(clock())
        self._starts: dict[str, list[float]] = {}
        self._durations: dict[str, float] = {}
        self._order: list[str] = []

    @staticmethod
    def _key(name: object) -> str:
        return str(name or "").strip()

    def start(self, name: str) -> None:
        key = self._key(name)
        if not key:
            return
        self._starts.setdefault(key, []).append(float(self._clock()))

    def stop(self, name: str) -> None:
        key = self._key(name)
        stack = self._starts.get(key)
        if not stack:
            return
        elapsed_ms = (float(self._clock()) - stack.pop()) * 1000.0
        if key not in self._durations:
            self._order.append(key)
        self._durations[key] = self._durations.get(key, 0.0) + max(0.0, elapsed_ms)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self.start(name)
        try:
            yield
        finally:
            self.stop(name)

    def as_dict(self) -> dict[str, float]:
        """Durées par étage, dans l'ordre de première traversée, arrondies."""
        return {name: round(self._durations[name], 3) for name in self._order}

    @property
    def total_ms(self) -> float:
        return round((float(self._clock()) - self._started_at) * 1000.0, 3)

    def __len__(self) -> int:
        return len(self._order)


def extract_stages_ms(record: Any) -> dict[str, float]:
    """Extrait ``stages_ms`` d'un enregistrement canonique ou d'une trace runtime.

    Un enregistrement sans étage (schéma antérieur) rend ``{}`` : l'appelant
    n'invente jamais un étage absent.
    """
    if not isinstance(record, dict):
        return {}
    candidates = (
        record.get("stages_ms"),
        (record.get("decision") or {}).get("stages_ms")
        if isinstance(record.get("decision"), dict)
        else None,
        (record.get("metadata") or {}).get("stages_ms")
        if isinstance(record.get("metadata"), dict)
        else None,
    )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        stages: dict[str, float] = {}
        for name, value in candidate.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            stages[str(name)] = float(value)
        if stages:
            return stages
    return {}


def summarize_stage_timings(
    records: Iterable[Any],
    *,
    percentiles: tuple[float, ...] = DEFAULT_STAGE_PERCENTILES,
) -> dict[str, Any]:
    """Percentiles par étage sur des enregistrements portant ``stages_ms``.

    Chaque étage est compté sur les **seuls** enregistrements qui le portent :
    un étage absent d'une décision n'est ni inventé, ni compté comme zéro.
    """
    per_stage: dict[str, list[float]] = {}
    records_with_stages = 0
    for record in records:
        stages = extract_stages_ms(record)
        if not stages:
            continue
        records_with_stages += 1
        for name, value in stages.items():
            per_stage.setdefault(name, []).append(value)

    summary: dict[str, Any] = {}
    for name, values in per_stage.items():
        ordered = sorted(values)
        entry: dict[str, Any] = {
            "count": len(ordered),
            "max": round(ordered[-1], 1),
        }
        for ratio in percentiles:
            label = f"p{int(round(ratio * 100))}"
            entry[label] = round(percentile(ordered, ratio), 1)
        entry["mean"] = round(sum(ordered) / len(ordered), 1)
        summary[name] = entry

    return {
        "records_with_stages": records_with_stages,
        "stage_count": len(summary),
        "stages": summary,
    }
