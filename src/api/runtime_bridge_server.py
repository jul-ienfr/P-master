import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.server import BotAPI
from src.data.database import DatabaseManager
from src.runtime.bridge_store import BridgeHitlProxy, BridgeRuntimeStatusProvider, RuntimeBridgeStore
from src.runtime.history_store import RuntimeHistoryStore
from src.runtime.timesfm_service import RuntimeTimesFMService


logger = logging.getLogger("RuntimeBridgeAPI")


def _load_json_config(config_path: str) -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return dict(payload) if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _parent_process_alive(pid: int) -> bool:
    if pid <= 0:
        return True

    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(0x100000, 0, int(pid))
        if not process:
            return False
        try:
            return kernel32.WaitForSingleObject(process, 0) == 0x00000102
        finally:
            kernel32.CloseHandle(process)
    except Exception:
        return True


class ObservationExporter:
    def __init__(self, config: dict) -> None:
        db_cfg = config.get("database", {}) or {}
        self.db = DatabaseManager(
            dsn=db_cfg.get("dsn"),
            mode=db_cfg.get("mode"),
            persistence_path=db_cfg.get("observation_persistence_path"),
            persistence_enabled=bool(db_cfg.get("observation_persistence_enabled", True)),
        )

    async def start(self) -> None:
        try:
            await self.db.connect()
        except Exception as exc:
            logger.warning("Observation exporter DB indisponible: %s", exc)

    async def stop(self) -> None:
        try:
            await self.db.close()
        except Exception:
            pass

    def export(self, player_limit: int = 50, hand_limit: int = 100) -> dict:
        return dict(self.db.export_observation_dataset(player_limit=player_limit, hand_limit=hand_limit) or {})

    def summary(self) -> dict:
        return dict(self.db.summarize_observation(limit=5) or {})


async def _watch_parent(parent_pid: int, stop_event: asyncio.Event) -> None:
    if parent_pid <= 0:
        return
    while not stop_event.is_set():
        if not _parent_process_alive(parent_pid):
            logger.warning("Le process runtime parent %s est termine. Arret de l'API bridge.", parent_pid)
            stop_event.set()
            return
        await asyncio.sleep(1.0)


async def _serve_runtime_bridge(args) -> None:
    config = _load_json_config(args.config)
    runtime_cfg = config.get("runtime_history", {}) or {}
    timesfm_cfg = config.get("timesfm", {}) or {}
    bridge_store = RuntimeBridgeStore(args.bridge_dir)
    history_store = RuntimeHistoryStore(
        enabled=runtime_cfg.get("enabled", True),
        file_path=args.history_path or runtime_cfg.get("file_path", "log/runtime_history.jsonl"),
        max_size_bytes=runtime_cfg.get("max_size_bytes", 1_048_576),
        session_id=None,
    )
    observation_exporter = ObservationExporter(config)
    await observation_exporter.start()

    runtime_provider = BridgeRuntimeStatusProvider(
        bridge_store=bridge_store,
        history_store=history_store,
        observation_provider=observation_exporter.summary,
    )
    timesfm_service = RuntimeTimesFMService(
        enabled=bool(timesfm_cfg.get("enabled", False) or str(os.getenv("POKER_ENABLE_TIMESFM", "")).strip().lower() in {"1", "true", "yes", "on"}),
        history_path=args.history_path or runtime_cfg.get("file_path", "log/runtime_history.jsonl"),
        default_horizon=int(timesfm_cfg.get("default_horizon", 12) or 12),
        default_max_context=int(timesfm_cfg.get("default_max_context", 256) or 256),
    )
    hitl_proxy = BridgeHitlProxy(bridge_store=bridge_store)
    api = BotAPI(
        hitl_proxy,
        runtime_status_provider=runtime_provider.get_status,
        runtime_operator_handler=bridge_store.queue_operator_patch,
        runtime_observation_provider=runtime_provider.get_observation_snapshot,
        runtime_observation_exporter=observation_exporter.export,
        runtime_timesfm_provider=timesfm_service.forecast_runtime_metrics if timesfm_service.enabled else None,
        host=args.host,
        port=args.port,
        runtime_history_store=history_store,
    )

    stop_event = asyncio.Event()
    parent_task = None
    if args.parent_pid > 0:
        parent_task = asyncio.create_task(_watch_parent(args.parent_pid, stop_event))

    await api.start()
    try:
        await api._build_runtime_snapshot_payload_async(force=True)
    except Exception as exc:
        logger.warning("Prechauffage snapshot bridge impossible: %s", exc)
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if parent_task is not None:
            parent_task.cancel()
        await api.stop()
        await observation_exporter.stop()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PokerMaster runtime bridge API server")
    parser.add_argument("--host", default=os.getenv("POKER_RUNTIME_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("POKER_RUNTIME_API_PORT", "8005")))
    parser.add_argument("--bridge-dir", default=os.getenv("POKER_RUNTIME_BRIDGE_DIR", "log/runtime_bridge"))
    parser.add_argument("--history-path", default=os.getenv("POKER_RUNTIME_HISTORY_PATH", "log/runtime_history.jsonl"))
    parser.add_argument("--config", default=os.getenv("POKER_RUNTIME_CONFIG_PATH", "config.json"))
    parser.add_argument("--parent-pid", type=int, default=int(os.getenv("POKER_RUNTIME_PARENT_PID", "0") or 0))
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _build_parser().parse_args()
    asyncio.run(_serve_runtime_bridge(args))


if __name__ == "__main__":
    main()
