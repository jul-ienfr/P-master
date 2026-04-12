"""Unified phase-2 runner for the V2/refonte validation stack."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.automation import RESULTS_DIR, build_automation_payload  # noqa: E402


PYTEST_TARGETS = (
    "poker/tests/test_v2_contracts.py",
    "poker/tests/test_decision_service.py",
    "poker/tests/test_range_tracker.py",
    "poker/tests/test_equity_backends.py",
    "poker/tests/test_native_equity.py",
    "poker/tests/test_decision_transcripts.py",
    "poker/tests/test_decisionmaker_gto_v2.py",
    "poker/tests/test_research_lab.py",
    "poker/tests/test_restapi_local_v2.py",
)


def _command_env() -> dict[str, str]:
    env = dict(os.environ)
    python_home = env.get("POKERMASTER_PYTHONHOME")
    if python_home:
        env["PYTHONHOME"] = python_home
    linker = env.get("POKERMASTER_LINKER")
    if linker:
        env["CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"] = linker
    cc = env.get("POKERMASTER_CC")
    if cc:
        env["CC"] = cc
    return env


def _run_step(
    name: str,
    command: list[str],
    *,
    cwd: Path | None = None,
    optional: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd or ROOT),
            env=_command_env(),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "name": name,
            "status": "skipped" if optional else "failed",
            "returncode": None,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "command": command,
            "reason": str(exc),
            "stdout_tail": "",
            "stderr_tail": "",
        }

    status = "passed" if completed.returncode == 0 else ("skipped" if optional else "failed")
    stdout_tail = completed.stdout[-4000:]
    stderr_tail = completed.stderr[-4000:]
    return {
        "name": name,
        "status": status,
        "returncode": completed.returncode,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "command": command,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


def _maybe_node_step(name: str, command: list[str], *, cwd: Path) -> dict[str, Any]:
    if shutil.which(command[0]) is None:
        return {
            "name": name,
            "status": "skipped",
            "returncode": None,
            "elapsed_ms": 0,
            "command": command,
            "reason": f"{command[0]} missing",
            "stdout_tail": "",
            "stderr_tail": "",
        }
    return _run_step(name, command, cwd=cwd, optional=True)


def main() -> None:
    python_bin = os.environ.get("POKERMASTER_PYTHON", sys.executable)
    cargo_bin = os.environ.get("POKERMASTER_CARGO", shutil.which("cargo") or "cargo")
    node_bin = os.environ.get("POKERMASTER_NODE", shutil.which("node") or "node")
    website_dir = ROOT / "website"

    steps = [
        _run_step(
            "python_v2_tests",
            [python_bin, "-m", "pytest", *PYTEST_TARGETS, "-q"],
        ),
        _run_step(
            "research_validation_suite",
            [python_bin, "research/run_validation_suite.py"],
        ),
        _run_step(
            "research_rl_lab",
            [python_bin, "research/run_rl_lab.py"],
        ),
        _run_step(
            "rust_v2_tests",
            [cargo_bin, "test", "--test", "v2_api", "--", "--nocapture"],
        ),
        _run_step(
            "rust_native_latency",
            [cargo_bin, "run", "--example", "native_latency"],
        ),
        _maybe_node_step(
            "website_typecheck",
            [node_bin, "node_modules/typescript/bin/tsc", "-p", "tsconfig.json", "--noEmit"],
            cwd=website_dir,
        ),
        _maybe_node_step(
            "website_build",
            [node_bin, "node_modules/vite/bin/vite.js", "build"],
            cwd=website_dir,
        ),
    ]

    passed = [step for step in steps if step["status"] == "passed"]
    failed = [step for step in steps if step["status"] == "failed"]
    skipped = [step for step in steps if step["status"] == "skipped"]
    payload = {
        "kind": "refonte_ci_summary",
        "python_bin": python_bin,
        "cargo_bin": cargo_bin,
        "node_bin": node_bin,
        "steps": steps,
        "summary": {
            "passed": len(passed),
            "failed": len(failed),
            "skipped": len(skipped),
            "status": "ok" if not failed else "failed",
        },
        "artifacts": [],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "refonte_ci_summary.json"
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["artifacts"] = build_automation_payload()["artifacts"]
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
