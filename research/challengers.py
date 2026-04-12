"""Optional challenger registry for offline RL and policy experiments."""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from typing import Any

from poker.decisionmaker.v2_contracts import SpotSnapshot, build_mock_spot_snapshot
from research.replay_adapters import (
    spot_to_pokerkit_payload,
    spot_to_pokerrl_payload,
    spot_to_pypokerengine_payload,
    spot_to_rlcard_payload,
)


def _available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _import_first(module_names: tuple[str, ...]) -> Any | None:
    for module_name in module_names:
        if not _available(module_name):
            continue
        try:
            return importlib.import_module(module_name)
        except Exception:
            continue
    return None


def _list_submodules(module: Any) -> list[str]:
    module_path = getattr(module, "__path__", None)
    if module_path is None:
        return []
    try:
        return sorted(
            {
                str(item.name)
                for item in pkgutil.iter_modules(module_path)
                if getattr(item, "name", None)
            }
        )
    except Exception:
        return []


def _sample_spot_payloads(spot: SpotSnapshot | None = None) -> dict[str, dict[str, Any]]:
    selected_spot = spot or build_mock_spot_snapshot()
    return {
        "pokerkit": spot_to_pokerkit_payload(selected_spot),
        "pypokerengine": spot_to_pypokerengine_payload(selected_spot),
        "rlcard": spot_to_rlcard_payload(selected_spot),
        "pokerrl": spot_to_pokerrl_payload(selected_spot),
    }


def challenger_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "pokerkit",
            "kind": "simulation_env",
            "available": _available("pokerkit"),
            "module": "pokerkit",
            "factory_hint": "pokerkit.State / Automation",
            "capabilities": ["simulation_env", "replay_bridge"],
        },
        {
            "id": "pypokerengine",
            "kind": "simulation_env",
            "available": _available("pypokerengine"),
            "module": "pypokerengine",
            "factory_hint": "pypokerengine.api.game.setup_config",
            "capabilities": ["simulation_env", "replay_bridge"],
        },
        {
            "id": "rlcard",
            "kind": "rl_challenger",
            "available": _available("rlcard"),
            "module": "rlcard",
            "factory_hint": "rlcard.make('no-limit-holdem')",
            "capabilities": ["offline_challenger", "evaluation", "self_play"],
        },
        {
            "id": "pokerrl",
            "kind": "rl_challenger",
            "available": _available("PokerRL") or _available("pokerrl"),
            "module": "PokerRL",
            "factory_hint": "TrainingProfileBase / AgentTournament",
            "capabilities": [
                "offline_challenger",
                "evaluation",
                "self_play",
                "best_response",
            ],
        },
        {
            "id": "neuron_poker",
            "kind": "rl_challenger",
            "available": _available("neuron_poker"),
            "module": "neuron_poker",
            "factory_hint": "gym.make('neuron_poker-v0')",
            "capabilities": ["offline_challenger", "gym_env", "self_play"],
        },
        {
            "id": "poker_ai",
            "kind": "rl_challenger",
            "available": _available("poker_ai"),
            "module": "poker_ai",
            "factory_hint": "poker_ai.poker.engine.PokerEngine",
            "capabilities": ["offline_challenger", "engine", "self_play"],
        },
    ]


def load_challenger(
    challenger_id: str,
    *,
    spot: SpotSnapshot | None = None,
) -> dict[str, Any]:
    registry = {entry["id"]: entry for entry in challenger_registry()}
    if challenger_id not in registry:
        raise KeyError(f"unknown challenger: {challenger_id}")

    entry = registry[challenger_id]
    sample_payloads = _sample_spot_payloads(spot)
    module = None

    if challenger_id == "pokerrl":
        module = _import_first(("PokerRL", "pokerrl"))
    else:
        module = _import_first((str(entry["module"]),))

    if module is None:
        return {
            **entry,
            "loaded": False,
            "reason": "module_unavailable",
            "sample_payload": sample_payloads.get(challenger_id, sample_payloads["rlcard"]),
        }

    descriptor: dict[str, Any] = {
        **entry,
        "loaded": True,
        "module_name": getattr(module, "__name__", str(entry["module"])),
        "sample_payload": sample_payloads.get(challenger_id, sample_payloads["rlcard"]),
        "discovered_submodules": _list_submodules(module)[:16],
    }

    if challenger_id == "pokerkit":
        descriptor["entry_points"] = ["State", "Automation"]
    elif challenger_id == "pypokerengine":
        descriptor["entry_points"] = ["setup_config", "start_poker", "Emulator"]
    elif challenger_id == "rlcard":
        descriptor["supported_envs"] = [
            "no-limit-holdem",
            "limit-holdem",
            "leduc-holdem",
        ]
        descriptor["entry_points"] = ["make", "models", "agents"]
    elif challenger_id == "pokerrl":
        descriptor["entry_points"] = [
            "TrainingProfileBase",
            "EvalAgentBase",
            "AgentTournament",
            "InteractiveGame",
        ]
    elif challenger_id == "neuron_poker":
        descriptor["entry_points"] = ["gym.make", "agents", "evaluate"]
        descriptor["gym_available"] = _available("gym") or _available("gymnasium")
    elif challenger_id == "poker_ai":
        descriptor["entry_points"] = ["PokerEngine", "Table", "Player"]

    return descriptor


def challenger_payload(spot: SpotSnapshot | None = None) -> list[dict[str, Any]]:
    return [load_challenger(entry["id"], spot=spot) for entry in challenger_registry()]
