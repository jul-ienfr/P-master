import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from research.timesfm_adapter import (
    build_forecast_evaluation,
    build_last_value_baseline,
    build_moving_average_baseline,
    forecast_runtime_metrics,
    forecast_runtime_metric,
    forecast_series,
    summarize_forecast_evaluations,
)
from research.timesfm_runtime_dataset import RuntimeMetricSeries, build_holdout_split


class _FakeModel:
    def __init__(self, point_forecast=None, quantile_forecast=None):
        self.compiled_config = None
        self.calls = []
        self.point_forecast = point_forecast or [0.55, 0.65]
        self.quantile_forecast = quantile_forecast or [[0.55], [0.65]]

    def compile(self, config):
        self.compiled_config = config

    def forecast(self, *, horizon, inputs):
        self.calls.append({"horizon": horizon, "inputs": inputs})
        return [self.point_forecast], [self.quantile_forecast]


def test_forecast_runtime_metric_uses_adapter_model_and_returns_baselines():
    series = RuntimeMetricSeries(
        name="fallback_rate",
        timestamps=[
            "2026-04-17T10:00:01Z",
            "2026-04-17T10:00:02Z",
            "2026-04-17T10:00:03Z",
            "2026-04-17T10:00:04Z",
        ],
        values=[0.1, 0.2, 0.3, 0.4],
    )
    split = build_holdout_split(series, horizon=2)
    fake_model = _FakeModel()

    result = forecast_runtime_metric(split, model=fake_model)

    assert result.metric_name == "fallback_rate"
    assert result.horizon == 2
    assert result.point_forecast == [0.55, 0.65]
    assert result.target_values == [0.3, 0.4]
    assert result.last_value_baseline == [0.2, 0.2]
    assert result.moving_average_baseline == [0.15, 0.15]
    assert fake_model.calls == [{"horizon": 2, "inputs": [[0.1, 0.2]]}]
    assert fake_model.compiled_config is not None


def test_build_forecast_evaluation_compares_timesfm_against_baselines():
    series = RuntimeMetricSeries(
        name="fallback_rate",
        timestamps=[
            "2026-04-17T10:00:01Z",
            "2026-04-17T10:00:02Z",
            "2026-04-17T10:00:03Z",
            "2026-04-17T10:00:04Z",
        ],
        values=[0.1, 0.2, 0.3, 0.4],
    )
    result = forecast_runtime_metric(build_holdout_split(series, horizon=2), model=_FakeModel())

    evaluation = build_forecast_evaluation(result)

    assert round(evaluation["mae"]["timesfm"], 6) == 0.25
    assert round(evaluation["relative_mae"]["timesfm"], 6) == round(0.25 / 0.35, 6)
    assert evaluation["best_forecaster"] == "last_value"
    assert evaluation["quantile_range_coverage"] == 0.0
    assert round(evaluation["baseline_comparison"]["last_value"]["absolute_mae_delta"], 6) == -0.1


def test_build_forecast_evaluation_marks_exact_mae_ties_without_timesfm_win():
    series = RuntimeMetricSeries(
        name="fallback_rate",
        timestamps=[
            "2026-04-17T10:00:01Z",
            "2026-04-17T10:00:02Z",
            "2026-04-17T10:00:03Z",
            "2026-04-17T10:00:04Z",
        ],
        values=[0.1, 0.2, 0.3, 0.4],
    )
    result = forecast_runtime_metric(
        build_holdout_split(series, horizon=2),
        model=_FakeModel(point_forecast=[0.2, 0.2]),
    )

    evaluation = build_forecast_evaluation(result)
    summary = summarize_forecast_evaluations({"fallback_rate": evaluation})

    assert evaluation["best_forecaster"] == "tie"
    assert summary["timesfm_win_count"] == 0
    assert summary["timesfm_win_rate"] == 0.0


def test_summarize_forecast_evaluations_reports_timesfm_win_rate_and_average_lift():
    summary = summarize_forecast_evaluations(
        {
            "fallback_rate": {
                "best_forecaster": "timesfm",
                "baseline_comparison": {
                    "last_value": {"relative_improvement": 0.5},
                    "moving_average": {"relative_improvement": 0.25},
                },
            },
            "block_rate": {
                "best_forecaster": "last_value",
                "baseline_comparison": {
                    "last_value": {"relative_improvement": -0.1},
                    "moving_average": {"relative_improvement": 0.0},
                },
            },
        }
    )

    assert summary["metric_count"] == 2
    assert summary["timesfm_win_count"] == 1
    assert summary["timesfm_win_rate"] == 0.5
    assert summary["best_by_metric"] == {"fallback_rate": "timesfm", "block_rate": "last_value"}
    assert summary["average_relative_improvement"] == {"last_value": 0.2, "moving_average": 0.125}


def test_build_last_value_baseline_repeats_the_last_context_point():
    assert build_last_value_baseline([0.2, 0.5, 0.7], horizon=3) == [0.7, 0.7, 0.7]


def test_build_moving_average_baseline_uses_tail_window():
    assert build_moving_average_baseline([0.2, 0.4, 0.6, 0.8], horizon=2, window=2) == [0.7, 0.7]


def test_forecast_series_uses_model_directly_without_runtime_split():
    fake_model = _FakeModel()

    result = forecast_series([0.1, 0.2, 0.3], horizon=2, model=fake_model)

    assert result.context_values == [0.1, 0.2, 0.3]
    assert result.point_forecast == [0.55, 0.65]
    assert result.quantile_forecast == [[0.55], [0.65]]
    assert fake_model.calls == [{"horizon": 2, "inputs": [[0.1, 0.2, 0.3]]}]
    assert fake_model.compiled_config is not None


def test_forecast_runtime_metrics_forecasts_each_series_from_mapping():
    fake_model = _FakeModel()
    series_map = {
        "fallback_rate": RuntimeMetricSeries(
            name="fallback_rate",
            timestamps=[
                "2026-04-17T10:00:01Z",
                "2026-04-17T10:00:02Z",
                "2026-04-17T10:00:03Z",
                "2026-04-17T10:00:04Z",
            ],
            values=[0.1, 0.2, 0.3, 0.4],
        ),
        "block_rate": RuntimeMetricSeries(
            name="block_rate",
            timestamps=[
                "2026-04-17T10:00:01Z",
                "2026-04-17T10:00:02Z",
                "2026-04-17T10:00:03Z",
                "2026-04-17T10:00:04Z",
            ],
            values=[0.4, 0.3, 0.2, 0.1],
        ),
    }

    results = forecast_runtime_metrics(series_map, horizon=2, model=fake_model)

    assert sorted(results) == ["block_rate", "fallback_rate"]
    assert results["fallback_rate"].target_values == [0.3, 0.4]
    assert results["block_rate"].target_values == [0.2, 0.1]
    assert len(fake_model.calls) == 2
