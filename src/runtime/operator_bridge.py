from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from src.runtime.health import HealthMonitor


class OperatorBridge:
    def __init__(
        self,
        *,
        root: Path,
        bridge_store,
        history_store,
        runtime_api_port: int,
        build_state: Callable[[], dict],
        apply_command: Callable[[dict], None],
        push_incident: Callable[..., None],
        health_monitor: Optional[HealthMonitor] = None,
        publish_interval_s: float = 0.15,
        process_factory: Optional[Callable[..., object]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = Path(root)
        self.bridge_store = bridge_store
        self.history_store = history_store
        self.runtime_api_port = int(runtime_api_port)
        self.build_state = build_state
        self.apply_command = apply_command
        self.push_incident = push_incident
        self.health_monitor = health_monitor
        self.publish_interval_s = float(publish_interval_s or 0.15)
        self.process_factory = process_factory or subprocess.Popen
        self.sleep_fn = sleep_fn
        self._last_runtime_state_published_at = 0.0
        self.api_process = None
        self._api_stdout_handle = None
        self._api_stderr_handle = None

    def publish_state(self, force: bool = False) -> None:
        if self.bridge_store is None:
            return

        now = time.monotonic()
        if not force and (now - self._last_runtime_state_published_at) < self.publish_interval_s:
            return

        try:
            self.bridge_store.publish_runtime_state(self.build_state())
            if self.health_monitor is not None:
                self.health_monitor.record_success("bridge")
        except Exception as exc:
            if self.health_monitor is not None:
                self.health_monitor.record_error("bridge", str(exc) or "bridge_publish_error", status="degraded", cooldown_s=1.0)
            return

        self._last_runtime_state_published_at = now

    def process_pending_commands(self, limit: int = 8) -> None:
        try:
            commands = self.bridge_store.consume_pending_commands(limit=limit)
            if self.health_monitor is not None:
                self.health_monitor.record_success("bridge")
        except Exception as exc:
            if self.health_monitor is not None:
                self.health_monitor.record_error("bridge", str(exc) or "bridge_consume_error", status="degraded", cooldown_s=1.0)
            raise

        if not commands:
            return

        for command in commands:
            try:
                self.apply_command(command)
            except Exception as exc:
                self.push_incident(
                    "bridge_command_error",
                    severity="error",
                    command_id=str(command.get("command_id") or ""),
                    kind=str(command.get("kind") or ""),
                    error=str(exc),
                )

    def start_api_process(self) -> None:
        if self.api_process is not None and self.api_process.poll() is None:
            if self.health_monitor is not None:
                self.health_monitor.record_success("api")
            return

        api_entrypoint = self.root / "src" / "api" / "runtime_bridge_server.py"
        if not api_entrypoint.is_file():
            raise RuntimeError(f"API bridge introuvable: {api_entrypoint}")

        os.makedirs("log", exist_ok=True)
        self._api_stdout_handle = open("log/runtime_api_stdout.log", "a", encoding="utf-8")
        self._api_stderr_handle = open("log/runtime_api_stderr.log", "a", encoding="utf-8")

        env = os.environ.copy()
        env["POKER_RUNTIME_API_PORT"] = str(self.runtime_api_port)
        env["POKER_RUNTIME_BRIDGE_DIR"] = str(self.bridge_store.bridge_dir)
        env["POKER_RUNTIME_HISTORY_PATH"] = str(self.history_store.file_path)
        env["POKER_RUNTIME_CONFIG_PATH"] = str(self.root / "config.json")
        env["POKER_RUNTIME_PARENT_PID"] = str(os.getpid())

        self.api_process = self.process_factory(
            [sys.executable, str(api_entrypoint)],
            cwd=str(self.root),
            stdin=subprocess.DEVNULL,
            stdout=self._api_stdout_handle,
            stderr=self._api_stderr_handle,
            env=env,
        )
        self.sleep_fn(0.35)
        if self.api_process.poll() is not None:
            if self.health_monitor is not None:
                self.health_monitor.record_error("api", "api_process_exited_early", status="unavailable", cooldown_s=2.0)
            raise RuntimeError(
                f"Le process API bridge a quitte immediatement avec le code {self.api_process.returncode}."
            )
        if self.health_monitor is not None:
            self.health_monitor.record_success("api")

    def stop_api_process(self) -> None:
        process = self.api_process
        self.api_process = None
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=2.0)
                if self.health_monitor is not None:
                    self.health_monitor.record_success("api")
            except Exception:
                if self.health_monitor is not None:
                    self.health_monitor.record_error("api", "api_process_stop_error", status="degraded")
                try:
                    process.kill()
                except Exception:
                    pass

        for handle_name in ("_api_stdout_handle", "_api_stderr_handle"):
            handle = getattr(self, handle_name, None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
            setattr(self, handle_name, None)
