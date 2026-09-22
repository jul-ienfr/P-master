import asyncio
import importlib.util
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

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
        self._started_at = time.time()
        self._started_at_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        # Chemin de log explicite optionnel pour /debug/log-tail (sinon auto-découverte).
        self.debug_log_path: str | None = None

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
        self.app.router.add_get("/debug/status", self.handle_debug_status)
        self.app.router.add_get("/debug/health-detail", self.handle_debug_health_detail)
        self.app.router.add_get("/debug/log-tail", self.handle_debug_log_tail)

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

    # --- Endpoints /debug/* (diag local, best-effort, ne crashe jamais) ---

    @staticmethod
    def _module_availability(module_name: str) -> dict:
        """Best-effort : le module est-il importable, sans jamais lever d'exception."""
        try:
            spec = importlib.util.find_spec(module_name)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"import probe failed: {exc}"}
        if spec is None:
            return {"ok": False, "detail": f"module '{module_name}' not importable"}
        return {"ok": True, "detail": "importable"}

    def _collect_subsystem_status(self) -> dict:
        return {
            # Bridge solveur natif Rust (PyO3, cf. src/bot/decision_maker.py).
            "solver_native_bridge": self._module_availability("postflop_solver_py"),
            "vision": self._module_availability("src.vision.capture"),
        }

    def _config_snapshot(self) -> dict | None:
        """Dump compact de la config si l'instance en porte une (clés + sections)."""
        config = getattr(self, "config", None)
        if not isinstance(config, dict) or not config:
            return None
        snapshot: dict = {"keys": sorted(str(key) for key in config.keys())}
        sections = {
            str(key): sorted(str(inner) for inner in value.keys())
            for key, value in config.items()
            if isinstance(value, dict)
        }
        if sections:
            snapshot["sections"] = sections
        return snapshot

    def _discover_log_path(self) -> str | None:
        """Retrouve le fichier de log applicatif le plus récent (cf. logging de src/main.py)."""
        if self.debug_log_path:
            return self.debug_log_path
        candidates: list[Path] = []
        for logger_name in ("SuperBot2026", "BotAPI", ""):
            for handler in logging.getLogger(logger_name).handlers:
                base_filename = getattr(handler, "baseFilename", None)
                if base_filename:
                    candidates.append(Path(base_filename))
        existing = [path for path in candidates if path.exists()]
        if existing:
            return str(max(existing, key=lambda path: path.stat().st_mtime))
        default_path = Path("log/superbot.log")
        return str(default_path) if default_path.exists() else None

    @staticmethod
    def _read_log_tail(path: Path, limit: int) -> list[str]:
        try:
            size = path.stat().st_size
        except OSError:
            return []
        max_bytes = 1024 * 1024
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            raw = handle.read()
        return raw.decode("utf-8", errors="replace").splitlines()[-limit:]

    async def handle_debug_status(self, request):
        """Statut processus : version Python, uptime, sous-systèmes, snapshot config."""
        uptime_seconds = max(0.0, time.time() - self._started_at)
        return web.json_response(
            {
                "ok": True,
                "python_version": sys.version.split()[0],
                "python_version_info": list(sys.version_info[:3]),
                "python_executable": sys.executable,
                "started_at": self._started_at_iso,
                "uptime_seconds": round(uptime_seconds, 3),
                "subsystems": self._collect_subsystem_status(),
                "config_snapshot": self._config_snapshot(),
                "refreshed_at": self._now_iso(),
            }
        )

    async def handle_debug_health_detail(self, request):
        """Santé agrégée : chaque sous-check porte ok:bool et detail:string."""
        checks: list[dict] = []

        hitl_ok = self.hitl is not None
        checks.append(
            {
                "name": "hitl_module",
                "ok": hitl_ok,
                "detail": "available" if hitl_ok else "hitl module missing",
            }
        )

        runtime: dict = {}
        if self.runtime_status_provider is None:
            checks.append(
                {
                    "name": "runtime_status_provider",
                    "ok": False,
                    "detail": "no runtime status provider configured",
                }
            )
        else:
            try:
                runtime = (
                    await asyncio.to_thread(self.runtime_status_provider) or {}
                )
                checks.append(
                    {
                        "name": "runtime_status_provider",
                        "ok": True,
                        "detail": "runtime status snapshot available",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    {
                        "name": "runtime_status_provider",
                        "ok": False,
                        "detail": f"provider raised: {exc}",
                    }
                )
        if not isinstance(runtime, dict):
            runtime = {}

        snapshot_cache = self._runtime_snapshot_cache
        cache_ok = isinstance(snapshot_cache, dict)
        checks.append(
            {
                "name": "runtime_snapshot_cache",
                "ok": cache_ok,
                "detail": (
                    "cached snapshot present" if cache_ok else "no snapshot cached yet"
                ),
            }
        )

        for name, availability in self._collect_subsystem_status().items():
            checks.append(
                {"name": name, "ok": availability["ok"], "detail": availability["detail"]}
            )

        log_path = self._discover_log_path()
        checks.append(
            {
                "name": "log_file",
                "ok": bool(log_path),
                "detail": log_path or "no log file discovered",
            }
        )

        health = runtime.get("health", {})
        return web.json_response(
            {
                "ok": all(check["ok"] for check in checks),
                "checks": checks,
                "last_success_at": runtime.get("last_success_at"),
                "health": dict(health) if isinstance(health, dict) else {},
                "refreshed_at": self._now_iso(),
            }
        )

    async def handle_debug_log_tail(self, request):
        """Dernières n lignes du log applicatif (n clamp 1..1000, défaut 100)."""
        log_path = self._discover_log_path()
        if not log_path:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Aucun fichier de log applicatif découvert "
                    "(config logging sans chemin de fichier).",
                },
                status=404,
            )
        path = Path(log_path)
        if not path.is_file():
            return web.json_response(
                {"ok": False, "error": f"Fichier de log introuvable: {log_path}"},
                status=404,
            )
        limit = self._parse_limit(request.query.get("n"), default=100, maximum=1000)
        lines = self._read_log_tail(path, limit)
        return web.json_response(
            {
                "ok": True,
                "path": str(path),
                "n": limit,
                "count": len(lines),
                "lines": lines,
                "refreshed_at": self._now_iso(),
            }
        )
