import asyncio
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from datetime import UTC, datetime
import cv2
import numpy as np
import json
import os
import uuid
from typing import Dict, Tuple, List, Optional

# Imports de nos modules
from src.vision.capture import ScreenCapture
from src.vision.detector import PokerDetector, TableState, DetectionResult, decode_card_token
from src.vision.ocr import PokerOCR
from src.data.database import DatabaseManager
from src.bot.table_tracker import TableTracker
from src.bot.decision_maker import DecisionMaker
from src.bot.action_controller import ActionController
from src.bot.sanity_checker import ActionIntent, GateResult, SanityChecker
from src.bot.live_reconstruction import (
    derive_legal_actions,
    derive_street,
    infer_hero_seat_id,
    normalize_board_for_street,
    ordered_stacks_by_table_geometry,
    smooth_state_confidence_window,
    stable_window_value,
)
from src.bot.runtime_types import CanonicalPlayer, CanonicalTableState

# --- Imports Active Learning ---
from src.bot.active_learning import HumanInTheLoop
from src.api.server import BotAPI
from src.runtime.history_store import RuntimeHistoryStore

# --- Configuration de Logs Persistants ---
os.makedirs("log", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        RotatingFileHandler("log/superbot.log", maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SuperBot2026")


def _parse_bool_flag(value: object) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _compact_solver_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}

    original = dict(payload)
    compact = dict(payload)
    alternatives = compact.get("alternatives")
    if not isinstance(alternatives, list):
        alternatives = []
    compact["alternatives"] = [dict(item) for item in alternatives if isinstance(item, dict)]

    if "alternatives_complete" in original and isinstance(compact.get("alternatives_complete"), list):
        compact["alternatives_complete"] = [
            dict(item) for item in compact.get("alternatives_complete", []) if isinstance(item, dict)
        ]
    else:
        compact.pop("alternatives_complete", None)

    for map_key in ("ev_by_action", "freq_by_action", "action_metadata", "backend_details", "cache_details"):
        value = compact.get(map_key)
        if not isinstance(value, dict):
            compact.pop(map_key, None)

    for float_key in ("elapsed_ms", "exploitability"):
        value = compact.get(float_key)
        if isinstance(value, (int, float)):
            compact[float_key] = float(value)
        else:
            compact.pop(float_key, None)

    node_count = compact.get("node_count")
    if isinstance(node_count, (int, float)):
        compact["node_count"] = int(node_count)
    else:
        compact.pop("node_count", None)

    for string_key in ("backend", "solver_id", "preset_id"):
        value = compact.get(string_key)
        if value in (None, ""):
            compact.pop(string_key, None)
        else:
            compact[string_key] = str(value)

    warnings = compact.get("warnings")
    if isinstance(warnings, list):
        compact["warnings"] = [str(item) for item in warnings if str(item).strip()]
    elif warnings is not None:
        compact.pop("warnings", None)

    for list_key in ("warning_details", "action_buckets"):
        values = compact.get(list_key)
        if isinstance(values, list):
            compact[list_key] = [dict(item) if isinstance(item, dict) else str(item) for item in values if str(item).strip()]
        elif values is not None:
            compact.pop(list_key, None)

    return compact

class SuperBotController:
    def __init__(self, config_path: str = "config.json"):
        # 1. Chargement de la Configuration
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            logger.error(f"Fichier de config {config_path} introuvable. Arrêt.")
            exit(1)
            
        bot_cfg = self.config.get("bot", {})
        
        # --- 2. Vision ---
        self.camera = ScreenCapture(target_fps=bot_cfg.get("target_fps", 30))
        self.detector = PokerDetector(model_path=self.config.get("yolo", {}).get("model_path", "models/poker_yolo_v11.engine"))
        self.ocr = PokerOCR.from_config(self.config.get("ocr", {}))
        
        # --- 3. Data & Tracking ---
        self.db = DatabaseManager(dsn=self.config.get("database", {}).get("dsn"))
        self.tracker = TableTracker(self.db)
        
        runtime_cfg = self.config.get("runtime_history", {}) or {}
        self.runtime_session_id = self._build_runtime_session_id()
        self.runtime_history_store = RuntimeHistoryStore(
            enabled=runtime_cfg.get("enabled", True),
            file_path=runtime_cfg.get("file_path", "log/runtime_history.jsonl"),
            max_size_bytes=runtime_cfg.get("max_size_bytes", 1_048_576),
            session_id=self.runtime_session_id,
        )

        # --- 4. Cerveau IA ---
        rl_cfg = self._build_rl_runtime_config()
        self.decision_maker = DecisionMaker(
            self.db,
            create_rl_agent=rl_cfg["enable_rl"],
            enable_validated_rl=rl_cfg["enable_validated_rl"],
            autoload_rl_model=rl_cfg["autoload_rl_model"],
        )
        self.runtime_sanity = SanityChecker()
        
        # --- 5. Exécuteur Stealth ---
        self.action_controller = ActionController(window_title_keywords=bot_cfg.get("window_title_keywords", "VirtualBox"))
        
        # --- 6. ACTIVE LEARNING (HITL) ---
        self.hitl = HumanInTheLoop(target_dataset_size=100)
        # Configuration de l'Auto-Adaptation via API
        self.hitl.setup_api_fallback(
            api_key=self.config.get("auto_annotator", {}).get("api_key", ""),
            base_url=self.config.get("auto_annotator", {}).get("base_url", ""),
            model=self.config.get("auto_annotator", {}).get("model", "gpt-4o")
        )
        self.operator_controls: Dict[str, object] = {
            "profile_name": "live-runtime",
            "surface": "bot_cockpit",
            "capture_source": "ocr",
            "auto_refresh_enabled": True,
            "shadow_mode_enabled": False,
            "manual_override_enabled": False,
            "paused": False,
            "updated_at": self._utc_now(),
        }
        self.api_server = BotAPI(
            self.hitl,
            runtime_status_provider=self._get_runtime_status,
            runtime_operator_handler=self.update_operator_controls,
            port=8080,
            runtime_history_store=self.runtime_history_store,
        )
        
        self.is_running = False
        self.fallback_coords = self.config.get("fallback_coordinates", {})
        
        # Cache OCR
        self.last_pot_crop: np.ndarray = None
        self.last_pot_value: float = 0.0
        self.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
        self.last_tracker_snapshot: Dict[str, object] = {
            "street": "IDLE",
            "board": [],
            "pot": 0.0,
            "hero_cards": [],
            "in_hand": False,
            "legal_actions": [],
            "hero_seat_id": "",
            "state_confidence": 0.0,
            "ocr_metadata": {},
        }
        self.last_decision_summary: Dict[str, object] = {
            "action": "",
            "source": "idle",
            "confidence": 0.0,
            "cache_hit": False,
            "fallback_used": False,
            "warnings": [],
            "incidents": [],
            "profile": {},
            "solver": {},
            "confidence_details": {},
        }
        self.last_canonical_spot_snapshot: Optional[Dict[str, object]] = None
        self.runtime_event_history = deque(maxlen=24)
        self.decision_trace_history = deque(maxlen=16)
        self.incident_history = deque(maxlen=16)
        self.metric_snapshot_history = deque(maxlen=24)
        self._last_hero_seat_id: Optional[str] = None
        self._last_runtime_street = "IDLE"
        self._last_metrics_persisted_at: Optional[datetime] = None
        self._last_metrics_snapshot_signature: Optional[tuple] = None
        self._recent_runtime_streets = deque(maxlen=3)
        self._recent_runtime_legal_actions = deque(maxlen=3)
        self._recent_runtime_state_confidences = deque(maxlen=3)
        self._recent_runtime_hero_seat_ids = deque(maxlen=3)

    def _resolve_runtime_flag(self, config_value: object, env_var_name: str, default: bool) -> bool:
        env_value = _parse_bool_flag(os.getenv(env_var_name))
        if env_value is not None:
            return env_value

        configured_value = _parse_bool_flag(config_value)
        if configured_value is not None:
            return configured_value

        return default

    def _get_runtime_session_id(self) -> str:
        return getattr(self, "runtime_session_id", None) or self._build_runtime_session_id()

    def _build_rl_runtime_config(self) -> dict:
        rl_cfg = self.config.get("rl", {}) or {}
        bot_cfg = self.config.get("bot", {}) or {}

        enable_rl = self._resolve_runtime_flag(
            rl_cfg.get("enable", bot_cfg.get("enable_rl")),
            "POKER_ENABLE_RL",
            True,
        )
        autoload_rl_model = self._resolve_runtime_flag(
            rl_cfg.get("autoload_model", bot_cfg.get("autoload_rl_model")),
            "POKER_AUTOLOAD_RL_MODEL",
            enable_rl,
        )
        enable_validated_rl = self._resolve_runtime_flag(
            rl_cfg.get("enable_validated", bot_cfg.get("enable_validated_rl")),
            "POKER_ENABLE_VALIDATED_RL",
            False,
        )

        if not enable_rl:
            autoload_rl_model = False
            enable_validated_rl = False

        logger.info(
            "Runtime RL config resolved: enable_rl=%s, enable_validated_rl=%s, autoload_rl_model=%s",
            enable_rl,
            enable_validated_rl,
            autoload_rl_model,
        )

        return {
            "enable_rl": enable_rl,
            "enable_validated_rl": enable_validated_rl,
            "autoload_rl_model": autoload_rl_model,
        }

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _build_runtime_session_id() -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"runtime-{timestamp}-{uuid.uuid4().hex[:8]}"

    def _build_operator_snapshot(self) -> Dict[str, object]:
        controls = dict(getattr(self, "operator_controls", {}) or {})
        paused = bool(controls.get("paused", False))
        shadow_mode_enabled = bool(controls.get("shadow_mode_enabled", False))
        manual_override_enabled = bool(controls.get("manual_override_enabled", False))
        auto_refresh_enabled = bool(controls.get("auto_refresh_enabled", True))
        if not self.is_running:
            status = "offline"
        elif paused:
            status = "paused"
        elif manual_override_enabled:
            status = "manual_override"
        elif shadow_mode_enabled:
            status = "shadow"
        else:
            status = "ready"
        return {
            "profile_name": str(controls.get("profile_name") or "live-runtime"),
            "surface": str(controls.get("surface") or "bot_cockpit"),
            "capture_source": str(controls.get("capture_source") or "ocr"),
            "auto_refresh_enabled": auto_refresh_enabled,
            "shadow_mode_enabled": shadow_mode_enabled,
            "manual_override_enabled": manual_override_enabled,
            "paused": paused,
            "status": status,
            "updated_at": str(controls.get("updated_at") or self._utc_now()),
        }

    def _operator_action_mode(self) -> str:
        return str(self._build_operator_snapshot().get("status") or "ready")

    def update_operator_controls(self, patch: Dict[str, object]) -> Dict[str, object]:
        if not isinstance(patch, dict):
            return self._build_operator_snapshot()

        controls = dict(getattr(self, "operator_controls", {}) or {})
        current_snapshot = self._build_operator_snapshot()
        normalized_patch: Dict[str, bool] = {}
        aliases = {
            "paused": ("paused",),
            "shadow_mode_enabled": ("shadow_mode_enabled", "shadowModeEnabled"),
            "manual_override_enabled": ("manual_override_enabled", "manualOverrideEnabled"),
            "auto_refresh_enabled": ("auto_refresh_enabled", "autoRefreshEnabled"),
        }

        for canonical_key, candidate_keys in aliases.items():
            for candidate_key in candidate_keys:
                if candidate_key not in patch:
                    continue
                parsed_value = _parse_bool_flag(patch.get(candidate_key))
                if parsed_value is not None:
                    normalized_patch[canonical_key] = parsed_value
                break

        if not normalized_patch:
            return current_snapshot

        controls.update(normalized_patch)
        if normalized_patch.get("shadow_mode_enabled"):
            controls["manual_override_enabled"] = False
        if normalized_patch.get("manual_override_enabled"):
            controls["shadow_mode_enabled"] = False
        controls["updated_at"] = self._utc_now()
        self.operator_controls = controls

        next_snapshot = self._build_operator_snapshot()
        changed_fields = {
            key: next_snapshot.get(key)
            for key in (
                "paused",
                "shadow_mode_enabled",
                "manual_override_enabled",
                "auto_refresh_enabled",
                "status",
            )
            if next_snapshot.get(key) != current_snapshot.get(key)
        }
        if changed_fields:
            self._push_runtime_event(
                "operator",
                "controls_updated",
                previous_status=current_snapshot.get("status", "offline"),
                **changed_fields,
            )

        return next_snapshot

    def _push_runtime_event(self, kind: str, message: str, **context) -> None:
        event = {
            "timestamp": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "kind": kind,
            "message": message,
            "context": context,
        }
        self.runtime_event_history.appendleft(event)
        self.runtime_history_store.append("events", event)

    def _push_incident(self, incident_id: str, severity: str = "warning", **context) -> None:
        entry = {
            "id": incident_id,
            "severity": severity,
            "timestamp": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "context": context,
        }
        if entry not in self.incident_history:
            self.incident_history.appendleft(entry)
            self.runtime_history_store.append("incidents", entry)

    def _record_runtime_transition(self, tracker_snapshot: dict) -> None:
        current_street = str(tracker_snapshot.get("street", "IDLE") or "IDLE")
        if current_street != self._last_runtime_street:
            self._push_runtime_event(
                "tracker",
                "street_changed",
                previous_street=self._last_runtime_street,
                street=current_street,
                board=list(tracker_snapshot.get("board", [])),
                pot=float(tracker_snapshot.get("pot", 0.0) or 0.0),
            )
            self._last_runtime_street = current_street

    @staticmethod
    def _normalize_incidents(incidents: List[object]) -> List[str]:
        normalized: List[str] = []
        for incident in incidents:
            if isinstance(incident, dict):
                incident_id = incident.get("id") or incident.get("label") or incident.get("kind")
                if incident_id:
                    normalized.append(str(incident_id))
            elif incident:
                normalized.append(str(incident))
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _derive_live_hero_position(primary_villain) -> str:
        if primary_villain is None:
            return "unknown"
        return "oop" if bool(primary_villain.has_button) else "ip"

    def _record_decision_trace(self, canonical_state: CanonicalTableState, decision: dict, gate_result: GateResult) -> None:
        warnings = list(decision.get("warnings", []))
        incidents = self._normalize_incidents(list(decision.get("incidents", [])))
        ab_decision = decision.get("ab_decision") if isinstance(decision.get("ab_decision"), dict) else None
        metadata = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
        solver_metadata = _compact_solver_payload(metadata.get("solver", {}) or {})
        trace_metadata = dict(metadata)
        trace_metadata["solver"] = solver_metadata
        session_id = self._get_runtime_session_id()
        if not gate_result.allowed:
            incidents.append("gate_blocked")

        trace = {
            "timestamp": self._utc_now(),
            "session_id": session_id,
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "board": list(canonical_state.board),
            "hero_cards": list(canonical_state.hero_cards),
            "pot": canonical_state.pot,
            "legal_actions": list(canonical_state.legal_actions),
            "action_history": list(self.tracker.current_hand_actions),
            "chosen_action": decision.get("action", ""),
            "source": decision.get("source", "unknown"),
            "confidence": float(decision.get("confidence", 0.0) or 0.0),
            "latency_ms": float(decision.get("elapsed_ms", 0) or 0),
            "ev": float(decision.get("ev", 0.0) or 0.0),
            "warnings": warnings,
            "incidents": list(dict.fromkeys(incidents)),
            "backend": decision.get("backend", "unknown"),
            "cache_hit": bool(decision.get("cache_hit", solver_metadata.get("cache_hit", False))),
            "chosen_action_raw": solver_metadata.get("chosen_action_raw"),
            "gto_action": solver_metadata.get("gto_action"),
            "final_action": solver_metadata.get("final_action", decision.get("action", "")),
            "ev_by_action": dict(solver_metadata.get("ev_by_action", {}) or {}),
            "freq_by_action": dict(solver_metadata.get("freq_by_action", {}) or {}),
            "action_metadata": dict(solver_metadata.get("action_metadata", {}) or {}),
            "solver_warnings": list(solver_metadata.get("warnings", []) or []),
            "solver_warning_details": list(solver_metadata.get("warning_details", []) or []),
            "backend_details": dict(solver_metadata.get("backend_details", {}) or {}),
            "cache_details": dict(solver_metadata.get("cache_details", {}) or {}),
            "node_count": solver_metadata.get("node_count", (solver_metadata.get("backend_details", {}) or {}).get("node_count")),
            "exploitability": solver_metadata.get("exploitability"),
            "solver_elapsed_ms": solver_metadata.get("elapsed_ms"),
            "solver_id": solver_metadata.get("solver_id"),
            "preset_id": solver_metadata.get("preset_id"),
            "action_buckets": list(solver_metadata.get("action_buckets", []) or []),
            "ab_decision": dict(ab_decision) if ab_decision else None,
            "metadata": trace_metadata,
            "gate_result": gate_result.to_dict(),
            "explanation": (
                f"Decision {decision.get('action', 'pending')} on {canonical_state.street.lower()} "
                f"from {decision.get('source', 'unknown')} with state_confidence={canonical_state.state_confidence:.2f}."
            ),
        }
        self.decision_trace_history.appendleft(trace)
        self.runtime_history_store.append("decisions", trace)

    async def _run_decision_gate_flow(
        self,
        canonical_state: CanonicalTableState,
        state: TableState,
        primary_villain,
        effective_stack: float,
    ) -> dict:
        dynamic_coords = self._get_dynamic_coordinates(state)
        hero_position = self._derive_live_hero_position(primary_villain)
        decision = await self.decision_maker.get_best_action(
            hero_hand="".join(canonical_state.hero_cards),
            board=list(canonical_state.board),
            pot=canonical_state.pot,
            effective_stack=effective_stack,
            villain_name=primary_villain.name,
            legal_actions=list(canonical_state.legal_actions),
            spot_id=canonical_state.spot_id,
            hero_position=hero_position,
            state_confidence=canonical_state.state_confidence,
            action_history=self.tracker.current_hand_actions,
        )
        normalized_incidents = self._normalize_incidents(list(decision.get("incidents", [])))
        self.last_decision_summary = {
            "action": decision.get("action", ""),
            "source": decision.get("source", "unknown"),
            "confidence": decision.get("confidence", 0.0),
            "observed_hands": int(decision.get("profile", {}).get("observed_hands", 0) or 0),
            "cache_hit": bool(decision.get("cache_hit", False)),
            "fallback_used": bool(decision.get("fallback_used", False)),
            "fallback_reason": decision.get("fallback_reason"),
            "warnings": list(decision.get("warnings", [])),
            "incidents": normalized_incidents,
            "elapsed_ms": decision.get("elapsed_ms", 0),
            "backend": decision.get("backend", "unknown"),
            "action_history": list(self.tracker.current_hand_actions),
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "hero_cards": list(canonical_state.hero_cards),
            "board": list(canonical_state.board),
            "hero_position": hero_position,
            "effective_stack": float(effective_stack or 0.0),
            "villain_name": primary_villain.name,
            "ab_decision": decision.get("ab_decision"),
            "profile": dict(decision.get("metadata", {}).get("profile", {})),
            "solver": _compact_solver_payload(decision.get("metadata", {}).get("solver", {})),
            "confidence_details": dict(decision.get("metadata", {}).get("confidence", {})),
        }

        action_intent = ActionIntent.from_payload(decision)
        self.last_tracker_snapshot["legal_actions"] = [
            str(action).upper() for action in canonical_state.legal_actions
        ]
        gate_result = self.runtime_sanity.evaluate_action_gate(
            action_intent=action_intent,
            tracker_state=self.last_tracker_snapshot,
            coords_mapping=dynamic_coords,
        )
        self.last_gate_result = gate_result
        self.last_decision_summary["gate_confidence"] = float(gate_result.confidence or 0.0)
        self.last_decision_summary["gate_reason"] = gate_result.reason
        self.last_decision_summary["gate_allowed"] = gate_result.allowed
        self.last_decision_summary["trace_updated_at"] = self._utc_now()
        self.last_decision_summary["history"] = {
            "fallback": [decision.get("fallback_reason")] if decision.get("fallback_reason") else [],
            "warnings": list(decision.get("warnings", [])),
            "incidents": self._normalize_incidents(normalized_incidents + (["gate_blocked"] if not gate_result.allowed else [])),
        }
        self._record_decision_trace(canonical_state, decision, gate_result)
        self._push_runtime_event(
            "decision",
            "decision_ready",
            action=decision.get("action", ""),
            source=decision.get("source", "unknown"),
            spot_id=canonical_state.spot_id,
            confidence=float(decision.get("confidence", 0.0) or 0.0),
            gate_allowed=bool(gate_result.allowed),
        )

        for warning in decision.get("warnings", []):
            self._push_runtime_event("warning", warning, spot_id=canonical_state.spot_id)
        for incident in normalized_incidents:
            self._push_incident(str(incident), severity="warning", spot_id=canonical_state.spot_id)
        if not gate_result.allowed:
            self.last_decision_summary["execution"] = {
                "status": "blocked_by_gate",
                "reason": gate_result.reason,
            }
            self._push_incident("gate_blocked", severity="error", reason=gate_result.reason)
            self._push_runtime_event(
                "gate",
                "action_blocked",
                action=decision.get("action", ""),
                reason=gate_result.reason,
                spot_id=canonical_state.spot_id,
            )
        else:
            operator_mode = self._operator_action_mode()
            self.last_decision_summary["operator_status"] = operator_mode
            if operator_mode in {"paused", "shadow", "manual_override"}:
                self.last_decision_summary["execution"] = {
                    "status": "suppressed_by_operator",
                    "reason": operator_mode,
                }
                self._push_runtime_event(
                    "operator",
                    "action_suppressed",
                    action=decision.get("action", ""),
                    spot_id=canonical_state.spot_id,
                    operator_status=operator_mode,
                )
            else:
                await self.action_controller.execute_action(action_intent, dynamic_coords)
                self.last_decision_summary["execution"] = {
                    "status": "executed",
                    "reason": "live_runtime",
                }
                self._push_runtime_event(
                    "action",
                    "executed_action",
                    action=decision.get("action", ""),
                    spot_id=canonical_state.spot_id,
                )
                await asyncio.sleep(1.0)

        return {
            "decision": decision,
            "gate_result": gate_result,
            "dynamic_coords": dynamic_coords,
        }

    @staticmethod
    def _parse_runtime_timestamp(value: object) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _build_local_metrics(self, history: dict) -> dict:
        decisions = history.get("decisions", []) or []
        decision_count = len(decisions)
        blocked_count = 0
        fallback_count = 0
        latencies: List[float] = []

        for entry in decisions:
            if not isinstance(entry, dict):
                continue
            gate_result = entry.get("gate_result", {}) or {}
            incidents = {str(item) for item in entry.get("incidents", [])}
            if not bool(gate_result.get("allowed", True)) or "gate_blocked" in incidents:
                blocked_count += 1
            if str(entry.get("source", "")).lower() == "fallback":
                fallback_count += 1
            latency_ms = entry.get("latency_ms")
            if isinstance(latency_ms, (int, float)):
                latencies.append(float(latency_ms))

        rolling_latency_ms = round(sum(latencies[:5]) / min(len(latencies), 5), 1) if latencies else 0.0
        block_rate = round(blocked_count / decision_count, 3) if decision_count else 0.0
        fallback_rate = round(fallback_count / decision_count, 3) if decision_count else 0.0

        timestamps = [
            parsed
            for parsed in (self._parse_runtime_timestamp(entry.get("timestamp")) for entry in decisions)
            if parsed is not None
        ]
        if len(timestamps) >= 2:
            newest = max(timestamps)
            oldest = min(timestamps)
            span_seconds = max((newest - oldest).total_seconds(), 1.0)
            decision_rate = round((decision_count * 60.0) / span_seconds, 2)
        else:
            decision_rate = float(decision_count)

        return {
            "decision_count": decision_count,
            "blocked_count": blocked_count,
            "fallback_count": fallback_count,
            "block_rate": block_rate,
            "fallback_rate": fallback_rate,
            "rolling_latency_ms": rolling_latency_ms,
            "decision_rate": decision_rate,
            "window_size": decision_count,
        }

    @staticmethod
    def _latest_timestamp(entries: List[dict]) -> Optional[str]:
        if entries and isinstance(entries[0], dict):
            return entries[0].get("timestamp")
        return None

    @staticmethod
    def _normalize_runtime_street_name(value: object) -> str:
        street = str(value or "UNKNOWN").strip().upper()
        return street or "UNKNOWN"

    @staticmethod
    def _normalize_runtime_action_name(value: object) -> str:
        if value in (None, ""):
            return ""
        return str(value).strip().upper()

    @staticmethod
    def _policy_slug(value: object, fallback: str = "runtime") -> str:
        text = str(value or fallback).strip().lower()
        return text.replace(" ", "_") or fallback

    @staticmethod
    def _safe_runtime_float(value: object) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_policy_compare_actions(cls, entry: dict) -> dict[str, str]:
        if not isinstance(entry, dict):
            return {}

        policy_actions: dict[str, str] = {}
        chosen_action = cls._normalize_runtime_action_name(
            entry.get("chosen_action", entry.get("action", ""))
        )
        if chosen_action:
            policy_actions[cls._policy_slug(entry.get("source"), "runtime")] = chosen_action

        ab_decision = cls._extract_runtime_ab_decision(entry) or {}
        gto_action = cls._normalize_runtime_action_name(ab_decision.get("gto_action"))
        if gto_action:
            policy_actions.setdefault("gto_solver", gto_action)

        comparison = ab_decision.get("comparison") if isinstance(ab_decision.get("comparison"), dict) else {}
        final_action = cls._normalize_runtime_action_name(ab_decision.get("final_action"))
        rl_action = cls._normalize_runtime_action_name(ab_decision.get("rl_action"))
        for branch in ("rl_off", "rl_on"):
            branch_action = cls._normalize_runtime_action_name((comparison.get(branch, {}) or {}).get("action"))
            if not branch_action and branch == "rl_off":
                branch_action = gto_action or chosen_action
            if not branch_action and branch == "rl_on":
                branch_action = rl_action or final_action or chosen_action
            if branch_action:
                policy_actions.setdefault(branch, branch_action)

        return policy_actions

    @classmethod
    def _extract_policy_compare_ev_by_action(cls, entry: dict) -> dict[str, float]:
        if not isinstance(entry, dict):
            return {}

        ev_by_action: dict[str, float] = {}

        def remember(action_name: object, ev_value: object) -> None:
            action = cls._normalize_runtime_action_name(action_name)
            ev = cls._safe_runtime_float(ev_value)
            if action and ev is not None and action not in ev_by_action:
                ev_by_action[action] = ev

        metadata = dict(entry.get("metadata", {}) or {})
        solver = dict(metadata.get("solver", entry.get("solver", {})) or {})
        for item in solver.get("alternatives", []) or []:
            if not isinstance(item, dict):
                continue
            remember(item.get("action", item.get("raw_action")), item.get("ev", item.get("hero_ev")))

        ab_decision = cls._extract_runtime_ab_decision(entry) or {}
        comparison = ab_decision.get("comparison") if isinstance(ab_decision.get("comparison"), dict) else {}
        for branch in ("rl_off", "rl_on"):
            branch_snapshot = dict(comparison.get(branch, {}) or {})
            remember(branch_snapshot.get("action"), branch_snapshot.get("ev"))

        remember(entry.get("chosen_action", entry.get("action")), entry.get("ev"))
        return ev_by_action

    @staticmethod
    def _build_empty_policy_compare_summary() -> dict:
        return {
            "sample_count": 0,
            "comparable_count": 0,
            "agreement_count": 0,
            "disagreement_count": 0,
            "agreement_rate": 0.0,
            "changed_action_count": 0,
            "changed_action_rate": 0.0,
            "ev_coverage_count": 0,
            "ev_coverage_rate": 0.0,
            "policies": [],
            "policy_counts": {},
            "street_counts": {},
            "source_counts": {},
            "comparisons": [],
            "highlights": {
                "most_compared_pair": None,
                "most_divergent_pair": None,
                "top_spots": [],
            },
        }

    @classmethod
    def _policy_compare_sample_id(cls, entry: dict, fallback: str) -> str:
        if not isinstance(entry, dict):
            return fallback
        spot_id = str(entry.get("spot_id", "") or "").strip()
        timestamp = str(entry.get("timestamp", "") or "").strip()
        if spot_id and timestamp:
            return f"{spot_id}@{timestamp}"
        if spot_id:
            return spot_id
        if timestamp:
            return timestamp
        return fallback

    @classmethod
    def _policy_compare_spot_example(
        cls,
        entry: dict,
        sample_id: str,
        baseline_action: str,
        challenger_action: str,
        ev_by_action: dict[str, float],
    ) -> dict:
        example = {
            "sample_id": sample_id,
            "spot_id": str(entry.get("spot_id", "") or "").strip() or sample_id,
            "street": cls._normalize_runtime_street_name(entry.get("street")),
            "baseline_action": baseline_action,
            "challenger_action": challenger_action,
            "action_pair": f"{baseline_action}->{challenger_action}",
        }
        hero_cards = list(entry.get("hero_cards", []) or [])
        board = list(entry.get("board", []) or [])
        if hero_cards:
            example["hero_cards"] = hero_cards[:2]
        if board:
            example["board"] = board[:5]
        pot = cls._safe_runtime_float(entry.get("pot"))
        if pot is not None:
            example["pot"] = round(pot, 4)
        baseline_ev = ev_by_action.get(baseline_action)
        challenger_ev = ev_by_action.get(challenger_action)
        if baseline_ev is not None:
            example["baseline_ev"] = round(float(baseline_ev), 4)
        if challenger_ev is not None:
            example["challenger_ev"] = round(float(challenger_ev), 4)
        if baseline_ev is not None and challenger_ev is not None:
            example["ev_delta"] = round(float(challenger_ev) - float(baseline_ev), 4)
        return example

    @staticmethod
    def _compact_policy_compare_examples(examples: list[dict], limit: int = 2) -> list[dict]:
        ranked = sorted(
            [item for item in examples if isinstance(item, dict)],
            key=lambda item: (
                -abs(float(item.get("ev_delta", 0.0) or 0.0)),
                item.get("sample_id", ""),
            ),
        )
        return ranked[:limit]

    def _build_policy_compare_summary(self, decisions: List[dict]) -> dict:
        summary = self._build_empty_policy_compare_summary()
        if not isinstance(decisions, list) or not decisions:
            return summary

        policy_counts: dict[str, int] = {}
        street_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        comparisons: dict[tuple[str, str], dict] = {}
        spot_counts: dict[str, dict] = {}

        for index, entry in enumerate(decisions, start=1):
            if not isinstance(entry, dict):
                continue

            policy_actions = self._extract_policy_compare_actions(entry)
            if not policy_actions:
                continue

            sample_id = self._policy_compare_sample_id(entry, f"sample-{index:03d}")

            summary["sample_count"] += 1
            source = self._policy_slug(entry.get("source"), "runtime")
            source_counts[source] = source_counts.get(source, 0) + 1

            for policy in policy_actions:
                policy_counts[policy] = policy_counts.get(policy, 0) + 1

            if len(policy_actions) < 2:
                continue

            summary["comparable_count"] += 1
            street = self._normalize_runtime_street_name(entry.get("street"))
            street_counts[street] = street_counts.get(street, 0) + 1
            spot_id = str(entry.get("spot_id", "") or "").strip() or sample_id
            spot_summary = spot_counts.setdefault(
                spot_id,
                {
                    "spot_id": spot_id,
                    "sample_count": 0,
                    "streets": set(),
                    "sample_ids": [],
                },
            )
            spot_summary["sample_count"] += 1
            spot_summary["streets"].add(street)
            if sample_id not in spot_summary["sample_ids"] and len(spot_summary["sample_ids"]) < 3:
                spot_summary["sample_ids"].append(sample_id)

            unique_actions = sorted(set(policy_actions.values()))
            if len(unique_actions) == 1:
                summary["agreement_count"] += 1
            else:
                summary["changed_action_count"] += 1

            ev_by_action = self._extract_policy_compare_ev_by_action(entry)
            policies = sorted(policy_actions)
            for index, baseline in enumerate(policies):
                for challenger in policies[index + 1 :]:
                    baseline_action = policy_actions.get(baseline, "")
                    challenger_action = policy_actions.get(challenger, "")
                    if not baseline_action or not challenger_action:
                        continue

                    key = (baseline, challenger)
                    pair_summary = comparisons.setdefault(
                        key,
                        {
                            "baseline_policy": baseline,
                            "challenger_policy": challenger,
                            "sample_count": 0,
                            "agreement_count": 0,
                            "disagreement_count": 0,
                            "ev_coverage_count": 0,
                            "baseline_ev_sum": 0.0,
                            "challenger_ev_sum": 0.0,
                            "action_pairs": {},
                            "sample_ids": [],
                            "spot_examples": [],
                            "divergence_examples": [],
                        },
                    )
                    pair_summary["sample_count"] += 1
                    pair_key = f"{baseline_action}->{challenger_action}"
                    pair_summary["action_pairs"][pair_key] = pair_summary["action_pairs"].get(pair_key, 0) + 1
                    if sample_id not in pair_summary["sample_ids"] and len(pair_summary["sample_ids"]) < 3:
                        pair_summary["sample_ids"].append(sample_id)

                    example = self._policy_compare_spot_example(
                        entry,
                        sample_id,
                        baseline_action,
                        challenger_action,
                        ev_by_action,
                    )
                    pair_summary["spot_examples"].append(example)

                    if baseline_action == challenger_action:
                        pair_summary["agreement_count"] += 1
                    else:
                        pair_summary["disagreement_count"] += 1
                        pair_summary["divergence_examples"].append(example)

                    baseline_ev = ev_by_action.get(baseline_action)
                    challenger_ev = ev_by_action.get(challenger_action)
                    if baseline_ev is not None and challenger_ev is not None:
                        pair_summary["ev_coverage_count"] += 1
                        pair_summary["baseline_ev_sum"] += float(baseline_ev)
                        pair_summary["challenger_ev_sum"] += float(challenger_ev)

        summary["disagreement_count"] = summary["comparable_count"] - summary["agreement_count"]
        summary["agreement_rate"] = round(
            summary["agreement_count"] / summary["comparable_count"], 4
        ) if summary["comparable_count"] else 0.0
        summary["changed_action_rate"] = round(
            summary["changed_action_count"] / summary["comparable_count"], 4
        ) if summary["comparable_count"] else 0.0

        comparison_rows = []
        for pair_summary in comparisons.values():
            sample_count = pair_summary["sample_count"]
            ev_coverage_count = pair_summary["ev_coverage_count"]
            summary["ev_coverage_count"] += ev_coverage_count
            top_action_pairs = sorted(
                pair_summary["action_pairs"].items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
            comparison_rows.append(
                {
                    "baseline_policy": pair_summary["baseline_policy"],
                    "challenger_policy": pair_summary["challenger_policy"],
                    "sample_count": sample_count,
                    "agreement_count": pair_summary["agreement_count"],
                    "disagreement_count": pair_summary["disagreement_count"],
                    "agreement_rate": round(pair_summary["agreement_count"] / sample_count, 4) if sample_count else 0.0,
                    "ev_coverage_count": ev_coverage_count,
                    "ev_coverage_rate": round(ev_coverage_count / sample_count, 4) if sample_count else 0.0,
                    "challenger_ev_delta": round(
                        pair_summary["challenger_ev_sum"] - pair_summary["baseline_ev_sum"],
                        4,
                    ),
                    "sample_ids": list(pair_summary["sample_ids"]),
                    "top_action_pairs": [
                        {"actions": action_pair, "count": count}
                        for action_pair, count in top_action_pairs
                    ],
                    "top_spots": self._compact_policy_compare_examples(pair_summary["spot_examples"]),
                    "divergence_examples": self._compact_policy_compare_examples(
                        pair_summary["divergence_examples"],
                    ),
                }
            )

        total_pair_samples = sum(item["sample_count"] for item in comparison_rows)
        summary["ev_coverage_rate"] = round(
            summary["ev_coverage_count"] / total_pair_samples,
            4,
        ) if total_pair_samples else 0.0
        summary["policies"] = sorted(policy_counts)
        summary["policy_counts"] = {policy: policy_counts[policy] for policy in sorted(policy_counts)}
        summary["street_counts"] = {street: street_counts[street] for street in sorted(street_counts)}
        summary["source_counts"] = {name: source_counts[name] for name in sorted(source_counts)}
        summary["comparisons"] = sorted(
            comparison_rows,
            key=lambda item: (-item["sample_count"], item["agreement_rate"], item["baseline_policy"], item["challenger_policy"]),
        )[:6]
        top_spots = sorted(
            spot_counts.values(),
            key=lambda item: (-item["sample_count"], item["spot_id"]),
        )[:3]
        if summary["comparisons"]:
            most_divergent = min(
                summary["comparisons"],
                key=lambda item: (item["agreement_rate"], -item["sample_count"], item["baseline_policy"], item["challenger_policy"]),
            )
            summary["highlights"] = {
                "most_compared_pair": {
                    "baseline_policy": summary["comparisons"][0]["baseline_policy"],
                    "challenger_policy": summary["comparisons"][0]["challenger_policy"],
                    "sample_count": summary["comparisons"][0]["sample_count"],
                    "sample_ids": list(summary["comparisons"][0].get("sample_ids", [])),
                    "top_spots": list(summary["comparisons"][0].get("top_spots", [])),
                },
                "most_divergent_pair": {
                    "baseline_policy": most_divergent["baseline_policy"],
                    "challenger_policy": most_divergent["challenger_policy"],
                    "agreement_rate": most_divergent["agreement_rate"],
                    "sample_ids": list(most_divergent.get("sample_ids", [])),
                    "divergence_examples": list(most_divergent.get("divergence_examples", [])),
                },
                "top_spots": [
                    {
                        "spot_id": item["spot_id"],
                        "sample_count": item["sample_count"],
                        "streets": sorted(item["streets"]),
                        "sample_ids": list(item["sample_ids"]),
                    }
                    for item in top_spots
                ],
            }
        return summary

    @staticmethod
    def _extract_runtime_ab_decision(entry: dict) -> Optional[dict]:
        if not isinstance(entry, dict):
            return None

        ab_decision = entry.get("ab_decision")
        if isinstance(ab_decision, dict):
            return ab_decision

        metadata = entry.get("metadata")
        if isinstance(metadata, dict):
            nested = metadata.get("rl_ab")
            if isinstance(nested, dict):
                return nested

        return None

    @staticmethod
    def _runtime_ab_decision_key(entry: dict) -> Optional[tuple]:
        if not isinstance(entry, dict):
            return None

        spot_id = str(entry.get("spot_id", "") or "").strip()
        timestamp = str(entry.get("timestamp", "") or "").strip()
        if spot_id and timestamp:
            return ("spot_id_timestamp", spot_id, timestamp)

        street = str(entry.get("street", "") or "").strip().upper()
        chosen_action = str(entry.get("chosen_action", entry.get("action", "")) or "").strip().upper()
        source = str(entry.get("source", "") or "").strip().lower()
        if timestamp and street and chosen_action:
            return ("timestamp_street_action", timestamp, street, chosen_action, source)

        return None

    def _dedupe_runtime_ab_decisions(self, decisions: List[dict]) -> List[dict]:
        deduped: List[dict] = []
        seen_keys: set[tuple] = set()

        for entry in decisions:
            if not isinstance(entry, dict):
                continue

            decision_key = self._runtime_ab_decision_key(entry)
            if decision_key is None:
                deduped.append(entry)
                continue

            if decision_key in seen_keys:
                continue

            seen_keys.add(decision_key)
            deduped.append(entry)

        return deduped

    def _build_runtime_ab_summary(self, decisions: List[dict]) -> dict:
        summary = {
            "sample_count": 0,
            "compared_count": 0,
            "eligible_count": 0,
            "applied_count": 0,
            "diff_count": 0,
            "action_change_count": 0,
            "avg_delta_ev": None,
            "avg_delta_freq": None,
            "impacted_streets": [],
            "street_counts": {},
        }
        if not isinstance(decisions, list) or not decisions:
            return summary

        compared_count = 0
        eligible_count = 0
        applied_count = 0
        diff_count = 0
        action_change_count = 0
        ev_delta_total = 0.0
        ev_delta_count = 0
        freq_delta_total = 0.0
        freq_delta_count = 0
        impacted_streets: dict[str, int] = {}

        for entry in decisions:
            ab_decision = self._extract_runtime_ab_decision(entry)
            if not ab_decision:
                continue

            summary["sample_count"] += 1
            if ab_decision.get("compared"):
                compared_count += 1
            if ab_decision.get("eligible"):
                eligible_count += 1
            if ab_decision.get("applied"):
                applied_count += 1
            if ab_decision.get("rl_differs_from_gto") or ab_decision.get("would_override"):
                diff_count += 1

            comparison = ab_decision.get("comparison") if isinstance(ab_decision.get("comparison"), dict) else {}
            action_changed = bool(comparison.get("action_changed"))
            if action_changed:
                action_change_count += 1
                street = self._normalize_runtime_street_name(entry.get("street"))
                impacted_streets[street] = impacted_streets.get(street, 0) + 1

            ev_delta = comparison.get("ev_delta")
            if isinstance(ev_delta, (int, float)):
                ev_delta_total += float(ev_delta)
                ev_delta_count += 1

            freq_delta = comparison.get("freq_delta")
            if isinstance(freq_delta, (int, float)):
                freq_delta_total += float(freq_delta)
                freq_delta_count += 1

        summary["compared_count"] = compared_count
        summary["eligible_count"] = eligible_count
        summary["applied_count"] = applied_count
        summary["diff_count"] = diff_count
        summary["action_change_count"] = action_change_count
        summary["avg_delta_ev"] = round(ev_delta_total / ev_delta_count, 4) if ev_delta_count else None
        summary["avg_delta_freq"] = round(freq_delta_total / freq_delta_count, 4) if freq_delta_count else None
        summary["impacted_streets"] = sorted(impacted_streets)
        summary["street_counts"] = {street: impacted_streets[street] for street in sorted(impacted_streets)}
        return summary

    def _build_persisted_metrics_snapshot(self, local_metrics: dict, history: dict, persistence: dict) -> dict:
        runtime_history = {
            "events": history.get("events", []) or [],
            "decisions": history.get("decisions", []) or [],
            "incidents": history.get("incidents", []) or [],
        }
        persisted_history = history.get("persisted", {}) or {}
        store_summary = self.runtime_history_store.summarize_records()

        return {
            "timestamp": self._utc_now(),
            "decision_count": int(local_metrics.get("decision_count", 0) or 0),
            "blocked_count": int(local_metrics.get("blocked_count", 0) or 0),
            "fallback_count": int(local_metrics.get("fallback_count", 0) or 0),
            "block_rate": float(local_metrics.get("block_rate", 0.0) or 0.0),
            "fallback_rate": float(local_metrics.get("fallback_rate", 0.0) or 0.0),
            "rolling_latency_ms": float(local_metrics.get("rolling_latency_ms", 0.0) or 0.0),
            "decision_rate": float(local_metrics.get("decision_rate", 0.0) or 0.0),
            "window_size": int(local_metrics.get("window_size", 0) or 0),
            "runtime": {
                "event_count": len(runtime_history["events"]),
                "decision_count": len(runtime_history["decisions"]),
                "incident_count": len(runtime_history["incidents"]),
                "latest_event_at": self._latest_timestamp(runtime_history["events"]),
                "latest_decision_at": self._latest_timestamp(runtime_history["decisions"]),
                "latest_incident_at": self._latest_timestamp(runtime_history["incidents"]),
            },
            "persisted": {
                "event_count": int(store_summary["counts"].get("events", len(persisted_history.get("events", []))) or 0),
                "decision_count": int(store_summary["counts"].get("decisions", len(persisted_history.get("decisions", []))) or 0),
                "incident_count": int(store_summary["counts"].get("incidents", len(persisted_history.get("incidents", []))) or 0),
                "metrics_count": int(store_summary["counts"].get("metrics", 0) or 0),
                "latest_event_at": store_summary["latest_at"].get("events") or self._latest_timestamp(persisted_history.get("events", [])),
                "latest_decision_at": store_summary["latest_at"].get("decisions") or self._latest_timestamp(persisted_history.get("decisions", [])),
                "latest_incident_at": store_summary["latest_at"].get("incidents") or self._latest_timestamp(persisted_history.get("incidents", [])),
                "latest_metrics_at": store_summary["latest_at"].get("metrics"),
            },
            "storage": {
                "path": persistence.get("path"),
                "available": bool(persistence.get("available", False)),
                "size_bytes": int(persistence.get("size_bytes", 0) or 0),
                "write_failed": bool(persistence.get("write_failed", False)),
            },
        }

    def _persist_runtime_metrics_snapshot(self, force: bool = False) -> Optional[dict]:
        persistence = self.runtime_history_store.summarize()
        history = {
            "events": list(self.runtime_event_history),
            "decisions": list(self.decision_trace_history),
            "incidents": list(self.incident_history),
            "persisted": {
                "events": self.runtime_history_store.read_recent("events", limit=10),
                "decisions": self.runtime_history_store.read_recent("decisions", limit=10),
                "incidents": self.runtime_history_store.read_recent("incidents", limit=10),
                "metrics": self.runtime_history_store.read_recent("metrics", limit=10),
            },
        }
        local_metrics = self._build_local_metrics(history)
        snapshot = self._build_persisted_metrics_snapshot(local_metrics, history, persistence)
        signature = (
            snapshot["decision_count"],
            snapshot["blocked_count"],
            snapshot["fallback_count"],
            snapshot["runtime"]["event_count"],
            snapshot["runtime"]["incident_count"],
            snapshot["persisted"]["event_count"],
            snapshot["persisted"]["decision_count"],
            snapshot["persisted"]["incident_count"],
            snapshot["storage"]["size_bytes"],
            snapshot["storage"]["write_failed"],
        )
        now = datetime.now(UTC)
        should_persist = force

        if not should_persist and self._last_metrics_snapshot_signature != signature:
            should_persist = True
        if not should_persist and self._last_metrics_persisted_at is not None:
            should_persist = (now - self._last_metrics_persisted_at).total_seconds() >= 30.0

        if should_persist:
            self.runtime_history_store.append("metrics", snapshot)
            self._last_metrics_persisted_at = now
            self._last_metrics_snapshot_signature = signature
            self.metric_snapshot_history.appendleft(snapshot)

        return snapshot

    def _get_dynamic_coordinates(self, state: TableState) -> dict:
        mapping = {}
        button_map = {
            "fold_button": "FOLD",
            "call_button": "CALL",
            "check_button": "CALL",
            "bet_button": "BET_BTN",
            "raise_button": "BET_BTN",
        }
        for button in state.action_buttons:
            center = self._center(button)
            coord = (int(center[0]), int(center[1]))
            mapped = button_map.get(button.class_name.lower())
            if mapped:
                mapping[mapped] = coord
        for btn in ["FOLD", "CALL", "BET_BTN", "BET_BOX"]:
            mapping.setdefault(btn, self.fallback_coords.get(btn))
        return mapping

    @staticmethod
    def _safe_crop(frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = bbox
        height, width = frame.shape[:2]
        x1 = max(0, min(x1, width))
        x2 = max(0, min(x2, width))
        y1 = max(0, min(y1, height))
        y2 = max(0, min(y2, height))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        return crop if crop.size > 0 else None

    @staticmethod
    def _center(det: DetectionResult) -> Tuple[float, float]:
        x1, y1, x2, y2 = det.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def _is_image_changed(self, img1: np.ndarray, img2: np.ndarray, threshold: float = 0.95) -> bool:
        if img1 is None or img2 is None:
            return True
        try:
            i1 = cv2.resize(img1, (100, 30))
            i2 = cv2.resize(img2, (100, 30))
            i1 = cv2.GaussianBlur(i1, (3, 3), 0)
            i2 = cv2.GaussianBlur(i2, (3, 3), 0)
            diff = cv2.absdiff(i1, i2)
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray_diff, 15, 255, cv2.THRESH_BINARY)
            difference_ratio = np.count_nonzero(thresh) / thresh.size
            return difference_ratio > (1.0 - threshold)
        except Exception:
            return True

    async def _process_frame(self, frame) -> TableState:
        # Analyse Visuelle
        state = await asyncio.to_thread(self.detector.analyze_frame, frame)
        
        # --- DÉCLENCHEUR D'ACTIVE LEARNING ---
        # Exemple de règle : Si le pot est censé être présent mais YOLO a un doute (ou ne le voit pas)
        # On pourrait aussi vérifier si 'state.pots' est vide alors qu'il y a des cartes sur le board.
        if len(state.board_cards) >= 3 and not state.pots:
            # Anomalie ! Un board a toujours un pot. Le bot est perdu (nouvelle interface ?)
            resolution = await self.hitl.request_intervention(
                frame=frame,
                issue_type="MISSING_POT",
                reason="Le flop est distribué mais je ne détecte aucun pot."
            )
            # Si résolu (soit par GPT-4o, soit par l'Humain), on recharge l'analyse sur le frame modifié
            if resolution.get("status") in ["resolved_by_api", "resolved_by_human"]:
                state = await asyncio.to_thread(self.detector.analyze_frame, frame)
        
        # Suite normale (OCR)
        if state.pots:
            pot_box = state.pots[0].bbox
            pot_crop = frame[pot_box[1]:pot_box[3], pot_box[0]:pot_box[2]]
            if not self._is_image_changed(self.last_pot_crop, pot_crop, threshold=0.98):
                state.pots[0].confidence = self.last_pot_value
            else:
                pot_value = await asyncio.to_thread(self.ocr.read_and_parse_amount, pot_crop)
                val = pot_value if pot_value else 0.0
                state.pots[0].confidence = val
                state.metadata["pot_ocr"] = self.ocr.get_metadata()
                self.last_pot_value = val
                self.last_pot_crop = pot_crop.copy()

        return state

    def _pair_stack_and_name(
        self,
        stack_det: DetectionResult,
        state: TableState,
        frame: np.ndarray,
        seat_index: int,
        seat_id: str,
        is_hero: bool,
    ) -> CanonicalPlayer:
        sx, sy = self._center(stack_det)
        nearest_name = None
        nearest_distance = float("inf")
        for name_det in state.player_names:
            nx, ny = self._center(name_det)
            distance = abs(nx - sx) + abs(ny - sy)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_name = name_det

        stack_crop = self._safe_crop(frame, stack_det.bbox)
        stack_value = self.ocr.read_and_parse_amount(stack_crop) if stack_crop is not None else None
        stack_ocr_metadata = self.ocr.get_metadata()
        if stack_value is None:
            stack_value = 0.0

        player_name = ""
        name_confidence = 0.0
        if nearest_name is not None:
            name_crop = self._safe_crop(frame, nearest_name.bbox)
            player_name = self.ocr.read_text(name_crop).strip() if name_crop is not None else ""
            name_ocr_metadata = self.ocr.get_metadata()
            name_confidence = nearest_name.confidence
        else:
            name_ocr_metadata = {}

        has_button = False
        if state.dealer_button is not None:
            bx, by = self._center(state.dealer_button)
            has_button = abs(bx - sx) + abs(by - sy) < 220

        return CanonicalPlayer(
            seat_id=seat_id,
            seat_index=seat_index,
            stack=float(stack_value),
            name=player_name,
            is_active=float(stack_value) > 0.0,
            has_folded=False,
            is_hero=is_hero,
            has_button=has_button,
            confidence=round((stack_det.confidence + name_confidence) / 2.0, 3),
            metadata={
                "stack_ocr": stack_ocr_metadata,
                "name_ocr": name_ocr_metadata,
            },
        )

    def _ordered_stacks_by_table_geometry(self, state: TableState, frame: np.ndarray) -> List[tuple[str, DetectionResult]]:
        ordered = ordered_stacks_by_table_geometry(
            stack_bboxes=[stack_det.bbox for stack_det in state.stacks],
            frame_shape=frame.shape[:2],
            pot_bbox=state.pots[0].bbox if state.pots else None,
        )
        stack_by_bbox = {stack_det.bbox: stack_det for stack_det in state.stacks}
        return [(seat_id, stack_by_bbox[stack_bbox]) for seat_id, stack_bbox in ordered]

    def _infer_hero_seat_id(
        self,
        ordered_stacks: List[tuple[str, DetectionResult]],
        state: TableState,
        frame: np.ndarray,
    ) -> Optional[str]:
        best_seat_id = infer_hero_seat_id(
            ordered_stacks=[(seat_id, stack_det.bbox) for seat_id, stack_det in ordered_stacks],
            hero_card_bboxes=[card.bbox for card in state.hero_cards],
            frame_shape=frame.shape[:2],
            last_hero_seat_id=self._last_hero_seat_id,
        )
        best_seat_id = stable_window_value(
            list(self._recent_runtime_hero_seat_ids),
            best_seat_id,
            ignore_values=(None, ""),
        )
        self._last_hero_seat_id = best_seat_id
        if best_seat_id:
            self._recent_runtime_hero_seat_ids.append(best_seat_id)
        return best_seat_id

    def _build_players(self, state: TableState, frame: np.ndarray) -> List[CanonicalPlayer]:
        if not state.stacks:
            return []

        ordered_stacks = self._ordered_stacks_by_table_geometry(state, frame)
        hero_seat_id = self._infer_hero_seat_id(ordered_stacks, state, frame)
        return [
            self._pair_stack_and_name(
                stack_det=stack_det,
                state=state,
                frame=frame,
                seat_index=index,
                seat_id=seat_id,
                is_hero=seat_id == hero_seat_id,
            )
            for index, (seat_id, stack_det) in enumerate(ordered_stacks)
        ]

    @staticmethod
    def _derive_legal_actions(state: TableState) -> Tuple[tuple[str, ...], tuple[str, ...]]:
        return derive_legal_actions(button.class_name for button in state.action_buttons)

    @staticmethod
    def _normalize_board_for_street(board: tuple[str, ...], street: str) -> tuple[str, ...]:
        return normalize_board_for_street(board, street)

    def _derive_street(self, board: List[str], hero_cards: List[str]) -> str:
        incoming_street = derive_street(board, hero_cards)
        stable_street = stable_window_value(
            list(self._recent_runtime_streets),
            incoming_street,
            ignore_values=("IDLE",),
        )
        self._recent_runtime_streets.append(stable_street)
        return stable_street

    def _smooth_legal_actions(
        self,
        legal_actions: tuple[str, ...],
        action_buttons: tuple[str, ...],
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        same_runtime_context = bool(hero_cards) and (
            not self.last_canonical_spot_snapshot
            or (
                list(board) == list(self.last_canonical_spot_snapshot.get("board", []))
                and list(hero_cards) == list(self.last_canonical_spot_snapshot.get("hero_cards", []))
            )
        )
        if not same_runtime_context:
            self._recent_runtime_legal_actions.clear()
            if legal_actions:
                self._recent_runtime_legal_actions.append(legal_actions)
            return legal_actions, action_buttons

        stable_actions = stable_window_value(
            list(self._recent_runtime_legal_actions),
            legal_actions,
            ignore_values=((),),
        )
        if stable_actions:
            self._recent_runtime_legal_actions.append(stable_actions)
            if not legal_actions:
                return stable_actions, action_buttons
        return legal_actions, action_buttons

    def _smooth_runtime_state_confidence(
        self,
        state_confidence: float,
        street: str,
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> float:
        same_runtime_context = not self.last_canonical_spot_snapshot or (
            street == self.last_canonical_spot_snapshot.get("street")
            and list(board) == list(self.last_canonical_spot_snapshot.get("board", []))
            and list(hero_cards) == list(self.last_canonical_spot_snapshot.get("hero_cards", []))
        )
        if not same_runtime_context:
            self._recent_runtime_state_confidences.clear()
            smoothed = round(float(state_confidence or 0.0), 3)
        else:
            smoothed = smooth_state_confidence_window(
                list(self._recent_runtime_state_confidences),
                state_confidence,
            )
        self._recent_runtime_state_confidences.append(smoothed)
        return smoothed

    def _convert_state_for_tracker(self, state: TableState, frame: np.ndarray) -> CanonicalTableState:
        board = tuple(card for card in (decode_card_token(c.class_name) for c in state.board_cards) if card)
        hero_cards = tuple(card for card in (decode_card_token(c.class_name) for c in state.hero_cards) if card)
        pot_value = float(getattr(state.pots[0], "confidence", 0.0) or 0.0) if state.pots else 0.0
        players = tuple(self._build_players(state, frame))
        legal_actions, action_buttons = self._derive_legal_actions(state)
        street = self._derive_street(list(board), list(hero_cards))
        board = self._normalize_board_for_street(board, street)
        legal_actions, action_buttons = self._smooth_legal_actions(
            legal_actions,
            action_buttons,
            board,
            hero_cards,
        )
        confidence_parts = [
            1.0 if len(hero_cards) == 2 else 0.0,
            min(len(board) / 5.0, 1.0),
            1.0 if pot_value >= 0 else 0.0,
            1.0 if players else 0.0,
            1.0 if legal_actions else 0.0,
        ]
        state_confidence = round(sum(confidence_parts) / len(confidence_parts), 3)
        state_confidence = self._smooth_runtime_state_confidence(state_confidence, street, board, hero_cards)
        spot_suffix = "-".join(board) if board else street.lower()

        return CanonicalTableState(
            spot_id=f"live:{street}:{spot_suffix}",
            street=street,
            pot=pot_value,
            board=board,
            hero_cards=hero_cards,
            players=players,
            legal_actions=legal_actions,
            action_buttons=action_buttons,
            state_confidence=state_confidence,
            metadata={
                "detected_player_count": len(players),
                "has_dealer_button": state.dealer_button is not None,
                "hero_seat_id": next((player.seat_id for player in players if player.is_hero), ""),
                "ocr": {
                    "pot": state.metadata.get("pot_ocr", {}),
                    "engines": self.ocr.get_metadata().get("loaded_engines", []),
                    "requested_engines": self.ocr.get_metadata().get("requested_engines", []),
                    "mode": self.ocr.get_metadata().get("mode", "consensus_amounts"),
                    "parallel": self.ocr.get_metadata().get("parallel", True),
                },
            },
        )

    def _build_tracker_snapshot(self, tracker_data: dict) -> dict:
        hero_seat_id = next(
            (seat_id for seat_id, player in self.tracker.players.items() if player.is_hero),
            "",
        )
        ocr_metadata = {}
        if isinstance(tracker_data, dict):
            metadata = tracker_data.get("metadata", {}) or {}
            ocr_metadata = dict(metadata.get("ocr", {}) or {})

        return {
            "street": self.tracker.state,
            "board": list(self.tracker.current_board),
            "pot": float(self.tracker.pot_total or 0.0),
            "hero_cards": list(self.tracker.hero_cards),
            "action_history": list(self.tracker.current_hand_actions),
            "in_hand": len(self.tracker.hero_cards) == 2 and self.tracker.state != "IDLE",
            "legal_actions": [str(action).upper() for action in self.tracker.legal_actions],
            "hero_seat_id": str(hero_seat_id or ""),
            "state_confidence": float(self.tracker.state_confidence or 0.0),
            "ocr_metadata": ocr_metadata,
        }

    def _get_runtime_status(self) -> dict:
        persistence = self.runtime_history_store.summarize()
        persisted_history = {
            "events": self.runtime_history_store.read_recent("events", limit=10),
            "decisions": self.runtime_history_store.read_recent("decisions", limit=10),
            "incidents": self.runtime_history_store.read_recent("incidents", limit=10),
            "metrics": self.runtime_history_store.read_recent("metrics", limit=10),
        }
        history = {
            "events": list(self.runtime_event_history),
            "decisions": list(self.decision_trace_history),
            "incidents": list(self.incident_history),
            "metrics": list(self.metric_snapshot_history),
            "persisted": persisted_history,
        }
        local_metrics = self._build_local_metrics(history)
        metrics_snapshot = self._build_persisted_metrics_snapshot(local_metrics, history, persistence)
        runtime_ab_summary = self._build_runtime_ab_summary(history["decisions"])
        persisted_ab_summary = self._build_runtime_ab_summary(persisted_history["decisions"])
        combined_decisions = self._dedupe_runtime_ab_decisions(
            list(history["decisions"]) + list(persisted_history["decisions"])
        )
        combined_ab_summary = self._build_runtime_ab_summary(
            combined_decisions
        )
        runtime_policy_compare_summary = self._build_policy_compare_summary(history["decisions"])
        persisted_policy_compare_summary = self._build_policy_compare_summary(persisted_history["decisions"])
        combined_policy_compare_summary = self._build_policy_compare_summary(combined_decisions)
        if not history["metrics"]:
            history["metrics"] = [metrics_snapshot]
        return {
            "is_running": self.is_running,
            "app_name": "PokerMaster",
            "service": "PokerMaster",
            "version": "v2",
            "session_id": self._get_runtime_session_id(),
            "tracker": self.last_tracker_snapshot,
            "canonical_spot": dict(self.last_canonical_spot_snapshot) if isinstance(self.last_canonical_spot_snapshot, dict) else None,
            "gate": self.last_gate_result.to_dict(),
            "decision": self.last_decision_summary,
            "operator": self._build_operator_snapshot(),
            "history": history,
            "metrics": {
                **local_metrics,
                "latest_snapshot": metrics_snapshot,
            },
            "history_summary": {
                "event_count": len(history["events"]),
                "decision_count": len(history["decisions"]),
                "incident_count": len(history["incidents"]),
                "metrics_count": len(history["metrics"]),
                "latest_event_at": history["events"][0]["timestamp"] if history["events"] else None,
                "latest_decision_at": history["decisions"][0]["timestamp"] if history["decisions"] else None,
                "latest_incident_at": history["incidents"][0]["timestamp"] if history["incidents"] else None,
                "latest_metrics_at": history["metrics"][0]["timestamp"] if history["metrics"] else None,
                "metrics_window_size": local_metrics["window_size"],
                "persisted_event_count": len(persisted_history["events"]),
                "persisted_decision_count": len(persisted_history["decisions"]),
                "persisted_incident_count": len(persisted_history["incidents"]),
                "persisted_metrics_count": len(persisted_history["metrics"]),
                "latest_persisted_event_at": persisted_history["events"][0]["timestamp"] if persisted_history["events"] else None,
                "latest_persisted_decision_at": persisted_history["decisions"][0]["timestamp"] if persisted_history["decisions"] else None,
                "latest_persisted_incident_at": persisted_history["incidents"][0]["timestamp"] if persisted_history["incidents"] else None,
                "latest_persisted_metrics_at": persisted_history["metrics"][0]["timestamp"] if persisted_history["metrics"] else None,
                "rl_ab": {
                    "runtime": runtime_ab_summary,
                    "persisted": persisted_ab_summary,
                    "combined": combined_ab_summary,
                },
                "policy_compare": {
                    "runtime": runtime_policy_compare_summary,
                    "persisted": persisted_policy_compare_summary,
                    "combined": combined_policy_compare_summary,
                },
                "persistence": persistence,
            },
        }

    async def main_loop(self):
        try:
            await self.db.connect()
        except Exception as e:
            logger.error(f"Échec de connexion DB: {e}")
            
        # Démarrage de l'API locale pour le pont avec React
        await self.api_server.start()
        self._push_runtime_event("lifecycle", "api_started", port=8080)
        self._persist_runtime_metrics_snapshot(force=True)
        
        self.camera.start()
        self.is_running = True
        logger.info("🚀 SuperBot 2026 Démarré. API Locale sur le port 8080.")
        self._push_runtime_event("lifecycle", "bot_started")

        try:
            while self.is_running:
                try:
                    if self._operator_action_mode() == "paused":
                        await asyncio.sleep(0.1)
                        continue

                    frame = self.camera.get_latest_frame()
                    if frame is None:
                        await asyncio.sleep(0.01)
                        continue

                    state = await self._process_frame(frame)
                    canonical_state = self._convert_state_for_tracker(state, frame)
                    self.last_canonical_spot_snapshot = canonical_state.to_dict()
                    tracker_data = canonical_state.to_tracker_payload()
                    
                    await self.tracker.update_from_vision(tracker_data)

                    self.last_tracker_snapshot = self._build_tracker_snapshot(tracker_data)
                    self._record_runtime_transition(self.last_tracker_snapshot)
                    self._persist_runtime_metrics_snapshot()

                    # Si le bot a les cartes en main
                    if len(canonical_state.hero_cards) == 2 and canonical_state.legal_actions:
                        primary_villain = self.tracker.get_primary_villain()
                        effective_stack = self.tracker.get_effective_stack()

                        if primary_villain and effective_stack > 0:
                            flow_result = await self._run_decision_gate_flow(
                                canonical_state=canonical_state,
                                state=state,
                                primary_villain=primary_villain,
                                effective_stack=effective_stack,
                            )

                            if not flow_result["gate_result"].allowed:
                                logger.warning("Action live bloquee par le gate: %s", flow_result["gate_result"].to_dict())

                    await asyncio.sleep(0.05)
                    
                except Exception as loop_err:
                    logger.error(f"Erreur mineure dans l'analyse: {loop_err}")
                    self._push_incident("loop_error", severity="error", error=str(loop_err))
                    self._push_runtime_event("error", "loop_error", error=str(loop_err))
                    self._persist_runtime_metrics_snapshot(force=True)
                    await asyncio.sleep(1.0)
                
        except asyncio.CancelledError:
            logger.info("Fermeture demandée.")
        except Exception as e:
            logger.critical(f"Erreur FATALE: {e}")
            self._push_incident("fatal_error", severity="critical", error=str(e))
            self._push_runtime_event("error", "fatal_error", error=str(e))
            self._persist_runtime_metrics_snapshot(force=True)
        finally:
            self._push_runtime_event("lifecycle", "bot_stopped")
            self._persist_runtime_metrics_snapshot(force=True)
            self.camera.stop()
            await self.api_server.stop()
            await self.db.close()
            logger.info("Arrêt complet effectué.")

def run_bot():
    bot = SuperBotController()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(bot.main_loop())
    except KeyboardInterrupt:
        logger.info("Extinction gracieuse...")
        bot.is_running = False
        loop.run_until_complete(asyncio.sleep(1))

if __name__ == "__main__":
    run_bot()
