"""Snapshot pot rapide et gestion du contexte de capture (extrait de src/main.py)."""
import logging
import time
from typing import Dict, Optional, Tuple

from src.bot.runtime_types import CanonicalTableState

logger = logging.getLogger("SuperBot2026")


class CaptureContextMixin:
    def _update_fast_pot_snapshot(self, snapshot: dict[str, object] | None) -> None:
        if not isinstance(snapshot, dict) or not snapshot:
            return
        value = float(snapshot.get("value", 0.0) or 0.0)
        if value <= 0.0:
            return
        enriched = dict(snapshot)
        enriched.setdefault("observed_at_monotonic", time.monotonic())
        self._last_fast_pot_snapshot = enriched

    def _get_recent_fast_pot_snapshot(self) -> dict[str, object]:
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

    def _refresh_capture_region(self, force: bool = False) -> tuple[int, int, int, int] | None:
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

