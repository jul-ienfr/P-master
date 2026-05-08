from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional


class RuntimeTimesFMService:
    def __init__(
        self,
        *,
        enabled: bool,
        history_path: str,
        default_horizon: int = 12,
        default_max_context: Optional[int] = 256,
        series_loader: Optional[Callable[..., Mapping[str, Any]]] = None,
        forecaster: Optional[Callable[..., Mapping[str, Any]]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.history_path = str(history_path)
        self.default_horizon = int(default_horizon)
        self.default_max_context = int(default_max_context) if default_max_context is not None else None
        self._series_loader = series_loader
        self._forecaster = forecaster

    def _load_series_map(self, history_path: Path):
        if self._series_loader is not None:
            return self._series_loader(history_path)
        from research.timesfm_runtime_dataset import load_runtime_metric_series_map

        return load_runtime_metric_series_map(history_path)

    def _forecast(self, series_map, horizon: int, max_context: Optional[int]):
        if self._forecaster is not None:
            return self._forecaster(series_map, horizon=horizon, max_context=max_context)
        from research.timesfm_adapter import forecast_runtime_metrics

        return forecast_runtime_metrics(series_map, horizon=horizon, max_context=max_context)

    @staticmethod
    def _build_forecast_evaluation(result) -> dict:
        from research.timesfm_adapter import build_forecast_evaluation

        return build_forecast_evaluation(result)

    def forecast_runtime_metrics(
        self,
        *,
        metric: Optional[str] = None,
        horizon: Optional[int] = None,
        max_context: Optional[int] = None,
        history_path: Optional[str] = None,
    ) -> dict:
        if not self.enabled:
            raise RuntimeError("TimesFM runtime forecasts are disabled.")

        resolved_horizon = int(horizon or self.default_horizon)
        if resolved_horizon <= 0:
            raise ValueError("horizon must be strictly positive")

        resolved_max_context = self.default_max_context if max_context is None else int(max_context)
        resolved_history_path = Path(history_path or self.history_path)
        requested_metric = str(metric or "").strip() or None
        forecast_all_metrics = requested_metric is None or requested_metric.lower() == "all"
        series_map = dict(self._load_series_map(resolved_history_path) or {})
        if not forecast_all_metrics:
            if requested_metric not in series_map:
                raise ValueError(f"Unknown metric: {requested_metric}")
            series_map = {requested_metric: series_map[requested_metric]}
        if not series_map:
            raise ValueError("No runtime metrics available for TimesFM forecasting.")

        payload_results = {}
        errors = {}
        attempted_metric_count = len(series_map)
        forecast_batches = (
            ({metric_name: metric_series} for metric_name, metric_series in series_map.items())
            if forecast_all_metrics
            else (series_map,)
        )
        for forecast_batch in forecast_batches:
            try:
                forecast_results = self._forecast(
                    forecast_batch,
                    horizon=resolved_horizon,
                    max_context=resolved_max_context,
                )
            except Exception as exc:
                if not forecast_all_metrics:
                    raise
                for metric_name in forecast_batch:
                    errors[metric_name] = str(exc)
                continue

            for metric_name, result in forecast_results.items():
                payload_results[metric_name] = {
                    "metric": result.metric_name,
                    "horizon": result.horizon,
                    "context_length": len(result.context_values),
                    "target_values": list(result.target_values),
                    "point_forecast": list(result.point_forecast),
                    "quantile_forecast": list(result.quantile_forecast),
                    "last_value_baseline": list(result.last_value_baseline),
                    "moving_average_baseline": list(result.moving_average_baseline),
                    **self._build_forecast_evaluation(result),
                }
        from research.timesfm_adapter import summarize_forecast_evaluations

        return {
            "enabled": True,
            "history_path": str(resolved_history_path),
            "horizon": resolved_horizon,
            "max_context": resolved_max_context,
            "metric": "all" if forecast_all_metrics else requested_metric,
            "results": payload_results,
            "errors": errors,
            "attempted_metric_count": attempted_metric_count,
            "error_count": len(errors),
            "success_rate": len(payload_results) / float(attempted_metric_count) if attempted_metric_count else 0.0,
            **summarize_forecast_evaluations(payload_results),
        }
