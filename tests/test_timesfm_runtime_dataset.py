import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from research.timesfm_runtime_dataset import (
    RuntimeMetricSeries,
    build_holdout_split,
    load_runtime_metric_series_map,
)


def test_load_runtime_metric_series_map_extracts_known_metrics_in_timestamp_order(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                '{"stream": "events", "timestamp": "2026-04-17T10:00:00Z", "message": "boot"}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:02Z", "fallback_rate": 0.3, "block_rate": 0.2, "rolling_latency_ms": 180.0, "decision_rate": 4.0}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:01Z", "fallback_rate": 0.1, "block_rate": 0.05, "rolling_latency_ms": 120.0, "decision_rate": 2.0}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:03Z", "fallback_rate": 0.5, "block_rate": 0.4, "rolling_latency_ms": 240.0, "decision_rate": 6.0}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    series_map = load_runtime_metric_series_map(history_path)

    assert sorted(series_map) == ["block_rate", "decision_rate", "fallback_rate", "rolling_latency_ms"]
    assert series_map["fallback_rate"].timestamps == [
        "2026-04-17T10:00:01Z",
        "2026-04-17T10:00:02Z",
        "2026-04-17T10:00:03Z",
    ]
    assert series_map["fallback_rate"].values == [0.1, 0.3, 0.5]
    assert series_map["rolling_latency_ms"].values == [120.0, 180.0, 240.0]


def test_load_runtime_metric_series_map_skips_invalid_metric_values(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:01Z", "fallback_rate": 0.1}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:02Z", "fallback_rate": "bad"}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:03Z", "fallback_rate": null}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:04Z", "fallback_rate": 0.4}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    series_map = load_runtime_metric_series_map(history_path, metric_names=("fallback_rate",))

    assert series_map["fallback_rate"].timestamps == [
        "2026-04-17T10:00:01Z",
        "2026-04-17T10:00:04Z",
    ]
    assert series_map["fallback_rate"].values == [0.1, 0.4]


def test_load_runtime_metric_series_map_skips_non_finite_metric_values(tmp_path):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:01Z", "fallback_rate": 0.1}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:02Z", "fallback_rate": NaN}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:03Z", "fallback_rate": Infinity}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:04Z", "fallback_rate": -Infinity}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:05Z", "fallback_rate": 0.4}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    series_map = load_runtime_metric_series_map(history_path, metric_names=("fallback_rate",))

    assert series_map["fallback_rate"].timestamps == [
        "2026-04-17T10:00:01Z",
        "2026-04-17T10:00:05Z",
    ]
    assert series_map["fallback_rate"].values == [0.1, 0.4]


def test_build_holdout_split_returns_context_and_expected_target_tail():
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

    assert split.metric_name == "fallback_rate"
    assert split.context_values == [0.1, 0.2]
    assert split.target_values == [0.3, 0.4]
    assert split.context_timestamps == [
        "2026-04-17T10:00:01Z",
        "2026-04-17T10:00:02Z",
    ]
    assert split.target_timestamps == [
        "2026-04-17T10:00:03Z",
        "2026-04-17T10:00:04Z",
    ]


def test_build_holdout_split_rejects_series_shorter_than_context_plus_horizon():
    series = RuntimeMetricSeries(
        name="fallback_rate",
        timestamps=["2026-04-17T10:00:01Z", "2026-04-17T10:00:02Z"],
        values=[0.1, 0.2],
    )

    try:
        build_holdout_split(series, horizon=2)
    except ValueError as exc:
        assert "at least" in str(exc)
    else:
        raise AssertionError("Expected build_holdout_split to reject too-short series")
