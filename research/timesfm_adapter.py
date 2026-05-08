"""Thin local adapter around the vendored TimesFM snapshot."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .timesfm_runtime_dataset import RuntimeMetricHoldoutSplit, RuntimeMetricSeries, build_holdout_split


VENDORED_TIMESFM_SRC = Path(__file__).resolve().parent / "vendor" / "timesfm" / "src"


@dataclass(frozen=True)
class RuntimeMetricForecastResult:
  metric_name: str
  horizon: int
  context_values: list[float]
  target_values: list[float]
  point_forecast: list[float]
  quantile_forecast: list[list[float]]
  last_value_baseline: list[float]
  moving_average_baseline: list[float]


@dataclass(frozen=True)
class SeriesForecastResult:
  context_values: list[float]
  point_forecast: list[float]
  quantile_forecast: list[list[float]]


def _load_timesfm_module():
  vendor_path = str(VENDORED_TIMESFM_SRC)
  if vendor_path not in sys.path:
    sys.path.insert(0, vendor_path)
  return importlib.import_module("timesfm")


def mean_absolute_error(actual: list[float], predicted: list[float]) -> float:
  if not actual:
    return 0.0
  return sum(abs(lhs - rhs) for lhs, rhs in zip(actual, predicted)) / float(len(actual))


def relative_mae(actual: list[float], predicted: list[float]) -> float | None:
  denominator = sum(abs(value) for value in actual) / float(len(actual)) if actual else 0.0
  if denominator == 0.0:
    return None
  return mean_absolute_error(actual, predicted) / denominator


def relative_improvement(candidate_mae: float, baseline_mae: float) -> float | None:
  if baseline_mae == 0.0:
    return None
  return (baseline_mae - candidate_mae) / baseline_mae


def quantile_range_coverage(actual: list[float], quantile_forecast: list[list[float]] | None) -> float | None:
  if not actual or not quantile_forecast or len(actual) != len(quantile_forecast):
    return None

  covered = 0
  eligible = 0
  for actual_value, forecast_row in zip(actual, quantile_forecast):
    if not forecast_row:
      continue
    eligible += 1
    lower = min(forecast_row)
    upper = max(forecast_row)
    if lower <= actual_value <= upper:
      covered += 1

  if eligible == 0:
    return None
  return covered / float(eligible)


def _best_forecaster(mae: Mapping[str, float]) -> str:
  best_value = min(mae.values())
  winners = [name for name, value in mae.items() if value == best_value]
  return winners[0] if len(winners) == 1 else "tie"


def build_forecast_evaluation(result) -> dict:
  mae = {
    "timesfm": mean_absolute_error(result.target_values, result.point_forecast),
    "last_value": mean_absolute_error(result.target_values, result.last_value_baseline),
    "moving_average": mean_absolute_error(result.target_values, result.moving_average_baseline),
  }
  return {
    "mae": mae,
    "relative_mae": {
      "timesfm": relative_mae(result.target_values, result.point_forecast),
      "last_value": relative_mae(result.target_values, result.last_value_baseline),
      "moving_average": relative_mae(result.target_values, result.moving_average_baseline),
    },
    "baseline_comparison": {
      baseline_name: {
        "absolute_mae_delta": mae[baseline_name] - mae["timesfm"],
        "relative_improvement": relative_improvement(mae["timesfm"], mae[baseline_name]),
      }
      for baseline_name in ("last_value", "moving_average")
    },
    "best_forecaster": _best_forecaster(mae),
    "quantile_range_coverage": quantile_range_coverage(
      result.target_values,
      getattr(result, "quantile_forecast", None),
    ),
  }


def summarize_forecast_evaluations(result_payloads: Mapping[str, Mapping[str, object]]) -> dict:
  metric_count = len(result_payloads)
  best_by_metric = {
    metric_name: str(payload.get("best_forecaster") or "")
    for metric_name, payload in result_payloads.items()
  }
  timesfm_win_count = sum(1 for winner in best_by_metric.values() if winner == "timesfm")
  average_relative_improvement: dict[str, float | None] = {}
  for baseline_name in ("last_value", "moving_average"):
    values = []
    for payload in result_payloads.values():
      baseline_comparison = payload.get("baseline_comparison")
      if not isinstance(baseline_comparison, Mapping):
        continue
      comparison = baseline_comparison.get(baseline_name)
      if not isinstance(comparison, Mapping):
        continue
      value = comparison.get("relative_improvement")
      if isinstance(value, (int, float)):
        values.append(float(value))
    average_relative_improvement[baseline_name] = (
      sum(values) / float(len(values))
      if values
      else None
    )

  return {
    "metric_count": metric_count,
    "timesfm_win_count": timesfm_win_count,
    "timesfm_win_rate": timesfm_win_count / float(metric_count) if metric_count else 0.0,
    "best_by_metric": best_by_metric,
    "average_relative_improvement": average_relative_improvement,
  }


def build_last_value_baseline(context_values: list[float], horizon: int) -> list[float]:
  if not context_values:
    raise ValueError("context_values must not be empty")
  return [float(context_values[-1])] * horizon


def build_moving_average_baseline(
  context_values: list[float],
  horizon: int,
  window: int = 4,
) -> list[float]:
  if not context_values:
    raise ValueError("context_values must not be empty")
  window = max(1, min(int(window), len(context_values)))
  baseline_value = round(sum(context_values[-window:]) / float(window), 12)
  return [float(baseline_value)] * horizon


def build_default_forecast_config(context_length: int, horizon: int):
  timesfm = _load_timesfm_module()
  max_context = max(32, int(context_length))
  max_horizon = max(1, int(horizon))
  return timesfm.ForecastConfig(
    max_context=max_context,
    max_horizon=max_horizon,
    normalize_inputs=True,
    use_continuous_quantile_head=True,
    force_flip_invariance=True,
    infer_is_positive=False,
    fix_quantile_crossing=True,
  )


def load_timesfm_model(
  model_id: str = "google/timesfm-2.5-200m-pytorch",
  *,
  torch_compile: bool = False,
):
  timesfm = _load_timesfm_module()
  return timesfm.TimesFM_2p5_200M_torch.from_pretrained(
    model_id,
    torch_compile=torch_compile,
  )


def forecast_series(
  series: list[float],
  horizon: int,
  config=None,
  *,
  model=None,
) -> SeriesForecastResult:
  if horizon <= 0:
    raise ValueError("horizon must be strictly positive")
  if not series:
    raise ValueError("series must not be empty")
  if model is None:
    model = load_timesfm_model()
  if config is None:
    config = build_default_forecast_config(context_length=len(series), horizon=horizon)

  model.compile(config)
  point_forecast, quantile_forecast = model.forecast(
    horizon=horizon,
    inputs=[list(series)],
  )
  return SeriesForecastResult(
    context_values=[float(value) for value in series],
    point_forecast=[float(value) for value in point_forecast[0]],
    quantile_forecast=[
      [float(component) for component in row]
      for row in quantile_forecast[0]
    ],
  )


def forecast_runtime_metric(
  split: RuntimeMetricHoldoutSplit,
  *,
  model=None,
  forecast_config=None,
) -> RuntimeMetricForecastResult:
  horizon = len(split.target_values)
  series_forecast = forecast_series(
    split.context_values,
    horizon,
    config=forecast_config,
    model=model,
  )
  return RuntimeMetricForecastResult(
    metric_name=split.metric_name,
    horizon=horizon,
    context_values=list(split.context_values),
    target_values=list(split.target_values),
    point_forecast=series_forecast.point_forecast,
    quantile_forecast=series_forecast.quantile_forecast,
    last_value_baseline=build_last_value_baseline(split.context_values, horizon),
    moving_average_baseline=build_moving_average_baseline(split.context_values, horizon),
  )


def forecast_runtime_metrics(
  series_map: Mapping[str, RuntimeMetricSeries],
  horizon: int,
  *,
  model=None,
  forecast_config=None,
  max_context: int | None = None,
) -> dict[str, RuntimeMetricForecastResult]:
  if horizon <= 0:
    raise ValueError("horizon must be strictly positive")

  results: dict[str, RuntimeMetricForecastResult] = {}
  shared_model = model
  for metric_name, series in series_map.items():
    context_series = series
    if max_context is not None and max_context > 0 and len(series.values) > horizon + max_context:
      start_index = len(series.values) - (horizon + max_context)
      context_series = RuntimeMetricSeries(
        name=series.name,
        timestamps=series.timestamps[start_index:],
        values=series.values[start_index:],
      )
    split = build_holdout_split(context_series, horizon=horizon)
    results[metric_name] = forecast_runtime_metric(
      split,
      model=shared_model,
      forecast_config=forecast_config,
    )
  return results
