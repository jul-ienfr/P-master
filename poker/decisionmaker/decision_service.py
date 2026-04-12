"""Canonical V2 decision orchestration for live and offline workflows."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

from poker.decisionmaker.v2_contracts import (
    ActionOptionV2,
    BenchmarkResult,
    CachePolicy,
    CacheTier,
    DecisionGateResult,
    DecisionSnapshot,
    RangeModelVersion,
    ReplayRecord,
    SolveRequestV2,
    SolveResponseV2,
    SpotSnapshot,
)
from poker.decisionmaker.tree_presets import build_prewarm_requests, preset_catalog_payload

logger = logging.getLogger(__name__)

DEFAULT_SOLVER_CACHE_DIR = (
    Path(__file__).resolve().parents[1] / ".cache" / "solver_v2"
)


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _range_fingerprint(request: SolveRequestV2) -> tuple[str, ...]:
    villain_ranges = tuple(item.strip() for item in request.villain_ranges if str(item).strip())
    return tuple(item for item in (request.hero_range.strip(), *villain_ranges) if item)


def _request_cache_key(request: SolveRequestV2) -> str:
    payload = request.to_dict()
    payload["villain_ranges"] = list(_range_fingerprint(request)[1:])
    payload["hero_range"] = _range_fingerprint(request)[0] if _range_fingerprint(request) else ""
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


class PersistentSolverCache:
    """Disk-backed cache for canonical V2 solve requests."""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir or DEFAULT_SOLVER_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_request(self, request: SolveRequestV2) -> Path:
        return self.cache_dir / f"{_request_cache_key(request)}.json"

    def get(self, request: SolveRequestV2) -> SolveResponseV2 | None:
        path = self._path_for_request(request)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Persistent solver cache read failed for %s: %s", path, exc)
            return None
        response = SolveResponseV2.from_dict(payload)
        metadata = dict(response.metadata)
        metadata.setdefault("persistent_cache_key", path.stem)
        metadata.setdefault("persistent_cache_path", str(path))
        return replace(
            response,
            cache_hit=True,
            cache_tier=CacheTier.DISK,
            metadata=metadata,
        )

    def put(self, request: SolveRequestV2, response: SolveResponseV2) -> None:
        path = self._path_for_request(request)
        metadata = dict(response.metadata)
        metadata.setdefault("persistent_cache_key", path.stem)
        metadata.setdefault("persistent_cache_path", str(path))
        serializable = replace(response, metadata=metadata)
        path.write_text(serializable.to_json(), encoding="utf-8")

    def list_entries(self, limit: int = 32) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        paths = sorted(
            self.cache_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for path in paths[: max(1, limit)]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                response = SolveResponseV2.from_dict(payload)
                entries.append(
                    {
                        "cache_key": path.stem,
                        "path": str(path),
                        "chosen_action": response.chosen_action,
                        "preset_id": response.preset_id,
                        "backend": response.backend,
                        "cache_tier": getattr(response.cache_tier, "value", response.cache_tier),
                        "decision_confidence": response.decision_confidence,
                        "warnings": list(response.warnings),
                    }
                )
            except Exception as exc:
                logger.debug("Persistent solver cache index failed for %s: %s", path, exc)
        return entries


class DecisionGate:
    """Validate OCR/state snapshots before any live action is allowed."""

    def __init__(self, minimum_confidence: float = 0.62, frame_window: int = 4):
        self.minimum_confidence = minimum_confidence
        self.frame_window = max(2, int(frame_window))
        self._recent_frames: dict[str, list[SpotSnapshot]] = {}

    def _history_key(self, spot: SpotSnapshot) -> str:
        return (
            spot.spot_id
            or str(spot.metadata.get("game_id", ""))
            or str(spot.metadata.get("table_name", ""))
            or f"{spot.source}:{spot.game_stage}"
        )

    def _recent_history(self, spot: SpotSnapshot) -> list[SpotSnapshot]:
        return list(self._recent_frames.get(self._history_key(spot), []))

    def _store_frame(self, spot: SpotSnapshot) -> None:
        key = self._history_key(spot)
        history = self._recent_frames.setdefault(key, [])
        history.append(spot)
        if len(history) > self.frame_window:
            del history[:-self.frame_window]

    def _temporal_consistency(
        self,
        spot: SpotSnapshot,
        history: list[SpotSnapshot],
    ) -> tuple[bool, str, list[str], dict[str, Any]]:
        warnings: list[str] = []
        metadata: dict[str, Any] = {
            "recent_frame_count": len(history),
            "temporal_stability": 1.0,
            "history_key": self._history_key(spot),
        }
        if not history:
            metadata["temporal_warning_count"] = 0
            return True, "", warnings, metadata

        previous = history[-1]
        severe_reason = ""

        if previous.hero_cards and spot.hero_cards and tuple(previous.hero_cards) != tuple(spot.hero_cards):
            severe_reason = "hero_cards_changed_recently"
            warnings.append("hero_cards_changed_recently")
        elif previous.board and spot.board:
            compare_len = min(len(previous.board), len(spot.board))
            if len(spot.board) < len(previous.board):
                severe_reason = "board_regressed_recently"
                warnings.append("board_regressed_recently")
            elif compare_len > 0 and tuple(previous.board[:compare_len]) != tuple(spot.board[:compare_len]):
                severe_reason = "board_changed_recently"
                warnings.append("board_changed_recently")

        if previous.game_stage == spot.game_stage:
            if abs(float(previous.pot) - float(spot.pot)) > max(2.0, float(previous.pot) * 0.8):
                warnings.append("unstable_pot_recently")
            if abs(float(previous.stack) - float(spot.stack)) > max(4.0, float(previous.stack) * 0.45):
                warnings.append("unstable_stack_recently")

        previous_actions = set(previous.legal_actions)
        current_actions = set(spot.legal_actions)
        if previous_actions and current_actions and previous_actions.isdisjoint(current_actions):
            severe_reason = severe_reason or "legal_actions_changed_recently"
            warnings.append("legal_actions_changed_recently")

        stability = 1.0
        if warnings:
            stability -= min(0.75, len(set(warnings)) * 0.18)
        metadata["temporal_stability"] = round(max(stability, 0.0), 3)
        metadata["previous_spot_id"] = previous.spot_id
        metadata["previous_stage"] = previous.game_stage
        metadata["previous_board_len"] = len(previous.board)
        metadata["current_board_len"] = len(spot.board)
        metadata["previous_legal_actions"] = ",".join(previous.legal_actions)
        metadata["current_legal_actions"] = ",".join(spot.legal_actions)
        metadata["temporal_warning_count"] = len(set(warnings))
        metadata["temporal_reason"] = severe_reason or ""
        return severe_reason == "", severe_reason, list(dict.fromkeys(warnings)), metadata

    def evaluate(self, spot: SpotSnapshot) -> DecisionGateResult:
        warnings: list[str] = []
        metadata: dict[str, Any] = {
            "spot_id": spot.spot_id,
            "source": spot.source,
            "history_key": self._history_key(spot),
        }
        cards = tuple(card for card in (*spot.hero_cards, *spot.board) if card)
        history = self._recent_history(spot)

        overall_confidence = spot.state_confidence or (
            spot.ocr_confidence.overall if spot.ocr_confidence else 0.0
        )
        if overall_confidence <= 0.0:
            overall_confidence = 0.85 if len(spot.hero_cards) == 2 else 0.0

        reason = ""
        allowed = True

        temporal_allowed, temporal_reason, temporal_warnings, temporal_metadata = self._temporal_consistency(
            spot,
            history,
        )
        warnings.extend(temporal_warnings)
        metadata.update(temporal_metadata)

        if len(set(cards)) != len(cards):
            allowed = False
            reason = "duplicate_cards"
            warnings.append("duplicate_cards")
        elif len(spot.hero_cards) != 2:
            allowed = False
            reason = "missing_hero_cards"
            warnings.append("missing_hero_cards")
        elif spot.game_stage != "PreFlop" and len(spot.board) < 3:
            allowed = False
            reason = "incomplete_board"
            warnings.append("incomplete_board")
        elif not spot.legal_actions:
            allowed = False
            reason = "missing_legal_actions"
            warnings.append("missing_legal_actions")
        elif spot.pot < 0 or spot.stack < 0:
            allowed = False
            reason = "negative_stack_or_pot"
            warnings.append("negative_stack_or_pot")
        elif not temporal_allowed:
            allowed = False
            reason = temporal_reason or "temporal_inconsistency"
        elif temporal_warnings and overall_confidence < max(self.minimum_confidence + 0.08, 0.72):
            allowed = False
            reason = "unstable_recent_frames"
            warnings.append("unstable_recent_frames")
        elif overall_confidence < self.minimum_confidence:
            allowed = False
            reason = "low_state_confidence"
            warnings.append("low_state_confidence")

        metadata["overall_confidence"] = overall_confidence
        metadata["board_len"] = len(spot.board)
        metadata["legal_actions"] = ",".join(spot.legal_actions)
        metadata["warning_count"] = len(set(warnings))
        metadata["blocked"] = not allowed
        metadata["decision_stage"] = spot.game_stage
        self._store_frame(spot)

        return DecisionGateResult(
            allowed=allowed,
            confidence=round(overall_confidence, 3),
            reason=reason or "ready",
            warnings=tuple(warnings),
            metadata=metadata,
        )


class CanonicalDecisionService:
    """Own the canonical V2 request/response pipeline around the legacy bridge."""

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        default_cache_policy: CachePolicy = CachePolicy.PERSISTENT,
    ):
        self.cache = PersistentSolverCache(cache_dir)
        self.gate = DecisionGate()
        self.default_cache_policy = default_cache_policy

    def build_solve_request(
        self,
        spot: SpotSnapshot,
        hero_range: str,
        villain_ranges: tuple[str, ...] | list[str],
        *,
        hero_position: str,
        tree_preset_id: str,
        rake: float,
        num_players: int,
        time_budget_ms: int,
        use_cache: bool = True,
        cache_policy: CachePolicy | None = None,
        range_model_version: RangeModelVersion = RangeModelVersion.CALIBRATED_V3,
        metadata: dict[str, Any] | None = None,
    ) -> SolveRequestV2:
        legal_actions = tuple(getattr(spot, "legal_actions", ()) or ())
        board = tuple(getattr(spot, "board", ()) or ())
        action_history = tuple(getattr(spot, "action_history", ()) or ())
        ocr_confidence = getattr(spot, "ocr_confidence", None)
        hero_cards = tuple(getattr(spot, "hero_cards", ()) or ())
        state_confidence = float(getattr(spot, "state_confidence", 0.0) or 0.0)
        action_options = tuple(
            ActionOptionV2(name=name, label=name.title())
            for name in legal_actions
        )
        confidence = state_confidence or (
            ocr_confidence.overall if ocr_confidence else 0.0
        )
        return SolveRequestV2(
            spot_id=str(getattr(spot, "spot_id", "") or ""),
            hero_range=hero_range,
            villain_ranges=tuple(villain_ranges),
            board=board,
            starting_pot=float(getattr(spot, "pot", 0.0) or 0.0),
            effective_stack=float(getattr(spot, "stack", 0.0) or 0.0),
            hero_position=hero_position,
            action_history=action_history,
            tree_preset_id=tree_preset_id,
            rake=rake,
            num_players=num_players,
            legal_actions=action_options,
            cache_policy=cache_policy or self.default_cache_policy,
            hero_confidence=(
                ocr_confidence.hero_cards if ocr_confidence else (1.0 if len(hero_cards) == 2 else 0.0)
            ),
            state_confidence=confidence,
            range_model_version=range_model_version,
            use_cache=use_cache,
            time_budget_ms=time_budget_ms,
            metadata=dict(metadata or {}),
        )

    def evaluate_gate(self, spot: SpotSnapshot) -> DecisionGateResult:
        return self.gate.evaluate(spot)

    def solve_request(
        self,
        request: SolveRequestV2,
        native_solver: Callable[[SolveRequestV2], Any],
        http_solver: Callable[[SolveRequestV2], Any] | None = None,
    ) -> SolveResponseV2:
        if request.use_cache and request.cache_policy == CachePolicy.PERSISTENT:
            cached = self.cache.get(request)
            if cached is not None:
                return cached

        response = self._invoke_solver(native_solver, request, backend="native")
        if response is None and http_solver is not None:
            response = self._invoke_solver(http_solver, request, backend="http")

        if response is None:
            response = SolveResponseV2(
                chosen_action="",
                backend="fallback",
                cache_tier=CacheTier.NONE,
                normalized_ranges=_range_fingerprint(request),
                decision_confidence=0.0,
                fallback_reason="no_backend_result",
                warnings=("fallback_used",),
                preset_id=request.tree_preset_id,
                metadata={"spot_id": request.spot_id},
            )

        if request.use_cache and request.cache_policy == CachePolicy.PERSISTENT and (
            response.chosen_action or response.actions
        ):
            self.cache.put(request, response)

        return response

    def warm_cache(
        self,
        requests: list[SolveRequestV2],
        native_solver: Callable[[SolveRequestV2], Any],
        http_solver: Callable[[SolveRequestV2], Any] | None = None,
    ) -> list[SolveResponseV2]:
        return [self.solve_request(item, native_solver, http_solver) for item in requests]

    def warm_preset_catalog(
        self,
        native_solver: Callable[[SolveRequestV2], Any],
        http_solver: Callable[[SolveRequestV2], Any] | None = None,
        *,
        preset_ids: list[str] | tuple[str, ...] | None = None,
        time_budget_ms: int | None = None,
    ) -> list[SolveResponseV2]:
        requests = build_prewarm_requests(
            preset_ids,
            cache_policy=self.default_cache_policy,
            time_budget_ms=time_budget_ms,
        )
        return self.warm_cache(requests, native_solver, http_solver)

    def list_cache_entries(self, limit: int = 32) -> list[dict[str, Any]]:
        return self.cache.list_entries(limit=limit)

    def inspection_payload(self, limit: int = 32) -> dict[str, Any]:
        return {
            "preset_catalog": preset_catalog_payload(),
            "cache_entries": self.list_cache_entries(limit=limit),
        }

    def build_replay_record(
        self,
        replay_id: str,
        spot: SpotSnapshot,
        decision: DecisionSnapshot,
        *,
        result_metadata: dict[str, Any] | None = None,
        tags: tuple[str, ...] | list[str] = (),
    ) -> ReplayRecord:
        return ReplayRecord(
            replay_id=replay_id,
            spot=spot,
            decision=decision,
            result_metadata=dict(result_metadata or {}),
            tags=tuple(tags),
        )

    def build_benchmark_result(
        self,
        *,
        name: str,
        backend: str,
        metric: str,
        score: float,
        elapsed_ms: int,
        passed: bool,
        metadata: dict[str, Any] | None = None,
    ) -> BenchmarkResult:
        return BenchmarkResult(
            name=name,
            backend=backend,
            metric=metric,
            score=score,
            elapsed_ms=elapsed_ms,
            passed=passed,
            metadata=dict(metadata or {}),
        )

    def _invoke_solver(
        self,
        solver: Callable[[SolveRequestV2], Any],
        request: SolveRequestV2,
        *,
        backend: str,
    ) -> SolveResponseV2 | None:
        try:
            result = solver(request)
        except Exception as exc:
            logger.debug("Canonical solver backend %s failed: %s", backend, exc)
            return None
        if result is None:
            return None
        response = result if isinstance(result, SolveResponseV2) else SolveResponseV2.from_dict(result)
        metadata = dict(response.metadata)
        metadata.setdefault("spot_id", request.spot_id)
        metadata.setdefault(
            "range_model_version",
            getattr(request.range_model_version, "value", str(request.range_model_version)),
        )
        metadata.setdefault(
            "cache_policy",
            getattr(request.cache_policy, "value", str(request.cache_policy)),
        )
        return replace(
            response,
            backend=response.backend or backend,
            cache_tier=(
                response.cache_tier
                if response.cache_tier != CacheTier.NONE
                else (CacheTier.MEMORY if response.cache_hit else CacheTier.NONE)
            ),
            normalized_ranges=response.normalized_ranges or _range_fingerprint(request),
            decision_confidence=(
                response.decision_confidence
                or round(max(request.state_confidence, request.hero_confidence) * 0.95, 3)
            ),
            metadata=metadata,
        )
