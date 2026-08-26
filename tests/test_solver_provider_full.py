"""Tests du SolverProvider : chaînes native -> HTTP -> fallback."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.solver.provider import SolverProvider


class RecordingHealth:
    def __init__(self):
        self.events = []

    def record_success(self, component):
        self.events.append(("success", component))

    def record_error(self, component, reason, **kwargs):
        self.events.append(("error", reason))


def make_provider(**kwargs):
    health = RecordingHealth()
    provider = SolverProvider(health_monitor=health, **kwargs)
    return provider, health


GOOD_PAYLOAD = {
    "chosen_action": "BET",
    "actions": [{"action": "BET", "freq": 0.8}],
    "hero_ev": 2.5,
}


class NativeBackend:
    backend_name = "rust_native"

    @staticmethod
    def solve_spot_v2(**payload):
        return dict(GOOD_PAYLOAD)


def test_solve_with_native_backend_success():
    provider, health = make_provider(native_backend=NativeBackend())
    result = provider.solve_spot_v2(hero_hand="AhKd")
    assert result["chosen_action"] == "BET"
    assert result["backend"] == "rust_native"
    assert result["fallback_used"] is False
    assert provider.active_backend() == "rust_native"
    assert ("success", "solver") in health.events


def test_native_backend_without_module_returns_fallback():
    provider, _health = make_provider(native_backend=None)
    result = provider.solve_spot_v2()
    assert result["fallback_used"] is True
    assert provider.fallback_reason()


def test_native_backend_missing_entrypoint_falls_back():
    provider, _health = make_provider(native_backend=SimpleNamespace(nothing=1))
    result = provider.solve_spot_v2()
    assert result["fallback_used"] is True


def test_normalize_response_rejects_payload_without_action():
    provider = SolverProvider()
    assert provider._normalize_response(None, backend="x") is None
    assert provider._normalize_response({"no_action": 1}, backend="x") is None
    normalized = provider._normalize_response({"chosen_action": "FOLD"}, backend="x")
    assert normalized["backend"] == "x"
    # objet avec to_dict()
    obj = SimpleNamespace(to_dict=lambda: {"chosen_action": "CALL"})
    assert provider._normalize_response(obj, backend="y")["chosen_action"] == "CALL"


def test_http_fallback_success_adds_transport_metadata(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url})
        return SimpleNamespace(status_code=200, json=lambda: dict(GOOD_PAYLOAD))

    calls = []
    provider, health = make_provider(
        http_url="http://127.0.0.1:9/solve",
        request_post=fake_post,
    )
    result = provider.solve_spot_v2()
    assert result["chosen_action"] == "BET"
    assert result["backend"] == "gto_server"
    assert result["metadata"]["transport"] == "local_http"
    assert result["backend_details"]["url"].endswith("/solve")
    assert ("success", "solver") in health.events


def test_http_error_status_then_fallback():
    def fake_post(url, json=None, timeout=None):
        return SimpleNamespace(status_code=500)

    provider, health = make_provider(http_url="http://127.0.0.1:9", request_post=fake_post)
    result = provider.solve_spot_v2()
    assert result["fallback_used"] is True
    assert any(event[0] == "error" for event in health.events)


def test_http_exception_then_fallback():
    def fake_post(url, json=None, timeout=None):
        raise ConnectionError("down")

    provider, _health = make_provider(http_url="http://127.0.0.1:9", request_post=fake_post)
    result = provider.solve_spot_v2()
    assert result["fallback_used"] is True


def test_fallback_response_shape_and_reasons():
    provider = SolverProvider()
    fallback = provider._fallback_response("test_reason", native_reason="n", http_reason="h")
    assert fallback["fallback_reason"] == "test_reason"
    assert fallback["chosen_action"] == ""
    assert fallback["exploitability"] == 1.0
    assert fallback["metadata"]["native_reason"] == "n"
    assert fallback["metadata"]["http_reason"] == "h"


def test_no_backends_at_all_yields_clean_fallback():
    provider, _health = make_provider(http_url="")
    result = provider.solve_spot_v2()
    assert result["fallback_used"] is True
    assert provider.active_backend() == "fallback"
    assert provider.last_success_at() is None
