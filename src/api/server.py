import asyncio
import logging
from collections.abc import Callable

from aiohttp import web

try:
    import aiohttp_cors
except ImportError:
    aiohttp_cors = None
try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

from src.api.routes_history import HistoryRoutesMixin
from src.api.routes_resolve import ResolveRoutesMixin
from src.api.routes_runtime import RuntimeRoutesMixin
from src.api.snapshots import SnapshotPayloadMixin

logger = logging.getLogger("BotAPI")


class BotAPI(
    SnapshotPayloadMixin,
    RuntimeRoutesMixin,
    HistoryRoutesMixin,
    ResolveRoutesMixin,
):
    def __init__(
        self,
        hitl_module,
        runtime_status_provider: Callable[[], dict] | None = None,
        runtime_operator_handler: Callable[[dict], dict] | None = None,
        runtime_observation_provider: Callable[[], dict] | None = None,
        runtime_observation_exporter: Callable[..., dict] | None = None,
        runtime_timesfm_provider: Callable[..., dict] | None = None,
        host: str = "127.0.0.1",
        port: int = 8005,
        runtime_history_store=None,
    ):
        """
        Serveur API asynchrone (aiohttp) permettant à l'interface React/Tauri
        de communiquer avec le bot Python en temps réel.
        """
        self.hitl = hitl_module
        self.runtime_status_provider = runtime_status_provider
        self.runtime_operator_handler = runtime_operator_handler
        self.runtime_observation_provider = runtime_observation_provider
        self.runtime_observation_exporter = runtime_observation_exporter
        self.runtime_timesfm_provider = runtime_timesfm_provider
        self.runtime_history_store = runtime_history_store
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._runtime_snapshot_cache: dict | None = None
        self._runtime_snapshot_cached_at: float = 0.0
        self._runtime_snapshot_ttl_seconds = 0.9
        self._runtime_snapshot_lock = asyncio.Lock()

        self._setup_routes()
        self._setup_cors()

    def _setup_routes(self):
        self.app.router.add_get("/api/hitl/status", self.handle_get_status)
        self.app.router.add_post("/api/hitl/resolve", self.handle_resolve)
        self.app.router.add_get("/runtime-snapshot", self.handle_runtime_snapshot)
        self.app.router.add_get("/runtime-observation", self.handle_runtime_observation)
        self.app.router.add_get(
            "/runtime-observation/export", self.handle_runtime_observation_export
        )
        self.app.router.add_get("/runtime-forecast/timesfm", self.handle_runtime_timesfm_forecast)
        self.app.router.add_get("/runtime-history", self.handle_runtime_history)
        self.app.router.add_get("/runtime-history/export", self.handle_runtime_history_export)
        self.app.router.add_post("/runtime-history/import", self.handle_runtime_history_import)
        self.app.router.add_get("/bot-cockpit/payload", self.handle_runtime_snapshot)
        self.app.router.add_get("/bot-cockpit/refresh", self.handle_runtime_snapshot)
        self.app.router.add_post("/bot-cockpit/operator", self.handle_operator_control)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_limit(raw_limit: str | None, default: int = 10, maximum: int = 50) -> int:
        try:
            limit = int(raw_limit) if raw_limit is not None else default
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, maximum))

    @staticmethod
    def _slice_history_entries(entries, limit: int) -> list:
        return list(entries[:limit]) if isinstance(entries, list) else []

    def _setup_cors(self):
        if aiohttp_cors is None:
            logger.warning("aiohttp_cors n'est pas installe. Configuration CORS desactivee.")
            return

        allowed_origins = {
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8765",
            "http://127.0.0.1:8765",
            "http://localhost:8005",
            "http://127.0.0.1:8005",
            "http://localhost:8006",
            "http://127.0.0.1:8006",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        }
        cors = aiohttp_cors.setup(
            self.app,
            defaults={
                origin: aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                )
                for origin in allowed_origins
            },
        )
        for route in list(self.app.router.routes()):
            cors.add(route)

    async def start(self):
        """Démarre le serveur API en arrière-plan."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"API Locale démarrée sur http://{self.host}:{self.port}")

    async def stop(self):
        """Arrête le serveur proprement."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("API Locale arrêtée.")
