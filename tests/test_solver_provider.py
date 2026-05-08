from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.solver.provider import SolverProvider


class FakeNativeSolver:
    backend_name = "fake_native"

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def solve_spot_v2(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeHTTPResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_solver_provider_prefers_native_before_http():
    native = FakeNativeSolver(response={"chosen_action": "BET", "backend": "native_solver", "elapsed_ms": 4})
    http_calls = []

    def fake_post(*args, **kwargs):
        http_calls.append((args, kwargs))
        return FakeHTTPResponse({"chosen_action": "CHECK", "backend": "gto_server"})

    provider = SolverProvider(native_backend=native, request_post=fake_post)

    result = provider.solve_spot_v2(hero_range="AsKd", villain_ranges=["QQ+,AK"], board=[], legal_actions=["CHECK", "BET"])

    assert result["chosen_action"] == "BET"
    assert provider.active_backend() == "native_solver"
    assert len(native.calls) == 1
    assert http_calls == []


def test_solver_provider_uses_http_when_native_is_unavailable():
    native = FakeNativeSolver(error=RuntimeError("native_solver_down"))
    http_calls = []

    def fake_post(url, json, timeout):
        http_calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeHTTPResponse({"chosen_action": "CHECK", "backend": "gto_server", "elapsed_ms": 12})

    provider = SolverProvider(native_backend=native, request_post=fake_post)

    result = provider.solve_spot_v2(hero_range="AsKd", villain_ranges=["QQ+,AK"], board=[], legal_actions=["CHECK", "BET"])

    assert result["chosen_action"] == "CHECK"
    assert provider.active_backend() == "gto_server"
    assert provider.fallback_reason() == ""
    assert len(http_calls) == 1
    assert result["metadata"]["transport"] == "local_http"


def test_solver_provider_returns_safe_fallback_when_all_backends_fail():
    native = FakeNativeSolver(error=RuntimeError("native_solver_down"))

    def fake_post(url, json, timeout):
        raise RuntimeError("http_down")

    provider = SolverProvider(native_backend=native, request_post=fake_post)

    result = provider.solve_spot_v2(hero_range="AsKd", villain_ranges=["QQ+,AK"], board=[], legal_actions=["CHECK", "BET"])

    assert result["backend"] == "fallback"
    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "native_solver_down"
    assert result["warnings"] == ["fallback_used"]
    assert result["metadata"]["http_reason"] == "http_solver_unavailable"
