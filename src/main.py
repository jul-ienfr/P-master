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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- PROFIL HARDWARE AUTO (Phase 2.0) : 3G / 12G / CPU, overrides env ---
from src.runtime.hardware import apply_hardware_profile, get_active_hardware_profile
from src.utils.seed import seed_everything

apply_hardware_profile(torch)
seed_everything()
# -------------------------------------------------

# Imports de nos modules
from src.vision.capture import ScreenCapture
from src.vision.detector import (
    PokerDetector,
    TableState,
    DetectionResult,
)
from src.vision.table_geometry import (
    build_dynamic_coordinates,
    copy_table_state,
    detection_center,
    is_image_changed,
    safe_crop,
)
from src.vision.ocr import PokerOCR
from src.vision.button_classifier import (
    ButtonClassifier,
    button_slot_overlap_ratio,
    is_resume_like_button_text,
    normalize_action_button_text,
)
from src.vision.numeric_reader import NumericReader
from src.vision.player_name_reader import PlayerNameReader
from src.data.database import DatabaseManager
from src.bot.table_tracker import TableTracker
from src.bot.decision_maker import DecisionMaker
from src.bot.action_controller import ActionController
from src.bot.sanity_checker import ActionIntent, GateReason, GateResult, SanityChecker
from src.bot.live_execution import (
    ASSISTED_FALLBACK_MIN_DECISION_CONFIDENCE,
    ASSISTED_MIN_DECISION_CONFIDENCE,
    ASSISTED_MIN_GATE_CONFIDENCE,
    ASSISTED_MIN_OBSERVED_HANDS,
    ASSISTED_MIN_PROFILE_RELIABILITY,
    ASSISTED_MIN_STATE_CONFIDENCE,
    LiveExecutionMixin,
)
from src.bot.gate_flow import GateFlowMixin, compact_solver_payload as _compact_solver_payload
from src.bot.metrics import MetricsMixin
from src.bot.players_builder import PlayersBuilderMixin
from src.bot.operator_snapshot import OperatorSnapshotMixin
from src.bot.state_resolver import StateResolverMixin
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
from src.runtime.policy_compare import (
    build_empty_policy_compare_summary,
    build_policy_compare_summary,
    build_runtime_ab_summary,
    compact_policy_compare_examples,
    dedupe_runtime_ab_decisions,
    extract_policy_compare_actions,
    extract_policy_compare_ev_by_action,
    extract_runtime_ab_decision,
    normalize_runtime_action_name,
    normalize_runtime_street_name,
    policy_compare_sample_id,
    policy_compare_spot_example,
    policy_slug,
    runtime_ab_decision_key,
    safe_runtime_float,
)
from src.runtime.preflight import Preflight, PreflightError
from src.runtime.player_identity_state import PlayerIdentityState
from src.runtime.player_name_resolver import resolve_player_name
from src.runtime.readiness import build_runtime_readiness
from src.runtime.session import (
    RUNTIME_PORT_CANDIDATES,
    RuntimeSessionMixin,
    parse_bool_flag as _parse_bool_flag,
    resolve_runtime_api_port as _resolve_runtime_api_port,
    select_available_runtime_port as _select_available_runtime_port,
)
from src.runtime.capture_context import CaptureContextMixin
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
RUNTIME_BRIDGE_DIR = "log/runtime_bridge"
LIVE_DETAILS_LOG_INTERVAL_S = 1.2




def resolve_observation_capture_enabled(observation_capture_cfg: dict, profile) -> bool:
    """Config explicite prioritaire ; sinon défaut par profil hardware (3G off / 12G on)."""
    cfg = observation_capture_cfg or {}
    if "enabled" in cfg:
        return bool(cfg["enabled"])
    return bool(getattr(profile, "observation_capture", False))


class SuperBotController(
    RuntimeSessionMixin,
    CaptureContextMixin,
    LiveExecutionMixin,
    GateFlowMixin,
    MetricsMixin,
    PlayersBuilderMixin,
    OperatorSnapshotMixin,
    StateResolverMixin,
):
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

        # Profil hardware détecté au boot (Phase 2.0) — pilote les défauts vision.
        self.hardware_profile = get_active_hardware_profile()

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
            enabled_engines=["rapidocr"],
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
            enabled=resolve_observation_capture_enabled(
                observation_capture_cfg, self.hardware_profile
            ),
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

    def _get_dynamic_coordinates(self, state: TableState) -> dict:
        mapping, diagnostics = build_dynamic_coordinates(state, self.fallback_coords)
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
        return safe_crop(frame, bbox, pad_x=pad_x, pad_y=pad_y,
                         pad_ratio_x=pad_ratio_x, pad_ratio_y=pad_ratio_y)

    @staticmethod
    def _center(det: DetectionResult) -> Tuple[float, float]:
        return detection_center(det)

    def _is_image_changed(self, img1: np.ndarray, img2: np.ndarray, threshold: float = 0.95, mask_edges: bool = True) -> bool:
        return is_image_changed(img1, img2, threshold=threshold, mask_edges=mask_edges)

    @staticmethod
    def _copy_table_state(state: TableState) -> TableState:
        return copy_table_state(state)

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

    async def _process_frame(self, frame) -> TableState:
        return await self._get_frame_pipeline()._process_frame(frame)

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
        return normalize_action_button_text(raw_text)

    @staticmethod
    def _is_resume_like_button_text(normalized_text: str) -> bool:
        return is_resume_like_button_text(normalized_text)

    def _get_button_classifier(self) -> ButtonClassifier:
        classifier = getattr(self, "_button_classifier", None)
        if classifier is None:
            classifier = ButtonClassifier(
                getattr(self, "ocr", None),
                read_text_fn=self._read_action_button_text,
            )
            self._button_classifier = classifier
        return classifier

    def _read_action_button_text(self, image_crop: Optional[np.ndarray]) -> str:
        classifier = self._get_button_classifier()
        if classifier._read_text_fn == self._read_action_button_text:
            # Lecteur par défaut : casser le cycle en appelant l'OCR natif.
            return classifier.native_read_action_button_text(image_crop)
        return classifier.read_action_button_text(image_crop)

    def _classify_action_button_label(
        self,
        image_crop: Optional[np.ndarray],
        button_index: int,
        button_count: int,
    ) -> str:
        return self._get_button_classifier().classify_action_button_label(
            image_crop, button_index, button_count
        )

    @staticmethod
    def _button_slot_overlap_ratio(
        bbox: Tuple[int, int, int, int],
        slot_bbox: Tuple[int, int, int, int],
    ) -> float:
        return button_slot_overlap_ratio(bbox, slot_bbox)

    def _slot_key_for_button(
        self,
        button: DetectionResult,
        slot_boxes: Dict[str, object],
    ) -> str:
        return self._get_button_classifier().slot_key_for_button(button, slot_boxes)

    def _classify_slot_button_label(
        self,
        image_crop: Optional[np.ndarray],
        slot_key: str,
        visible_slot_keys,
        fallback_label: str,
    ) -> str:
        return self._get_button_classifier().classify_slot_button_label(
            image_crop=image_crop,
            slot_key=slot_key,
            visible_slot_keys=visible_slot_keys,
            fallback_label=fallback_label,
        )

    def _label_generic_action_buttons(self, state: TableState, frame: np.ndarray) -> TableState:
        return self._get_button_classifier().label_generic_action_buttons(
            state, frame, self._safe_crop
        )

    @staticmethod
    def _promote_fast_fold_outliers(buttons: List[DetectionResult]) -> List[DetectionResult]:
        return ButtonClassifier.promote_fast_fold_outliers(buttons)

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
