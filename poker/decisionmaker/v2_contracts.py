"""V2 Python bridge contracts for the local PokerMaster suite.

These dataclasses are intentionally self-contained so the future desktop UI,
the live runtime bridge, and the optional LLM copilot can all share the same
shape without depending on the old runtime internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
import platform
import sys
from typing import Any

try:  # pragma: no cover - optional metadata lookup
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover - Python < 3.8 fallback
    import importlib_metadata  # type: ignore


def _to_primitive(value: Any) -> Any:
    """Convert nested dataclasses/enums/containers to JSON-friendly values."""
    if is_dataclass(value):
        return {field.name: _to_primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_primitive(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_primitive(item) for item in value]
    return value


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),)


def _as_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _as_any_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _payload_get(payload: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload:
            return payload.get(key)
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _merge_bool_map(defaults: dict[str, bool], overrides: Any) -> dict[str, bool]:
    result = dict(defaults)
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            result[str(key)] = _as_bool(value, result.get(str(key), False))
        return result
    if isinstance(overrides, (list, tuple, set)):
        for key in overrides:
            if key not in (None, ""):
                result[str(key)] = True
    return result


def _safe_package_version() -> str:
    for candidate in ("PokerMaster", "poker", "Poker-master"):
        try:
            return importlib_metadata.version(candidate)
        except Exception:  # pragma: no cover - best effort only
            continue
    return "unknown"


class SerializableDataclass:
    """Mixin that provides stable dict/json round-tripping."""

    def to_dict(self) -> dict[str, Any]:
        return _to_primitive(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str):
        return cls.from_dict(json.loads(payload))


class LlmProviderMode(str, Enum):
    DISABLED = "disabled"
    OPENAI_COMPATIBLE_REMOTE = "openai_compatible_remote"
    OPENAI_COMPATIBLE_LOCAL = "openai_compatible_local"


class LlmAssistTaskType(str, Enum):
    SPOT_EXPLAIN = "spot_explain"
    LINE_COMPARE = "line_compare"
    DECISION_RATIONALE = "decision_rationale"
    OCR_DIAGNOSTIC = "ocr_diagnostic"
    FALLBACK_DIAGNOSTIC = "fallback_diagnostic"
    SESSION_SUMMARY = "session_summary"
    STRATEGY_REVIEW = "strategy_review"
    REPLAY_COACH = "replay_coach"


class EquityBackend(str, Enum):
    RUST_EXACT = "rust_exact"
    RUST_MONTE_CARLO = "rust_monte_carlo"
    ORACLE_BACKEND = "oracle_backend"
    UNKNOWN = "unknown"


class RangeModelVersion(str, Enum):
    HEURISTIC_V1 = "heuristic_v1"
    BOARD_AWARE_V2 = "board_aware_v2"
    CALIBRATED_V3 = "calibrated_v3"


class CachePolicy(str, Enum):
    DISABLED = "disabled"
    MEMORY = "memory"
    PERSISTENT = "persistent"


class CacheTier(str, Enum):
    NONE = "none"
    MEMORY = "memory"
    DISK = "disk"


@dataclass
class ActionOptionV2(SerializableDataclass):
    name: str = ""
    label: str = ""
    size: float | None = None
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "ActionOptionV2":
        if isinstance(payload, str):
            normalized = payload.strip()
            return cls(name=normalized, label=normalized.title())
        payload = payload or {}
        return cls(
            name=str(payload.get("name", "")),
            label=str(payload.get("label", payload.get("name", ""))),
            size=(
                None
                if payload.get("size") in (None, "")
                else _as_float(payload.get("size"))
            ),
            available=_as_bool(payload.get("available", True), default=True),
            metadata=_as_any_dict(payload.get("metadata")),
        )


@dataclass
class OcrConfidenceReport(SerializableDataclass):
    overall: float = 0.0
    hero_cards: float = 0.0
    board: float = 0.0
    pot: float = 0.0
    stack: float = 0.0
    actions: float = 0.0
    notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: Any) -> "OcrConfidenceReport":
        payload = payload or {}
        return cls(
            overall=_as_float(payload.get("overall", payload.get("confidence", 0.0))),
            hero_cards=_as_float(payload.get("hero_cards", payload.get("heroCards", 0.0))),
            board=_as_float(payload.get("board", 0.0)),
            pot=_as_float(payload.get("pot", 0.0)),
            stack=_as_float(payload.get("stack", 0.0)),
            actions=_as_float(payload.get("actions", 0.0)),
            notes=_as_tuple(payload.get("notes")),
        )


@dataclass
class DecisionGateResult(SerializableDataclass):
    allowed: bool = True
    confidence: float = 1.0
    reason: str = ""
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "DecisionGateResult":
        payload = payload or {}
        return cls(
            allowed=_as_bool(payload.get("allowed", True), default=True),
            confidence=_as_float(payload.get("confidence", 1.0)),
            reason=str(payload.get("reason", "")),
            warnings=_as_tuple(payload.get("warnings")),
            metadata=_as_any_dict(payload.get("metadata")),
        )


@dataclass
class ActionEstimate(SerializableDataclass):
    name: str = ""
    size: float = 0.0
    frequency: float = 0.0
    ev: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "ActionEstimate":
        payload = payload or {}
        return cls(
            name=str(payload.get("name", "")),
            size=_as_float(payload.get("size", 0.0)),
            frequency=_as_float(payload.get("frequency", 0.0)),
            ev=_as_float(payload.get("ev", 0.0)),
            metadata=_as_any_dict(payload.get("metadata")),
        )


@dataclass
class SpotSnapshot(SerializableDataclass):
    spot_id: str = ""
    source: str = "live"
    game_stage: str = ""
    hero_cards: tuple[str, ...] = ()
    board: tuple[str, ...] = ()
    hero_position: str = ""
    positions: dict[str, str] = field(default_factory=dict)
    pot: float = 0.0
    stack: float = 0.0
    legal_actions: tuple[str, ...] = ()
    action_history: tuple[str, ...] = ()
    hero_range: str = ""
    villain_ranges: tuple[str, ...] = ()
    state_confidence: float = 0.0
    ocr_confidence: OcrConfidenceReport | None = None
    range_model_version: RangeModelVersion = RangeModelVersion.BOARD_AWARE_V2
    ocr_metadata: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "SpotSnapshot":
        payload = payload or {}
        return cls(
            spot_id=str(payload.get("spot_id", payload.get("spotId", ""))),
            source=str(payload.get("source", "live")),
            game_stage=str(payload.get("game_stage", "")),
            hero_cards=_as_tuple(payload.get("hero_cards")),
            board=_as_tuple(payload.get("board")),
            hero_position=str(payload.get("hero_position", "")),
            positions=_as_str_dict(payload.get("positions")),
            pot=_as_float(payload.get("pot", 0.0)),
            stack=_as_float(payload.get("stack", 0.0)),
            legal_actions=_as_tuple(payload.get("legal_actions")),
            action_history=_as_tuple(payload.get("action_history")),
            hero_range=str(payload.get("hero_range", "")),
            villain_ranges=_as_tuple(payload.get("villain_ranges")),
            state_confidence=_as_float(
                payload.get("state_confidence", payload.get("stateConfidence", 0.0))
            ),
            ocr_confidence=(
                payload.get("ocr_confidence")
                if isinstance(payload.get("ocr_confidence"), OcrConfidenceReport)
                else (
                    OcrConfidenceReport.from_dict(payload.get("ocr_confidence"))
                    if isinstance(payload.get("ocr_confidence"), dict)
                    else (
                        OcrConfidenceReport.from_dict(payload.get("ocr_metadata"))
                        if isinstance(payload.get("ocr_metadata"), dict)
                        and payload.get("ocr_metadata", {}).get("confidence") not in (None, "")
                        else None
                    )
                )
            ),
            range_model_version=_coerce_range_model_version(
                payload.get("range_model_version", payload.get("rangeModelVersion"))
            ),
            ocr_metadata=_as_any_dict(payload.get("ocr_metadata")),
            metadata=_as_any_dict(payload.get("metadata")),
        )

    @classmethod
    def from_legacy(
        cls,
        table: Any,
        history: Any = None,
        strategy: Any = None,
        source: str = "live",
    ) -> "SpotSnapshot":
        hero_cards = _as_tuple(getattr(table, "mycards", None))
        board = _as_tuple(getattr(table, "cardsOnTable", None))
        game_stage = str(getattr(table, "gameStage", ""))
        pot = _as_float(getattr(table, "totalPotValue", 0.0))
        stack = _as_float(getattr(table, "myFunds", 100.0))
        hero_position = str(
            getattr(table, "position_utg_plus", "")
            or getattr(table, "hero_position", "")
            or getattr(table, "position", "")
        )

        legal_actions: list[str] = []
        if _as_bool(getattr(table, "checkButton", False)):
            legal_actions.append("check")
        min_call = _as_float(getattr(table, "minCall", 0.0))
        min_bet = _as_float(getattr(table, "minBet", 0.0))
        if min_call > 0:
            legal_actions.extend(["call", "fold"])
        else:
            legal_actions.append("fold")
        if min_bet > 0:
            legal_actions.append("bet")

        positions: dict[str, str] = {}
        if hasattr(table, "other_players"):
            positions["players"] = str(len(getattr(table, "other_players", []) or []))
        if hero_position:
            positions["hero"] = hero_position

        action_history = _extract_history(history)
        ocr_metadata = {
            "table_name": getattr(table, "table_name", ""),
            "screen_resolution": getattr(table, "screen_resolution", ""),
            "check_button": _as_bool(getattr(table, "checkButton", False)),
            "min_call": min_call,
            "min_bet": min_bet,
        }
        if strategy is not None and hasattr(strategy, "selected_strategy"):
            ocr_metadata["strategy_name"] = getattr(strategy, "selected_strategy", {}).get(
                "name", ""
            )

        hero_conf = 1.0 if len(hero_cards) == 2 else 0.0
        board_conf = 0.75 if game_stage == "PreFlop" else min(len(board) / 5.0, 1.0)
        pot_conf = 1.0 if pot >= 0 else 0.0
        stack_conf = 1.0 if stack >= 0 else 0.0
        actions_conf = 1.0 if legal_actions else 0.3
        overall_confidence = round(
            (hero_conf + board_conf + pot_conf + stack_conf + actions_conf) / 5.0,
            3,
        )
        confidence_report = OcrConfidenceReport(
            overall=overall_confidence,
            hero_cards=hero_conf,
            board=board_conf,
            pot=pot_conf,
            stack=stack_conf,
            actions=actions_conf,
            notes=(
                "legacy_ocr_bridge",
                "derived_confidence",
            ),
        )
        spot_id = str(
            getattr(table, "GameID", "")
            or getattr(table, "game_id", "")
            or f"{source}:{game_stage}:{'-'.join(board) if board else 'pre'}"
        )
        ocr_metadata.setdefault("confidence", overall_confidence)

        return cls(
            spot_id=spot_id,
            source=source,
            game_stage=game_stage,
            hero_cards=hero_cards,
            board=board,
            hero_position=hero_position,
            positions=positions,
            pot=pot,
            stack=stack,
            legal_actions=tuple(dict.fromkeys(legal_actions)),
            action_history=action_history,
            hero_range="",
            villain_ranges=(),
            state_confidence=overall_confidence,
            ocr_confidence=confidence_report,
            range_model_version=RangeModelVersion.BOARD_AWARE_V2,
            ocr_metadata=ocr_metadata,
            metadata={
                "table_name": getattr(table, "table_name", ""),
                "is_heads_up": _as_bool(getattr(table, "isHeadsUp", False)),
                "source": source,
            },
        )

    @classmethod
    def from_legacy_json(cls, payload: str) -> "SpotSnapshot":
        return cls.from_dict(json.loads(payload))


@dataclass
class DecisionSnapshot(SerializableDataclass):
    action: str = ""
    alternatives: tuple[ActionEstimate, ...] = ()
    ev_by_action: dict[str, float] = field(default_factory=dict)
    exploitability: float = 0.0
    source: str = "legacy"
    warnings: tuple[str, ...] = ()
    latency_ms: int = 0
    confidence: float = 0.0
    gate_result: DecisionGateResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "DecisionSnapshot":
        payload = payload or {}
        alternatives = payload.get("alternatives", [])
        if alternatives is None:
            alternatives = []
        return cls(
            action=str(payload.get("action", "")),
            alternatives=tuple(
                ActionEstimate.from_dict(item) if not isinstance(item, ActionEstimate) else item
                for item in alternatives
            ),
            ev_by_action={str(key): _as_float(value) for key, value in _as_any_dict(payload.get("ev_by_action")).items()},
            exploitability=_as_float(payload.get("exploitability", 0.0)),
            source=str(payload.get("source", "legacy")),
            warnings=_as_tuple(payload.get("warnings")),
            latency_ms=_as_int(payload.get("latency_ms", 0)),
            confidence=_as_float(payload.get("confidence", 0.0)),
            gate_result=(
                payload.get("gate_result")
                if isinstance(payload.get("gate_result"), DecisionGateResult)
                else (
                    DecisionGateResult.from_dict(payload.get("gate_result"))
                    if isinstance(payload.get("gate_result"), dict)
                    else None
                )
            ),
            metadata=_as_any_dict(payload.get("metadata")),
        )

    @classmethod
    def from_legacy(cls, decision: Any, source: str = "legacy") -> "DecisionSnapshot":
        action = str(getattr(decision, "decision", ""))
        alternatives = getattr(decision, "alternatives", None) or getattr(decision, "actions", None) or []
        ev_map = getattr(decision, "ev_by_action", None) or getattr(decision, "evs", None) or {}
        warnings = getattr(decision, "warnings", None) or []
        return cls(
            action=action,
            alternatives=tuple(
                item if isinstance(item, ActionEstimate) else ActionEstimate.from_dict(item)
                for item in alternatives
            ),
            ev_by_action={str(key): _as_float(value) for key, value in _as_any_dict(ev_map).items()},
            exploitability=_as_float(getattr(decision, "exploitability", 0.0)),
            source=source,
            warnings=_as_tuple(warnings),
            latency_ms=_as_int(getattr(decision, "latency_ms", getattr(decision, "elapsed_ms", 0))),
            confidence=_as_float(getattr(decision, "confidence", 0.0)),
            gate_result=(
                getattr(decision, "gate_result")
                if isinstance(getattr(decision, "gate_result", None), DecisionGateResult)
                else (
                    DecisionGateResult.from_dict(getattr(decision, "gate_result"))
                    if isinstance(getattr(decision, "gate_result", None), dict)
                    else None
                )
            ),
            metadata=_as_any_dict(getattr(decision, "metadata", {})),
        )


@dataclass
class SolveRequestV2(SerializableDataclass):
    spot_id: str = ""
    hero_range: str = ""
    villain_ranges: tuple[str, ...] = ()
    board: tuple[str, ...] = ()
    starting_pot: float = 0.0
    effective_stack: float = 0.0
    hero_position: str = ""
    action_history: tuple[str, ...] = ()
    tree_preset_id: str = ""
    rake: float = 0.0
    num_players: int = 2
    legal_actions: tuple[ActionOptionV2, ...] = ()
    cache_policy: CachePolicy = CachePolicy.MEMORY
    hero_confidence: float = 0.0
    state_confidence: float = 0.0
    range_model_version: RangeModelVersion = RangeModelVersion.BOARD_AWARE_V2
    use_cache: bool = True
    time_budget_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "SolveRequestV2":
        payload = payload or {}
        return cls(
            spot_id=str(_payload_get(payload, "spot_id", "spotId", default="")),
            hero_range=str(_payload_get(payload, "hero_range", "heroRange", default="")),
            villain_ranges=_as_tuple(
                _payload_get(payload, "villain_ranges", "villainRanges")
            ),
            board=_as_tuple(_payload_get(payload, "board")),
            starting_pot=_as_float(
                _payload_get(payload, "starting_pot", "startingPot", default=0.0)
            ),
            effective_stack=_as_float(
                _payload_get(payload, "effective_stack", "effectiveStack", default=0.0)
            ),
            hero_position=str(
                _payload_get(payload, "hero_position", "heroPosition", default="")
            ),
            action_history=_as_tuple(
                _payload_get(payload, "action_history", "actionHistory")
            ),
            tree_preset_id=str(
                _payload_get(payload, "tree_preset_id", "treePresetId", default="")
            ),
            rake=_as_float(_payload_get(payload, "rake", default=0.0)),
            num_players=_as_int(
                _payload_get(payload, "num_players", "numPlayers", default=2), default=2
            ),
            legal_actions=tuple(
                ActionOptionV2.from_dict(item)
                for item in (_payload_get(payload, "legal_actions", "legalActions", default=()) or ())
            ),
            cache_policy=_coerce_cache_policy(
                _payload_get(payload, "cache_policy", "cachePolicy")
            ),
            hero_confidence=_as_float(
                _payload_get(payload, "hero_confidence", "heroConfidence", default=0.0)
            ),
            state_confidence=_as_float(
                _payload_get(payload, "state_confidence", "stateConfidence", default=0.0)
            ),
            range_model_version=_coerce_range_model_version(
                _payload_get(payload, "range_model_version", "rangeModelVersion")
            ),
            use_cache=_as_bool(
                _payload_get(payload, "use_cache", "useCache", default=True), default=True
            ),
            time_budget_ms=_as_int(
                _payload_get(payload, "time_budget_ms", "timeBudgetMs", default=0)
            ),
            metadata=_as_any_dict(_payload_get(payload, "metadata")),
        )


@dataclass
class SolveResponseV2(SerializableDataclass):
    chosen_action: str = ""
    actions: tuple[ActionEstimate, ...] = ()
    hero_ev: float = 0.0
    exploitability: float = 0.0
    backend: str = "native"
    cache_tier: CacheTier = CacheTier.NONE
    normalized_ranges: tuple[str, ...] = ()
    decision_confidence: float = 0.0
    fallback_reason: str = ""
    cache_hit: bool = False
    elapsed_ms: int = 0
    preset_id: str = ""
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "SolveResponseV2":
        payload = payload or {}
        actions = _payload_get(payload, "actions", default=[])
        if actions is None:
            actions = []
        return cls(
            chosen_action=str(
                _payload_get(
                    payload,
                    "chosen_action",
                    "chosenAction",
                    "recommended_action",
                    "recommendedAction",
                    "action",
                    "selected_action",
                    "selectedAction",
                    default="",
                )
            ),
            actions=tuple(
                ActionEstimate.from_dict(item) if not isinstance(item, ActionEstimate) else item
                for item in actions
            ),
            hero_ev=_as_float(_payload_get(payload, "hero_ev", "heroEv", default=0.0)),
            exploitability=_as_float(_payload_get(payload, "exploitability", default=0.0)),
            backend=str(_payload_get(payload, "backend", default="native")),
            cache_tier=_coerce_cache_tier(
                _payload_get(payload, "cache_tier", "cacheTier")
            ),
            normalized_ranges=_as_tuple(
                _payload_get(payload, "normalized_ranges", "normalizedRanges")
            ),
            decision_confidence=_as_float(
                _payload_get(payload, "decision_confidence", "decisionConfidence", default=0.0)
            ),
            fallback_reason=str(
                _payload_get(payload, "fallback_reason", "fallbackReason", default="")
            ),
            cache_hit=_as_bool(_payload_get(payload, "cache_hit", "cacheHit", default=False)),
            elapsed_ms=_as_int(_payload_get(payload, "elapsed_ms", "elapsedMs", default=0)),
            preset_id=str(_payload_get(payload, "preset_id", "presetId", default="")),
            warnings=_as_tuple(_payload_get(payload, "warnings")),
            metadata=_as_any_dict(_payload_get(payload, "metadata")),
        )


@dataclass
class ReplayRecord(SerializableDataclass):
    replay_id: str = ""
    spot: SpotSnapshot = field(default_factory=SpotSnapshot)
    decision: DecisionSnapshot = field(default_factory=DecisionSnapshot)
    result_metadata: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: Any) -> "ReplayRecord":
        payload = payload or {}
        return cls(
            replay_id=str(payload.get("replay_id", payload.get("replayId", ""))),
            spot=SpotSnapshot.from_dict(payload.get("spot")),
            decision=DecisionSnapshot.from_dict(payload.get("decision")),
            result_metadata=_as_any_dict(payload.get("result_metadata")),
            tags=_as_tuple(payload.get("tags")),
        )


@dataclass
class BenchmarkResult(SerializableDataclass):
    name: str = ""
    backend: str = ""
    metric: str = ""
    score: float = 0.0
    elapsed_ms: int = 0
    passed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "BenchmarkResult":
        payload = payload or {}
        return cls(
            name=str(payload.get("name", "")),
            backend=str(payload.get("backend", "")),
            metric=str(payload.get("metric", "")),
            score=_as_float(payload.get("score", 0.0)),
            elapsed_ms=_as_int(payload.get("elapsed_ms", payload.get("elapsedMs", 0))),
            passed=_as_bool(payload.get("passed", False), default=False),
            metadata=_as_any_dict(payload.get("metadata")),
        )


def _default_roles_enabled() -> dict[str, bool]:
    return {
        "analysis": False,
        "operator_assistance": False,
        "strategy_coach": False,
        "replay_coach": False,
    }


def _default_context_scopes_enabled() -> dict[str, bool]:
    return {
        "spot": False,
        "decision": False,
        "runtime": False,
        "ocr": False,
        "replay": False,
    }


@dataclass
class LlmConfig(SerializableDataclass):
    enabled: bool = False
    provider_mode: LlmProviderMode = LlmProviderMode.DISABLED
    base_url: str = ""
    api_key_ref: str | None = None
    model: str = ""
    temperature: float = 0.0
    max_output_tokens: int = 0
    streaming: bool = False
    roles_enabled: dict[str, bool] = field(default_factory=_default_roles_enabled)
    context_scopes_enabled: dict[str, bool] = field(default_factory=_default_context_scopes_enabled)
    privacy_mode: str = "strict_local"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def disabled_default(cls) -> "LlmConfig":
        return cls()

    @classmethod
    def from_dict(cls, payload: Any) -> "LlmConfig":
        payload = payload or {}
        return cls(
            enabled=_as_bool(_payload_get(payload, "enabled", default=False), default=False),
            provider_mode=_coerce_provider_mode(
                _payload_get(payload, "provider_mode", "providerMode")
            ),
            base_url=str(_payload_get(payload, "base_url", "baseUrl", default="")),
            api_key_ref=_payload_get(payload, "api_key_ref", "apiKeyRef"),
            model=str(_payload_get(payload, "model", default="")),
            temperature=_as_float(_payload_get(payload, "temperature", default=0.0)),
            max_output_tokens=_as_int(
                _payload_get(payload, "max_output_tokens", "maxOutputTokens", default=0)
            ),
            streaming=_as_bool(_payload_get(payload, "streaming", default=False)),
            roles_enabled=_merge_bool_map(
                _default_roles_enabled(),
                _payload_get(payload, "roles_enabled", "rolesEnabled"),
            ),
            context_scopes_enabled=_merge_bool_map(
                _default_context_scopes_enabled(),
                _payload_get(payload, "context_scopes_enabled", "contextScopesEnabled"),
            ),
            privacy_mode=str(
                _payload_get(payload, "privacy_mode", "privacyMode", default="strict_local")
            ),
            metadata=_as_any_dict(_payload_get(payload, "metadata")),
        )

    def is_enabled(self) -> bool:
        return self.enabled and self.provider_mode != LlmProviderMode.DISABLED


@dataclass
class LlmAssistTask(SerializableDataclass):
    task_type: LlmAssistTaskType = LlmAssistTaskType.SPOT_EXPLAIN
    prompt: str = ""
    spot: SpotSnapshot | None = None
    decision: DecisionSnapshot | None = None
    context: dict[str, Any] = field(default_factory=dict)
    role: str = ""
    temperature_override: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "LlmAssistTask":
        payload = payload or {}
        spot = _payload_get(payload, "spot")
        decision = _payload_get(payload, "decision")
        return cls(
            task_type=_coerce_task_type(
                _payload_get(payload, "task_type", "taskType", "kind")
            ),
            prompt=str(
                _payload_get(
                    payload,
                    "prompt",
                    "instruction",
                    "context_summary",
                    default="",
                )
            ),
            spot=SpotSnapshot.from_dict(spot) if isinstance(spot, dict) else spot,
            decision=DecisionSnapshot.from_dict(decision) if isinstance(decision, dict) else decision,
            context=_as_any_dict(_payload_get(payload, "context")),
            role=str(_payload_get(payload, "role", default="")),
            temperature_override=(
                None
                if _payload_get(payload, "temperature_override", "temperatureOverride") in (None, "")
                else _as_float(_payload_get(payload, "temperature_override", "temperatureOverride"))
            ),
            metadata=_as_any_dict(_payload_get(payload, "metadata")),
        )


@dataclass
class LlmAssistResponse(SerializableDataclass):
    summary: str = ""
    recommendations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    confidence: float = 0.0
    used_context: tuple[str, ...] = ()
    latency_ms: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Any) -> "LlmAssistResponse":
        payload = payload or {}
        return cls(
            summary=str(_payload_get(payload, "summary", default="")),
            recommendations=_as_tuple(_payload_get(payload, "recommendations")),
            warnings=_as_tuple(_payload_get(payload, "warnings")),
            confidence=_as_float(_payload_get(payload, "confidence", default=0.0)),
            used_context=_as_tuple(_payload_get(payload, "used_context", "usedContext")),
            latency_ms=_as_int(_payload_get(payload, "latency_ms", "latencyMs", default=0)),
            provider_metadata=_as_any_dict(
                _payload_get(payload, "provider_metadata", "providerMetadata")
            ),
            raw_text=str(_payload_get(payload, "raw_text", "rawText", default="")),
            metadata=_as_any_dict(_payload_get(payload, "metadata")),
        )


def _coerce_provider_mode(value: Any) -> LlmProviderMode:
    if isinstance(value, LlmProviderMode):
        return value
    if isinstance(value, str):
        try:
            return LlmProviderMode(value)
        except ValueError:
            return LlmProviderMode.DISABLED
    return LlmProviderMode.DISABLED


def _coerce_cache_policy(value: Any) -> CachePolicy:
    if isinstance(value, CachePolicy):
        return value
    if isinstance(value, str):
        try:
            return CachePolicy(value)
        except ValueError:
            return CachePolicy.MEMORY
    return CachePolicy.MEMORY


def _coerce_cache_tier(value: Any) -> CacheTier:
    if isinstance(value, CacheTier):
        return value
    if isinstance(value, str):
        try:
            return CacheTier(value)
        except ValueError:
            return CacheTier.NONE
    return CacheTier.NONE


def _coerce_range_model_version(value: Any) -> RangeModelVersion:
    if isinstance(value, RangeModelVersion):
        return value
    if isinstance(value, str):
        try:
            return RangeModelVersion(value)
        except ValueError:
            return RangeModelVersion.BOARD_AWARE_V2
    return RangeModelVersion.BOARD_AWARE_V2


def _coerce_task_type(value: Any) -> LlmAssistTaskType:
    if isinstance(value, LlmAssistTaskType):
        return value
    if isinstance(value, str):
        try:
            return LlmAssistTaskType(value)
        except ValueError:
            return LlmAssistTaskType.SPOT_EXPLAIN
    return LlmAssistTaskType.SPOT_EXPLAIN


def _extract_history(history: Any) -> tuple[str, ...]:
    if history is None:
        return ()
    for attr in ("action_history", "history", "actions", "last_actions", "hand_actions"):
        value = getattr(history, attr, None)
        if value:
            if isinstance(value, dict):
                return tuple(str(item) for item in value.values())
            if isinstance(value, (list, tuple, set)):
                return tuple(str(item) for item in value if item not in (None, ""))
            return (str(value),)
    return ()


def build_default_llm_config() -> LlmConfig:
    return LlmConfig.disabled_default()


def build_mock_spot_snapshot() -> SpotSnapshot:
    return SpotSnapshot(
        spot_id="mock-spot-001",
        source="mock",
        game_stage="Flop",
        hero_cards=("As", "Kd"),
        board=("Qh", "7s", "2c"),
        hero_position="BTN",
        positions={"hero": "BTN", "villain": "BB"},
        pot=12.5,
        stack=87.5,
        legal_actions=("check", "bet", "fold", "call"),
        action_history=("preflop:raise", "flop:check"),
        hero_range="AsKd",
        villain_ranges=("22+,A2s+,K9s+,QTs+,JTs,ATo+",),
        state_confidence=0.97,
        ocr_confidence=OcrConfidenceReport(
            overall=0.97,
            hero_cards=1.0,
            board=1.0,
            pot=0.92,
            stack=0.95,
            actions=0.98,
            notes=("mock_capture",),
        ),
        range_model_version=RangeModelVersion.CALIBRATED_V3,
        ocr_metadata={"source": "mock", "confidence": 1.0},
        metadata={"scenario": "mock_spot"},
    )


def build_mock_gate_result() -> DecisionGateResult:
    return DecisionGateResult(
        allowed=True,
        confidence=0.94,
        reason="ready",
        warnings=(),
        metadata={"source": "mock_gate"},
    )


def build_mock_decision_snapshot() -> DecisionSnapshot:
    return DecisionSnapshot(
        action="bet",
        alternatives=(
            ActionEstimate(name="check", size=0.0, frequency=0.45, ev=0.12),
            ActionEstimate(name="bet", size=0.5, frequency=0.55, ev=0.34),
        ),
        ev_by_action={"check": 0.12, "bet": 0.34},
        exploitability=0.08,
        source="mock",
        warnings=(),
        latency_ms=18,
        confidence=0.91,
        gate_result=build_mock_gate_result(),
        metadata={
            "scenario": "mock_decision",
            "explanation": "Betting keeps the initiative on a range-advantaged flop and preserves a clear fallback path.",
            "fallback_history": [],
            "warning_history": [],
        },
    )


def build_mock_replay_record() -> ReplayRecord:
    return ReplayRecord(
        replay_id="mock-replay-001",
        spot=build_mock_spot_snapshot(),
        decision=build_mock_decision_snapshot(),
        result_metadata={"result_bb": 3.4, "outcome": "won"},
        tags=("mock", "srp_hu_100bb"),
    )


def build_mock_benchmark_result() -> BenchmarkResult:
    return BenchmarkResult(
        name="native_vs_oracle",
        backend="native",
        metric="equity_parity",
        score=0.999,
        elapsed_ms=23,
        passed=True,
        metadata={"oracle": "pokerkit"},
    )


def build_mock_benchmark_catalog_entry() -> dict[str, Any]:
    benchmark = build_mock_benchmark_result()
    return {
        "id": benchmark.name,
        "label": "Native vs Oracle",
        "status": "ready" if benchmark.passed else "blocked",
        "score": benchmark.score,
        "backend": benchmark.backend,
    }


def build_mock_llm_task() -> LlmAssistTask:
    return LlmAssistTask(
        task_type=LlmAssistTaskType.SPOT_EXPLAIN,
        prompt="Explain the mock spot and the main strategic trade-off.",
        spot=build_mock_spot_snapshot(),
        decision=build_mock_decision_snapshot(),
        context={"surface": "solver_studio"},
        role="analysis",
        temperature_override=None,
        metadata={"scenario": "mock_task"},
    )


def build_mock_llm_assist_payload(request_payload: Any = None) -> dict[str, Any]:
    payload = request_payload or {}
    if not isinstance(payload, dict):
        payload = {}
    task_name = str(payload.get("task") or payload.get("task_type") or "spot_explain")
    prompt = str(payload.get("prompt") or payload.get("context_summary") or payload.get("notes") or "")
    tags = _as_tuple(payload.get("tags"))
    return {
        "summary": f"Local mock copilot response for {task_name}.",
        "recommendations": [
            "Keep the deterministic solver as the decision authority.",
            "Use the copilot output as explanatory help, not as the action source.",
        ],
        "warnings": [],
        "confidence": 0.18,
        "used_context": [task_name, *tags],
        "latency_ms": 0,
        "provider_metadata": {
            "source": "local_rest_mock",
            "provider_mode": "disabled",
        },
        "raw_text": prompt,
    }


def build_mock_solve_response_payload(request_payload: Any = None) -> dict[str, Any]:
    payload = request_payload or {}
    if not isinstance(payload, dict):
        payload = {}

    if any(
        key in payload
        for key in ("hero_range", "heroRange", "villain_ranges", "villainRanges")
    ):
        request = SolveRequestV2.from_dict(payload)
    else:
        hero_is_oop = _as_bool(payload.get("hero_is_oop"), default=True)
        request = SolveRequestV2(
            spot_id=str(payload.get("spot_id", "")),
            hero_range=str(payload.get("oop_range" if hero_is_oop else "ip_range", "")),
            villain_ranges=(
                str(payload.get("ip_range" if hero_is_oop else "oop_range", "")),
            ),
            board=_as_tuple(payload.get("board")),
            starting_pot=_as_float(payload.get("starting_pot", 0.0)),
            effective_stack=_as_float(payload.get("effective_stack", 0.0)),
            hero_position="oop" if hero_is_oop else "ip",
            action_history=(),
            tree_preset_id="srp_hu_100bb",
            rake=0.0,
            num_players=2,
            legal_actions=tuple(
                ActionOptionV2.from_dict(item)
                for item in payload.get("legal_actions", ("check", "bet", "call", "fold"))
            ),
            cache_policy=CachePolicy.PERSISTENT,
            hero_confidence=1.0,
            state_confidence=0.95,
            range_model_version=RangeModelVersion.BOARD_AWARE_V2,
            use_cache=True,
            time_budget_ms=0,
            metadata={
                "legacy_payload": True,
                "max_iterations": payload.get("max_iterations"),
                "target_exploitability": payload.get("target_exploitability"),
            },
        )

    board_len = len(request.board)
    hero_is_oop = request.hero_position.lower() in {"oop", "sb", "bb"}
    fallback = False
    warnings: list[str] = []

    if request.num_players != 2:
        fallback = True
        warnings.extend(["unsupported_spot", "multiway_approximation", "fallback_used"])

    if not request.hero_range or not any(item.strip() for item in request.villain_ranges):
        fallback = True
        warnings.extend(["approximate_ranges", "fallback_used"])

    if board_len >= 5:
        chosen_action = "check" if hero_is_oop else "bet_75"
        actions = [
            {"name": "check", "label": "Check", "size": 0.0, "frequency": 0.42, "ev": 0.18},
            {"name": "bet_75", "label": "Bet 75%", "size": 0.75, "frequency": 0.58, "ev": 0.26},
        ]
    elif board_len >= 3:
        chosen_action = "check" if hero_is_oop else "bet_50"
        actions = [
            {"name": "check", "label": "Check", "size": 0.0, "frequency": 0.36, "ev": 0.12},
            {"name": "bet_50", "label": "Bet 50%", "size": 0.5, "frequency": 0.64, "ev": 0.24},
        ]
    else:
        chosen_action = "call" if request.starting_pot > 0 else "check"
        actions = [
            {"name": "check", "label": "Check", "size": 0.0, "frequency": 0.35, "ev": 0.03},
            {"name": "call", "label": "Call", "size": None, "frequency": 0.65, "ev": 0.07},
        ]

    for action in actions:
        action["is_recommended"] = action["name"] == chosen_action

    hero_ev = max(0.0, round(0.08 + (0.04 * min(board_len, 5)), 3))
    exploitability = round(0.45 if fallback else 0.08, 3)
    elapsed_ms = request.time_budget_ms or (48 if not fallback else 12)

    return {
        "chosen_action": chosen_action,
        "recommended_action": chosen_action,
        "action": chosen_action,
        "actions": actions,
        "hero_ev": hero_ev,
        "exploitability": exploitability,
        "backend": "native" if not fallback else "fallback",
        "cache_tier": "memory" if request.use_cache and not fallback else "none",
        "normalized_ranges": (request.hero_range, *request.villain_ranges),
        "decision_confidence": 0.9 if not fallback else 0.25,
        "fallback_reason": "" if not fallback else "unsupported_v2_spot",
        "cache_hit": bool(request.use_cache and not fallback),
        "elapsed_ms": int(elapsed_ms),
        "preset_id": request.tree_preset_id or "srp_hu_100bb",
        "warnings": tuple(dict.fromkeys(warnings)),
        "metadata": {
            "source": "local_rest_mock",
            "request_echo": request.to_dict(),
            "hero_is_oop": hero_is_oop,
            "explanation": "Structured mock solve with explicit fallback metadata for UI inspection.",
        },
    }


def build_mock_replay_analytics_payload() -> dict[str, Any]:
    spot_snapshot = build_mock_spot_snapshot()
    decision_snapshot = build_mock_decision_snapshot()
    return {
        "session_id": "mock-session-042",
        "table_name": "Local Test Table",
        "hands_indexed": 24812,
        "tagged_leaks": 18,
        "saved_spots": 412,
        "session_trend_bb": 12.4,
        "best_hour_bb": 18.1,
        "leak_clusters": [
            {
                "id": "turn_probe_overfold",
                "label": "Turn probe overfold",
                "hands": 7,
                "severity": "warning",
            },
            {
                "id": "river_bluffcatch",
                "label": "River bluff-catch hesitation",
                "hands": 4,
                "severity": "info",
            },
        ],
        "timeline": [
            {
                "id": "hand-1001",
                "street": spot_snapshot.game_stage.lower(),
                "result_bb": 3.4,
                "label": "BTN vs BB single-raised pot",
                "spot_snapshot": spot_snapshot.to_dict(),
                "decision_snapshot": decision_snapshot.to_dict(),
            },
            {
                "id": "hand-1002",
                "street": "turn",
                "result_bb": -1.2,
                "label": "Turn probe defended late",
                "spot_snapshot": spot_snapshot.to_dict(),
                "decision_snapshot": decision_snapshot.to_dict(),
            },
        ],
    }


def build_mock_config_lab_payload() -> dict[str, Any]:
    llm_config = build_default_llm_config()
    return {
        "preset_packs": [
            {
                "id": "srp_hu_100bb",
                "label": "SRP HU 100bb",
                "family": "srp",
                "status": "active",
            },
            {
                "id": "turn_probe_hu",
                "label": "Turn Probe HU",
                "family": "turn",
                "status": "active",
            },
        ],
        "backends": [
            {
                "id": "native",
                "label": "Native Rust",
                "ready": True,
                "kind": "primary",
            },
            {
                "id": "http",
                "label": "HTTP fallback",
                "ready": True,
                "kind": "fallback",
            },
            {
                "id": "oracle",
                "label": "Oracle benchmark backend",
                "ready": False,
                "kind": "validation",
            },
        ],
        "privacy_mode": llm_config.privacy_mode,
        "llm_enabled": llm_config.enabled,
        "llm_config": llm_config.to_dict(),
        "benchmarks": [
            {
                "id": "pokerkit",
                "label": "PokerKit validation",
                "status": "ready",
            },
            {
                "id": "rlcard",
                "label": "RLCard lab",
                "status": "ready",
            },
            build_mock_benchmark_catalog_entry(),
        ],
    }


def _enabled_flag_keys(flags: dict[str, bool]) -> list[str]:
    return [key for key, enabled in flags.items() if enabled]


def build_mock_ocr_snapshot() -> dict[str, Any]:
    return {
        "confidence": 0.96,
        "drift": "stable",
        "frame_label": "mock-frame-001",
        "report": build_mock_spot_snapshot().ocr_confidence.to_dict(),
        "notes": [
            "OCR pipeline is stable in local mock mode.",
            "Card and pot regions are aligned.",
        ],
        "source": "local_rest",
    }


def build_mock_operator_snapshot() -> dict[str, Any]:
    return {
        "profile_name": "local-operator",
        "surface": "bot_cockpit",
        "capture_source": "runtime_snapshot",
        "auto_refresh_enabled": True,
        "shadow_mode_enabled": False,
        "manual_override_enabled": False,
        "paused": False,
        "status": "ready",
    }


def build_suite_samples() -> dict[str, Any]:
    llm_config = build_default_llm_config()
    spot_snapshot = build_mock_spot_snapshot()
    decision_snapshot = build_mock_decision_snapshot()
    llm_task = build_mock_llm_task()
    return {
        "llm_config": llm_config.to_dict(),
        "spot_snapshot": spot_snapshot.to_dict(),
        "decision_snapshot": decision_snapshot.to_dict(),
        "llm_task": llm_task.to_dict(),
        "decision_gate": build_mock_gate_result().to_dict(),
        "replay_record": build_mock_replay_record().to_dict(),
        "benchmark_result": build_mock_benchmark_result().to_dict(),
        "replay_analytics": build_mock_replay_analytics_payload(),
        "config_lab": build_mock_config_lab_payload(),
    }


def build_mock_bot_cockpit_payload(
    service_name: str = "poker-restapi-local",
    endpoint: str = "/bot-cockpit/payload",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    llm_config = build_default_llm_config()
    spot_snapshot = build_mock_spot_snapshot()
    decision_snapshot = build_mock_decision_snapshot()
    ocr_snapshot = build_mock_ocr_snapshot()
    warnings: list[str] = []
    if ocr_snapshot["confidence"] < 0.7:
        warnings.append("ocr_low_confidence")
    return {
        "state": "live",
        "source": "local_rest",
        "message": "Bot cockpit live on local_rest.",
        "runtime": {
            "app_name": service_name,
            "version": "v2",
            "runtime": "local_rest",
            "dev_mode": False,
            "http_fallback_enabled": True,
            "healthy": True,
            "status": "ok",
            "uptime_ms": 0,
            "llm": {
                "enabled": llm_config.enabled,
                "provider_mode": llm_config.provider_mode.value,
                "base_url": llm_config.base_url,
                "model": llm_config.model,
                "privacy_mode": llm_config.privacy_mode,
            },
        },
        "spot": spot_snapshot.to_dict(),
        "decision": decision_snapshot.to_dict(),
        "ocr": ocr_snapshot,
        "operator": build_mock_operator_snapshot(),
        "signals": [
            {"label": "Runtime", "value": "local_rest", "note": "Dedicated cockpit payload"},
            {"label": "OCR", "value": "96%", "note": "Stable mock capture"},
            {"label": "Decision", "value": decision_snapshot.action, "note": "Mock action trace"},
        ],
        "warnings": warnings,
        "notes": [
            "Dedicated cockpit payload for the premium suite.",
            "The deterministic decision path remains primary.",
        ],
        "transport": {
            "endpoint": endpoint,
            "source": "local_rest",
            "reachable": True,
            "httpStatus": 200,
        },
        "refreshedAt": now,
    }


def build_replay_analytics_surface_payload(
    service_name: str = "poker-restapi-local",
    endpoint: str = "/replay-analytics/payload",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    samples = build_suite_samples()
    replay_payload = build_mock_replay_analytics_payload()
    decision_snapshot = build_mock_decision_snapshot()
    leak_clusters = replay_payload.get("leak_clusters", [])
    timeline = replay_payload.get("timeline", [])
    highlights = [
        {
            "id": str(cluster.get("id", f"highlight-{index + 1}")),
            "title": str(cluster.get("label", f"Replay highlight {index + 1}")),
            "street": str(timeline[index].get("street", "unknown")) if index < len(timeline) else "unknown",
            "result": (
                f"{timeline[index].get('result_bb', 0.0):+.1f} bb"
                if index < len(timeline)
                else "n/a"
            ),
            "confidence": 0.9 if str(cluster.get("severity", "")) == "warning" else 0.78,
            "tags": [str(cluster.get("id", f"cluster-{index + 1}"))],
            "note": f"{cluster.get('hands', 0)} tagged hand(s) in the current replay cluster.",
        }
        for index, cluster in enumerate(leak_clusters)
    ]
    return {
        "kind": "replay_analytics",
        "status": "ready",
        "source": "runtime",
        "refreshedAt": now,
        "runtime": {
            "connected": True,
            "transport": "rest",
            "endpoint": endpoint,
            "refreshedAt": now,
            "raw": {"service": service_name},
        },
        "summary": {
            "totalSessions": 1,
            "totalHands": replay_payload["hands_indexed"],
            "analyzedHands": replay_payload["saved_spots"],
            "totalWinningsBb": replay_payload["best_hour_bb"],
            "evBbPer100": replay_payload["session_trend_bb"],
            "winRateBbPer100": replay_payload["best_hour_bb"],
            "p95LatencyMs": decision_snapshot.latency_ms,
            "fallbackRate": 0.0,
        },
        "highlights": highlights,
        "filters": {
            "room": "all",
            "hero": "hero",
            "dateRange": "latest_local_run",
            "presetIds": ["srp_hu_100bb", "turn_probe_hu"],
            "tags": [str(cluster.get("id", "")) for cluster in leak_clusters if cluster.get("id")],
        },
        "warnings": [],
        "recommendations": [
            "Open the turn probe cluster first and compare it against the current tree preset.",
            "Promote the highest-confidence replay node into Solver Studio for deeper review.",
        ],
        "notes": [
            "Dedicated replay analytics payload served from the local runtime.",
            "This route mirrors the workstation happy path more closely than /runtime-snapshot.",
        ],
        "samples": {"replay_analytics": replay_payload, "decision_snapshot": samples["decision_snapshot"]},
    }


def build_config_lab_surface_payload(
    service_name: str = "poker-restapi-local",
    endpoint: str = "/config-lab/payload",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    llm_config = build_default_llm_config()
    llm_payload = llm_config.to_dict()
    config_payload = build_mock_config_lab_payload()
    preset_packs = config_payload["preset_packs"]
    benchmarks = config_payload["benchmarks"]
    selected_preset_id = str(preset_packs[0]["id"]) if preset_packs else "srp_hu_100bb"
    available_preset_ids = [str(preset["id"]) for preset in preset_packs if preset.get("id")]
    return {
        "kind": "config_lab",
        "status": "ready",
        "source": "runtime",
        "refreshedAt": now,
        "runtime": {
            "connected": True,
            "transport": "rest",
            "endpoint": endpoint,
            "refreshedAt": now,
            "raw": {"service": service_name},
        },
        "llm": {
            "enabled": llm_payload["enabled"],
            "providerMode": llm_payload["provider_mode"],
            "baseUrl": llm_payload["base_url"],
            "apiKeyRef": llm_payload["api_key_ref"] or "",
            "model": llm_payload["model"],
            "temperature": llm_payload["temperature"],
            "maxOutputTokens": llm_payload["max_output_tokens"],
            "streaming": llm_payload["streaming"],
            "rolesEnabled": _enabled_flag_keys(llm_payload["roles_enabled"]),
            "contextScopesEnabled": _enabled_flag_keys(llm_payload["context_scopes_enabled"]),
            "privacyMode": llm_payload["privacy_mode"],
        },
        "solver": {
            "selectedPresetId": selected_preset_id,
            "availablePresetIds": available_preset_ids,
            "treeCompression": "balanced",
            "timeBudgetMs": 2500,
            "cacheEnabled": True,
        },
        "privacy": {
            "strictLocal": llm_payload["privacy_mode"] == "strict_local",
            "redactedRemote": llm_payload["privacy_mode"] == "redacted_remote",
            "fullRemote": llm_payload["privacy_mode"] == "full_remote",
        },
        "benchmarks": [
            {
                "id": str(entry.get("id", f"benchmark-{index + 1}")),
                "name": str(entry.get("label", f"Benchmark {index + 1}")),
                "status": str(entry.get("status", "ready")),
                "score": 1.0 if str(entry.get("status", "ready")) == "ready" else 0.0,
                "note": f"{entry.get('label', 'Benchmark')} is available in local mock mode.",
            }
            for index, entry in enumerate(benchmarks)
        ],
        "warnings": [],
        "recommendations": [
            "Keep strict-local privacy mode as the default operating posture.",
            "Use the benchmark suite to validate parity before enabling optional copilot flows.",
        ],
        "samples": {"config_lab": config_payload},
    }


def build_runtime_snapshot(service_name: str = "poker-restapi-local") -> dict[str, Any]:
    """Return a local-only runtime snapshot for the future suite integration."""
    now = datetime.now(timezone.utc).isoformat()
    llm_config = build_default_llm_config()
    samples = build_suite_samples()
    return {
        "service": service_name,
        "api_version": "v2",
        "package_version": _safe_package_version(),
        "timestamp_utc": now,
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "process_id": os.getpid(),
            "cwd": os.getcwd(),
        },
        "llm": {
            "enabled": llm_config.enabled,
            "provider_mode": llm_config.provider_mode.value,
            "privacy_mode": llm_config.privacy_mode,
        },
        "samples": samples,
    }


def build_mock_config_payload() -> dict[str, Any]:
    return build_suite_samples()


def build_health_payload() -> dict[str, Any]:
    config = build_default_llm_config()
    return {
        "status": "ok",
        "service": "poker-restapi-local",
        "api_version": "v2",
        "llm_enabled": config.is_enabled(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_version_payload() -> dict[str, Any]:
    return {
        "service": "poker-restapi-local",
        "api_version": "v2",
        "package_version": _safe_package_version(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    }
