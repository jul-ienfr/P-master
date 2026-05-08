"""CLI runner for offline TimesFM runtime-metric experiments."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from research.timesfm_adapter import build_forecast_evaluation, forecast_runtime_metric, summarize_forecast_evaluations
from research.timesfm_runtime_dataset import RuntimeMetricSeries, build_holdout_split, load_runtime_metric_series_map


def _truncate_series(series: RuntimeMetricSeries, max_context: int | None, horizon: int) -> RuntimeMetricSeries:
  if max_context is None or max_context <= 0:
    return series
  keep = max_context + horizon
  if len(series.values) <= keep:
    return series
  start_index = len(series.values) - keep
  return RuntimeMetricSeries(
    name=series.name,
    timestamps=series.timestamps[start_index:],
    values=series.values[start_index:],
  )


def _build_run_metadata(args, history_path: Path) -> dict:
  return {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "config": {
      "metric": str(args.metric),
      "horizon": int(args.horizon),
      "max_context": args.max_context,
      "history_path": str(history_path),
      "output_path": str(args.output_path) if args.output_path else None,
    },
  }


def _build_metric_payload(
  series: RuntimeMetricSeries,
  *,
  horizon: int,
  max_context: int | None,
  history_path: Path,
) -> dict:
  truncated_series = _truncate_series(series, max_context, horizon)
  split = build_holdout_split(truncated_series, horizon=horizon)
  result = forecast_runtime_metric(split)
  return {
    "metric": result.metric_name,
    "horizon": result.horizon,
    "series_length": len(truncated_series.values),
    "context_length": len(result.context_values),
    "history_path": str(history_path),
    "target_values": result.target_values,
    "point_forecast": result.point_forecast,
    "last_value_baseline": result.last_value_baseline,
    "moving_average_baseline": result.moving_average_baseline,
    **build_forecast_evaluation(result),
  }


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--metric", default="fallback_rate", help="Runtime metric to forecast")
  parser.add_argument("--horizon", type=int, default=4, help="Holdout horizon")
  parser.add_argument(
    "--max-context",
    type=int,
    default=None,
    help="Maximum number of context points kept before the holdout tail",
  )
  parser.add_argument(
    "--history-path",
    default="log/runtime_history.jsonl",
    help="Path to runtime history jsonl",
  )
  parser.add_argument(
    "--output-path",
    default=None,
    help="Optional path where the benchmark JSON payload should be written",
  )
  args = parser.parse_args()

  history_path = Path(args.history_path)
  run_metadata = _build_run_metadata(args, history_path)
  series_map = load_runtime_metric_series_map(history_path)
  if str(args.metric).strip().lower() == "all":
    results = {}
    errors = {}
    attempted_metric_count = len(series_map)
    for metric_name, series in series_map.items():
      if not series.values:
        errors[metric_name] = "No samples available for this runtime metric."
        continue
      try:
        results[metric_name] = _build_metric_payload(
          series,
          horizon=args.horizon,
          max_context=args.max_context,
          history_path=history_path,
        )
      except Exception as exc:
        errors[metric_name] = str(exc)

    summary = summarize_forecast_evaluations(results)
    payload = {
      **run_metadata,
      "metric": "all",
      "horizon": args.horizon,
      "history_path": str(history_path),
      "results": results,
      "errors": errors,
      "attempted_metric_count": attempted_metric_count,
      "error_count": len(errors),
      "success_rate": len(results) / float(attempted_metric_count) if attempted_metric_count else 0.0,
      **summary,
    }
  else:
    series = series_map.get(args.metric)
    if series is None:
      raise SystemExit(f"Unknown metric: {args.metric}")
    metric_payload = _build_metric_payload(
      series,
      horizon=args.horizon,
      max_context=args.max_context,
      history_path=history_path,
    )
    payload = {
      **run_metadata,
      **metric_payload,
      "attempted_metric_count": 1,
      "error_count": 0,
      "success_rate": 1.0,
      **summarize_forecast_evaluations({metric_payload["metric"]: metric_payload}),
    }
  output_json = json.dumps(payload, indent=2)
  if args.output_path:
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_json + "\n", encoding="utf-8")
  print(output_json)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
