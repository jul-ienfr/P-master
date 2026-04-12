"""Local REST API used for the desktop suite and the existing React frontend."""

from __future__ import annotations

from datetime import datetime, timezone
import io

try:  # pragma: no cover - optional runtime dependency
    from fastapi import FastAPI, Response
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:  # pragma: no cover - lightweight fallback for tests and inspection
    from types import SimpleNamespace

    class Response:  # type: ignore[override]
        def __init__(self, content=b"", media_type: str | None = None):
            self.content = content
            self.media_type = media_type

    class CORSMiddleware:  # type: ignore[override]
        pass

    class FastAPI:  # type: ignore[override]
        def __init__(self, title: str | None = None, version: str | None = None):
            self.title = title
            self.version = version
            self.routes = []
            self.state = SimpleNamespace()

        def add_middleware(self, *args, **kwargs):
            return None

        def get(self, path: str):
            def decorator(func):
                self.routes.append(SimpleNamespace(path=path, endpoint=func, methods={"GET"}))
                return func

            return decorator

        def post(self, path: str):
            def decorator(func):
                self.routes.append(SimpleNamespace(path=path, endpoint=func, methods={"POST"}))
                return func

            return decorator

try:  # pragma: no cover - optional when only importing the module in tests
    import uvicorn
except ImportError:  # pragma: no cover - local API can still be inspected without a server
    uvicorn = None

from poker.decisionmaker.v2_contracts import (
    build_config_lab_surface_payload,
    build_health_payload,
    build_mock_bot_cockpit_payload,
    build_mock_config_payload,
    build_mock_llm_assist_payload,
    build_mock_replay_record,
    build_mock_solve_response_payload,
    build_replay_analytics_surface_payload,
    build_runtime_snapshot,
    build_version_payload,
)
from poker.decisionmaker.decision_service import CanonicalDecisionService
from poker.decisionmaker.oracle_backends import detect_oracle_backends
from poker.decisionmaker.tree_presets import preset_catalog_payload
from research.automation import build_automation_payload
from research.calibration import benchmark_range_model_versions, fit_calibration_profile
from research.challengers import challenger_payload
from research.opponent_datasets import build_opponent_dataset
from research.postflop_vendor import summarize_postflop_bundle
from research.rl_lab import build_rl_lab_payload
from research.self_play import (
    BestAlternativePolicy,
    ReplayDecisionPolicy,
    estimate_local_best_response,
    run_head_to_head,
)
from research.validation import build_validation_lab_payload

try:  # pragma: no cover - optional legacy runtime dependency
    from poker.tools.helper import COMPUTER_NAME
except Exception:  # pragma: no cover - keep the local API importable in minimal environments
    COMPUTER_NAME = "unknown"

try:  # pragma: no cover - optional legacy runtime dependency
    from poker.tools.screen_operations import take_screenshot
except Exception:  # pragma: no cover - keep the local API importable in minimal environments
    def take_screenshot(*args, **kwargs):
        raise RuntimeError("screenshot capture is unavailable in this environment")

APP_NAME = "poker-restapi-local"
_CORS_CONFIGURED = False
_DECISION_SERVICE = CanonicalDecisionService()

app = FastAPI(title="PokerMaster Local API", version="v2")


def _configure_cors_once() -> None:
    global _CORS_CONFIGURED
    if _CORS_CONFIGURED:
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://deepermind-pokerbot.com",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _CORS_CONFIGURED = True


_configure_cors_once()


def _build_refresh_payload(payload: dict) -> dict:
    return {
        "status": "ok",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "heartbeat_ms": 0,
        "payload": payload,
    }


def build_solver_inspection_payload() -> dict:
    payload = _DECISION_SERVICE.inspection_payload(limit=24)
    payload["kind"] = "solver_inspection"
    payload["source"] = "runtime"
    payload["refreshedAt"] = datetime.now(timezone.utc).isoformat()
    return payload


def build_research_lab_payload() -> dict:
    record = build_mock_replay_record()
    records = [record]
    calibration = fit_calibration_profile(records)
    promotions = benchmark_range_model_versions(records)
    head_to_head = run_head_to_head(
        records,
        baseline=ReplayDecisionPolicy(name="baseline_trace"),
        challenger=BestAlternativePolicy(name="best_alt"),
    )
    best_response = estimate_local_best_response(
        records,
        policy=ReplayDecisionPolicy(name="baseline_trace"),
    )
    return {
        "kind": "research_lab",
        "source": "runtime",
        "refreshedAt": datetime.now(timezone.utc).isoformat(),
        "preset_catalog": preset_catalog_payload(),
        "challengers": challenger_payload(record.spot),
        "calibration": calibration,
        "range_model_benchmarks": promotions,
        "head_to_head": head_to_head,
        "local_best_response": best_response,
        "opponent_dataset": build_opponent_dataset(records),
        "postflop_bridge": summarize_postflop_bundle(),
        "validation": build_validation_lab_payload(records),
        "rl_lab": build_rl_lab_payload(records),
        "automation": build_automation_payload(),
        "oracles": [
            {
                "name": entry.name,
                "available": entry.available,
                "reason": entry.reason,
                "metadata": entry.metadata,
            }
            for entry in detect_oracle_backends()
        ],
    }


