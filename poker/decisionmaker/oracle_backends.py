"""Optional oracle evaluators used for conformance and offline validation."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any


ORACLE_RUNNER_PATH = (
    Path(__file__).resolve().parents[2] / "research" / "node_oracle_runner.js"
)


@dataclass(frozen=True)
class OracleAvailability:
    name: str
    available: bool
    reason: str
    metadata: dict[str, Any]


def _module_exists(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def detect_oracle_backends() -> list[OracleAvailability]:
    node_binary = shutil.which("node")
    dotnet_binary = shutil.which("dotnet")
    return [
        OracleAvailability(
            name="phevaluator",
            available=_module_exists("phevaluator"),
            reason="python_module" if _module_exists("phevaluator") else "python_module_missing",
            metadata={"module": "phevaluator"},
        ),
        OracleAvailability(
            name="pokersolver",
            available=bool(node_binary),
            reason="node_runner" if node_binary else "node_missing",
            metadata={"node": node_binary or "", "runner": str(ORACLE_RUNNER_PATH)},
        ),
        OracleAvailability(
            name="poker_evaluator",
            available=bool(node_binary),
            reason="node_runner" if node_binary else "node_missing",
            metadata={"node": node_binary or "", "runner": str(ORACLE_RUNNER_PATH)},
        ),
        OracleAvailability(
            name="skpokereval",
            available=bool(dotnet_binary),
            reason="dotnet_runtime" if dotnet_binary else "dotnet_missing",
            metadata={"dotnet": dotnet_binary or ""},
        ),
    ]


def rank_with_phevaluator(cards: list[str] | tuple[str, ...]) -> dict[str, Any]:
    from phevaluator.evaluator import evaluate_cards  # type: ignore[import-not-found]

    rank = evaluate_cards(*cards)
    return {
        "backend": "phevaluator",
        "rank": int(rank),
        "cards": list(cards),
    }


def rank_with_node_oracle(
    cards: list[str] | tuple[str, ...],
    *,
    backend: str,
    allow_download: bool = False,
) -> dict[str, Any]:
    node_binary = shutil.which("node")
    if not node_binary:
        raise RuntimeError("node is required for JS oracle backends")
    if not ORACLE_RUNNER_PATH.exists():
        raise RuntimeError(f"node oracle runner is missing: {ORACLE_RUNNER_PATH}")

    command = [node_binary, str(ORACLE_RUNNER_PATH), backend, *cards]
    env = None
    if allow_download:
        env = dict(os.environ)
        env["POKERMASTER_ALLOW_ORACLE_DOWNLOAD"] = "1"
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(completed.stdout)


def rank_showdown_hand(
    cards: list[str] | tuple[str, ...],
    *,
    backend: str = "auto",
    allow_download: bool = False,
) -> dict[str, Any]:
    normalized_cards = [str(card) for card in cards if str(card).strip()]
    if backend in {"auto", "phevaluator"} and _module_exists("phevaluator"):
        return rank_with_phevaluator(normalized_cards)
    if backend in {"auto", "pokersolver"}:
        return rank_with_node_oracle(
            normalized_cards,
            backend="pokersolver",
            allow_download=allow_download,
        )
    if backend == "poker_evaluator":
        return rank_with_node_oracle(
            normalized_cards,
            backend="poker_evaluator",
            allow_download=allow_download,
        )
    raise RuntimeError(f"requested oracle backend is unavailable: {backend}")
