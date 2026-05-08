# -*- coding: utf-8 -*-
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from pathlib import Path
try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc
import cv2
import numpy as np
import json
import os
import socket
import subprocess
import sys
import time
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def ensure_admin() -> None:
    if is_admin():
        return
    print("Demande des droits administrateur...")
    # Re-run the program with admin rights
    # Need to quote sys.executable just in case, but ShellExecuteW handles it.
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(['"'+arg+'"' for arg in sys.argv]), None, 1)
    sys.exit(0)

import traceback

import unicodedata
from types import SimpleNamespace
import uuid
from typing import Dict, Tuple, List, Optional, Iterable
import warnings
import torch

warnings.filterwarnings("ignore", message=".*'pin_memory'.*")
warnings.filterwarnings("ignore", message=".*weights_only=False.*")
try:
    import onnxruntime
    onnxruntime.set_default_logger_severity(3)
except ImportError:
    pass

# --- PROTECTION VRAM (GTX 1060 3GB) ---
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
if torch.cuda.is_available():
    # On bride le moteur PyTorch pour qu'il n'engloutisse jamais plus de 70% des 3Go (soit ~2.1 Go).
    # Cela laisse ~900 Mo pour le bureau Windows, la vidéo, et le moteur vision (ONNX/YOLO).
    torch.cuda.set_per_process_memory_fraction(0.70, device=0)
    # Désactiver le benchmark cuDNN évite l'allocation de VRAM inutile
    torch.backends.cudnn.benchmark = False
# --------------------------------------

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Imports de nos modules
from src.vision.capture import ScreenCapture
from src.vision.detector import (
    PokerDetector,
    TableState,
    DetectionResult,
    decode_card_token,
    dedupe_nearby_detections,
    detection_sort_key,
)
from src.vision.ocr import PokerOCR
from src.vision.numeric_reader import NumericReader
from src.vision.player_name_reader import PlayerNameReader
from src.data.database import DatabaseManager
from src.bot.table_tracker import TableTracker
from src.bot.decision_maker import DecisionMaker
from src.bot.action_controller import ActionController
from src.bot.sanity_checker import ActionIntent, GateReason, GateResult, SanityChecker
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
from src.bot.pixel_probe import FastPixelProbe

# --- Imports Active Learning ---
from src.bot.active_learning import HumanInTheLoop
from src.runtime.bridge_store import RuntimeBridgeStore
from src.runtime.frame_pipeline import FramePipeline
from src.runtime.go_live_gate import evaluate_go_live_gate
from src.runtime.health import HealthMonitor
from src.runtime.history_store import RuntimeHistoryStore
from src.runtime.loop import RuntimeLoop
from src.runtime.operator_bridge import OperatorBridge
from src.runtime.poker_state_validator import PokerStateValidator
from src.runtime.preflight import Preflight, PreflightError
from src.runtime.player_identity_state import PlayerIdentityState
from src.runtime.player_name_resolver import resolve_player_name
from src.runtime.readiness import build_runtime_readiness
from src.solver.provider import SolverProvider
from src.vision.observation_dataset import ObservationDatasetCollector
from src.vision.runtime_failure_dataset import RuntimeFailureDataset

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
RUNTIME_PORT_CANDIDATES = (8005, 8080)
RUNTIME_BRIDGE_DIR = "log/runtime_bridge"
ASSISTED_MIN_STATE_CONFIDENCE = 0.72
ASSISTED_MIN_DECISION_CONFIDENCE = 0.67
ASSISTED_MIN_GATE_CONFIDENCE = 0.95
ASSISTED_MIN_PROFILE_RELIABILITY = 0.12
ASSISTED_MIN_OBSERVED_HANDS = 12
ASSISTED_PROFILE_REQUIRED_SOURCES = {"EXPLOIT_PROFILE", "RL_VALIDATED"}
ASSISTED_FALLBACK_PASSIVE_ACTIONS = {"CHECK", "FOLD"}
ASSISTED_FALLBACK_MIN_DECISION_CONFIDENCE = 0.42
LIVE_DETAILS_LOG_INTERVAL_S = 1.2


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


def _select_available_runtime_port(candidates: Tuple[int, ...] = RUNTIME_PORT_CANDIDATES) -> int:
    for port in candidates:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            probe.close()
    return candidates[0]


def _resolve_runtime_api_port(candidates: Tuple[int, ...] = RUNTIME_PORT_CANDIDATES) -> int:
    configured = os.getenv("POKER_RUNTIME_API_PORT")
    if configured:
        try:
            return int(configured)
        except ValueError:
            logger.warning("POKER_RUNTIME_API_PORT invalide (%s), selection automatique.", configured)
    return _select_available_runtime_port(candidates)

