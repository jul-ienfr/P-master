"""Tests des endpoints /debug/* de BotAPI (status, health-detail, log-tail)."""

import asyncio
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if "aiohttp_cors" not in sys.modules:

    class _StubResourceOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _StubCors:
        def add(self, route):
            return route

    def _stub_setup(app, defaults=None):
        return _StubCors()

    sys.modules["aiohttp_cors"] = types.SimpleNamespace(
        setup=_stub_setup,
        ResourceOptions=_StubResourceOptions,
    )


from src.api.server import BotAPI


def run(coro):
    return asyncio.run(coro)


class StubHITL:
    def __init__(self):
        self.annotations_count = 0
        self.target_dataset_size = 10
        self.is_waiting_for_human = False
        self.current_issue = None

    def check_convergence(self):
        return False


class FakeQueryRequest:
    def __init__(self, query=None):
        self.query = query or {}


def _payload(response):
    return json.loads(response.text)


def _check_shapes(payload):
    checks = payload["checks"]
    assert isinstance(checks, list) and checks
    for check in checks:
        assert set(check) == {"name", "ok", "detail"}
        assert isinstance(check["name"], str) and check["name"]
        assert isinstance(check["ok"], bool)
        assert isinstance(check["detail"], str)


def test_debug_status_returns_python_uptime_subsystems():
    async def scenario():
        api = BotAPI(StubHITL(), runtime_status_provider=lambda: {})
        response = await api.handle_debug_status(FakeQueryRequest())
        payload = _payload(response)

        assert response.status == 200
        assert payload["ok"] is True
        assert payload["python_version"] == sys.version.split()[0]
        assert payload["python_version_info"] == list(sys.version_info[:3])
        assert payload["python_executable"] == sys.executable
        assert payload["uptime_seconds"] >= 0.0
        assert payload["started_at"]
        assert payload["refreshed_at"]

        subsystems = payload["subsystems"]
        assert "solver_native_bridge" in subsystems
        assert "vision" in subsystems
        for subsystem in subsystems.values():
            assert isinstance(subsystem["ok"], bool)
            assert isinstance(subsystem["detail"], str) and subsystem["detail"]

        assert "config_snapshot" in payload

    run(scenario())


def test_debug_health_detail_lists_named_checks_with_flags():
    async def scenario():
        api = BotAPI(
            StubHITL(),
            runtime_status_provider=lambda: {
                "health": {"solver": {"status": "healthy"}},
                "last_success_at": "2026-04-14T10:00:00Z",
            },
        )
        response = await api.handle_debug_health_detail(FakeQueryRequest())
        payload = _payload(response)

        assert response.status == 200
        assert isinstance(payload["ok"], bool)
        _check_shapes(payload)
        names = {check["name"] for check in payload["checks"]}
        assert {"hitl_module", "runtime_status_provider", "runtime_snapshot_cache"} <= names
        assert payload["health"] == {"solver": {"status": "healthy"}}
        assert payload["last_success_at"] == "2026-04-14T10:00:00Z"

    run(scenario())


def test_debug_health_detail_flags_missing_runtime_provider():
    async def scenario():
        api = BotAPI(StubHITL())
        response = await api.handle_debug_health_detail(FakeQueryRequest())
        payload = _payload(response)

        assert response.status == 200
        _check_shapes(payload)
        provider_check = next(
            check for check in payload["checks"] if check["name"] == "runtime_status_provider"
        )
        assert provider_check["ok"] is False
        assert "no runtime status provider" in provider_check["detail"]
        assert payload["ok"] is False

    run(scenario())


def test_debug_log_tail_returns_last_lines(tmp_path):
    async def scenario():
        log_file = tmp_path / "app.log"
        log_file.write_text(
            "\n".join(f"line-{index}" for index in range(1, 21)) + "\n",
            encoding="utf-8",
        )
        api = BotAPI(StubHITL())
        api.debug_log_path = str(log_file)

        response = await api.handle_debug_log_tail(FakeQueryRequest({"n": "5"}))
        payload = _payload(response)

        assert response.status == 200
        assert payload["ok"] is True
        assert payload["n"] == 5
        assert payload["count"] == 5
        assert payload["lines"] == [f"line-{index}" for index in range(16, 21)]

    run(scenario())


def test_debug_log_tail_clamps_n_to_1000(tmp_path):
    async def scenario():
        log_file = tmp_path / "app.log"
        log_file.write_text("a\nb\nc\n", encoding="utf-8")
        api = BotAPI(StubHITL())
        api.debug_log_path = str(log_file)

        response = await api.handle_debug_log_tail(FakeQueryRequest({"n": "99999"}))
        payload = _payload(response)

        assert response.status == 200
        assert payload["n"] == 1000
        assert payload["lines"] == ["a", "b", "c"]

        default_response = await api.handle_debug_log_tail(FakeQueryRequest({"n": "abc"}))
        default_payload = _payload(default_response)
        assert default_payload["n"] == 100

    run(scenario())


def test_debug_log_tail_returns_404_without_log(tmp_path, monkeypatch):
    async def scenario():
        api = BotAPI(StubHITL())
        monkeypatch.setattr(BotAPI, "_discover_log_path", lambda self: None)

        response = await api.handle_debug_log_tail(FakeQueryRequest())
        payload = _payload(response)

        assert response.status == 404
        assert payload["ok"] is False
        assert "log" in payload["error"].lower()

        # Chemin explicitement configuré mais inexistant : 404 également.
        monkeypatch.undo()
        api.debug_log_path = str(tmp_path / "missing.log")
        missing_response = await api.handle_debug_log_tail(FakeQueryRequest())
        missing_payload = _payload(missing_response)
        assert missing_response.status == 404
        assert missing_payload["ok"] is False

    run(scenario())
