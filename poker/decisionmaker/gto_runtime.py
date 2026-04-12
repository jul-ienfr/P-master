"""Helpers to locate and start a bundled local GTO backend."""

from __future__ import annotations

import atexit
import logging
import pathlib
import subprocess
import threading
import time

try:
    import requests
except ImportError:  # pragma: no cover - optional at runtime
    requests = None

from poker.tools.helper import get_dir

logger = logging.getLogger(__name__)

GTO_SERVER_URL = "http://127.0.0.1:8765"
HEALTHCHECK_URL = f"{GTO_SERVER_URL}/health"
_SERVER_PROCESS: subprocess.Popen | None = None
_SERVER_LOCK = threading.Lock()


def ensure_local_gto_server(timeout_sec: int = 10) -> bool:
    """Ensure the HTTP backend is reachable, starting a bundled server when possible."""
    if requests is None:
        return False

    if http_backend_ready():
        return True

    with _SERVER_LOCK:
        if http_backend_ready():
            return True

        global _SERVER_PROCESS

        if _SERVER_PROCESS is not None:
            if _SERVER_PROCESS.poll() is None:
                return wait_for_http_backend(timeout_sec)
            _SERVER_PROCESS = None

        executable = find_gto_server_executable()
        if executable is None:
            logger.debug("No local gto_server executable found for HTTP fallback")
            return False

        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            _SERVER_PROCESS = subprocess.Popen(
                [str(executable)],
                cwd=str(executable.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as exc:  # pragma: no cover - runtime fallback path
            logger.warning("Unable to start bundled gto_server from %s: %s", executable, exc)
            _SERVER_PROCESS = None
            return False

        if wait_for_http_backend(timeout_sec):
            logger.info("Started bundled gto_server from %s", executable)
            return True

        logger.warning("Bundled gto_server did not become healthy in %ss", timeout_sec)
        terminate_local_gto_server()
        return False


def terminate_local_gto_server():
    """Terminate the locally spawned server, if any."""
    with _SERVER_LOCK:
        global _SERVER_PROCESS
        if _SERVER_PROCESS is None:
            return

        process = _SERVER_PROCESS
        _SERVER_PROCESS = None

        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def http_backend_ready() -> bool:
    """Return True when the HTTP backend is already healthy."""
    if requests is None:
        return False

    try:
        response = requests.get(HEALTHCHECK_URL, timeout=1)
    except requests.RequestException:
        return False
    return response.ok


def wait_for_http_backend(timeout_sec: int) -> bool:
    """Poll the health endpoint until the server is ready or timeout expires."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if http_backend_ready():
            return True
        time.sleep(0.25)
    return False


def find_gto_server_executable() -> pathlib.Path | None:
    """Locate a bundled or repository-local gto_server executable."""
    codebase = pathlib.Path(get_dir("codebase"))
    candidates = (
        codebase / "gto_server.exe",
        codebase / "backend" / "gto_server.exe",
        codebase.parent / "gto_server.exe",
        codebase.parent / "backend" / "gto_server.exe",
        codebase.parent / "gto_server" / "target" / "release" / "gto_server.exe",
        codebase.parent / "gto_server" / "target" / "debug" / "gto_server.exe",
        pathlib.Path.cwd() / "gto_server.exe",
        pathlib.Path.cwd() / "backend" / "gto_server.exe",
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return None


atexit.register(terminate_local_gto_server)