class SuperBotController:
    def __init__(self, config_path: str = "config.json"):
        # 1. Chargement de la Configuration
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            logger.error(f"Fichier de config {config_path} introuvable. ArrÃªt.")
            exit(1)
            
        bot_cfg = self.config.get("bot", {})
        db_cfg = self.config.get("database", {}) or {}
        
        # --- 2. Vision ---
        self.camera = ScreenCapture(
            target_fps=bot_cfg.get("target_fps", 30),
            prefer_window_capture=bool(bot_cfg.get("prefer_window_capture", False)),
        )
        yolo_cfg = self.config.get("yolo", {}) or {}
        vision_pipeline = self.config.get("vision_pipeline", ["yolo", "llm", "opencv"])
        
        self.detector = PokerDetector(
            model_path=yolo_cfg.get("model_path", "models/poker_yolo_v11.engine"),
            pipeline=vision_pipeline
        )
        if not bool(yolo_cfg.get("live_enabled", False)):
            self.detector.model = None
            logger.info("YOLO desactive pour la boucle live. Backend template force.")
        ocr_cfg = self.config.get("ocr", {}) or {}
        self.analysis_ocr = PokerOCR.from_config(ocr_cfg)
        fast_amount_ocr = PokerOCR.from_config(
            {
                **ocr_cfg,
                "mode": "fallback",
                "parallel": False,
            }
        )
        fast_live_ocr = PokerOCR(
            use_gpu=bool(ocr_cfg.get("use_gpu", True)),
            enabled_engines=["easyocr"],
            mode="priority",
            parallel=False,
        )
        self.ocr = fast_live_ocr if getattr(fast_live_ocr, "engines", []) else self.analysis_ocr
        self.amount_ocr = (
            fast_amount_ocr
            if getattr(fast_amount_ocr, "engines", [])
            else (self.analysis_ocr if getattr(self.analysis_ocr, "engines", []) else self.ocr)
        )
        
        # --- 3. Data & Tracking ---
        self.db = DatabaseManager(
            dsn=db_cfg.get("dsn"),
            mode=db_cfg.get("mode"),
            persistence_path=db_cfg.get("observation_persistence_path"),
            persistence_enabled=bool(db_cfg.get("observation_persistence_enabled", True)),
        )
        self.tracker = TableTracker(self.db)
        
        runtime_cfg = self.config.get("runtime_history", {}) or {}
        self.runtime_session_id = self._build_runtime_session_id()
        self.runtime_history_store = RuntimeHistoryStore(
            enabled=runtime_cfg.get("enabled", True),
            file_path=runtime_cfg.get("file_path", "log/runtime_history.jsonl"),
            max_size_bytes=runtime_cfg.get("max_size_bytes", 1_048_576),
            session_id=self.runtime_session_id,
        )
        self.health_monitor = HealthMonitor()

        # --- 4. Cerveau IA ---
        rl_cfg = self._build_rl_runtime_config()
        solver_provider = SolverProvider(
            native_backend=None,
            http_url=os.getenv("POKER_GTO_SERVER_URL") or "http://127.0.0.1:8765/v2/solve",
            health_monitor=self.health_monitor,
        )
        self.solver_provider = solver_provider
        self.decision_maker = DecisionMaker(
            self.db,
            solver_provider=solver_provider,
            create_rl_agent=rl_cfg["enable_rl"],
            enable_validated_rl=rl_cfg["enable_validated_rl"],
            autoload_rl_model=rl_cfg["autoload_rl_model"],
        )
        self.runtime_sanity = SanityChecker()
        
        # --- 5. ExÃ©cuteur Stealth ---
        self.action_controller = ActionController(window_title_keywords=bot_cfg.get("window_title_keywords", "VirtualBox"))
        
        # --- 6. ACTIVE LEARNING (HITL) ---
        self.hitl = HumanInTheLoop(target_dataset_size=100)
        # Configuration de l'Auto-Adaptation via API
        self.hitl.setup_api_fallback(
            providers=self.config.get("auto_annotator", {}).get("providers", [])
        )
        self.detector.ai_fallback = self.hitl.ai_fallback
        self.pixel_probe = FastPixelProbe()
        observation_capture_cfg = yolo_cfg.get("observation_capture", {}) or {}
        self.observation_dataset = ObservationDatasetCollector(
            enabled=bool(observation_capture_cfg.get("enabled", False)),
            dataset_dir=str(observation_capture_cfg.get("dataset_dir", "dataset/runtime_observation") or "dataset/runtime_observation"),
            capture_interval_s=float(observation_capture_cfg.get("capture_interval_s", 6.0) or 6.0),
            require_visual_change=bool(observation_capture_cfg.get("require_visual_change", True)),
            max_samples_per_session=int(observation_capture_cfg.get("max_samples_per_session", 500) or 500),
        )
        self.operator_controls: Dict[str, object] = {
            "profile_name": "live-runtime",
            "surface": "bot_cockpit",
            "capture_source": "ocr",
            "auto_refresh_enabled": True,
            "assisted_mode_enabled": False,
            "observation_mode_enabled": False,
            "shadow_mode_enabled": False,
            "manual_override_enabled": False,
            "paused": False,
            "updated_at": self._utc_now(),
        }
        self.runtime_api_port = _resolve_runtime_api_port()
        self.runtime_bridge_store = RuntimeBridgeStore(os.getenv("POKER_RUNTIME_BRIDGE_DIR") or RUNTIME_BRIDGE_DIR)
        self._runtime_state_publish_interval_s = 0.15
        self.operator_bridge = OperatorBridge(
            root=ROOT,
            bridge_store=self.runtime_bridge_store,
            history_store=self.runtime_history_store,
            runtime_api_port=self.runtime_api_port,
            build_state=self._build_runtime_bridge_state,
            apply_command=self._apply_bridge_command,
            push_incident=self._push_incident,
            health_monitor=self.health_monitor,
            publish_interval_s=self._runtime_state_publish_interval_s,
        )
        self.frame_pipeline = FramePipeline(self)
        self.runtime_loop = RuntimeLoop(self)
        
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
        self.last_resolved_runtime_state: Optional[Dict[str, object]] = None
        self.last_valid_frame: Optional[np.ndarray] = None
        self.runtime_event_history = deque(maxlen=24)
        self.decision_trace_history = deque(maxlen=16)
        self.incident_history = deque(maxlen=16)
        self.metric_snapshot_history = deque(maxlen=24)
        self._last_hero_seat_id: Optional[str] = None
        self._last_runtime_street = "IDLE"
        self._last_metrics_persisted_at: Optional[datetime] = None
        self._last_metrics_snapshot_signature: Optional[tuple] = None
        self._last_valid_player_names_by_seat: Dict[str, str] = {}
        self.player_identity_state = PlayerIdentityState()
        self._recent_runtime_streets = deque(maxlen=3)
        self._recent_runtime_legal_actions = deque(maxlen=3)
        self._recent_runtime_state_confidences = deque(maxlen=3)
        self._recent_runtime_hero_seat_ids = deque(maxlen=3)
        self._recent_runtime_action_button_signatures = deque(maxlen=5)
        self._last_capture_region_refresh_at = 0.0
        self._capture_region_refresh_interval_s = 1.0
        self._cached_runtime_players: tuple[CanonicalPlayer, ...] = ()
        self.poker_state_validator = PokerStateValidator()
        self._cached_runtime_players_signature: tuple = ()
        self._cached_runtime_players_at = 0.0
        self._last_live_details_signature: tuple = ()
        self._last_live_details_logged_at = 0.0
        self._player_ocr_refresh_interval_s = 8.0
        self._last_good_runtime_hero_cards: tuple[str, ...] = ()
        self._last_good_runtime_hero_cards_at = 0.0
        self._runtime_hero_cards_ttl_s = 1.75
        self._runtime_hero_cards_rank_flip_ttl_s = float(bot_cfg.get("runtime_hero_cards_rank_flip_ttl_s", 1.0) or 1.0)
        self.go_live_gate_thresholds = dict(bot_cfg.get("go_live_gate", {}) or {})
        self.runtime_failure_dataset = RuntimeFailureDataset(
            enabled=bool(bot_cfg.get("runtime_failure_dataset_enabled", True)),
            dataset_dir=str(bot_cfg.get("runtime_failure_dataset_dir", "dataset/runtime_failures") or "dataset/runtime_failures"),
        )
        self._max_live_frame_age_s = float(bot_cfg.get("max_live_frame_age_s", 1.25) or 1.25)
        self._slow_loop_log_threshold_ms = float(bot_cfg.get("slow_loop_log_threshold_ms", 750.0) or 750.0)
        self._post_action_settle_delay_s = float(bot_cfg.get("post_action_settle_delay_s", 0.2) or 0.2)
        self._post_action_settle_timeout_s = float(bot_cfg.get("post_action_settle_timeout_s", 0.9) or 0.9)
        self._post_action_settle_poll_interval_s = float(bot_cfg.get("post_action_settle_poll_interval_s", 0.03) or 0.03)
        self._visual_state_refresh_interval_s = float(bot_cfg.get("visual_state_refresh_interval_s", 0.9) or 0.9)
        self._visual_state_change_threshold = float(bot_cfg.get("visual_state_change_threshold", 0.985) or 0.985)
        self._pot_ocr_refresh_interval_s = float(bot_cfg.get("pot_ocr_refresh_interval_s", 0.12) or 0.12)
        self._pot_crop_change_threshold = float(bot_cfg.get("pot_crop_change_threshold", 0.85) or 0.85)
        self._last_pot_ocr_at = 0.0
        self._last_fast_pot_snapshot: Dict[str, object] = {}
        self._fast_pot_stale_after_s = float(bot_cfg.get("fast_pot_stale_after_s", 0.35) or 0.35)
        self._live_debounce_reset_sleep_s = float(bot_cfg.get("live_debounce_reset_sleep_s", 0.03) or 0.03)
        self._live_debounce_stable_window_s = float(bot_cfg.get("live_debounce_stable_window_s", 0.12) or 0.12)
        self._live_debounce_poll_sleep_s = float(bot_cfg.get("live_debounce_poll_sleep_s", 0.02) or 0.02)
        self._last_visual_previews: Dict[str, np.ndarray] = {}
        self._last_visual_state: Optional[TableState] = None
        self._last_visual_state_at = 0.0
        self._post_action_context_guard_s = float(bot_cfg.get("post_action_context_guard_s", 2.25) or 2.25)
        self._live_action_repeat_cooldown_s = float(bot_cfg.get("live_action_repeat_cooldown_s", 3.5) or 3.5)
        self._last_live_execution_signature: tuple = ()
        self._last_live_execution_context_signature: tuple = ()
        self._last_live_execution_action = ""
        self._last_live_execution_at = 0.0
        self._last_live_execution_status = ""
        self._last_live_execution_settle_status = ""
        self._last_locked_decision_signature: tuple = ()
        self._last_locked_decision_action = ""
        self._last_locked_decision_reason = ""
        self._last_locked_decision_at = 0.0
        self._last_locked_decision_log_signature: tuple = ()
        self._last_locked_decision_log_at = 0.0
        self._last_decision_signature: tuple = ()
        self._last_decision_payload: Optional[Dict[str, object]] = None
        self._last_decision_cached_at = 0.0
        self._decision_cache_ttl_s = float(bot_cfg.get("decision_cache_ttl_s", 0.35) or 0.35)
        self._locked_spot_log_interval_s = float(bot_cfg.get("locked_spot_log_interval_s", 1.0) or 1.0)
        self._locked_spot_poll_interval_s = float(bot_cfg.get("locked_spot_poll_interval_s", 0.1) or 0.1)
        self._runtime_readiness_failure_cooldown_s = float(bot_cfg.get("runtime_readiness_failure_cooldown_s", 2.0) or 2.0)
        self._last_runtime_readiness_failure_signature: tuple = ()
        self._last_runtime_readiness_failure_at = 0.0
        self._last_turn_probe_snapshot: Dict[str, object] = {}
        self._last_capture_context_signature: tuple = ()
        self._last_capture_context_changed_at = 0.0
        self._loop_stage = "startup"

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

    def _update_fast_pot_snapshot(self, snapshot: Optional[Dict[str, object]]) -> None:
        if not isinstance(snapshot, dict) or not snapshot:
            return
        value = float(snapshot.get("value", 0.0) or 0.0)
        if value <= 0.0:
            return
        enriched = dict(snapshot)
        enriched.setdefault("observed_at_monotonic", time.monotonic())
        self._last_fast_pot_snapshot = enriched

    def _get_recent_fast_pot_snapshot(self) -> Dict[str, object]:
        snapshot = dict(getattr(self, "_last_fast_pot_snapshot", {}) or {})
        if not snapshot:
            return {}
        age_s = max(0.0, time.monotonic() - float(snapshot.get("observed_at_monotonic", 0.0) or 0.0))
        if age_s > float(getattr(self, "_fast_pot_stale_after_s", 0.35) or 0.35):
            return {}
        snapshot["age_s"] = age_s
        return snapshot

    @staticmethod
    def _is_valid_capture_region(region: object) -> bool:
        if not isinstance(region, (tuple, list)) or len(region) != 4:
            return False
        try:
            left, top, right, bottom = [int(value) for value in region]
        except Exception:
            return False
        if right <= left or bottom <= top:
            return False
        if min(left, top, right, bottom) <= -30000:
            return False
        return True

    def _refresh_capture_region(self, force: bool = False) -> Optional[Tuple[int, int, int, int]]:
        now = time.monotonic()
        if not force and (now - self._last_capture_region_refresh_at) < self._capture_region_refresh_interval_s:
            return self.camera.region

        self._last_capture_region_refresh_at = now
        next_region = self.action_controller.get_client_rect(refresh=True)
        if not self._is_valid_capture_region(next_region):
            next_region = self.action_controller.get_window_rect(refresh=False)
        if not self._is_valid_capture_region(next_region):
            next_region = None
        if next_region != self.camera.region:
            previous_region = self.camera.region
            previous_hwnd = getattr(self.camera, "window_hwnd", None)
            self.camera.region = next_region
            self.camera.window_hwnd = self.action_controller.hwnd
            if (
                getattr(self.camera, "capture_mode", self.camera.backend) == "dxcam"
                and getattr(self.camera, "is_capturing", False)
            ):
                try:
                    self.camera.stop()
                    self.camera.start(region=next_region, hwnd=self.action_controller.hwnd)
                except Exception as exc:
                    logger.warning(
                        "Impossible de reconfigurer la capture DXcam de %s vers %s: %s",
                        previous_region,
                        next_region,
                        exc,
                    )
            if next_region:
                logger.info("Capture ciblee sur la fenetre %s: %s", self.action_controller.window_title, next_region)
            else:
                logger.info("Aucune fenetre cible detectee, retour en capture plein ecran.")
            self._handle_capture_context_change(previous_hwnd, previous_region, self.action_controller.hwnd, next_region)
        return self.camera.region

    def _handle_capture_context_change(
        self,
        previous_hwnd: object,
        previous_region: object,
        next_hwnd: object,
        next_region: object,
    ) -> None:
        previous_signature = (
            int(previous_hwnd or 0),
            tuple(int(value) for value in previous_region) if isinstance(previous_region, (tuple, list)) and len(previous_region) == 4 else (),
        )
        next_signature = (
            int(next_hwnd or 0),
            tuple(int(value) for value in next_region) if isinstance(next_region, (tuple, list)) and len(next_region) == 4 else (),
        )
        if previous_signature == next_signature:
            return
        self._last_capture_context_signature = next_signature
        self._last_capture_context_changed_at = time.monotonic()
        self._last_fast_pot_snapshot = {}
        self._last_turn_probe_snapshot = {}
        self._debounce_state_hash = None
        self._debounce_start_time = 0.0
        self.last_valid_frame = None
        self.tracker.reset_for_new_hand()
        self.tracker.sanity.reset_pot_reconciliation()
        self.runtime_sanity.reset_pot_reconciliation()
        self._clear_live_execution_guard()
        idle_state = CanonicalTableState(spot_id="live:IDLE:capture_context_change", street="IDLE", pot=0.0)
        self._clear_live_decision_summary(idle_state)
        logger.info("Capture context reset: hwnd=%s region=%s", next_signature[0], next_signature[1])

    def _capture_context_recently_changed(self) -> bool:
        changed_at = float(getattr(self, "_last_capture_context_changed_at", 0.0) or 0.0)
        if changed_at <= 0.0:
            return False
        return (time.monotonic() - changed_at) <= 1.25

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
        assisted_mode_enabled = bool(controls.get("assisted_mode_enabled", False))
        observation_mode_enabled = bool(controls.get("observation_mode_enabled", False))
        shadow_mode_enabled = bool(controls.get("shadow_mode_enabled", False))
        manual_override_enabled = bool(controls.get("manual_override_enabled", False))
        auto_refresh_enabled = bool(controls.get("auto_refresh_enabled", True))
        is_running = bool(getattr(self, "is_running", True))
        go_live_gate = dict(getattr(self, "last_go_live_gate", {}) or {})
        go_live_gate_passed = bool(go_live_gate.get("passed", False))
        if not is_running:
            status = "offline"
        elif paused:
            status = "paused"
        elif manual_override_enabled:
            status = "manual_override"
        elif observation_mode_enabled:
            status = "observation"
        elif shadow_mode_enabled:
            status = "shadow"
        elif assisted_mode_enabled:
            status = "assisted"
        elif not go_live_gate_passed:
            status = "go_live_blocked"
        else:
            status = "ready"
        return {
            "profile_name": str(controls.get("profile_name") or "live-runtime"),
            "surface": str(controls.get("surface") or "bot_cockpit"),
            "capture_source": str(controls.get("capture_source") or "ocr"),
            "auto_refresh_enabled": auto_refresh_enabled,
            "assisted_mode_enabled": assisted_mode_enabled,
            "observation_mode_enabled": observation_mode_enabled,
            "shadow_mode_enabled": shadow_mode_enabled,
            "manual_override_enabled": manual_override_enabled,
            "paused": paused,
            "status": status,
            "go_live_gate": go_live_gate,
            "updated_at": str(controls.get("updated_at") or self._utc_now()),
        }

    def _build_observation_snapshot(self) -> Dict[str, object]:
        database = getattr(self, "db", None)
        summary = dict(database.summarize_observation(limit=5) or {}) if database is not None else {}
        operator = self._build_operator_snapshot()
        mode_enabled = bool(operator.get("observation_mode_enabled", False))
        operator_status = str(operator.get("status") or "offline")
        observation_dataset = getattr(self, "observation_dataset", None)
        vision_dataset_snapshot = (
            observation_dataset.snapshot()
            if observation_dataset is not None and hasattr(observation_dataset, "snapshot")
            else {}
        )
        return {
            "mode_enabled": mode_enabled,
            "collecting": bool(
                bool(getattr(self, "is_running", True))
                and operator_status in {"ready", "assisted", "observation", "shadow"}
                and not bool(operator.get("paused", False))
            ),
            "vision_dataset": vision_dataset_snapshot,
            **summary,
        }

    def _capture_observation_dataset_sample(
        self,
        frame: np.ndarray,
        canonical_state: CanonicalTableState,
        detector_state: TableState,
    ) -> None:
        collector = getattr(self, "observation_dataset", None)
        if collector is None:
            return
        try:
            collector.maybe_capture(frame=frame, canonical_state=canonical_state, detector_state=detector_state)
        except Exception as exc:
            logger.warning("Capture observation YOLO ignoree: %s", exc)

    async def _capture_observation_dataset_sample_async(
        self,
        frame: np.ndarray,
        canonical_state: CanonicalTableState,
        detector_state: TableState,
    ) -> None:
        if bool(getattr(self, "_observation_capture_task_running", False)):
            return
        self._observation_capture_task_running = True
        try:
            frame_copy = frame.copy() if isinstance(frame, np.ndarray) else frame
            canonical_copy = canonical_state.model_copy(deep=True) if hasattr(canonical_state, "model_copy") else canonical_state
            detector_copy = self._copy_table_state(detector_state) if detector_state is not None else detector_state
            await asyncio.to_thread(
                self._capture_observation_dataset_sample,
                frame_copy,
                canonical_copy,
                detector_copy,
            )
        finally:
            self._observation_capture_task_running = False

    def _export_observation_dataset(self, player_limit: int = 50, hand_limit: int = 100) -> Dict[str, object]:
        dataset = dict(self.db.export_observation_dataset(player_limit=player_limit, hand_limit=hand_limit) or {})
        dataset["session_id"] = self._get_runtime_session_id()
        dataset["mode_enabled"] = bool(self._build_operator_snapshot().get("observation_mode_enabled", False))
        dataset["is_running"] = bool(self.is_running)
        return dataset

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
            "assisted_mode_enabled": ("assisted_mode_enabled", "assistedModeEnabled"),
            "observation_mode_enabled": ("observation_mode_enabled", "observationModeEnabled"),
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
        if normalized_patch.get("assisted_mode_enabled"):
            controls["observation_mode_enabled"] = False
            controls["shadow_mode_enabled"] = False
            controls["manual_override_enabled"] = False
        if normalized_patch.get("observation_mode_enabled"):
            controls["assisted_mode_enabled"] = False
            controls["shadow_mode_enabled"] = False
            controls["manual_override_enabled"] = False
        if normalized_patch.get("shadow_mode_enabled"):
            controls["assisted_mode_enabled"] = False
            controls["observation_mode_enabled"] = False
            controls["manual_override_enabled"] = False
        if normalized_patch.get("manual_override_enabled"):
            controls["assisted_mode_enabled"] = False
            controls["observation_mode_enabled"] = False
            controls["shadow_mode_enabled"] = False
        controls["updated_at"] = self._utc_now()
        self.operator_controls = controls

        next_snapshot = self._build_operator_snapshot()
        changed_fields = {
            key: next_snapshot.get(key)
            for key in (
                "paused",
                "assisted_mode_enabled",
                "observation_mode_enabled",
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
        self._publish_runtime_bridge_state(force=True)

        return next_snapshot

    def _build_hitl_snapshot(self) -> Dict[str, object]:
        current_issue = self.hitl.current_issue if isinstance(self.hitl.current_issue, dict) else None
        serialized_issue = None
        if current_issue is not None:
            serialized_issue = {
                "type": current_issue.get("type"),
                "reason": current_issue.get("reason"),
                "image_base64": current_issue.get("image_base64"),
                "width": current_issue.get("width"),
                "height": current_issue.get("height"),
                "resolution": current_issue.get("resolution"),
            }
        return {
            "ready_for_training": bool(self.hitl.check_convergence()),
            "collected_samples": int(getattr(self.hitl, "annotations_count", 0) or 0),
            "target_samples": int(getattr(self.hitl, "target_dataset_size", 0) or 0),
            "is_waiting_for_human": bool(getattr(self.hitl, "is_waiting_for_human", False)),
            "current_issue": serialized_issue,
        }

    def _get_frame_pipeline(self) -> FramePipeline:
        pipeline = getattr(self, "frame_pipeline", None)
        if pipeline is None:
            pipeline = FramePipeline(self)
            self.frame_pipeline = pipeline
        return pipeline

    def _get_runtime_loop(self) -> RuntimeLoop:
        runtime_loop = getattr(self, "runtime_loop", None)
        if runtime_loop is None:
            runtime_loop = RuntimeLoop(self)
            self.runtime_loop = runtime_loop
        return runtime_loop

    def _build_runtime_bridge_state(self) -> Dict[str, object]:
        health_snapshot = self.health_monitor.snapshot() if getattr(self, "health_monitor", None) is not None else {}
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
        metrics_snapshot = self._build_persisted_metrics_snapshot(local_metrics, history, self.runtime_history_store.summarize())
        current_readiness = dict(self.last_decision_summary.get("runtime_readiness", {}) or {})
        current_validation = dict((self.last_resolved_runtime_state or {}).get("metadata", {}).get("poker_state_validation", {}) or {}) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else {}
        go_live_gate = evaluate_go_live_gate(
            local_metrics,
            metrics_snapshot,
            readiness=current_readiness,
            validation=current_validation,
            thresholds=getattr(self, "go_live_gate_thresholds", {}),
        )
        self.last_go_live_gate = go_live_gate.to_dict()
        return {
            "generated_at": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "is_running": bool(self.is_running),
            "app_name": "PokerMaster",
            "service": "PokerMaster",
            "version": "v2",
            "runtime_api_port": self.runtime_api_port,
            "tracker": dict(self.last_tracker_snapshot),
            "canonical_spot": dict(self.last_canonical_spot_snapshot) if isinstance(self.last_canonical_spot_snapshot, dict) else None,
            "gate": self.last_gate_result.to_dict(),
            "decision": dict(self.last_decision_summary),
            "readiness": dict(self.last_decision_summary.get("runtime_readiness", {}) or {}),
            "go_live_gate": go_live_gate.to_dict(),
            "health": health_snapshot,
            "active_solver_backend": self.solver_provider.active_backend() if getattr(self, "solver_provider", None) is not None else "fallback",
            "degraded_reasons": self.health_monitor.degraded_reasons() if getattr(self, "health_monitor", None) is not None else [],
            "last_success_at": self.health_monitor.overall_last_success_at() if getattr(self, "health_monitor", None) is not None else None,
            "operator": self._build_operator_snapshot(),
            "observation": self._build_observation_snapshot(),
            "loop_stage": str(getattr(self, "_loop_stage", "")),
            "history": {
                "events": list(self.runtime_event_history),
                "decisions": list(self.decision_trace_history),
                "incidents": list(self.incident_history),
                "metrics": list(self.metric_snapshot_history),
            },
            "hitl": self._build_hitl_snapshot(),
        }

    def _publish_runtime_bridge_state(self, force: bool = False) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.publish_state(force=force)

    def _set_loop_stage(self, stage: str, publish: bool = False) -> None:
        self._loop_stage = str(stage or "")
        if publish:
            self._publish_runtime_bridge_state(force=True)

    def _apply_bridge_command(self, command: Dict[str, object]) -> None:
        kind = str(command.get("kind") or "").strip().lower()
        payload = dict(command.get("payload") or {})
        command_id = str(command.get("command_id") or "")

        if kind == "operator_patch":
            applied = self.update_operator_controls(payload)
            self._push_runtime_event(
                "operator",
                "bridge_operator_patch_applied",
                command_id=command_id,
                status=applied.get("status", "unknown"),
            )
            return

        if kind == "hitl_resolve":
            boxes = payload.get("boxes", [])
            if bool(self.hitl.is_waiting_for_human):
                self.hitl.resolve_human_intervention(list(boxes or []))
                self._push_runtime_event(
                    "hitl",
                    "bridge_hitl_resolved",
                    command_id=command_id,
                    box_count=len(list(boxes or [])),
                )
            else:
                self._push_runtime_event(
                    "hitl",
                    "bridge_hitl_ignored",
                    command_id=command_id,
                    reason="not_waiting_for_human",
                )
            return

        self._push_incident(
            "bridge_unknown_command",
            severity="warning",
            command_id=command_id,
            kind=kind or "unknown",
        )

    def _process_bridge_commands(self) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.process_pending_commands(limit=8)

    def _start_runtime_api_process(self) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.start_api_process()

    def _stop_runtime_api_process(self) -> None:
        bridge = getattr(self, "operator_bridge", None)
        if bridge is None:
            return
        bridge.stop_api_process()

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
        self._publish_runtime_bridge_state()

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
            self._record_runtime_failure(
                category="incident",
                incident_id=incident_id,
                severity=severity,
                context=context,
            )
            self._publish_runtime_bridge_state()

    def _record_runtime_failure(
        self,
        *,
        category: str,
        incident_id: str,
        severity: str = "warning",
        context: Optional[dict] = None,
    ) -> None:
        dataset = getattr(self, "runtime_failure_dataset", None)
        if dataset is None:
            return
        payload = {
            "timestamp": self._utc_now(),
            "session_id": self._get_runtime_session_id(),
            "category": str(category or "incident"),
            "incident_id": str(incident_id or "unknown"),
            "severity": str(severity or "warning"),
            "context": dict(context or {}),
            "decision": dict(self.last_decision_summary or {}),
            "tracker": dict(self.last_tracker_snapshot or {}),
            "canonical_spot": dict(self.last_resolved_runtime_state or {}) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else None,
            "runtime_readiness": dict(self.last_decision_summary.get("runtime_readiness", {}) or {}),
            "fallback_execution_readiness": dict(self.last_decision_summary.get("fallback_execution_readiness", {}) or {}),
            "frame": self.last_valid_frame.copy() if isinstance(getattr(self, "last_valid_frame", None), np.ndarray) else None,
            "crops": self._build_runtime_failure_crops(),
        }
        dataset.record_incident(payload)

        operator = self._build_operator_snapshot() if hasattr(self, "_build_operator_snapshot") else {}
        shadow_mode_enabled = bool(operator.get("shadow_mode_enabled", False))
        hitl = getattr(self, "hitl", None)
        if shadow_mode_enabled and hitl is not None and hasattr(hitl, "record_shadow_failure"):
            try:
                hitl.record_shadow_failure(
                    payload.get("frame"),
                    issue_type=str(incident_id or category or "runtime_failure"),
                    reason=str((context or {}).get("reason") or incident_id or category or "runtime_failure"),
                    context={
                        "category": str(category or "incident"),
                        "severity": str(severity or "warning"),
                        "runtime_context": dict(context or {}),
                        "tracker": dict(self.last_tracker_snapshot or {}),
                    },
                )
            except Exception as exc:
                logger.debug("Shadow mode capture ignoree: %s", exc)

    def _record_shadow_mode_failure(self, issue_type: str, reason: str, **context) -> None:
        operator = self._build_operator_snapshot()
        if not bool(operator.get("shadow_mode_enabled", False)):
            return
        hitl = getattr(self, "hitl", None)
        if hitl is None or not hasattr(hitl, "record_shadow_failure"):
            return
        frame = self.last_valid_frame.copy() if isinstance(getattr(self, "last_valid_frame", None), np.ndarray) else None
        hitl.record_shadow_failure(frame, issue_type=issue_type, reason=reason, context=context)

    def _on_action_gate_failure(
        self,
        gate_result: GateResult,
        canonical_state: CanonicalTableState,
        action_intent: ActionIntent,
    ) -> None:
        reason_codes = [reason.code for reason in (gate_result.reasons or [])]
        if any(code in {"HERO_CARDS_UNCERTAIN", "STATE_INCOHERENT", "BOARD_UNCERTAIN", "MISSING_POSTFLOP_POT", "LOW_STATE_CONFIDENCE"} for code in reason_codes):
            self._record_shadow_mode_failure(
                issue_type="sanity_gate_failure",
                reason=gate_result.reason,
                spot_id=str(canonical_state.spot_id or ""),
                action=action_intent.action,
                street=str(canonical_state.street or "IDLE"),
                board=list(canonical_state.board),
                hero_cards=list(canonical_state.hero_cards),
                reason_codes=reason_codes,
            )

    def _build_runtime_failure_crops(self) -> dict[str, np.ndarray]:
        frame = getattr(self, "last_valid_frame", None)
        canonical = getattr(self, "last_resolved_runtime_state", None)
        if not isinstance(frame, np.ndarray) or not isinstance(canonical, dict):
            return {}
        vision = dict((canonical.get("metadata") or {}).get("vision", {}) or {})
        crops = {}
        region_resolutions = dict(vision.get("region_resolutions", {}) or {})
        for field_name in ("pot", "hero", "actions"):
            selected = dict((region_resolutions.get(field_name) or {}).get("selected", {}) or {})
            bbox = selected.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                crop = self._safe_crop(frame, tuple(int(value) for value in bbox))
                if isinstance(crop, np.ndarray) and crop.size:
                    crops[field_name] = crop
        return crops

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

    def _should_record_runtime_readiness_failure(
        self,
        canonical_state: CanonicalTableState,
        validation,
        readiness,
    ) -> bool:
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        hero_participation = str(metadata.get("hero_participation", "") or "idle")
        if hero_participation in {"idle", "waiting_next_hand", "sitting_out", "observing_hand"}:
            return False

        signature = (
            str(canonical_state.spot_id or ""),
            str(getattr(validation, "state", "") or ""),
            str(getattr(readiness, "state", "") or ""),
            tuple(getattr(readiness, "degraded_fields", ()) or ()),
            tuple(getattr(readiness, "reasons", ()) or ()),
        )
        now = time.monotonic()
        last_signature = getattr(self, "_last_runtime_readiness_failure_signature", ())
        last_at = float(getattr(self, "_last_runtime_readiness_failure_at", 0.0) or 0.0)
        cooldown_s = float(getattr(self, "_runtime_readiness_failure_cooldown_s", 2.0) or 2.0)
        if signature == last_signature and (now - last_at) < cooldown_s:
            return False
        self._last_runtime_readiness_failure_signature = signature
        self._last_runtime_readiness_failure_at = now
        return True

    @staticmethod
    def _resolve_action_coord_key(action_name: str) -> str:
        normalized = str(action_name or "").strip().upper()
        if normalized == "FOLD":
            return "FOLD"
        if normalized in {"CALL", "CHECK"}:
            return "CALL"
        if normalized == "BET_BOX":
            return "BET_BOX"
        return "BET_BTN"

    def _get_action_coord_diagnostic(self, state: TableState, action_name: str) -> Dict[str, object]:
        metadata = dict(getattr(state, "metadata", {}) or {})
        diagnostics = dict(metadata.get("dynamic_coord_diagnostics", {}) or {})
        coord_key = self._resolve_action_coord_key(action_name)
        diagnostic = dict(diagnostics.get(coord_key, {}) or {})
        diagnostic.setdefault("coord_key", coord_key)
        diagnostic.setdefault("slot_boxes", dict(metadata.get("button_slot_boxes", {}) or {}))
        return diagnostic

    def _build_resolved_runtime_state(self, canonical_state: CanonicalTableState) -> CanonicalTableState:
        tracker_snapshot = dict(self._build_tracker_snapshot(canonical_state.to_tracker_payload()) or {})
        fast_pot_snapshot = self._get_recent_fast_pot_snapshot()
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        tracker_street = str(tracker_snapshot.get("street", canonical_state.street) or canonical_state.street)
        tracker_board = tuple(tracker_snapshot.get("board", []) or [])
        tracker_hero_cards = tuple(tracker_snapshot.get("hero_cards", []) or [])
        tracker_legal_actions = tuple(str(action).upper() for action in (tracker_snapshot.get("legal_actions", []) or []))
        tracker_pot = float(tracker_snapshot.get("pot", canonical_state.pot) or canonical_state.pot or 0.0)
        fast_pot_value = float(fast_pot_snapshot.get("value", 0.0) or 0.0)
        tracker_confidence = float(tracker_snapshot.get("state_confidence", canonical_state.state_confidence) or canonical_state.state_confidence or 0.0)
        hero_participation = str(metadata.get("hero_participation", "") or "idle")
        observation_mode = bool(metadata.get("observation_mode", False))
        use_tracker_street = (
            not observation_mode
            and bool(tracker_street)
            and tracker_street != canonical_state.street
        )
        resolved_state = CanonicalTableState(
            spot_id=str(
                canonical_state.spot_id
                if observation_mode
                else (tracker_snapshot.get("spot_id", canonical_state.spot_id) or canonical_state.spot_id)
            ),
            street=tracker_street if use_tracker_street else canonical_state.street,
            pot=(
                fast_pot_value if fast_pot_value > 0.0 else (
                    tracker_pot if tracker_pot > 0.0 or canonical_state.pot <= 0.0 else canonical_state.pot
                )
            ) if not observation_mode else canonical_state.pot,
            board=(tracker_board if tracker_board else canonical_state.board) if not observation_mode else canonical_state.board,
            hero_cards=(
                tracker_hero_cards if len(tracker_hero_cards) == 2 else canonical_state.hero_cards
            ) if not observation_mode else canonical_state.hero_cards,
            players=canonical_state.players,
            legal_actions=(tracker_legal_actions or canonical_state.legal_actions) if not observation_mode else canonical_state.legal_actions,
            action_buttons=canonical_state.action_buttons,
            state_confidence=(
                tracker_confidence if tracker_confidence > 0.0 else canonical_state.state_confidence
            ) if not observation_mode else canonical_state.state_confidence,
            metadata={
                **metadata,
                "observed_street": canonical_state.street,
                "tracker_street": tracker_street,
                "resolved_street": tracker_street if use_tracker_street else canonical_state.street,
                "raw_board": list(canonical_state.board),
                "validated_board": list(tracker_board or canonical_state.board),
                "pending_street_promotion": str(getattr(self.tracker, "pending_street_promotion", "") or ""),
                "hero_participation": hero_participation,
                "observation_mode": observation_mode,
                "fast_pot_snapshot": fast_pot_snapshot,
            },
        )
        validation = self.poker_state_validator.validate(resolved_state)
        readiness = build_runtime_readiness(resolved_state, validation)
        resolved_metadata = dict(resolved_state.metadata or {})
        resolved_metadata["poker_state_validation"] = validation.to_dict()
        resolved_metadata["runtime_readiness"] = readiness.to_dict()
        resolved_state = CanonicalTableState(
            spot_id=resolved_state.spot_id,
            street=resolved_state.street,
            pot=resolved_state.pot,
            board=resolved_state.board,
            hero_cards=resolved_state.hero_cards,
            players=resolved_state.players,
            legal_actions=resolved_state.legal_actions,
            action_buttons=resolved_state.action_buttons,
            state_confidence=resolved_state.state_confidence,
            metadata=resolved_metadata,
        )
        self.last_decision_summary["runtime_readiness"] = readiness.to_dict()
        if validation.state != "fully_valid" and self._should_record_runtime_readiness_failure(
            resolved_state,
            validation,
            readiness,
        ):
            self._record_shadow_mode_failure(
                issue_type="runtime_state_desync",
                reason="runtime_readiness_not_fully_valid",
                spot_id=resolved_state.spot_id,
                validation=validation.to_dict(),
                readiness=readiness.to_dict(),
            )
            self._record_runtime_failure(
                category="near_miss",
                incident_id="runtime_readiness_not_fully_valid",
                severity="warning" if validation.state == "degraded_valid" else "error",
                context={
                    "validation": validation.to_dict(),
                    "readiness": readiness.to_dict(),
                    "spot_id": resolved_state.spot_id,
                },
            )
        self.last_resolved_runtime_state = resolved_state.to_dict()
        return resolved_state

    @staticmethod
    def _format_log_cards(cards: object) -> str:
        if not cards:
            return "-"
        return " ".join(str(card) for card in cards if str(card).strip()) or "-"

    @staticmethod
    def _format_log_list(values: object) -> str:
        if not values:
            return "-"
        return ", ".join(str(value) for value in values if str(value).strip()) or "-"

    def _log_live_details(self, canonical_state: CanonicalTableState, state: TableState) -> None:
        table_detected = bool((state.metadata or {}).get("table_detected"))
        button_names = tuple(str(button.class_name) for button in (state.action_buttons or []))
        actionable_buttons = self._extract_actionable_runtime_buttons(button_names)
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        hero_participation = str(metadata.get("hero_participation", "idle") or "idle")
        observed_street = str(metadata.get("observed_street", canonical_state.street) or canonical_state.street)
        tracker_street = str(metadata.get("tracker_street", canonical_state.street) or canonical_state.street)
        background_idle = (
            hero_participation == "idle"
            and table_detected
            and canonical_state.street == "IDLE"
            and not canonical_state.hero_cards
            and not canonical_state.board
            and float(canonical_state.pot or 0.0) <= 0.0
            and not canonical_state.legal_actions
            and not actionable_buttons
        )
        signature = (
            table_detected,
            hero_participation,
            "background_idle" if background_idle else canonical_state.street,
            tuple() if background_idle else tuple(canonical_state.hero_cards),
            tuple() if background_idle else tuple(canonical_state.board),
            0.0 if background_idle else round(float(canonical_state.pot or 0.0), 1),
            tuple() if background_idle else tuple(canonical_state.legal_actions),
            tuple(sorted(set(button_names))), # Toujours ignorer l'ordre d'apparition
            # Ne pas inclure la confidence dans la signature pour éviter le spam aux micro-décimales
        )
        
        # Debouncer absolu : on n'affiche plus jamais le log si l'état exact (la signature) n'a pas changé.
        if signature == self._last_live_details_signature:
            return

        self._last_live_details_signature = signature
        self._last_live_details_logged_at = time.monotonic()

        logger.info(
            "LIVE | table=%s mode=%s street=%s hero=%s board=%s pot=%.1f buttons=%s legal=%s conf=%.2f",
            "yes" if table_detected else "no",
            hero_participation,
            canonical_state.street,
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_cards(canonical_state.board),
            float(canonical_state.pot or 0.0),
            self._format_log_list(button_names),
            self._format_log_list(canonical_state.legal_actions),
            float(canonical_state.state_confidence or 0.0),
        )
        if observed_street != canonical_state.street or tracker_street != canonical_state.street:
            logger.info(
                "LIVE_STATE | observed=%s tracker=%s resolved=%s raw_board=%s validated_board=%s pending=%s spot=%s",
                observed_street,
                tracker_street,
                canonical_state.street,
                self._format_log_cards(metadata.get("raw_board", canonical_state.board)),
                self._format_log_cards(metadata.get("validated_board", canonical_state.board)),
                str(metadata.get("pending_street_promotion", "") or "-") or "-",
                canonical_state.spot_id,
            )
        self._last_live_details_signature = signature
        self._last_live_details_logged_at = time.monotonic()

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

    def _resolve_live_decision_context(
        self,
        canonical_state: CanonicalTableState,
    ) -> tuple[Optional[object], float]:
        primary_villain = self.tracker.get_primary_villain()
        effective_stack = float(self.tracker.get_effective_stack() or 0.0)
        if primary_villain is not None and effective_stack > 0.0:
            return primary_villain, effective_stack

        hero_tracker = next(
            (player for player in self.tracker.players.values() if getattr(player, "is_hero", False)),
            None,
        )
        tracker_villains = [
            player
            for player in self.tracker.players.values()
            if not getattr(player, "is_hero", False) and not getattr(player, "has_folded", False)
        ]
        canonical_hero = next((player for player in canonical_state.players if player.is_hero), None)
        canonical_villains = [player for player in canonical_state.players if not player.is_hero and not player.has_folded]

        if primary_villain is None:
            if tracker_villains:
                primary_villain = min(
                    tracker_villains,
                    key=lambda player: getattr(player, "current_stack", 0.0) or getattr(player, "starting_stack", 0.0) or float("inf"),
                )
            elif canonical_villains:
                chosen = min(
                    canonical_villains,
                    key=lambda player: player.stack if player.stack > 0.0 else float("inf"),
                )
                primary_villain = SimpleNamespace(
                    name=chosen.identity,
                    has_button=chosen.has_button,
                    current_stack=float(chosen.stack or 0.0),
                )

        hero_stack_candidates = [
            float(value)
            for value in (
                getattr(hero_tracker, "current_stack", 0.0) if hero_tracker else 0.0,
                getattr(hero_tracker, "starting_stack", 0.0) if hero_tracker else 0.0,
                canonical_hero.stack if canonical_hero else 0.0,
            )
            if float(value or 0.0) > 0.0
        ]
        villain_stack_candidates = [
            float(value)
            for value in (
                [getattr(player, "current_stack", 0.0) or getattr(player, "starting_stack", 0.0) for player in tracker_villains]
                + [player.stack for player in canonical_villains]
            )
            if float(value or 0.0) > 0.0
        ]
        hero_stack = max(hero_stack_candidates) if hero_stack_candidates else 0.0
        villain_stack = max(villain_stack_candidates) if villain_stack_candidates else 0.0

        if effective_stack <= 0.0:
            if hero_stack > 0.0 and villain_stack > 0.0:
                effective_stack = min(hero_stack, villain_stack)
            elif hero_stack > 0.0:
                effective_stack = hero_stack
            elif villain_stack > 0.0:
                effective_stack = villain_stack

        actionable_preflop = (
            canonical_state.street == "PREFLOP"
            and len(canonical_state.hero_cards) == 2
            and bool(canonical_state.legal_actions)
        )
        if actionable_preflop:
            hero_has_button = bool(
                canonical_hero.has_button if canonical_hero is not None else getattr(hero_tracker, "has_button", False)
            )
            if primary_villain is None:
                fallback_villain_name = (
                    next(
                        (
                            str(getattr(player, "name", "") or "").strip()
                            for player in tracker_villains
                            if str(getattr(player, "name", "") or "").strip()
                        ),
                        "",
                    )
                    or next((str(player.name or "").strip() for player in canonical_villains if str(player.name or "").strip()), "")
                    or "live_villain"
                )
                primary_villain = SimpleNamespace(
                    name=fallback_villain_name,
                    has_button=not hero_has_button,
                    current_stack=float(villain_stack or effective_stack or hero_stack or canonical_state.pot or 1.0),
                )
            if effective_stack <= 0.0:
                effective_stack = max(hero_stack, villain_stack, float(canonical_state.pot or 0.0), 1.0)

        return primary_villain, max(0.0, float(effective_stack or 0.0))

    @staticmethod
    def _normalize_live_execution_pot(value: object) -> float:
        try:
            return round(max(0.0, float(value or 0.0)), 1)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_live_execution_actions(values: Iterable[object]) -> tuple[str, ...]:
        normalized = []
        for value in values or ():
            text = str(value or "").strip().upper()
            if text and text not in normalized:
                normalized.append(text)
        return tuple(normalized)

    @staticmethod
    def _normalize_live_execution_buttons(values: Iterable[object]) -> tuple[str, ...]:
        normalized = []
        for value in values or ():
            text = str(value or "").strip().lower()
            if text and text not in normalized:
                normalized.append(text)
        return tuple(sorted(normalized))

    def _build_live_execution_material_signature(self, canonical_state: CanonicalTableState) -> tuple:
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        metadata_signature = metadata.get("spot_signature")
        if isinstance(metadata_signature, (list, tuple)) and len(metadata_signature) >= 6:
            normalized_metadata_signature = list(metadata_signature)
            normalized_metadata_signature[4] = list(self._normalize_live_execution_actions(metadata_signature[4]))
            normalized_metadata_signature[5] = list(self._normalize_live_execution_buttons(metadata_signature[5]))
            metadata_signature = tuple(normalized_metadata_signature)
        actionable_buttons = self._normalize_live_execution_buttons(
            self._extract_actionable_runtime_buttons(canonical_state.action_buttons)
        )
        hero_seat_id = str(
            metadata.get("hero_seat_id")
            or (self.last_tracker_snapshot or {}).get("hero_seat_id", "")
            or ""
        ).strip()
        return (
            str(canonical_state.spot_id or "").strip(),
            str(canonical_state.street or "").strip().upper(),
            tuple(canonical_state.hero_cards),
            tuple(canonical_state.board),
            self._normalize_live_execution_pot(canonical_state.pot),
            self._normalize_live_execution_actions(canonical_state.legal_actions),
            actionable_buttons,
            hero_seat_id,
            tuple(metadata_signature) if isinstance(metadata_signature, (list, tuple)) else metadata_signature,
        )

    def _build_live_execution_signature(self, canonical_state: CanonicalTableState) -> tuple:
        return (
            self._build_live_execution_material_signature(canonical_state),
        )

    def _build_live_execution_context_signature(self, canonical_state: CanonicalTableState) -> tuple:
        return (
            self._build_live_execution_material_signature(canonical_state),
        )

    def _build_live_decision_signature(self, canonical_state: CanonicalTableState) -> tuple:
        return self._build_live_execution_material_signature(canonical_state)

    def _clear_live_decision_lock(self) -> None:
        self._last_locked_decision_signature = ()
        self._last_locked_decision_action = ""
        self._last_locked_decision_reason = ""
        self._last_locked_decision_at = 0.0
        self._last_locked_decision_log_signature = ()
        self._last_locked_decision_log_at = 0.0

    def _clear_live_decision_cache(self) -> None:
        self._last_decision_signature = ()
        self._last_decision_payload = None
        self._last_decision_cached_at = 0.0

    def _clear_live_execution_guard(self) -> None:
        self._last_live_execution_signature = ()
        self._last_live_execution_context_signature = ()
        self._last_live_execution_action = ""
        self._last_live_execution_at = 0.0
        self._last_live_execution_status = ""
        self._last_live_execution_settle_status = ""
        self._clear_live_decision_lock()
        self._clear_live_decision_cache()

    def _remember_locked_decision(self, canonical_state: CanonicalTableState, action_name: str, reason: str) -> None:
        self._last_locked_decision_signature = self._build_live_decision_signature(canonical_state)
        self._last_locked_decision_action = str(action_name or "").strip().upper()
        self._last_locked_decision_reason = str(reason or "").strip()
        self._last_locked_decision_at = time.monotonic()

    def _should_log_locked_decision(self, canonical_state: CanonicalTableState, reason: str) -> bool:
        signature = (self._build_live_decision_signature(canonical_state), str(reason or "").strip())
        interval_s = float(getattr(self, "_locked_spot_log_interval_s", 1.0) or 1.0)
        now = time.monotonic()
        if (
            signature == getattr(self, "_last_locked_decision_log_signature", ())
            and (now - float(getattr(self, "_last_locked_decision_log_at", 0.0) or 0.0)) < interval_s
        ):
            return False
        self._last_locked_decision_log_signature = signature
        self._last_locked_decision_log_at = now
        return True

    def _build_locked_decision_skip(self, canonical_state: CanonicalTableState) -> Optional[Dict[str, object]]:
        decision_signature = self._build_live_decision_signature(canonical_state)
        locked_signature = getattr(self, "_last_locked_decision_signature", ())
        if not locked_signature or decision_signature != locked_signature:
            return None
        reason = str(getattr(self, "_last_locked_decision_reason", "") or "").strip() or "same_spot_locked"
        action_name = str(getattr(self, "_last_locked_decision_action", "") or "").strip().upper()
        return {
            "signature": decision_signature,
            "reason": reason,
            "action": action_name,
            "log_now": self._should_log_locked_decision(canonical_state, reason),
        }

    def _build_minimal_skipped_decision(
        self,
        canonical_state: CanonicalTableState,
        action_name: str,
        reason: str,
    ) -> Dict[str, object]:
        return {
            "action": str(action_name or "").strip().upper(),
            "source": "LOCKED_SPOT_SKIP",
            "confidence": float(self.last_decision_summary.get("confidence", 0.0) or 0.0),
            "cache_hit": True,
            "fallback_used": bool(self.last_decision_summary.get("fallback_used", False)),
            "fallback_reason": self.last_decision_summary.get("fallback_reason"),
            "warnings": [],
            "incidents": [str(reason or "same_spot_locked")],
            "elapsed_ms": 0.0,
            "backend": "locked_skip",
            "metadata": {
                "profile": dict(self.last_decision_summary.get("profile", {}) or {}),
                "solver": dict(self.last_decision_summary.get("solver", {}) or {}),
                "confidence": dict(self.last_decision_summary.get("confidence_details", {}) or {}),
            },
        }

    def _get_cached_live_decision(self, canonical_state: CanonicalTableState) -> Optional[Dict[str, object]]:
        decision_signature = self._build_live_decision_signature(canonical_state)
        if decision_signature != getattr(self, "_last_decision_signature", ()):
            return None
        payload = getattr(self, "_last_decision_payload", None)
        if not isinstance(payload, dict):
            return None
        ttl_s = float(getattr(self, "_decision_cache_ttl_s", 0.35) or 0.35)
        cached_at = float(getattr(self, "_last_decision_cached_at", 0.0) or 0.0)
        if (time.monotonic() - cached_at) >= ttl_s:
            return None
        return dict(payload)

    def _remember_cached_live_decision(self, canonical_state: CanonicalTableState, decision: Dict[str, object]) -> None:
        self._last_decision_signature = self._build_live_decision_signature(canonical_state)
        self._last_decision_payload = dict(decision)
        self._last_decision_cached_at = time.monotonic()

    def _should_suppress_duplicate_live_action(
        self,
        canonical_state: CanonicalTableState,
        action_name: str,
    ) -> bool:
        normalized_action = str(action_name or "").strip().upper()
        last_signature = getattr(self, "_last_live_execution_signature", ())
        last_action = str(getattr(self, "_last_live_execution_action", "") or "").strip().upper()
        cooldown_s = float(getattr(self, "_live_action_repeat_cooldown_s", 3.5) or 3.5)
        last_at = float(getattr(self, "_last_live_execution_at", 0.0) or 0.0)
        if not normalized_action or not last_signature or not last_action:
            return False
        if normalized_action != last_action:
            return False
        if self._build_live_execution_signature(canonical_state) != last_signature:
            return False
        return (time.monotonic() - last_at) < cooldown_s

    def _should_suppress_recent_live_execution(self, canonical_state: CanonicalTableState) -> bool:
        last_context_signature = getattr(self, "_last_live_execution_context_signature", ())
        if not last_context_signature:
            return False
        if self._build_live_execution_context_signature(canonical_state) != last_context_signature:
            return False
        last_settle_status = str(getattr(self, "_last_live_execution_settle_status", "") or "").strip().lower()
        last_at = float(getattr(self, "_last_live_execution_at", 0.0) or 0.0)
        if last_settle_status == "timeout":
            # Si l'action a expiré sans que l'interface ne valide (miss-click, lag serveur),
            # on bloque les redondances pendant 5.0 secondes avant de s'autoriser à réessayer.
            return (time.monotonic() - last_at) < 5.0
        if str(getattr(self, "_last_live_execution_status", "") or "") != "executed":
            return False
        cooldown_s = float(getattr(self, "_post_action_context_guard_s", 2.25) or 2.25)
        return (time.monotonic() - last_at) < cooldown_s

    def _remember_live_execution(
        self,
        canonical_state: CanonicalTableState,
        action_name: str,
        status: str,
        settle_status: str = "",
    ) -> None:
        normalized_action = str(action_name or "").strip().upper()
        if not normalized_action:
            return
        self._last_live_execution_signature = self._build_live_execution_signature(canonical_state)
        self._last_live_execution_context_signature = self._build_live_execution_context_signature(canonical_state)
        self._last_live_execution_action = normalized_action
        self._last_live_execution_at = time.monotonic()
        self._last_live_execution_status = str(status or "")
        self._last_live_execution_settle_status = str(settle_status or "")

    def _evaluate_assisted_execution(
        self,
        canonical_state: CanonicalTableState,
        decision: dict,
        gate_result: GateResult,
    ) -> dict:
        decision_metadata = dict(decision.get("metadata", {}) or {})
        profile = dict(decision_metadata.get("profile", {}) or {})
        confidence_details = dict(decision_metadata.get("confidence", {}) or {})
        decision_source = str(decision.get("source", "unknown") or "unknown").strip().upper()
        observed_hands = int(
            profile.get("observed_hands", decision.get("profile", {}).get("observed_hands", 0) or 0) or 0
        )
        profile_reliability = float(
            profile.get("reliability", confidence_details.get("profile_reliability", 0.0) or 0.0) or 0.0
        )
        exploit_confidence = float(profile.get("exploit_confidence", 0.0) or 0.0)
        decision_confidence = float(decision.get("confidence", 0.0) or 0.0)
        gate_confidence = float(gate_result.confidence or 0.0)
        final_action = str(decision.get("action", "") or "").strip().upper()
        legal_actions = {str(action).strip().upper() for action in canonical_state.legal_actions}
        state_confidence = float(
            confidence_details.get("state_confidence", canonical_state.state_confidence or 0.0) or 0.0
        )
        fallback_used = bool(decision.get("fallback_used", False))
        requires_profile_sample = decision_source in ASSISTED_PROFILE_REQUIRED_SOURCES
        runtime_readiness = dict((canonical_state.metadata or {}).get("runtime_readiness", {}) or {})
        readiness_state = str(runtime_readiness.get("state") or "")
        readiness_score = float(runtime_readiness.get("score", state_confidence) or state_confidence or 0.0)

        result = {
            "enabled": bool((getattr(self, "operator_controls", {}) or {}).get("assisted_mode_enabled", False)),
            "learning_live": True,
            "auto_execute": False,
            "requires_operator_action": True,
            "status": "manual_required",
            "reason": "manual_review_required",
            "signals": {
                "decision_source": decision_source,
                "state_confidence": round(state_confidence, 3),
                "decision_confidence": round(decision_confidence, 3),
                "gate_confidence": round(gate_confidence, 3),
                "observed_hands": observed_hands,
                "profile_reliability": round(profile_reliability, 3),
                "exploit_confidence": round(exploit_confidence, 3),
                "fallback_used": fallback_used,
                "runtime_readiness_state": readiness_state,
                "runtime_readiness_score": round(readiness_score, 3),
            },
            "thresholds": {
                "min_state_confidence": ASSISTED_MIN_STATE_CONFIDENCE,
                "min_decision_confidence": ASSISTED_MIN_DECISION_CONFIDENCE,
                "min_gate_confidence": ASSISTED_MIN_GATE_CONFIDENCE,
                "min_profile_reliability": ASSISTED_MIN_PROFILE_RELIABILITY,
                "min_observed_hands": ASSISTED_MIN_OBSERVED_HANDS,
            },
        }

        if not gate_result.allowed:
            result["reason"] = "gate_blocked"
            return result
        if readiness_state == "blocked_local":
            result["reason"] = "runtime_blocked"
            return result
        if readiness_state == "conservative" and not fallback_used:
            result["reason"] = "runtime_conservative"
            return result
        if fallback_used:
            if (
                final_action in ASSISTED_FALLBACK_PASSIVE_ACTIONS
                and final_action in legal_actions
                and readiness_score >= ASSISTED_MIN_STATE_CONFIDENCE
                and gate_confidence >= ASSISTED_MIN_GATE_CONFIDENCE
                and decision_confidence >= ASSISTED_FALLBACK_MIN_DECISION_CONFIDENCE
            ):
                result.update(
                    {
                        "auto_execute": True,
                        "requires_operator_action": False,
                        "status": "auto_execute",
                        "reason": "fallback_passive_ready",
                    }
                )
                return result
            result["reason"] = "solver_fallback"
            return result
        if state_confidence < ASSISTED_MIN_STATE_CONFIDENCE:
            result["reason"] = "low_state_confidence"
            return result
        if decision_confidence < ASSISTED_MIN_DECISION_CONFIDENCE:
            result["reason"] = "low_decision_confidence"
            return result
        if gate_confidence < ASSISTED_MIN_GATE_CONFIDENCE:
            result["reason"] = "low_gate_confidence"
            return result
        if (
            requires_profile_sample
            and observed_hands < ASSISTED_MIN_OBSERVED_HANDS
            and profile_reliability < ASSISTED_MIN_PROFILE_RELIABILITY
        ):
            result["reason"] = "insufficient_profile_data"
            return result

        result.update(
            {
                "auto_execute": True,
                "requires_operator_action": False,
                "status": "auto_execute",
                "reason": "ready",
            }
        )
        return result

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
        gate_tracker_snapshot: Optional[Dict[str, object]] = None,
        frame_age_ms: Optional[float] = None,
    ) -> dict:
        dynamic_coords = self._get_dynamic_coordinates(state)
        hero_position = self._derive_live_hero_position(primary_villain)
        locked_skip = self._build_locked_decision_skip(canonical_state)
        if locked_skip:
            reason = str(locked_skip.get("reason", "same_spot_locked") or "same_spot_locked")
            action_name = str(locked_skip.get("action", "") or "").strip().upper()
            self.last_gate_result = GateResult(allowed=True, status="locked_skip", reasons=[])
            self.last_decision_summary.update(
                {
                    "action": action_name,
                    "source": "LOCKED_SPOT_SKIP",
                    "confidence": float(self.last_decision_summary.get("confidence", 0.0) or 0.0),
                    "cache_hit": True,
                    "elapsed_ms": 0.0,
                    "backend": "locked_skip",
                    "action_history": list(self.tracker.current_hand_actions),
                    "spot_id": canonical_state.spot_id,
                    "street": canonical_state.street,
                    "hero_cards": list(canonical_state.hero_cards),
                    "board": list(canonical_state.board),
                    "frame_age_ms": float(frame_age_ms or 0.0),
                    "hero_position": hero_position,
                    "effective_stack": float(effective_stack or 0.0),
                    "villain_name": primary_villain.name,
                    "gate_confidence": 1.0,
                    "gate_reason": reason,
                    "gate_allowed": True,
                    "trace_updated_at": self._utc_now(),
                    "history": {
                        "fallback": list(self.last_decision_summary.get("history", {}).get("fallback", []) or []),
                        "warnings": [],
                        "incidents": [reason],
                    },
                    "execution": {
                        "status": "decision_locked",
                        "reason": reason,
                    },
                }
            )
            if locked_skip.get("log_now"):
                logger.info(
                    "DECISION | skipped reason=%s action=%s street=%s hero=%s legal=%s",
                    reason,
                    action_name or "-",
                    canonical_state.street,
                    self._format_log_cards(canonical_state.hero_cards),
                    self._format_log_list(canonical_state.legal_actions),
                )
                self._push_runtime_event(
                    "decision",
                    "decision_skipped_locked",
                    action=action_name,
                    reason=reason,
                    spot_id=canonical_state.spot_id,
                )
            return {
                "decision": self._build_minimal_skipped_decision(canonical_state, action_name, reason),
                "gate_result": self.last_gate_result,
                "dynamic_coords": dynamic_coords,
            }

        decision = self._get_cached_live_decision(canonical_state)
        if decision is None:
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
            self._remember_cached_live_decision(canonical_state, decision)
        else:
            decision["cache_hit"] = True
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
            "frame_age_ms": float(frame_age_ms or 0.0),
            "hero_position": hero_position,
            "effective_stack": float(effective_stack or 0.0),
            "villain_name": primary_villain.name,
            "ab_decision": decision.get("ab_decision"),
            "profile": dict(decision.get("metadata", {}).get("profile", {})),
            "solver": _compact_solver_payload(decision.get("metadata", {}).get("solver", {})),
            "confidence_details": dict(decision.get("metadata", {}).get("confidence", {})),
        }

        action_intent = ActionIntent.from_payload(decision)
        gate_tracker_state = dict(gate_tracker_snapshot or self._build_gate_tracker_snapshot(canonical_state))
        gate_result = self.runtime_sanity.evaluate_action_gate(
            action_intent=action_intent,
            tracker_state=gate_tracker_state,
            coords_mapping=dynamic_coords,
            on_failure=lambda result: self._on_action_gate_failure(result, canonical_state, action_intent),
        )
        fallback_execution_readiness = self._evaluate_fallback_execution_readiness(
            canonical_state,
            frame_age_ms=frame_age_ms,
        )
        self.last_gate_result = gate_result
        self.last_decision_summary["gate_confidence"] = float(gate_result.confidence or 0.0)
        self.last_decision_summary["gate_reason"] = gate_result.reason
        self.last_decision_summary["gate_allowed"] = gate_result.allowed
        self.last_decision_summary["fallback_execution_readiness"] = fallback_execution_readiness
        assisted_result = self._evaluate_assisted_execution(canonical_state, decision, gate_result)
        self.last_decision_summary["assisted"] = assisted_result
        self.last_decision_summary["trace_updated_at"] = self._utc_now()
        self.last_decision_summary["history"] = {
            "fallback": [decision.get("fallback_reason")] if decision.get("fallback_reason") else [],
            "warnings": list(decision.get("warnings", [])),
            "incidents": self._normalize_incidents(normalized_incidents + (["gate_blocked"] if not gate_result.allowed else [])),
        }
        logger.info(
            "DECISION | street=%s hero=%s board=%s action=%s source=%s conf=%.2f fallback=%s gate=%s/%s assisted=%s",
            canonical_state.street,
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_cards(canonical_state.board),
            decision.get("action", ""),
            decision.get("source", "unknown"),
            float(decision.get("confidence", 0.0) or 0.0),
            "yes" if decision.get("fallback_used", False) else "no",
            "ok" if gate_result.allowed else "blocked",
            gate_result.reason,
            assisted_result.get("reason", "unknown"),
        )
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
            logger.warning(
                "CLICK | blocked_by_gate action=%s reason=%s legal=%s hero=%s board=%s",
                decision.get("action", ""),
                gate_result.reason,
                self._format_log_list(canonical_state.legal_actions),
                self._format_log_cards(canonical_state.hero_cards),
                self._format_log_cards(canonical_state.board),
            )
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
            if operator_mode in {"paused", "observation", "shadow", "manual_override", "go_live_blocked"}:
                self.last_decision_summary["execution"] = {
                    "status": "suppressed_by_operator",
                    "reason": operator_mode,
                }
                logger.info(
                    "CLICK | suppressed action=%s operator=%s",
                    decision.get("action", ""),
                    operator_mode,
                )
                self._push_runtime_event(
                    "operator",
                    "action_suppressed",
                    action=decision.get("action", ""),
                    spot_id=canonical_state.spot_id,
                    operator_status=operator_mode,
                )
            elif operator_mode == "assisted" and not assisted_result.get("auto_execute", False):
                self.last_decision_summary["execution"] = {
                    "status": "manual_required",
                    "reason": assisted_result.get("reason", "manual_review_required"),
                }
                logger.info(
                    "CLICK | manual_required action=%s reason=%s hero=%s board=%s legal=%s",
                    decision.get("action", ""),
                    assisted_result.get("reason", "manual_review_required"),
                    self._format_log_cards(canonical_state.hero_cards),
                    self._format_log_cards(canonical_state.board),
                    self._format_log_list(canonical_state.legal_actions),
                )
                self._push_runtime_event(
                    "operator",
                    "manual_action_required",
                    action=decision.get("action", ""),
                    spot_id=canonical_state.spot_id,
                    operator_status=operator_mode,
                    assisted_reason=assisted_result.get("reason", "manual_review_required"),
                )
            else:
                action_name = str(decision.get("action", "") or "").strip().upper()
                if self._should_suppress_recent_live_execution(canonical_state):
                    suppression_reason = "same_spot_unconfirmed" if str(getattr(self, "_last_live_execution_settle_status", "") or "").strip().lower() == "timeout" else "same_hand_post_action_guard"
                    self._remember_locked_decision(canonical_state, action_name or decision.get("action", ""), suppression_reason)
                    self.last_decision_summary["execution"] = {
                        "status": "suppressed_recent_execution",
                        "reason": suppression_reason,
                    }
                    if self._should_log_locked_decision(canonical_state, suppression_reason):
                        logger.warning(
                            "CLICK | recent_execution_suppressed action=%s hero=%s board=%s legal=%s",
                            decision.get("action", ""),
                            self._format_log_cards(canonical_state.hero_cards),
                            self._format_log_cards(canonical_state.board),
                            self._format_log_list(canonical_state.legal_actions),
                        )
                        self._push_runtime_event(
                            "action",
                            "suppressed_recent_execution",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                        )
                    return {
                        "decision": decision,
                        "gate_result": gate_result,
                        "dynamic_coords": dynamic_coords,
                    }
                if self._should_suppress_duplicate_live_action(canonical_state, action_name):
                    self._remember_locked_decision(canonical_state, action_name or decision.get("action", ""), "same_live_spot_cooldown")
                    self.last_decision_summary["execution"] = {
                        "status": "suppressed_duplicate",
                        "reason": "same_live_spot_cooldown",
                    }
                    if self._should_log_locked_decision(canonical_state, "same_live_spot_cooldown"):
                        logger.warning(
                            "CLICK | duplicate_suppressed action=%s hero=%s board=%s legal=%s",
                            decision.get("action", ""),
                            self._format_log_cards(canonical_state.hero_cards),
                            self._format_log_cards(canonical_state.board),
                            self._format_log_list(canonical_state.legal_actions),
                        )
                        self._push_runtime_event(
                            "action",
                            "suppressed_duplicate",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                        )
                    return {
                        "decision": decision,
                        "gate_result": gate_result,
                        "dynamic_coords": dynamic_coords,
                    }
                async def _update_jit_baseline():
                    frame = self.camera.get_latest_frame()
                    if frame is not None:
                        self._last_visual_previews = self._capture_live_visual_previews(frame)

                try:
                    try:
                        execution_result = await self.action_controller.execute_action(
                            action_intent,
                            dynamic_coords,
                            jit_check=self._jit_action_validator,
                            update_jit_baseline=_update_jit_baseline
                        )
                    except TypeError as action_err:
                        if "update_jit_baseline" not in str(action_err):
                            raise
                        execution_result = await self.action_controller.execute_action(
                            action_intent,
                            dynamic_coords,
                            jit_check=self._jit_action_validator,
                        )
                except Exception as jit_err:
                    if "JIT Check Failed" in str(jit_err):
                        self._clear_live_decision_summary(canonical_state)
                        self.last_decision_summary["execution"] = {
                            "status": "aborted_jit",
                            "reason": "JIT Check Failed",
                        }
                        logger.warning("CLICK | aborted_jit action=%s", decision.get("action", ""))
                        self._push_incident("jit_abort", severity="warning", reason="Actions region mutated")
                        execution_result = {"ok": False, "reason": "JIT Abort"}
                    else:
                        raise
                execution_ok = bool((execution_result or {}).get("ok"))
                execution_reason = (
                    "assisted_runtime" if operator_mode == "assisted" else "live_runtime"
                ) if execution_ok else str((execution_result or {}).get("reason", "click_failed"))
                self.last_decision_summary["execution"] = {
                    "status": "executed" if execution_ok else "click_failed",
                    "reason": execution_reason,
                    "details": dict(execution_result or {}),
                }
                if execution_ok:
                    logger.info(
                        "CLICK | applied action=%s operator=%s target=%s",
                        decision.get("action", ""),
                        operator_mode,
                        (execution_result or {}).get("target"),
                    )
                    settle_result = await self._wait_for_action_settle()
                    self.last_decision_summary["execution"]["settle"] = dict(settle_result)
                    settle_status = "ok" if settle_result.get("settled") else "timeout"
                    if settle_status == "timeout":
                        self.last_decision_summary["execution"]["status"] = "unsettled_timeout"
                        self.last_decision_summary["execution"]["reason"] = "same_spot_unconfirmed"
                    logger.info(
                        "CLICK | settle status=%s elapsed_ms=%.1f buttons=%s",
                        settle_status,
                        float(settle_result.get("elapsed_ms", 0.0) or 0.0),
                        self._format_log_list(settle_result.get("buttons", [])),
                    )
                    self._remember_live_execution(
                        canonical_state,
                        action_name or decision.get("action", ""),
                        "executed",
                        settle_status=settle_status,
                    )
                    if settle_status == "timeout":
                        self._remember_locked_decision(canonical_state, action_name or decision.get("action", ""), "same_spot_unconfirmed")
                    else:
                        self._clear_live_decision_lock()
                    if settle_status == "timeout":
                        self._push_incident(
                            "action_unsettled_lock",
                            severity="warning",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                            buttons=list(settle_result.get("buttons", [])),
                        )
                        self._push_runtime_event(
                            "action",
                            "unsettled_timeout",
                            action=decision.get("action", ""),
                            spot_id=canonical_state.spot_id,
                            operator_status=operator_mode,
                            buttons=list(settle_result.get("buttons", [])),
                        )
                    self._push_runtime_event(
                        "action",
                        "executed_action",
                        action=decision.get("action", ""),
                        spot_id=canonical_state.spot_id,
                        operator_status=operator_mode,
                        execution=dict(execution_result or {}),
                    )
                else:
                    self._clear_live_decision_lock()
                    self._remember_live_execution(
                        canonical_state,
                        action_name or decision.get("action", ""),
                        self.last_decision_summary["execution"]["status"],
                    )
                    logger.error(
                        "CLICK | failed action=%s operator=%s reason=%s coords=%s",
                        decision.get("action", ""),
                        operator_mode,
                        execution_reason,
                        dynamic_coords,
                    )
                    self._push_incident(
                        "action_click_failed",
                        severity="error",
                        action=decision.get("action", ""),
                        reason=execution_reason,
                        operator_status=operator_mode,
                    )
                    self._push_runtime_event(
                        "action",
                        "click_failed",
                        action=decision.get("action", ""),
                        spot_id=canonical_state.spot_id,
                        operator_status=operator_mode,
                        execution=dict(execution_result or {}),
                    )

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
            self._publish_runtime_bridge_state()

        return snapshot

    def _get_dynamic_coordinates(self, state: TableState) -> dict:
        mapping = {}
        diagnostics: Dict[str, Dict[str, object]] = {}
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
                diagnostics[mapped] = {
                    "source": "detected_button",
                    "label": str(button.class_name),
                    "coord": [coord[0], coord[1]],
                    "bbox": [int(value) for value in button.bbox],
                    "confidence": round(float(getattr(button, "confidence", 0.0) or 0.0), 3),
                }
        slot_boxes = state.metadata.get("button_slot_boxes", {}) if isinstance(state.metadata, dict) else {}
        if isinstance(slot_boxes, dict):
            for key in ("FOLD", "CALL", "BET_BTN", "BET_BOX"):
                bbox = slot_boxes.get(key)
                if (
                    key not in mapping
                    and isinstance(bbox, (list, tuple))
                    and len(bbox) == 4
                ):
                    x1, y1, x2, y2 = [int(value) for value in bbox]
                    mapping[key] = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                    diagnostics[key] = {
                        "source": "slot_box",
                        "label": key,
                        "coord": [mapping[key][0], mapping[key][1]],
                        "bbox": [x1, y1, x2, y2],
                    }
        for btn in ["FOLD", "CALL", "BET_BTN", "BET_BOX"]:
            if btn not in mapping:
                fallback_coord = self.fallback_coords.get(btn)
                mapping.setdefault(btn, fallback_coord)
                if fallback_coord:
                    diagnostics[btn] = {
                        "source": "fallback",
                        "label": btn,
                        "coord": [int(fallback_coord[0]), int(fallback_coord[1])],
                    }
        if isinstance(state.metadata, dict):
            state.metadata["dynamic_coord_diagnostics"] = diagnostics
        return mapping

    @staticmethod
    def _safe_crop(
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        pad_x: int = 0,
        pad_y: int = 0,
        pad_ratio_x: float = 0.0,
        pad_ratio_y: float = 0.0,
    ) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = bbox
        height, width = frame.shape[:2]

        box_width = x2 - x1
        box_height = y2 - y1

        # Le padding relatif (ratio) prime sur le pixel absolu s'il est spÃ©cifiÃ©
        actual_pad_x = int(box_width * pad_ratio_x) if pad_ratio_x > 0 else pad_x
        actual_pad_y = int(box_height * pad_ratio_y) if pad_ratio_y > 0 else pad_y

        x1 = max(0, min(x1 - actual_pad_x, width))
        x2 = max(0, min(x2 + actual_pad_x, width))
        y1 = max(0, min(y1 - actual_pad_y, height))
        y2 = max(0, min(y2 + actual_pad_y, height))

        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame[y1:y2, x1:x2]
        return crop if crop.size > 0 else None

    @staticmethod
    def _center(det: DetectionResult) -> Tuple[float, float]:
        x1, y1, x2, y2 = det.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def _is_image_changed(self, img1: np.ndarray, img2: np.ndarray, threshold: float = 0.95, mask_edges: bool = True) -> bool:
        if img1 is None or img2 is None:
            return True
        try:
            # On redimensionne tout Ã  100x30 pour unifier la comparaison
            i1 = cv2.resize(img1, (100, 30))
            i2 = cv2.resize(img2, (100, 30))

            # Application d'un masque optionnel sur les bords de l'image.
            # En effet, les animations externes dÃ©bordent souvent sur les crop de pot/stack (avatar qui bouge, chat).
            if mask_edges:
                mask = np.zeros((30, 100), dtype=np.uint8)
                # On ne compare visuellement que la zone centrale (lÃ  ou se trouve le texte OCR)
                cv2.rectangle(mask, (15, 5), (85, 25), 255, -1)
                i1 = cv2.bitwise_and(i1, i1, mask=mask)
                i2 = cv2.bitwise_and(i2, i2, mask=mask)

            i1 = cv2.GaussianBlur(i1, (3, 3), 0)
            i2 = cv2.GaussianBlur(i2, (3, 3), 0)
            diff = cv2.absdiff(i1, i2)
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

            # Seuil de binarisation du diff augmentÃ© de 15 Ã  25 pour tolÃ©rer les lueurs
            _, thresh = cv2.threshold(gray_diff, 25, 255, cv2.THRESH_BINARY)
            difference_ratio = np.count_nonzero(thresh) / thresh.size

            # threshold: 0.95 (tolÃ¨re max 5% de pixels changÃ©s dans la zone non masquÃ©e)
            return difference_ratio > (1.0 - threshold)
        except Exception:
            return True

    @staticmethod
    def _copy_table_state(state: TableState) -> TableState:
        if hasattr(state, "model_copy"):
            return state.model_copy(deep=True)
        if hasattr(state, "copy"):
            return state.copy(deep=True)
        return state

    def _build_visual_preview(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        crop = self._safe_crop(frame, bbox)
        if crop is None or crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        target_width = max(24, min(128, crop.shape[1]))
        target_height = max(18, min(48, crop.shape[0]))
        preview = cv2.resize(gray, (target_width, target_height), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(preview, (3, 3), 0)

    def _capture_live_visual_previews(self, frame: np.ndarray) -> Dict[str, np.ndarray]:
        return self._get_frame_pipeline()._capture_live_visual_previews(frame)

    def _detect_relevant_visual_change(
        self,
        frame: np.ndarray,
    ) -> tuple[bool, Dict[str, np.ndarray], tuple[str, ...]]:
        return self._get_frame_pipeline()._detect_relevant_visual_change(frame)


    async def _jit_action_validator(self, ignore_action_region: bool = False) -> bool:
        """
        Vérification Just-In-Time (JIT) de l'état de l'écran juste avant le clic physique.
        Retourne `False` si la zone d'action a visuellement muté, annulant ainsi l'action obsolete.
        """
        try:
            # On force un rafraîchissement manuel de la région si nécessaire
            frame = self.camera.get_latest_frame()
            if frame is None:
                return False
            
            # Utilisation de notre nouvelle implémentation basée sur les previews stockées
            previews = self._capture_live_visual_previews(frame)
            last_previews = getattr(self, "_last_visual_previews", {})
            if "actions" not in previews or "actions" not in last_previews:
                return True # On manque de données, on autorise dans le doute

            if not ignore_action_region:
                old_action_preview = last_previews["actions"]
                new_action_preview = previews["actions"]
                
                # Check MSE diff
                mse = np.mean((old_action_preview - new_action_preview) ** 2)
                
                if mse > 5.0: # Seuil de mutation (le bouton s'est allumé, éteint, ou a disparu)
                    logger.warning(f"JIT CHECK FAILED : MSE de {mse:.2f} sur la zone d'action.")
                    return False
                
            return True
        except Exception as e:
            logger.error(f"Erreur durant l'évaluation JIT : {e}")
            return False

    async def _wait_for_action_settle(self) -> dict:
        camera = getattr(self, "camera", None)
        detector = getattr(self, "detector", None)
        refresh_capture_region = getattr(self, "_refresh_capture_region", None)
        if (
            camera is None
            or detector is None
            or not callable(getattr(camera, "get_latest_frame", None))
            or not callable(getattr(detector, "analyze_frame", None))
        ):
            return {"settled": True, "elapsed_ms": 0.0, "buttons": []}

        timeout_s = max(0.1, float(getattr(self, "_post_action_settle_timeout_s", 0.9) or 0.9))
        poll_interval_s = max(0.01, float(getattr(self, "_post_action_settle_poll_interval_s", 0.03) or 0.03))
        started_at = time.monotonic()
        actionable_buttons: tuple[str, ...] = ()

        while (time.monotonic() - started_at) <= timeout_s:
            await asyncio.sleep(poll_interval_s)
            if callable(refresh_capture_region):
                refresh_capture_region()
            frame = camera.get_latest_frame()
            if frame is None:
                continue

            state = await asyncio.to_thread(detector.analyze_frame, frame)
            state = self._label_generic_action_buttons(state, frame)
            actionable_buttons = self._extract_actionable_runtime_buttons(
                [button.class_name for button in state.action_buttons]
            )
            if not actionable_buttons:
                return {
                    "settled": True,
                    "elapsed_ms": round((time.monotonic() - started_at) * 1000.0, 1),
                    "buttons": [],
                }

        return {
            "settled": False,
            "elapsed_ms": round((time.monotonic() - started_at) * 1000.0, 1),
            "buttons": list(actionable_buttons),
        }

    async def _process_frame(self, frame) -> TableState:
        return await self._get_frame_pipeline()._process_frame(frame)

    def _known_stack_fallback(self, seat_id: str, cached_player: Optional[CanonicalPlayer]) -> float:
        if cached_player is not None and float(cached_player.stack or 0.0) > 0.0:
            return float(cached_player.stack or 0.0)

        tracked_player = getattr(getattr(self, "tracker", None), "players", {}).get(seat_id)
        if tracked_player is not None and float(getattr(tracked_player, "current_stack", 0.0) or 0.0) > 0.0:
            return float(getattr(tracked_player, "current_stack", 0.0) or 0.0)

        return 0.0

    def _build_stack_quarantine_metadata(self, seat_id: str, fallback_value: float, remaining_s: float) -> dict:
        return {
            "field": "amount",
            "mode": "quarantine",
            "parallel": False,
            "supported_engines": [],
            "requested_engines": [],
            "loaded_engines": [],
            "unavailable_engines": {},
            "selected_engine": "",
            "selected_text": "",
            "selected_variant": "",
            "selected_amount": fallback_value if fallback_value > 0.0 else None,
            "selected_confidence": 0.0,
            "engine_scores": {},
            "candidates": [],
            "agreement": "quarantined",
            "seat_id": seat_id,
            "skipped_due_to_quarantine": True,
            "quarantine_remaining_s": round(max(0.0, remaining_s), 3),
        }

    def _read_player_stack(
        self,
        stack_crop: Optional[np.ndarray],
        seat_id: str,
        cached_player: Optional[CanonicalPlayer] = None,
    ) -> tuple[Optional[float], dict]:
        if stack_crop is None:
            return None, {}

        tracker_sanity = getattr(getattr(self, "tracker", None), "sanity", None)
        if tracker_sanity is not None and tracker_sanity.is_stack_read_quarantined(seat_id):
            fallback_value = self._known_stack_fallback(seat_id, cached_player)
            remaining_s = tracker_sanity.get_stack_read_quarantine_remaining(seat_id)
            return fallback_value, self._build_stack_quarantine_metadata(seat_id, fallback_value, remaining_s)

        numeric_reader = getattr(self, "numeric_reader", None)
        if numeric_reader is None:
            numeric_reader = NumericReader(self.amount_ocr)
            self.numeric_reader = numeric_reader

        previous_value = self._known_stack_fallback(seat_id, cached_player)
        numeric_result = numeric_reader.read_amount("stack", stack_crop, previous_value=previous_value)
        metadata = {
            **dict(self.amount_ocr.get_metadata() or {}),
            "numeric_reader": {
                "selected_value": numeric_result.selected_value,
                "evidence": numeric_result.evidence.to_dict(),
                "metadata": dict(numeric_result.metadata),
            },
        }
        return numeric_result.selected_value, metadata

    def _get_player_name_reader(self) -> PlayerNameReader:
        reader = getattr(self, "player_name_reader", None)
        if reader is None:
            reader = PlayerNameReader(self.ocr)
            self.player_name_reader = reader
        return reader

    def _pair_stack_and_name(
        self,
        stack_det: DetectionResult,
        state: TableState,
        frame: np.ndarray,
        seat_index: int,
        seat_id: str,
        is_hero: bool,
        cached_player: Optional[CanonicalPlayer] = None,
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
        stack_value, stack_ocr_metadata = self._read_player_stack(
            stack_crop=stack_crop,
            seat_id=seat_id,
            cached_player=cached_player,
        )
        if stack_value is None:
            stack_value = 0.0

        player_name = ""
        name_confidence = 0.0
        raw_player_name = ""
        if nearest_name is not None:
            # Remplacement des padding pixels fixes (14, 6) par un ratio dynamique (15% en x, 25% en y)
            name_crop = self._safe_crop(frame, nearest_name.bbox, pad_ratio_x=0.15, pad_ratio_y=0.25)
            name_result = self._get_player_name_reader().read_name(seat_id, name_crop, self._last_valid_player_names_by_seat)
            raw_player_name = str(name_result.metadata.get("raw_text", "") or "")
            name_ocr_metadata = dict(name_result.metadata.get("ocr", {}) or {})
            name_confidence = nearest_name.confidence
        else:
            name_ocr_metadata = {}
            name_result = None
        if name_result is not None:
            player_name = name_result.selected_name
            name_resolution_source = name_result.resolution_source
        else:
            player_name, name_resolution_source = resolve_player_name(
                seat_id=seat_id,
                candidate_name=raw_player_name,
                seat_cache=self._last_valid_player_names_by_seat,
            )
        identity_state = self.player_identity_state.update(seat_id, player_name, name_resolution_source)

        has_button = False
        if state.dealer_button is not None:
            bx, by = self._center(state.dealer_button)
            has_button = abs(bx - sx) + abs(by - sy) < 220

        return CanonicalPlayer(
            seat_id=seat_id,
            seat_index=seat_index,
            stack=float(stack_value),
            name=player_name,
            # La simple perte d'une lecture OCR de stack ne doit pas faire "disparaÃ®tre"
            # le joueur pour le tracker live.
            is_active=True,
            has_folded=False,
            is_hero=is_hero,
            has_button=has_button,
            confidence=round((stack_det.confidence + name_confidence) / 2.0, 3),
            metadata={
                "stack_bbox": list(stack_det.bbox),
                "stack_ocr": stack_ocr_metadata,
                "name_ocr": {
                    **dict(name_ocr_metadata or {}),
                    "raw_text": raw_player_name,
                    "resolved_text": player_name,
                    "resolution_source": name_resolution_source,
                    "identity_state": identity_state,
                    "player_name_reader": name_result.evidence.to_dict() if name_result is not None else None,
                },
            },
        )

    def _pair_stack_quick(
        self,
        stack_det: DetectionResult,
        state: TableState,
        frame: np.ndarray,
        seat_index: int,
        seat_id: str,
        is_hero: bool,
        cached_player: Optional[CanonicalPlayer],
    ) -> CanonicalPlayer:
        stack_crop = self._safe_crop(frame, stack_det.bbox)
        stack_value, stack_ocr_metadata = self._read_player_stack(
            stack_crop=stack_crop,
            seat_id=seat_id,
            cached_player=cached_player,
        )
        if stack_value is None or float(stack_value or 0.0) <= 0.0:
            stack_value = float(cached_player.stack if cached_player else 0.0)

        player_name = ""
        if cached_player and str(cached_player.name or "").strip():
            player_name = str(cached_player.name).strip()
        elif seat_id in self._last_valid_player_names_by_seat:
            player_name = self._last_valid_player_names_by_seat[seat_id]
        else:
            player_name = seat_id

        sx, sy = self._center(stack_det)
        has_button = False
        if state.dealer_button is not None:
            bx, by = self._center(state.dealer_button)
            has_button = abs(bx - sx) + abs(by - sy) < 220

        metadata = dict((cached_player.metadata or {}) if cached_player else {})
        metadata.update(
            {
                "stack_bbox": list(stack_det.bbox),
                "stack_ocr": stack_ocr_metadata,
                "responsive_stack_seed": True,
            }
        )

        return CanonicalPlayer(
            seat_id=seat_id,
            seat_index=seat_index,
            stack=float(stack_value or 0.0),
            name=player_name,
            is_active=True,
            has_folded=False,
            is_hero=is_hero,
            has_button=has_button,
            confidence=float(cached_player.confidence if cached_player else stack_det.confidence),
            metadata=metadata,
        )

    @staticmethod
    def _runtime_players_have_meaningful_stacks(
        players: Iterable[CanonicalPlayer],
        hero_seat_id: Optional[str],
    ) -> bool:
        players = list(players or [])
        if not players:
            return False
        positive_stacks = [player for player in players if float(player.stack or 0.0) > 0.0]
        if len(positive_stacks) < 2:
            return False
        if hero_seat_id:
            hero_player = next((player for player in players if player.seat_id == hero_seat_id), None)
            if hero_player is not None and float(hero_player.stack or 0.0) <= 0.0:
                return False
        return True

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

    def _player_detection_signature(
        self,
        ordered_stacks: List[tuple[str, DetectionResult]],
        state: TableState,
    ) -> tuple:
        return (
            tuple((seat_id, tuple(stack_det.bbox)) for seat_id, stack_det in ordered_stacks),
            tuple(tuple(name_det.bbox) for name_det in state.player_names),
            tuple(state.dealer_button.bbox) if state.dealer_button is not None else None,
        )

    @staticmethod
    def _refresh_cached_player_runtime_flags(
        players: tuple[CanonicalPlayer, ...],
        hero_seat_id: Optional[str],
        state: TableState,
    ) -> tuple[CanonicalPlayer, ...]:
        if not players:
            return ()

        dealer_center = None
        if state.dealer_button is not None:
            x1, y1, x2, y2 = state.dealer_button.bbox
            dealer_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

        refreshed_players: List[CanonicalPlayer] = []
        for player in players:
            has_button = False
            if dealer_center is not None:
                stack_bbox = (((player.metadata or {}).get("stack_bbox")) or ())
                if len(stack_bbox) == 4:
                    sx = (stack_bbox[0] + stack_bbox[2]) / 2.0
                    sy = (stack_bbox[1] + stack_bbox[3]) / 2.0
                    has_button = abs(dealer_center[0] - sx) + abs(dealer_center[1] - sy) < 220

            refreshed_players.append(
                CanonicalPlayer(
                    seat_id=player.seat_id,
                    seat_index=player.seat_index,
                    stack=player.stack,
                    name=player.name,
                    is_active=player.is_active,
                    has_folded=player.has_folded,
                    is_hero=player.seat_id == hero_seat_id,
                    has_button=has_button,
                    confidence=player.confidence,
                    metadata=dict(player.metadata or {}),
                )
            )
        return tuple(refreshed_players)

    def _build_players(self, state: TableState, frame: np.ndarray) -> List[CanonicalPlayer]:
        if not state.stacks:
            return []

        ordered_stacks = self._ordered_stacks_by_table_geometry(state, frame)
        hero_seat_id = self._infer_hero_seat_id(ordered_stacks, state, frame)
        signature = self._player_detection_signature(ordered_stacks, state)
        now = time.monotonic()
        responsive_live_path = bool(state.action_buttons)
        reused_visual_state = bool((getattr(state, "metadata", {}) or {}).get("reused_visual_state", False))
        cached_by_seat = {player.seat_id: player for player in self._cached_runtime_players}
        if (
            self._cached_runtime_players
            and len(self._cached_runtime_players) == len(ordered_stacks)
            and (
                responsive_live_path
                or reused_visual_state
                or (now - self._cached_runtime_players_at) <= self._player_ocr_refresh_interval_s
            )
        ):
            return list(self._refresh_cached_player_runtime_flags(self._cached_runtime_players, hero_seat_id, state))

        if responsive_live_path:
            if not self._runtime_players_have_meaningful_stacks(self._cached_runtime_players, hero_seat_id):
                quick_players: List[CanonicalPlayer] = []
                for index, (seat_id, stack_det) in enumerate(ordered_stacks):
                    quick_players.append(
                        self._pair_stack_quick(
                            stack_det=stack_det,
                            state=state,
                            frame=frame,
                            seat_index=index,
                            seat_id=seat_id,
                            is_hero=seat_id == hero_seat_id,
                            cached_player=cached_by_seat.get(seat_id),
                        )
                    )
                self._cached_runtime_players = tuple(quick_players)
                self._cached_runtime_players_signature = signature
                self._cached_runtime_players_at = now
                return quick_players

            dealer_center = None
            if state.dealer_button is not None:
                x1, y1, x2, y2 = state.dealer_button.bbox
                dealer_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

            placeholder_players: List[CanonicalPlayer] = []
            for index, (seat_id, stack_det) in enumerate(ordered_stacks):
                cached_player = cached_by_seat.get(seat_id)
                has_button = False
                if dealer_center is not None:
                    sx = (stack_det.bbox[0] + stack_det.bbox[2]) / 2.0
                    sy = (stack_det.bbox[1] + stack_det.bbox[3]) / 2.0
                    has_button = abs(dealer_center[0] - sx) + abs(dealer_center[1] - sy) < 220

                metadata = dict((cached_player.metadata or {}) if cached_player else {})
                metadata["stack_bbox"] = list(stack_det.bbox)
                metadata["placeholder_runtime_player"] = True
                placeholder_players.append(
                    CanonicalPlayer(
                        seat_id=seat_id,
                        seat_index=index,
                        stack=float(cached_player.stack if cached_player else 0.0),
                        name=(
                            cached_player.name
                            if cached_player and str(cached_player.name or "").strip()
                            else self._last_valid_player_names_by_seat.get(seat_id, seat_id)
                        ),
                        is_active=True,
                        has_folded=False,
                        is_hero=seat_id == hero_seat_id,
                        has_button=has_button,
                        confidence=float(cached_player.confidence if cached_player else stack_det.confidence),
                        metadata=metadata,
                    )
                )
            return placeholder_players

        players = [
            self._pair_stack_and_name(
                stack_det=stack_det,
                state=state,
                frame=frame,
                seat_index=index,
                seat_id=seat_id,
                is_hero=seat_id == hero_seat_id,
                cached_player=cached_by_seat.get(seat_id),
            )
            for index, (seat_id, stack_det) in enumerate(ordered_stacks)
        ]
        self._cached_runtime_players = tuple(players)
        self._cached_runtime_players_signature = signature
        self._cached_runtime_players_at = now
        return players

    def _build_gate_tracker_snapshot(self, canonical_state: CanonicalTableState) -> Dict[str, object]:
        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        hero_seat_id = str(
            metadata.get("hero_seat_id")
            or (self.last_tracker_snapshot or {}).get("hero_seat_id", "")
            or ""
        )
        return {
            "street": canonical_state.street,
            "board": list(canonical_state.board),
            "pot": float(canonical_state.pot or 0.0),
            "hero_cards": list(canonical_state.hero_cards),
            "in_hand": bool(len(canonical_state.hero_cards) == 2 or canonical_state.board or canonical_state.legal_actions),
            "legal_actions": [str(action).upper() for action in canonical_state.legal_actions],
            "hero_seat_id": hero_seat_id,
            "state_confidence": float(canonical_state.state_confidence or 0.0),
            "ocr_metadata": dict(metadata.get("ocr", {}) or {}),
        }

    def _evaluate_fallback_execution_readiness(
        self,
        canonical_state: CanonicalTableState,
        *,
        frame_age_ms: Optional[float] = None,
    ) -> Dict[str, object]:
        legal_actions = {str(action).strip().upper() for action in (canonical_state.legal_actions or ())}
        action_buttons = tuple(sorted(str(button).strip().lower() for button in (canonical_state.action_buttons or ()) if str(button).strip()))
        target_action = "CHECK" if "CHECK" in legal_actions else ("FOLD" if "FOLD" in legal_actions else "")
        target_button = "check_button" if target_action == "CHECK" else ("fold_button" if target_action == "FOLD" else "")

        signature_history = getattr(self, "_recent_runtime_action_button_signatures", None)
        if signature_history is None:
            signature_history = deque(maxlen=5)
            self._recent_runtime_action_button_signatures = signature_history
        signature_history.append(action_buttons)
        stable_signature_count = sum(1 for signature in signature_history if signature and signature == action_buttons)
        button_signature_stable = bool(action_buttons) and stable_signature_count >= 3

        metadata = dict(getattr(canonical_state, "metadata", {}) or {})
        vision_metadata = dict(metadata.get("vision", {}) or {})
        visual_changed_regions = {str(region).lower() for region in (vision_metadata.get("visual_changed_regions", []) or [])}
        actions_region_stable = "actions" not in visual_changed_regions

        action_controller = getattr(self, "action_controller", None)
        target_hwnd = int(getattr(action_controller, "hwnd", 0) or 0)
        window_bound = target_hwnd > 0
        foreground_confirmed = False
        foreground_getter = getattr(action_controller, "_get_foreground_window", None)
        if window_bound and callable(foreground_getter):
            try:
                foreground_confirmed = int(foreground_getter() or 0) == target_hwnd
            except Exception:
                foreground_confirmed = False

        frame_fresh = frame_age_ms is not None and float(frame_age_ms or 0.0) <= 300.0
        hero_turn_confirmed = bool(legal_actions) and bool(
            set(action_buttons).intersection(
                {
                    "fold_button",
                    "call_button",
                    "check_button",
                    "bet_button",
                    "raise_button",
                    "all_in_call_button",
                }
            )
        )
        target_button_present = bool(target_button) and target_button in action_buttons

        reasons = []
        if not window_bound:
            reasons.append("window_unbound")
        if not foreground_confirmed:
            reasons.append("window_not_foreground")
        if not frame_fresh:
            reasons.append("stale_frame")
        if not hero_turn_confirmed:
            reasons.append("hero_turn_unconfirmed")
        if not target_action:
            reasons.append("no_conservative_action")
        if not target_button_present:
            reasons.append("target_button_missing")
        if not button_signature_stable:
            reasons.append("buttons_not_stable")
        if not actions_region_stable:
            reasons.append("actions_region_changed")

        ready = not reasons
        score_parts = [
            1.0 if window_bound else 0.0,
            1.0 if foreground_confirmed else 0.0,
            1.0 if frame_fresh else 0.0,
            1.0 if hero_turn_confirmed else 0.0,
            1.0 if target_button_present else 0.0,
            1.0 if button_signature_stable else 0.0,
            1.0 if actions_region_stable else 0.0,
        ]
        score = round(sum(score_parts) / len(score_parts), 3)
        return {
            "status": "ready" if ready else "blocked",
            "score": score,
            "recommended_action": target_action or None,
            "target_button": target_button or None,
            "reasons": reasons,
            "signals": {
                "window_bound": window_bound,
                "foreground_confirmed": foreground_confirmed,
                "frame_fresh": frame_fresh,
                "hero_turn_confirmed": hero_turn_confirmed,
                "target_button_present": target_button_present,
                "button_signature_stable": button_signature_stable,
                "actions_region_stable": actions_region_stable,
                "stable_signature_count": stable_signature_count,
                "visual_changed_regions": sorted(visual_changed_regions),
                "frame_age_ms": None if frame_age_ms is None else round(float(frame_age_ms or 0.0), 1),
            },
        }

    def _handle_stale_live_frame(self, canonical_state: CanonicalTableState, frame_age_s: float) -> None:
        frame_age_ms = round(max(frame_age_s, 0.0) * 1000.0, 1)
        max_age_ms = round(self._max_live_frame_age_s * 1000.0, 1)
        self._clear_live_decision_summary(canonical_state)
        self.last_gate_result = GateResult(
            allowed=False,
            status="blocked",
            reasons=[
                GateReason(
                    code="STALE_FRAME",
                    message="La frame live est trop ancienne pour une action fiable.",
                    context={
                        "frame_age_ms": frame_age_ms,
                        "max_age_ms": max_age_ms,
                    },
                )
            ],
            confidence=0.0,
        )
        self.last_decision_summary["gate_confidence"] = 0.0
        self.last_decision_summary["gate_reason"] = "STALE_FRAME"
        self.last_decision_summary["gate_allowed"] = False
        self.last_decision_summary["frame_age_ms"] = frame_age_ms
        self.last_decision_summary["fallback_execution_readiness"] = self._evaluate_fallback_execution_readiness(
            canonical_state,
            frame_age_ms=frame_age_ms,
        )
        self.last_decision_summary["assisted"] = {
            **dict(self.last_decision_summary.get("assisted", {}) or {}),
            "enabled": bool(self._build_operator_snapshot().get("assisted_mode_enabled", False)),
            "auto_execute": False,
            "requires_operator_action": False,
            "status": "stale_frame",
            "reason": "stale_frame",
        }
        self.last_decision_summary["execution"] = {
            "status": "stale_frame",
            "reason": "STALE_FRAME",
            "frame_age_ms": frame_age_ms,
        }
        logger.warning(
            "CLICK | stale_frame hero=%s board=%s legal=%s age_ms=%.1f max_age_ms=%.1f",
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_cards(canonical_state.board),
            self._format_log_list(canonical_state.legal_actions),
            frame_age_ms,
            max_age_ms,
        )
        self._push_incident(
            "stale_frame",
            severity="warning",
            frame_age_ms=frame_age_ms,
            max_age_ms=max_age_ms,
            spot_id=canonical_state.spot_id,
        )
        self._push_runtime_event(
            "warning",
            "stale_frame",
            frame_age_ms=frame_age_ms,
            max_age_ms=max_age_ms,
            spot_id=canonical_state.spot_id,
        )

    def _log_loop_timing(
        self,
        *,
        canonical_state: CanonicalTableState,
        frame_age_ms: float,
        detector_ms: float,
        convert_ms: float,
        decision_ms: float,
        tracker_ms: float,
        total_ms: float,
        stale_frame: bool,
    ) -> None:
        should_log = (
            stale_frame
            or bool(canonical_state.legal_actions)
            or (total_ms >= self._slow_loop_log_threshold_ms and canonical_state.street != "IDLE")
        )
        if not should_log:
            return

        logger.info(
            "TIMING | street=%s hero=%s legal=%s age_ms=%.1f detector_ms=%.1f convert_ms=%.1f decision_ms=%.1f tracker_ms=%.1f total_ms=%.1f stale=%s",
            canonical_state.street,
            self._format_log_cards(canonical_state.hero_cards),
            self._format_log_list(canonical_state.legal_actions),
            frame_age_ms,
            detector_ms,
            convert_ms,
            decision_ms,
            tracker_ms,
            total_ms,
            "yes" if stale_frame else "no",
        )

    def _clear_live_decision_summary(self, canonical_state: CanonicalTableState) -> None:
        self.last_gate_result = GateResult(allowed=False, status="idle", reasons=[])
        self.last_decision_summary = {
            "action": "",
            "source": "idle",
            "confidence": 0.0,
            "observed_hands": 0,
            "cache_hit": False,
            "fallback_used": False,
            "fallback_reason": None,
            "warnings": [],
            "incidents": [],
            "elapsed_ms": 0,
            "backend": "idle",
            "action_history": list(self.tracker.current_hand_actions),
            "spot_id": canonical_state.spot_id,
            "street": canonical_state.street,
            "hero_cards": list(canonical_state.hero_cards),
            "board": list(canonical_state.board),
            "hero_position": "",
            "effective_stack": 0.0,
            "villain_name": "",
            "ab_decision": None,
            "profile": {},
            "solver": {},
            "confidence_details": {},
            "gate_confidence": 0.0,
            "gate_reason": "idle",
            "gate_allowed": False,
            "fallback_execution_readiness": {
                "status": "idle",
                "score": 0.0,
                "recommended_action": None,
                "target_button": None,
                "reasons": ["idle"],
                "signals": {},
            },
            "assisted": {
                "enabled": bool(self._build_operator_snapshot().get("assisted_mode_enabled", False)),
                "learning_live": True,
                "auto_execute": False,
                "requires_operator_action": False,
                "status": "waiting_for_spot",
                "reason": "idle",
                "signals": {},
                "thresholds": {
                    "min_state_confidence": ASSISTED_MIN_STATE_CONFIDENCE,
                    "min_decision_confidence": ASSISTED_MIN_DECISION_CONFIDENCE,
                    "min_gate_confidence": ASSISTED_MIN_GATE_CONFIDENCE,
                    "min_profile_reliability": ASSISTED_MIN_PROFILE_RELIABILITY,
                    "min_observed_hands": ASSISTED_MIN_OBSERVED_HANDS,
                },
            },
            "trace_updated_at": self._utc_now(),
            "history": {
                "fallback": [],
                "warnings": [],
                "incidents": [],
            },
            "operator_status": self._operator_action_mode(),
            "execution": {
                "status": "idle",
                "reason": "no_live_action",
            },
        }

    def _get_live_loop_sleep_interval(self, actionable_spot: bool) -> float:
        if not actionable_spot:
            return 0.05
        execution = dict(self.last_decision_summary.get("execution", {}) or {})
        if str(execution.get("status", "") or "") == "decision_locked":
            return float(getattr(self, "_locked_spot_poll_interval_s", 0.1) or 0.1)
        return 0.01

    @staticmethod
    def _derive_legal_actions(state: TableState) -> Tuple[tuple[str, ...], tuple[str, ...]]:
        return derive_legal_actions(button.class_name for button in state.action_buttons)

    @staticmethod
    def _normalize_action_button_text(raw_text: str) -> str:
        if not raw_text:
            return ""
        normalized = unicodedata.normalize("NFKD", str(raw_text))
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in normalized.lower())
        return " ".join(cleaned.split())

    @staticmethod
    def _is_resume_like_button_text(normalized_text: str) -> bool:
        if not normalized_text:
            return False
        compact_text = normalized_text.replace(" ", "")
        if any(token in normalized_text for token in ("reprendre", "rejoindre", "jouer", "joue", "resume", "continuer", "play", "join")):
            return True
        return (
            compact_text in {"jouer", "joue", "resume", "play", "join", "continue"}
            or compact_text.startswith("jou")
            or compact_text.startswith("rejo")
            or compact_text.endswith("ouer")
        )

    def _read_action_button_text(self, image_crop: Optional[np.ndarray]) -> str:
        if image_crop is None or image_crop.size == 0:
            return ""

        cache_key = None
        cache = getattr(self, "_action_button_text_cache", None)
        if cache is None:
            cache = {}
            self._action_button_text_cache = cache

        try:
            preview = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
            preview = cv2.resize(preview, (48, 20), interpolation=cv2.INTER_AREA)
            cache_key = preview.tobytes()
            cached_text = cache.get(cache_key)
            if cached_text is not None:
                return cached_text
        except Exception:
            cache_key = None

        variants: List[np.ndarray] = [image_crop]
        try:
            gray = cv2.cvtColor(image_crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
            upscaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            variants.append(cv2.cvtColor(upscaled, cv2.COLOR_GRAY2BGR))

            _, threshold = cv2.threshold(upscaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(cv2.cvtColor(threshold, cv2.COLOR_GRAY2BGR))

            inverse = 255 - threshold
            variants.append(cv2.cvtColor(inverse, cv2.COLOR_GRAY2BGR))
        except Exception:
            pass

        best_text = ""
        best_score = -1
        keyword_tokens = (
            "check",
            "call",
            "fold",
            "bet",
            "raise",
            "miser",
            "suivre",
            "passer",
            "payer",
            "relancer",
            "reprendre",
            "rejoindre",
            "jouer",
            "resume",
            "play",
            "join",
            "back",
            "vite",
            "time",
            "temps",
            "bank",
            "banque",
            "more",
            "give",
        )
        for variant in variants:
            try:
                candidate = self._normalize_action_button_text(self.ocr.read_text(variant))
            except Exception:
                continue
            if not candidate:
                continue

            keyword_score = sum(1 for token in keyword_tokens if token in candidate)
            score = keyword_score * 100 + len(candidate)
            if score > best_score:
                best_text = candidate
                best_score = score
            if keyword_score > 0:
                break

        if cache_key is not None:
            if len(cache) >= 96:
                cache.clear()
            cache[cache_key] = best_text
        return best_text

    def _classify_action_button_label(
        self,
        image_crop: Optional[np.ndarray],
        button_index: int,
        button_count: int,
    ) -> str:
        normalized_text = self._read_action_button_text(image_crop)
        if normalized_text:
            compact_text = normalized_text.replace(" ", "")
            if self._is_resume_like_button_text(normalized_text):
                return "resume_hand"
            if "im back" in normalized_text or compact_text == "imback" or compact_text.endswith("back"):
                return "im_back"
            if (
                "passer vite" in normalized_text
                or "fast fold" in normalized_text
                or (
                    button_count == 1
                    and any(token in normalized_text for token in ("passer", "fold", "coucher"))
                )
            ):
                return "fast_fold_button"
            if any(token in normalized_text for token in ("fold", "passer", "coucher")):
                return "fold_button"
            if "check" in normalized_text:
                return "check_button"
            if any(token in normalized_text for token in ("call", "suivre", "payer")):
                return "call_button"
            if any(token in normalized_text for token in ("raise", "relancer")):
                return "raise_button"
            if any(token in normalized_text for token in ("bet", "miser")):
                return "bet_button"

            if any(char.isdigit() for char in normalized_text):
                if button_count <= 1:
                    return "resume_hand"
                return "raise_button" if button_index == max(button_count - 1, 0) else "call_button"

        if button_count >= 3:
            if button_index == 0:
                return "fold_button"
            if button_index == button_count - 1:
                return "raise_button"
            return "call_button"
        if button_count == 2:
            return "check_button" if button_index == 0 else "bet_button"
        return "resume_hand"

    @staticmethod
    def _button_slot_overlap_ratio(
        bbox: Tuple[int, int, int, int],
        slot_bbox: Tuple[int, int, int, int],
    ) -> float:
        x1 = max(bbox[0], slot_bbox[0])
        y1 = max(bbox[1], slot_bbox[1])
        x2 = min(bbox[2], slot_bbox[2])
        y2 = min(bbox[3], slot_bbox[3])
        if x2 <= x1 or y2 <= y1:
            return 0.0
        intersection = float((x2 - x1) * (y2 - y1))
        area = float(max(1, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
        return intersection / area

    def _slot_key_for_button(
        self,
        button: DetectionResult,
        slot_boxes: Dict[str, object],
    ) -> str:
        best_slot = ""
        best_ratio = 0.0
        for slot_key, raw_bbox in dict(slot_boxes or {}).items():
            if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
                continue
            slot_bbox = tuple(int(value) for value in raw_bbox)
            overlap_ratio = self._button_slot_overlap_ratio(button.bbox, slot_bbox)
            if overlap_ratio > best_ratio:
                best_ratio = overlap_ratio
                best_slot = str(slot_key)
        return best_slot if best_ratio >= 0.2 else ""

    def _classify_slot_button_label(
        self,
        image_crop: Optional[np.ndarray],
        slot_key: str,
        visible_slot_keys: set[str],
        fallback_label: str,
    ) -> str:
        has_fold_slot = "FOLD" in visible_slot_keys
        has_call_slot = "CALL" in visible_slot_keys
        has_bet_slot = "BET_BTN" in visible_slot_keys
        normalized_text = ""
        compact_text = ""

        if slot_key == "FOLD":
            if (has_call_slot or has_bet_slot) and fallback_label != "fast_fold_button":
                return "fold_button"
            normalized_text = self._read_action_button_text(image_crop)
            compact_text = normalized_text.replace(" ", "")
            if (
                "passer vite" in normalized_text
                or "fast fold" in normalized_text
                or compact_text == "passervite"
            ):
                return "fast_fold_button"
            return "fold_button"

        if any(token in normalized_text for token in ("time", "temps", "bank", "banque")):
            return "time_bank_button"
            
        if slot_key == "CALL":
            if has_fold_slot:
                return fallback_label if fallback_label in {"call_button", "all_in_call_button"} else "call_button"
            if has_bet_slot:
                return fallback_label if fallback_label in {"check_button", "call_button", "all_in_call_button"} else "check_button"
            normalized_text = self._read_action_button_text(image_crop)
            compact_text = normalized_text.replace(" ", "")
            if "im back" in normalized_text or compact_text == "imback" or compact_text.endswith("back"):
                return "im_back"
            if self._is_resume_like_button_text(normalized_text):
                return "resume_hand"
            if "check" in normalized_text:
                return "check_button"
            if any(token in normalized_text for token in ("call", "suivre", "payer")):
                return "call_button"
            if fallback_label in {"resume_hand", "im_back"}:
                return fallback_label
            return "resume_hand"

        if slot_key == "BET_BTN":
            if has_call_slot and has_fold_slot:
                return fallback_label if fallback_label in {"bet_button", "raise_button"} else "raise_button"
            if has_call_slot:
                return fallback_label if fallback_label in {"bet_button", "raise_button"} else "bet_button"
            normalized_text = self._read_action_button_text(image_crop)
            compact_text = normalized_text.replace(" ", "")
            if any(token in normalized_text for token in ("raise", "relancer")):
                return "raise_button"
            if "all in" in normalized_text or compact_text == "allin":
                return "raise_button"
            if any(char.isdigit() for char in normalized_text):
                return "raise_button" if has_call_slot else "bet_button"
            if any(token in normalized_text for token in ("bet", "miser")):
                return "bet_button"
            if fallback_label in {"bet_button", "raise_button"}:
                return fallback_label
            return "bet_button"

        return fallback_label

    def _label_generic_action_buttons(self, state: TableState, frame: np.ndarray) -> TableState:
        if not state.action_buttons:
            return state

        ordered_buttons = sorted(state.action_buttons, key=lambda button: button.center[0])
        standard_labels = {
            "fold_button",
            "call_button",
            "check_button",
            "bet_button",
            "raise_button",
            "all_in_call_button",
        }
        slot_boxes = state.metadata.get("button_slot_boxes", {}) if isinstance(state.metadata, dict) else {}
        visible_slot_keys = {
            slot_key
            for button in state.action_buttons
            for slot_key in [self._slot_key_for_button(button, slot_boxes)]
            if slot_key
        }
        relabeled_buttons: List[DetectionResult] = []
        for button in state.action_buttons:
            generic_index = ordered_buttons.index(button)
            slot_key = self._slot_key_for_button(button, slot_boxes)
            if button.class_name in standard_labels and not slot_key:
                relabeled_buttons.append(button)
                continue

            # Remplacement des crop buttons absolus par le ratio dynamique (10% x, 15% y)
            crop = self._safe_crop(frame, button.bbox, pad_ratio_x=0.10, pad_ratio_y=0.15)
            if slot_key:
                classified = self._classify_slot_button_label(
                    image_crop=crop,
                    slot_key=slot_key,
                    visible_slot_keys=visible_slot_keys,
                    fallback_label=button.class_name,
                )
            else:
                classified = self._classify_action_button_label(crop, generic_index, len(ordered_buttons))
            specialized_labels = {"resume_hand", "im_back", "fast_fold_button"}
            if slot_key or button.class_name == "action_button_generic" or classified in specialized_labels:
                relabeled_buttons.append(
                    DetectionResult(
                        class_name=classified,
                        confidence=button.confidence,
                        bbox=button.bbox,
                    )
                )
            else:
                relabeled_buttons.append(button)

        relabeled_buttons = dedupe_nearby_detections(relabeled_buttons, x_tolerance=36.0, y_tolerance=24.0)
        relabeled_buttons = self._promote_fast_fold_outliers(relabeled_buttons)
        if any(button.class_name in standard_labels for button in relabeled_buttons):
            relabeled_buttons = [
                button
                for button in relabeled_buttons
                if button.class_name not in {"resume_hand", "im_back"}
            ]
        state.action_buttons = sorted(relabeled_buttons, key=detection_sort_key)
        return state

    @staticmethod
    def _promote_fast_fold_outliers(buttons: List[DetectionResult]) -> List[DetectionResult]:
        if len(buttons) < 3:
            return buttons

        reference_buttons = [
            button
            for button in buttons
            if button.class_name in {"check_button", "call_button", "bet_button", "raise_button", "all_in_call_button"}
        ]
        fold_candidates = [button for button in buttons if button.class_name == "fold_button"]
        if len(reference_buttons) < 2 or not fold_candidates:
            return buttons

        reference_ys = sorted(button.center[1] for button in reference_buttons)
        median_reference_y = reference_ys[len(reference_ys) // 2]
        reference_height = max(
            1.0,
            float(
                sum((button.bbox[3] - button.bbox[1]) for button in reference_buttons) / len(reference_buttons)
            ),
        )
        y_threshold = max(28.0, reference_height * 0.55)

        normalized: List[DetectionResult] = []
        for button in buttons:
            if button.class_name != "fold_button":
                normalized.append(button)
                continue

            center_x, center_y = button.center
            if center_y >= (median_reference_y + y_threshold):
                normalized.append(
                    DetectionResult(
                        class_name="fast_fold_button",
                        confidence=button.confidence,
                        bbox=button.bbox,
                    )
                )
                continue

            normalized.append(button)

        return normalized

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

    @staticmethod
    def _extract_actionable_runtime_buttons(action_buttons: Iterable[str]) -> tuple[str, ...]:
        actionable_button_labels = {
            "fold_button",
            "check_button",
            "call_button",
            "all_in_call_button",
            "bet_button",
            "raise_button",
        }
        return tuple(
            str(button_name)
            for button_name in action_buttons
            if str(button_name) in actionable_button_labels
        )

    def _derive_hero_participation_mode(
        self,
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
        pot_value: float,
        action_buttons: Iterable[str],
    ) -> str:
        button_names = tuple(str(button_name) for button_name in action_buttons)
        actionable_buttons = self._extract_actionable_runtime_buttons(button_names)
        button_set = set(button_names)
        if len(hero_cards) == 2:
            return "active_hand"
        if "resume_hand" in button_set:
            return "waiting_next_hand"
        if "im_back" in button_set:
            return "sitting_out"
        if actionable_buttons:
            return "actionable_without_hero"
        if board or float(pot_value or 0.0) > 0.0:
            return "observing_hand"
        return "idle"

    def _derive_runtime_street(
        self,
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
        action_buttons: tuple[str, ...],
    ) -> str:
        actionable_buttons = self._extract_actionable_runtime_buttons(action_buttons)
        if not board and len(hero_cards) != 2 and not actionable_buttons:
            self._recent_runtime_streets.clear()
            return "IDLE"

        incoming_street = derive_street(board, hero_cards)
        stable_street = stable_window_value(
            list(self._recent_runtime_streets),
            incoming_street,
            ignore_values=("IDLE",) if actionable_buttons else (),
        )
        self._recent_runtime_streets.append(stable_street)
        return stable_street

    @staticmethod
    def _normalize_auxiliary_action_state(
        legal_actions: tuple[str, ...],
        action_buttons: tuple[str, ...],
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        button_names = tuple(str(button_name) for button_name in action_buttons)
        button_set = set(button_names)
        if "fast_fold_button" in button_set and not board:
            if not button_set.intersection({"check_button", "bet_button", "raise_button"}):
                return (
                    (),
                    tuple(
                        button_name
                        for button_name in button_names
                        if button_name in {"fast_fold_button", "resume_hand", "im_back"}
                    ),
                )

        return legal_actions, action_buttons

    def _smooth_legal_actions(
        self,
        legal_actions: tuple[str, ...],
        action_buttons: tuple[str, ...],
        board: tuple[str, ...],
        hero_cards: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        actionable_button_labels = {
            "fold_button",
            "check_button",
            "call_button",
            "all_in_call_button",
            "bet_button",
            "raise_button",
        }
        actionable_buttons = tuple(
            button_name for button_name in action_buttons if button_name in actionable_button_labels
        )
        if not actionable_buttons:
            self._recent_runtime_legal_actions.clear()
            return (), action_buttons

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

    def _stabilize_runtime_hero_cards(
        self,
        hero_cards: tuple[str, ...],
        board: tuple[str, ...],
        state: TableState,
    ) -> tuple[str, ...]:
        now = time.monotonic()
        previous_hero_cards = tuple(self._last_good_runtime_hero_cards)

        def _split_card(card: str) -> tuple[str, str]:
            card_text = str(card or "")
            if len(card_text) < 2:
                return "", ""
            return card_text[0].upper(), card_text[1].lower()

        def _is_suspicious_rank_flip(previous_cards: tuple[str, ...], candidate_cards: tuple[str, ...]) -> bool:
            if len(previous_cards) != 2 or len(candidate_cards) != 2:
                return False
            if previous_cards == candidate_cards:
                return False
            changed_indexes = [
                index
                for index, (previous_card, candidate_card) in enumerate(zip(previous_cards, candidate_cards))
                if previous_card != candidate_card
            ]
            if len(changed_indexes) != 1:
                return False
            changed_index = changed_indexes[0]
            previous_rank, previous_suit = _split_card(previous_cards[changed_index])
            candidate_rank, candidate_suit = _split_card(candidate_cards[changed_index])
            if not previous_rank or not candidate_rank:
                return False
            if previous_suit != candidate_suit:
                return False
            return True

        if (
            len(hero_cards) == 2
            and len(previous_hero_cards) == 2
            and (now - self._last_good_runtime_hero_cards_at) <= float(getattr(self, "_runtime_hero_cards_rank_flip_ttl_s", 1.0) or 1.0)
            and _is_suspicious_rank_flip(previous_hero_cards, hero_cards)
        ):
            logger.info(
                "HERO_CARDS | suspicious_rank_flip previous=%s candidate=%s reused=%s",
                self._format_log_cards(previous_hero_cards),
                self._format_log_cards(hero_cards),
                self._format_log_cards(previous_hero_cards),
            )
            return previous_hero_cards

        if len(hero_cards) == 2:
            self._last_good_runtime_hero_cards = tuple(hero_cards)
            self._last_good_runtime_hero_cards_at = now
            return hero_cards

        pot_value = float(getattr(state.pots[0], "confidence", 0.0) or 0.0) if state.pots else 0.0
        has_live_context = bool(board) or pot_value > 0.0
        if (
            has_live_context
            and len(self._last_good_runtime_hero_cards) == 2
            and (now - self._last_good_runtime_hero_cards_at) <= self._runtime_hero_cards_ttl_s
        ):
            return tuple(self._last_good_runtime_hero_cards)

        if not has_live_context:
            self._last_good_runtime_hero_cards = ()
            self._last_good_runtime_hero_cards_at = 0.0
        return hero_cards

    def _convert_state_for_tracker(self, state: TableState, frame: np.ndarray) -> CanonicalTableState:
        return self._get_frame_pipeline()._convert_state_for_tracker(state, frame)

    def _build_tracker_snapshot(self, tracker_data: dict) -> dict:
        fallback_street = str((tracker_data or {}).get("street", "IDLE") or "IDLE")
        fallback_board = list((tracker_data or {}).get("board", []) or [])
        fallback_pot = float((tracker_data or {}).get("pot", 0.0) or 0.0)
        fallback_hero_cards = list((tracker_data or {}).get("hero_cards", []) or [])
        fallback_legal_actions = [str(action).upper() for action in ((tracker_data or {}).get("legal_actions", []) or [])]
        fallback_state_confidence = float((tracker_data or {}).get("state_confidence", 0.0) or 0.0)
        fallback_hero_seat_id = str(((tracker_data or {}).get("metadata", {}) or {}).get("hero_seat_id", "") or "")

        hero_seat_id = next(
            (seat_id for seat_id, player in self.tracker.players.items() if player.is_hero),
            fallback_hero_seat_id,
        )
        ocr_metadata = {}
        turn_probe_metadata = {}
        if isinstance(tracker_data, dict):
            metadata = tracker_data.get("metadata", {}) or {}
            ocr_metadata = dict(metadata.get("ocr", {}) or {})
            vision_metadata = dict(metadata.get("vision", {}) or {})
            observed_pot_metadata = dict(metadata.get("observed_pot", {}) or {})
            observed_pot_fast_metadata = dict(metadata.get("observed_pot_fast", {}) or {})
            turn_probe_metadata = dict(metadata.get("turn_probe", {}) or {})
            raw_board_count = int(vision_metadata.get("raw_board_count", 0) or 0)
        else:
            vision_metadata = {}
            observed_pot_metadata = {}
            observed_pot_fast_metadata = {}
            turn_probe_metadata = {}
            raw_board_count = 0

        tracker_street = str(self.tracker.state or "") if getattr(self, "tracker", None) is not None else ""
        tracker_board = list(getattr(self.tracker, "current_board", []) or [])
        tracker_pot = float(getattr(self.tracker, "pot_total", 0.0) or 0.0)
        tracker_hero_cards = list(getattr(self.tracker, "hero_cards", []) or [])
        tracker_legal_actions = [str(action).upper() for action in (getattr(self.tracker, "legal_actions", []) or [])]
        tracker_state_confidence = float(getattr(self.tracker, "state_confidence", 0.0) or 0.0)
        fast_pot_snapshot = self._get_recent_fast_pot_snapshot()
        fast_pot_value = float(fast_pot_snapshot.get("value", 0.0) or 0.0)
        fast_pot_age_s = float(fast_pot_snapshot.get("age_s", 999.0) or 999.0)
        observed_pot_fast_value = float(observed_pot_fast_metadata.get("value", 0.0) or 0.0)
        observed_pot_fast_age_s = max(
            0.0,
            time.monotonic() - float(observed_pot_fast_metadata.get("observed_at_monotonic", 0.0) or 0.0),
        )
        prefer_fast_pot_snapshot = (
            fast_pot_value > 0.0
            and fast_pot_age_s <= float(getattr(self, "_fast_pot_stale_after_s", 0.35) or 0.35)
        )
        observed_pot_value = float(observed_pot_metadata.get("value", 0.0) or 0.0)
        observed_pot_age_s = max(
            0.0,
            time.monotonic() - float(observed_pot_metadata.get("observed_at_monotonic", 0.0) or 0.0),
        )
        prefer_observed_pot_fast = (
            observed_pot_fast_value > 0.0
            and observed_pot_fast_age_s <= 0.20
            and str(observed_pot_fast_metadata.get("ocr_focus", "") or "") == "top_label"
            and str(observed_pot_fast_metadata.get("source_region", "") or "") == "fast_lane_geometry"
        )
        observed_pot_ocr_focus = str(observed_pot_metadata.get("ocr_focus", "") or "")
        observed_pot_source_region = str(observed_pot_metadata.get("source_region", "") or "")
        prefer_observed_pot = (
            observed_pot_value > 0.0
            and observed_pot_age_s <= 0.45
            and observed_pot_ocr_focus == "top_label"
            and observed_pot_source_region in {"preset_geometry", "detector_pot"}
        )

        force_idle_snapshot = (
            fallback_street == "IDLE"
            and not fallback_board
            and raw_board_count < 3
            and not fallback_hero_cards
            and not fallback_legal_actions
        )
        if force_idle_snapshot:
            street = "IDLE"
            board = []
            pot = fallback_pot
            hero_cards = []
            legal_actions = []
            state_confidence = fallback_state_confidence
        else:
            street = tracker_street or fallback_street
            board = tracker_board or fallback_board
            if prefer_fast_pot_snapshot:
                pot = fast_pot_value
            elif prefer_observed_pot_fast:
                pot = observed_pot_fast_value
            elif prefer_observed_pot:
                pot = observed_pot_value
            else:
                pot = tracker_pot if tracker_pot > 0.0 else fallback_pot
            hero_cards = tracker_hero_cards if len(tracker_hero_cards) == 2 else fallback_hero_cards
            legal_actions = tracker_legal_actions or fallback_legal_actions
            state_confidence = tracker_state_confidence if tracker_state_confidence > 0.0 else fallback_state_confidence

        return {
            "street": street,
            "board": board,
            "pot": pot,
            "hero_cards": hero_cards,
            "action_history": list(self.tracker.current_hand_actions),
            "in_hand": len(hero_cards) == 2 and street != "IDLE",
            "legal_actions": legal_actions,
            "hero_seat_id": str(hero_seat_id or ""),
            "state_confidence": state_confidence,
            "ocr_metadata": ocr_metadata,
            "vision_metadata": {
                **vision_metadata,
                "fast_pot_snapshot": fast_pot_snapshot,
                "prefer_fast_pot_snapshot": prefer_fast_pot_snapshot,
                "observed_pot_fast": observed_pot_fast_metadata,
                "prefer_observed_pot_fast": prefer_observed_pot_fast,
                "observed_pot_fast_age_s": round(observed_pot_fast_age_s, 3),
                "observed_pot": observed_pot_metadata,
                "prefer_observed_pot": prefer_observed_pot,
                "observed_pot_age_s": round(observed_pot_age_s, 3),
                "turn_probe": turn_probe_metadata,
            },
            "spot_id": str((tracker_data or {}).get("spot_id", "") or ""),
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
        current_readiness = dict(self.last_decision_summary.get("runtime_readiness", {}) or {})
        current_validation = dict((self.last_resolved_runtime_state or {}).get("metadata", {}).get("poker_state_validation", {}) or {}) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else {}
        go_live_gate = evaluate_go_live_gate(
            local_metrics,
            metrics_snapshot,
            readiness=current_readiness,
            validation=current_validation,
            thresholds=getattr(self, "go_live_gate_thresholds", {}),
        )
        self.last_go_live_gate = go_live_gate.to_dict()
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
        observation = self._build_observation_snapshot()
        return {
            "is_running": self.is_running,
            "app_name": "PokerMaster",
            "service": "PokerMaster",
            "version": "v2",
            "session_id": self._get_runtime_session_id(),
            "tracker": self.last_tracker_snapshot,
            "canonical_spot": dict(getattr(self, "last_resolved_runtime_state", None)) if isinstance(getattr(self, "last_resolved_runtime_state", None), dict) else (dict(self.last_canonical_spot_snapshot) if isinstance(self.last_canonical_spot_snapshot, dict) else None),
            "gate": self.last_gate_result.to_dict(),
            "decision": self.last_decision_summary,
            "readiness": dict(self.last_decision_summary.get("runtime_readiness", {}) or {}),
            "go_live_gate": go_live_gate.to_dict(),
            "operator": self._build_operator_snapshot(),
            "observation": observation,
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
        return await self._get_runtime_loop().run()

def run_bot():
    try:
        Preflight(ROOT).run()
    except PreflightError as exc:
        logger.critical("Preflight runtime V2 invalide: %s", exc)
        raise SystemExit(2) from exc

    bot = SuperBotController()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(bot.main_loop())
    except KeyboardInterrupt:
        logger.info("Extinction gracieuse...")
        bot.is_running = False
        loop.run_until_complete(asyncio.sleep(1))

if __name__ == "__main__":
    ensure_admin()
    run_bot()
