"""Tests des routes runtime : observation export, operator-control, timesfm."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.routes_runtime import RuntimeRoutesMixin


class FakeQueryRequest:
    def __init__(self, query=None, payload=None):
        self.query = query or {}
        self.payload = payload

    async def json(self):
        return self.payload


async def _fake_snapshot_payload(force=False):
    return {"state": "live", "forced": force}


class Api(RuntimeRoutesMixin):
    def __init__(self, **overrides):
        self.hitl = None
        self.runtime_status_provider = None
        self.runtime_operator_handler = None
        self.runtime_observation_provider = None
        self.runtime_observation_exporter = None
        self.runtime_timesfm_provider = None
        self.runtime_timesfm_calls = []
        self._runtime_snapshot_cache = None

        def invalidate():
            self.invalidated = True

        async def snapshot_payload(force=False):
            return {"state": "live", "forced": force}

        def observation_payload(limit=5):
            return {"observation": True}

        self._invalidate_runtime_snapshot_cache = invalidate
        self._build_runtime_snapshot_payload_async = snapshot_payload
        self._build_runtime_observation_payload = observation_payload
        for key, value in overrides.items():
            setattr(self, key, value)

    def _now_iso(self):
        return "2026-04-14T12:00:00Z"

    @staticmethod
    def _parse_limit(raw_limit, default=10, maximum=50):
        return max(1, min(int(raw_limit) if raw_limit else default, maximum))


def run(coro):
    return asyncio.run(coro)


def test_handle_runtime_observation_returns_payload():
    api = Api()
    response = run(api.handle_runtime_observation(FakeQueryRequest({"limit": "3"})))
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["observation"] is True
    assert payload["refreshed_at"] == "2026-04-14T12:00:00Z"


def test_handle_runtime_observation_export_requires_exporter():
    api = Api(runtime_observation_exporter=None)
    response = run(api.handle_runtime_observation_export(FakeQueryRequest()))
    assert response.status == 503


def test_handle_runtime_observation_export_happy_path():
    exporter_calls = []

    def exporter(player_limit, hand_limit):
        exporter_calls.append((player_limit, hand_limit))
        return {"hands": []}

    api = Api(runtime_observation_exporter=exporter)
    response = run(api.handle_runtime_observation_export(FakeQueryRequest({"players": "7", "hands": "9"})))
    assert response.status == 200
    assert exporter_calls == [(7, 9)]
    assert json.loads(response.text) == {"hands": []}


def test_handle_operator_control_unavailable():
    api = Api(runtime_operator_handler=None)
    response = run(api.handle_operator_control(FakeQueryRequest(payload={"paused": True})))
    assert response.status == 503


def test_handle_operator_control_invalid_json():
    class BadRequest:
        query = {}

        async def json(self):
            raise ValueError("bad")

    handled = []
    api = Api(runtime_operator_handler=lambda patch: handled.append(patch))
    response = run(api.handle_operator_control(BadRequest()))
    assert response.status == 400
    assert handled == []


def test_handle_operator_control_rejects_non_object_payload():
    handled = []
    api = Api(runtime_operator_handler=lambda patch: handled.append(patch))
    response = run(api.handle_operator_control(FakeQueryRequest(payload=[1, 2])))
    assert response.status == 400
    assert handled == []


def test_handle_operator_control_happy_path_invalidates_cache():
    applied = []
    api = Api(
        runtime_operator_handler=lambda patch: applied.append(patch),
    )
    response = run(
        api.handle_operator_control(
            FakeQueryRequest(payload={"operator": {"paused": True}})
        )
    )
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["state"] == "live"
    assert applied == [{"paused": True}]
    assert api.invalidated is True


def test_handle_timesfm_forecast_disabled():
    api = Api(runtime_timesfm_provider=None)
    response = run(api.handle_runtime_timesfm_forecast(FakeQueryRequest()))
    assert response.status == 404


def test_handle_timesfm_forecast_happy_path():
    calls = []

    def provider(metric=None, horizon=None, max_context=None, history_path=None):
        calls.append({"metric": metric, "horizon": horizon})
        return {"metric": metric or "all"}

    api = Api(runtime_timesfm_provider=provider)
    response = run(
        api.handle_runtime_timesfm_forecast(FakeQueryRequest({"metric": "block_rate", "horizon": "6"}))
    )
    assert response.status == 200
    payload = json.loads(response.text)
    assert payload["metric"] == "block_rate"
    assert payload["refreshed_at"] == "2026-04-14T12:00:00Z"
    assert calls == [{"metric": "block_rate", "horizon": 6}]


def test_handle_get_status_waiting_for_human():
    class Hitl:
        annotations_count = 2
        target_dataset_size = 8
        is_waiting_for_human = True
        current_issue = {
            "type": "vision",
            "reason": "low_conf",
            "image_base64": "ZmFrZQ==",
            "width": 320,
            "height": 200,
        }

        def check_convergence(self):
            return False

    api = Api(hitl=Hitl(), runtime_status_provider=None)
    response = run(api.handle_get_status(FakeQueryRequest()))
    payload = json.loads(response.text)
    assert payload["status"] == "waiting_for_human"
    assert payload["issue"]["type"] == "vision"


def test_handle_get_status_with_runtime_error(monkeypatch):
    class Hitl:
        annotations_count = 0
        target_dataset_size = 5
        is_waiting_for_human = False
        current_issue = None

        def check_convergence(self):
            return False

    def bad_provider():
        raise RuntimeError("down")

    monkeypatch.setattr(asyncio, "to_thread", lambda fn, *a, **k: _raise_later(fn))
    api = Api(hitl=Hitl(), runtime_status_provider=bad_provider)
    response = run(api.handle_get_status(FakeQueryRequest()))
    payload = json.loads(response.text)
    assert payload["gate"]["allowed"] is False
    assert payload["degraded_reasons"] == ["api:runtime_status_error"]


async def _raise_later(fn):
    raise RuntimeError("down")
