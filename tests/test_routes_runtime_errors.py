"""Tests des branches d'erreur TimesFM (routes runtime)."""
import asyncio
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


class Api(RuntimeRoutesMixin):
    def __init__(self, provider=None):
        self.runtime_timesfm_provider = provider

    def _now_iso(self):
        return "2026-04-14T12:00:00Z"


def run(coro):
    return asyncio.run(coro)


def test_handle_timesfm_forecast_invalid_horizon_returns_400():
    def provider(**kwargs):
        raise ValueError("horizon doit être >= 1")

    api = Api(provider=provider)
    response = run(api.handle_runtime_timesfm_forecast(FakeQueryRequest({"metric": "block_rate"})))
    assert response.status == 400


def test_handle_timesfm_forecast_unavailable_returns_503():
    def provider(**kwargs):
        raise RuntimeError("service indisponible")

    api = Api(provider=provider)
    response = run(api.handle_runtime_timesfm_forecast(FakeQueryRequest()))
    assert response.status == 503


def test_handle_timesfm_forecast_unexpected_error_returns_500():
    class Other(Exception):
        pass

    def provider(**kwargs):
        raise Other("kaboom")

    api = Api(provider=provider)
    response = run(api.handle_runtime_timesfm_forecast(FakeQueryRequest()))
    assert response.status == 500
