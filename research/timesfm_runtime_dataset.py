"""Runtime-metric series extraction for offline TimesFM experiments."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_RUNTIME_METRICS = (
  "fallback_rate",
  "block_rate",
  "rolling_latency_ms",
  "decision_rate",
)


@dataclass(frozen=True)
class RuntimeMetricSeries:
  name: str
  timestamps: list[str]
  values: list[float]


@dataclass(frozen=True)
class RuntimeMetricHoldoutSplit:
  metric_name: str
  context_timestamps: list[str]
  context_values: list[float]
  target_timestamps: list[str]
  target_values: list[float]


def _iter_metric_records(history_path: Path) -> Iterable[dict]:
  with history_path.open("r", encoding="utf-8") as handle:
    for raw_line in handle:
      line = raw_line.strip()
      if not line:
        continue
      try:
        payload = json.loads(line)
      except json.JSONDecodeError:
        continue
      if not isinstance(payload, dict):
        continue
      if payload.get("stream") != "metrics":
        continue
      timestamp = str(payload.get("timestamp", "") or "").strip()
      if not timestamp:
        continue
      yield payload


def load_runtime_metric_series_map(
  history_path: str | Path,
  metric_names: tuple[str, ...] = DEFAULT_RUNTIME_METRICS,
) -> dict[str, RuntimeMetricSeries]:
  path = Path(history_path)
  ordered_records = sorted(
    _iter_metric_records(path),
    key=lambda payload: str(payload.get("timestamp", "") or ""),
  )
  series_map: dict[str, list[tuple[str, float]]] = {name: [] for name in metric_names}

  for payload in ordered_records:
    timestamp = str(payload.get("timestamp", "") or "")
    for metric_name in metric_names:
      value = payload.get(metric_name)
      if value is None:
        continue
      try:
        numeric_value = float(value)
      except (TypeError, ValueError):
        continue
      if not math.isfinite(numeric_value):
        continue
      series_map[metric_name].append((timestamp, numeric_value))

  return {
    metric_name: RuntimeMetricSeries(
      name=metric_name,
      timestamps=[timestamp for timestamp, _ in entries],
      values=[value for _, value in entries],
    )
    for metric_name, entries in series_map.items()
  }


def build_holdout_split(
  series: RuntimeMetricSeries,
  horizon: int,
) -> RuntimeMetricHoldoutSplit:
  if horizon <= 0:
    raise ValueError("horizon must be strictly positive")
  if len(series.values) <= horizon:
    raise ValueError(
      f"Series '{series.name}' must contain at least {horizon + 1} points for a holdout split."
    )

  split_index = len(series.values) - horizon
  return RuntimeMetricHoldoutSplit(
    metric_name=series.name,
    context_timestamps=series.timestamps[:split_index],
    context_values=series.values[:split_index],
    target_timestamps=series.timestamps[split_index:],
    target_values=series.values[split_index:],
  )