def build_config_lab_payload() -> dict:
    payload = build_config_lab_surface_payload(
        service_name=APP_NAME,
        endpoint="/config-lab/payload",
    )
    payload["solver_inspection"] = build_solver_inspection_payload()
    payload["research"] = build_research_lab_payload()
    payload["solver"]["availablePresetIds"] = [
        item["preset_id"] for item in payload["solver_inspection"]["preset_catalog"]
    ]
    return payload


def build_config_lab_refresh_payload() -> dict:
    payload = build_config_lab_surface_payload(
        service_name=APP_NAME,
        endpoint="/config-lab/refresh",
    )
    payload["solver_inspection"] = build_solver_inspection_payload()
    payload["research"] = build_research_lab_payload()
    payload["solver"]["availablePresetIds"] = [
        item["preset_id"] for item in payload["solver_inspection"]["preset_catalog"]
    ]
    return payload


@app.get("/health")
async def get_health():
    return build_health_payload()


@app.get("/version")
async def get_version():
    return build_version_payload()


@app.get("/mock-config")
async def get_mock_config():
    return build_mock_config_payload()


@app.post("/v2/llm/assist")
async def post_llm_assist(request: dict | None = None):
    return build_mock_llm_assist_payload(request)


@app.post("/v2/solve")
async def post_v2_solve(request: dict | None = None):
    return build_mock_solve_response_payload(request)


@app.post("/solve")
async def post_solve_legacy(request: dict | None = None):
    return build_mock_solve_response_payload(request)


@app.get("/runtime-snapshot")
async def get_runtime_snapshot():
    return build_runtime_snapshot(service_name=APP_NAME)


@app.get("/solver-studio/preset-catalog")
async def get_solver_preset_catalog():
    return build_solver_inspection_payload()


@app.get("/solver-studio/cache-index")
async def get_solver_cache_index():
    return build_solver_inspection_payload()


@app.get("/bot-cockpit/payload")
async def get_bot_cockpit_payload():
    return build_mock_bot_cockpit_payload(
        service_name=APP_NAME, endpoint="/bot-cockpit/payload"
    )


@app.get("/bot-cockpit/refresh")
async def refresh_bot_cockpit_payload():
    return _build_refresh_payload(
        build_mock_bot_cockpit_payload(
            service_name=APP_NAME, endpoint="/bot-cockpit/refresh"
        )
    )


@app.get("/replay-analytics/payload")
async def get_replay_analytics_payload():
    return build_replay_analytics_surface_payload(
        service_name=APP_NAME, endpoint="/replay-analytics/payload"
    )


@app.get("/replay-analytics/refresh")
async def refresh_replay_analytics_payload():
    return _build_refresh_payload(
        build_replay_analytics_surface_payload(
            service_name=APP_NAME, endpoint="/replay-analytics/refresh"
        )
    )


@app.get("/config-lab/payload")
async def get_config_lab_payload():
    return build_config_lab_payload()


@app.get("/config-lab/refresh")
async def refresh_config_lab_payload():
    return _build_refresh_payload(build_config_lab_refresh_payload())


@app.get("/research/payload")
async def get_research_payload():
    return build_research_lab_payload()


@app.get("/research/refresh")
async def refresh_research_payload():
    return _build_refresh_payload(build_research_lab_payload())


@app.get("/get_computer_name")
async def get_computer_name():
    return {"computer_name": COMPUTER_NAME}


@app.get("/take_screenshot")
async def get_screenshot_result():
    screenshot = take_screenshot()
    image_bytes_io = io.BytesIO()
    screenshot.save(image_bytes_io, format="PNG")
    return Response(content=image_bytes_io.getvalue(), media_type="image/png")


def local_restapi():
    """Launch the local API server."""
    _configure_cors_once()
    if uvicorn is None:
        raise RuntimeError("uvicorn is required to run the local REST API server")
    uvicorn.run(app, host="127.0.0.1", port=8005)
