import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from research import run_timesfm_experiment


class _FakeResult:
    def __init__(self, metric_name="fallback_rate"):
        self.metric_name = metric_name
        self.horizon = 2
        self.context_values = [0.1, 0.2]
        self.target_values = [0.3, 0.4]
        self.point_forecast = [0.31, 0.39]
        self.quantile_forecast = [[0.25, 0.35], [0.35, 0.45]]
        self.last_value_baseline = [0.2, 0.2]
        self.moving_average_baseline = [0.15, 0.15]


def test_cli_runner_reports_series_length_and_respects_max_context(tmp_path, monkeypatch, capsys):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:01Z", "fallback_rate": 0.1}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:02Z", "fallback_rate": 0.2}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:03Z", "fallback_rate": 0.3}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:04Z", "fallback_rate": 0.4}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:05Z", "fallback_rate": 0.5}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    calls = []

    def _fake_forecast_runtime_metric(split):
        calls.append(split)
        return _FakeResult(split.metric_name)

    monkeypatch.setattr(run_timesfm_experiment, "forecast_runtime_metric", _fake_forecast_runtime_metric)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_timesfm_experiment.py",
            "--metric",
            "fallback_rate",
            "--horizon",
            "2",
            "--max-context",
            "2",
            "--history-path",
            str(history_path),
            "--output-path",
            str(tmp_path / "results" / "timesfm_summary.json"),
        ],
    )

    exit_code = run_timesfm_experiment.main()

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0].context_values == [0.2, 0.3]
    assert calls[0].target_values == [0.4, 0.5]

    payload = json.loads(capsys.readouterr().out)
    output_payload = json.loads((tmp_path / "results" / "timesfm_summary.json").read_text(encoding="utf-8"))
    assert output_payload == payload
    assert datetime.fromisoformat(payload["generated_at"]).tzinfo is not None
    assert payload["config"] == {
        "metric": "fallback_rate",
        "horizon": 2,
        "max_context": 2,
        "history_path": str(history_path),
        "output_path": str(tmp_path / "results" / "timesfm_summary.json"),
    }
    assert payload["metric"] == "fallback_rate"
    assert payload["metric_count"] == 1
    assert payload["attempted_metric_count"] == 1
    assert payload["error_count"] == 0
    assert payload["success_rate"] == 1.0
    assert payload["timesfm_win_count"] == 1
    assert payload["timesfm_win_rate"] == 1.0
    assert payload["best_by_metric"] == {"fallback_rate": "timesfm"}
    assert payload["series_length"] == 4
    assert payload["context_length"] == 2
    assert payload["horizon"] == 2
    assert payload["best_forecaster"] == "timesfm"
    assert payload["quantile_range_coverage"] == 1.0
    assert round(payload["mae"]["timesfm"], 6) == 0.01
    assert round(payload["relative_mae"]["timesfm"], 6) == round(0.01 / 0.35, 6)
    assert round(payload["baseline_comparison"]["last_value"]["absolute_mae_delta"], 6) == 0.14
    assert round(payload["baseline_comparison"]["last_value"]["relative_improvement"], 6) == round(14 / 15, 6)
    assert round(payload["average_relative_improvement"]["last_value"], 6) == round(14 / 15, 6)


def test_cli_runner_can_report_all_available_metrics(tmp_path, monkeypatch, capsys):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:01Z", "fallback_rate": 0.1, "block_rate": 0.4}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:02Z", "fallback_rate": 0.2, "block_rate": 0.3}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:03Z", "fallback_rate": 0.3, "block_rate": 0.2}',
                '{"stream": "metrics", "timestamp": "2026-04-17T10:00:04Z", "fallback_rate": 0.4, "block_rate": 0.1}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    calls = []

    def _fake_forecast_runtime_metric(split):
        calls.append(split)
        return _FakeResult(split.metric_name)

    monkeypatch.setattr(run_timesfm_experiment, "forecast_runtime_metric", _fake_forecast_runtime_metric)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_timesfm_experiment.py",
            "--metric",
            "all",
            "--horizon",
            "2",
            "--history-path",
            str(history_path),
        ],
    )

    exit_code = run_timesfm_experiment.main()

    assert exit_code == 0
    assert [call.metric_name for call in calls] == ["fallback_rate", "block_rate"]

    payload = json.loads(capsys.readouterr().out)
    assert payload["metric"] == "all"
    assert payload["config"] == {
        "metric": "all",
        "horizon": 2,
        "max_context": None,
        "history_path": str(history_path),
        "output_path": None,
    }
    assert payload["metric_count"] == 2
    assert payload["attempted_metric_count"] == 4
    assert payload["error_count"] == 2
    assert payload["success_rate"] == 0.5
    assert payload["timesfm_win_count"] == 2
    assert payload["timesfm_win_rate"] == 1.0
    assert sorted(payload["errors"]) == ["decision_rate", "rolling_latency_ms"]
    assert sorted(payload["results"]) == ["block_rate", "fallback_rate"]
    assert payload["results"]["block_rate"]["metric"] == "block_rate"
    assert payload["best_by_metric"] == {"fallback_rate": "timesfm", "block_rate": "timesfm"}
    assert round(payload["average_relative_improvement"]["last_value"], 6) == round(14 / 15, 6)


def test_cli_runner_reports_empty_all_metrics_as_errors(tmp_path, monkeypatch, capsys):
    history_path = tmp_path / "runtime_history.jsonl"
    history_path.write_text(
        '{"stream": "events", "timestamp": "2026-04-17T10:00:01Z", "message": "boot"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_timesfm_experiment.py",
            "--metric",
            "all",
            "--horizon",
            "2",
            "--history-path",
            str(history_path),
        ],
    )

    exit_code = run_timesfm_experiment.main()

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["metric"] == "all"
    assert payload["metric_count"] == 0
    assert payload["attempted_metric_count"] == 4
    assert payload["error_count"] == 4
    assert payload["success_rate"] == 0.0
    assert payload["timesfm_win_count"] == 0
    assert payload["timesfm_win_rate"] == 0.0
    assert sorted(payload["errors"]) == ["block_rate", "decision_rate", "fallback_rate", "rolling_latency_ms"]
