from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from src.vision.detector import decode_card_token
from src.vision.table_geometry import DEFAULT_RUNTIME_GEOMETRY, geometry_to_pixel_regions


logger = logging.getLogger("RuntimeLoop")


class RuntimeLoop:
    def __init__(self, controller) -> None:
        object.__setattr__(self, "controller", controller)

    def __setattr__(self, name: str, value) -> None:
        if name == "controller":
            object.__setattr__(self, name, value)
            return
        setattr(self.controller, name, value)

    def __getattr__(self, name: str):
        return getattr(self.controller, name)

    async def run(self):
        try:
            await self.db.connect()
        except Exception as e:
            logger.error(f"Echec de connexion DB: {e}")

        self._publish_runtime_bridge_state(force=True)
        self._start_runtime_api_process()
        self._push_runtime_event("lifecycle", "api_started", port=self.runtime_api_port)
        self._persist_runtime_metrics_snapshot(force=True)
        self._publish_runtime_bridge_state(force=True)

        capture_region = self._refresh_capture_region(force=True)
        self.camera.start(region=capture_region, hwnd=self.action_controller.hwnd)
        self.is_running = True
        logger.info("SuperBot 2026 demarre. API Locale sur le port %s.", self.runtime_api_port)
        self._push_runtime_event("lifecycle", "bot_started")
        self._publish_runtime_bridge_state(force=True)

        try:
            while self.is_running:
                try:
                    loop_started_at = time.monotonic()
                    self._set_loop_stage("process_bridge_commands", publish=True)
                    self._process_bridge_commands()
                    if self._operator_action_mode() == "paused":
                        self._set_loop_stage("paused", publish=True)
                        self._publish_runtime_bridge_state()
                        await asyncio.sleep(0.1)
                        continue

                    self._set_loop_stage("capture_frame", publish=True)
                    self._refresh_capture_region()
                    frame = self.camera.get_latest_frame()
                    if frame is None:
                        self._publish_runtime_bridge_state()
                        await asyncio.sleep(0.01)
                        continue
                    if isinstance(frame, np.ndarray):
                        self.last_valid_frame = frame.copy()
                    frame_acquired_at = time.monotonic()
                    fast_pot_snapshot = {}
                    turn_probe_snapshot = {}
                    try:
                        pot_box = geometry_to_pixel_regions(frame, DEFAULT_RUNTIME_GEOMETRY).get("pot")
                        fast_pot_snapshot = self.frame_pipeline._read_live_pot_fast(
                            frame,
                            tuple(int(value) for value in (pot_box or (0, 0, 0, 0)))
                        )
                    except Exception:
                        fast_pot_snapshot = {}
                    if fast_pot_snapshot:
                        self._update_fast_pot_snapshot(fast_pot_snapshot)
                    try:
                        probe = getattr(self, "pixel_probe", None)
                        turn_probe_snapshot = {
                            "is_our_turn": bool(probe and probe.is_our_turn(frame)),
                            "observed_at_monotonic": time.monotonic(),
                            "source": "FastPixelProbe",
                        }
                    except Exception:
                        turn_probe_snapshot = {
                            "is_our_turn": False,
                            "observed_at_monotonic": time.monotonic(),
                            "source": "FastPixelProbe",
                            "error": "probe_failed",
                        }
                    self._last_turn_probe_snapshot = dict(turn_probe_snapshot)

                    self._set_loop_stage("process_frame", publish=True)
                    detector_started_at = time.monotonic()
                    state = await self._process_frame(frame)
                    state_action_buttons = list(getattr(state, "action_buttons", []) or [])
                    state_hero_cards = list(getattr(state, "hero_cards", []) or [])

                    hitl = getattr(self, "hitl", None)
                    if hitl and not hitl.is_waiting_for_human:
                        action_labels = {str(button.class_name or "").lower() for button in state_action_buttons}
                        has_turn_layout = "fold_button" in action_labels and bool(
                            action_labels.intersection({"call_button", "check_button", "bet_button", "raise_button", "all_in_call_button"})
                        )
                        probe_detects_turn = bool(turn_probe_snapshot.get("is_our_turn", False))
                        resolved_hero_cards = tuple(
                            card for card in (decode_card_token(button.class_name) for button in state_hero_cards) if card
                        )
                        # Seulement déclencher HITL si YOLO ET le Tracker ont perdu les cartes
                        tracker_has_cards = hasattr(self, "tracker") and len(getattr(self.tracker, "hero_cards", [])) == 2
                        if (has_turn_layout or probe_detects_turn) and len(resolved_hero_cards) != 2:
                            if not tracker_has_cards:
                                logger.warning("HITL: C'est à notre tour, et aucune carte sauvée par le tracker ! Capture.")
                                await hitl.request_intervention_async(frame, issue_type="yolo_failure", reason="Missing hero cards on actionable spot (CRITICAL)")
                            else:
                                hitl.record_anomaly_silently(frame, issue_type="yolo_failure", reason="Missing hero cards on actionable spot (RESCUED BY TRACKER)")

                    time_bank_btn = next((b for b in state_action_buttons if b.class_name == "time_bank_button"), None)
                    if time_bank_btn:
                        logger.warning("TIME BANK ONSCREEN -> Clic auto securite pour acheter du temps.")
                        await self.action_controller.click_at(*(int(c) for c in time_bank_btn.center))
                        await asyncio.sleep(0.5)
                        continue

                    detector_ms = (time.monotonic() - detector_started_at) * 1000.0
                    state_ready_at = time.monotonic()
                    self._set_loop_stage("convert_state", publish=True)
                    convert_started_at = time.monotonic()
                    observed_canonical_state = self._convert_state_for_tracker(state, frame)
                    if hasattr(observed_canonical_state, "metadata"):
                        observed_metadata = dict(getattr(observed_canonical_state, "metadata", {}) or {})
                        observed_metadata["turn_probe"] = dict(turn_probe_snapshot)
                        if hasattr(observed_canonical_state, "to_tracker_payload") and hasattr(observed_canonical_state, "spot_id"):
                            observed_canonical_state = observed_canonical_state.__class__(
                                spot_id=observed_canonical_state.spot_id,
                                street=observed_canonical_state.street,
                                pot=observed_canonical_state.pot,
                                board=observed_canonical_state.board,
                                hero_cards=observed_canonical_state.hero_cards,
                                players=observed_canonical_state.players,
                                legal_actions=observed_canonical_state.legal_actions,
                                action_buttons=observed_canonical_state.action_buttons,
                                state_confidence=observed_canonical_state.state_confidence,
                                metadata=observed_metadata,
                            )
                        elif hasattr(observed_canonical_state, "to_dict"):
                            setattr(observed_canonical_state, "metadata", observed_metadata)
                    convert_ms = (time.monotonic() - convert_started_at) * 1000.0
                    self.last_canonical_spot_snapshot = observed_canonical_state.to_dict() if hasattr(observed_canonical_state, "to_dict") else {}
                    tracker_data = observed_canonical_state.to_tracker_payload() if hasattr(observed_canonical_state, "to_tracker_payload") else {}
                    decision_ms = 0.0
                    stale_frame = False
                    decision_context_started_at = state_ready_at

                    self._set_loop_stage("tracker_update", publish=True)
                    tracker_started_at = time.monotonic()
                    await self.tracker.update_from_vision(tracker_data)
                    tracker_ms = (time.monotonic() - tracker_started_at) * 1000.0

                    self._set_loop_stage("build_snapshot", publish=True)
                    self.last_tracker_snapshot = self._build_tracker_snapshot(tracker_data)
                    canonical_state = self._build_resolved_runtime_state(observed_canonical_state)
                    if getattr(getattr(self, "observation_dataset", None), "enabled", False):
                        asyncio.create_task(
                            self._capture_observation_dataset_sample_async(frame, observed_canonical_state, state)
                        )
                    self._log_live_details(canonical_state, state)
                    self._record_runtime_transition(self.last_tracker_snapshot)
                    actionable_spot = len(canonical_state.hero_cards) == 2 and bool(canonical_state.legal_actions)

                    if actionable_spot:
                        # --- OCR Debouncing Logging & Checks ---
                        current_debounce_hash = hash((
                            canonical_state.street,
                            canonical_state.pot,
                            tuple(canonical_state.hero_cards),
                            tuple(canonical_state.board),
                            tuple(canonical_state.legal_actions)
                        ))

                        _debounce_state_hash = getattr(self, "_debounce_state_hash", None)
                        _debounce_start_time = getattr(self, "_debounce_start_time", 0.0)

                        if _debounce_state_hash != current_debounce_hash:
                            self._debounce_state_hash = current_debounce_hash
                            self._debounce_start_time = time.monotonic()
                            logger.info("Debouncing: Nivellement OCR, attente de stabilite...")
                            self._publish_runtime_bridge_state()
                            await asyncio.sleep(float(getattr(self, "_live_debounce_reset_sleep_s", 0.03) or 0.03))
                            continue
                             
                        # Si l'etat n'a pas change depuis une courte fenetre, il est considere comme stable.
                        if time.monotonic() - _debounce_start_time < float(getattr(self, "_live_debounce_stable_window_s", 0.12) or 0.12):
                            await asyncio.sleep(float(getattr(self, "_live_debounce_poll_sleep_s", 0.02) or 0.02))
                            continue
                            
                        self._set_loop_stage("decision_context", publish=True)
                        decision_context_started_at = time.monotonic()
                        frame_age_s = max(0.0, time.monotonic() - decision_context_started_at)
                        capture_context_recently_changed = bool(
                            getattr(self, "_capture_context_recently_changed", lambda: False)()
                        )
                        if frame_age_s > self._max_live_frame_age_s and not capture_context_recently_changed:
                            stale_frame = True
                            self._handle_stale_live_frame(canonical_state, frame_age_s)
                        else:
                            gate_tracker_snapshot = self._build_gate_tracker_snapshot(canonical_state)
                            self.last_tracker_snapshot = dict(gate_tracker_snapshot)
                            primary_villain, effective_stack = self._resolve_live_decision_context(canonical_state)

                            if primary_villain and effective_stack > 0:
                                self._set_loop_stage("decision_gate_flow", publish=True)
                                decision_started_at = time.monotonic()
                                flow_result = await self._run_decision_gate_flow(
                                    canonical_state=canonical_state,
                                    state=state,
                                    primary_villain=primary_villain,
                                    effective_stack=effective_stack,
                                    gate_tracker_snapshot=gate_tracker_snapshot,
                                    frame_age_ms=frame_age_s * 1000.0,
                                )
                                decision_ms = (time.monotonic() - decision_started_at) * 1000.0

                                if not flow_result["gate_result"].allowed:
                                    logger.warning("Action live bloquee par le gate: %s", flow_result["gate_result"].to_dict())
                            else:
                                self._clear_live_decision_summary(canonical_state)
                                self.last_decision_summary["execution"] = {
                                    "status": "idle",
                                    "reason": "decision_context_unavailable",
                                }
                                logger.warning(
                                    "DECISION | skipped reason=decision_context_unavailable street=%s hero=%s legal=%s",
                                    canonical_state.street,
                                    self._format_log_cards(canonical_state.hero_cards),
                                    self._format_log_list(canonical_state.legal_actions),
                                )
                    else:
                        self._clear_live_decision_summary(canonical_state)
                        if canonical_state.street == "IDLE":
                            self._clear_live_execution_guard()
                    self._persist_runtime_metrics_snapshot()
                    total_ms = (time.monotonic() - loop_started_at) * 1000.0
                    timing_reference_at = decision_context_started_at if actionable_spot else frame_acquired_at
                    frame_age_ms = max(0.0, (time.monotonic() - timing_reference_at) * 1000.0)
                    self._log_loop_timing(
                        canonical_state=canonical_state,
                        frame_age_ms=frame_age_ms,
                        detector_ms=detector_ms,
                        convert_ms=convert_ms,
                        decision_ms=decision_ms,
                        tracker_ms=tracker_ms,
                        total_ms=total_ms,
                        stale_frame=stale_frame,
                    )

                    self._set_loop_stage("publish_state", publish=True)
                    self._publish_runtime_bridge_state()
                    await asyncio.sleep(self._get_live_loop_sleep_interval(actionable_spot))

                except Exception as loop_err:
                    logger.error(f"Erreur mineure dans l'analyse: {loop_err}")
                    self._push_incident("loop_error", severity="error", error=str(loop_err))
                    self._push_runtime_event("error", "loop_error", error=str(loop_err))
                    self._persist_runtime_metrics_snapshot(force=True)
                    self._publish_runtime_bridge_state(force=True)
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("Fermeture demandee.")
        except Exception as e:
            logger.critical(f"Erreur FATALE: {e}")
            self._push_incident("fatal_error", severity="critical", error=str(e))
            self._push_runtime_event("error", "fatal_error", error=str(e))
            self._persist_runtime_metrics_snapshot(force=True)
            self._publish_runtime_bridge_state(force=True)
        finally:
            self.is_running = False
            self._push_runtime_event("lifecycle", "bot_stopped")
            self._persist_runtime_metrics_snapshot(force=True)
            self._publish_runtime_bridge_state(force=True)
            self.camera.stop()
            self._stop_runtime_api_process()
            await self.db.close()
            logger.info("Arret complet effectue.")
