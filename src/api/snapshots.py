"""Builders de payload runtime snapshot/observation (extrait de src/api/server.py)."""
import asyncio
import logging
import time

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = UTC
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import web

logger = logging.getLogger("BotAPI")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_limit(raw_limit, default: int = 10, maximum: int = 50) -> int:
    try:
        limit = int(raw_limit) if raw_limit is not None else default
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, maximum))


def slice_history_entries(entries, limit: int) -> list:
    return list(entries[:limit]) if isinstance(entries, list) else []


def safe_float(value: object):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None



class SnapshotPayloadMixin:
    _now_iso = staticmethod(now_iso)
    _parse_limit = staticmethod(parse_limit)
    _slice_history_entries = staticmethod(slice_history_entries)
    _safe_float = staticmethod(safe_float)
    def _build_runtime_observation_payload(self, limit: int = 5) -> dict:
        observation = {}
        if self.runtime_observation_provider is not None:
            observation = self.runtime_observation_provider() or {}
        elif self.runtime_status_provider is not None:
            runtime = self.runtime_status_provider() or {}
            observation = runtime.get("observation", {}) or {}

        top_profiles = observation.get("top_profiles", []) if isinstance(observation, dict) else []
        if not isinstance(top_profiles, list):
            top_profiles = []
        return {
            "mode_enabled": bool((observation or {}).get("mode_enabled", False)),
            "collecting": bool((observation or {}).get("collecting", False)),
            "backend": str((observation or {}).get("backend") or "unknown"),
            "persistence": dict((observation or {}).get("persistence") or {}),
            "player_count": int((observation or {}).get("player_count", 0) or 0),
            "observed_hands": int((observation or {}).get("observed_hands", 0) or 0),
            "hands_recorded": int((observation or {}).get("hands_recorded", 0) or 0),
            "last_seen": (observation or {}).get("last_seen"),
            "top_profiles": list(top_profiles[:limit]),
        }

    @staticmethod

    @staticmethod
    def _runtime_players(canonical_spot: dict) -> list[dict]:
        players = canonical_spot.get("players", []) if isinstance(canonical_spot, dict) else []
        return [dict(player) for player in players if isinstance(player, dict)]

    @classmethod
    def _runtime_hero_and_villains(cls, canonical_spot: dict) -> tuple[dict | None, list[dict]]:
        players = cls._runtime_players(canonical_spot)
        active_players = [
            player for player in players
            if bool(player.get("active", True)) and not bool(player.get("folded", False))
        ]
        hero_player = next((player for player in active_players if bool(player.get("is_hero"))), None)
        villains = [player for player in active_players if not bool(player.get("is_hero"))]
        if hero_player is None:
            hero_player = next((player for player in players if bool(player.get("is_hero"))), None)
        if not villains:
            villains = [player for player in players if not bool(player.get("is_hero"))]
        return hero_player, villains

    @staticmethod
    def _runtime_effective_stack(hero_player: dict | None, villains: list[dict]) -> float:
        hero_stack = safe_float((hero_player or {}).get("stack"))
        villain_stacks = [
            stack
            for stack in (safe_float(player.get("stack")) for player in villains)
            if stack is not None
        ]
        if hero_stack is not None and villain_stacks:
            return max(0.0, min([hero_stack, *villain_stacks]))
        if hero_stack is not None:
            return max(0.0, hero_stack)
        if villain_stacks:
            return max(0.0, min(villain_stacks))
        return 0.0

    @staticmethod
    def _runtime_hero_position(hero_player: dict | None, villains: list[dict], tracker: dict) -> str | None:
        if hero_player and bool(hero_player.get("has_button")):
            return "ip" if len(villains) <= 1 else "btn"
        if any(bool(player.get("has_button")) for player in villains):
            if len(villains) == 1:
                return "oop"
            seat_id = str((hero_player or {}).get("seat_id") or tracker.get("hero_seat_id") or "").strip()
            return seat_id or None
        seat_id = str((hero_player or {}).get("seat_id") or tracker.get("hero_seat_id") or "").strip()
        return seat_id or None

    @classmethod
    def _runtime_spot_ranges(cls, decision: dict, canonical_spot: dict) -> dict:
        metadata = dict(decision.get("metadata", {}) or {})
        solver_metadata = dict(metadata.get("solver", {}) or {})
        profile_metadata = dict(metadata.get("profile", {}) or {})
        hero_cards = list(canonical_spot.get("hero_cards", [])) if isinstance(canonical_spot, dict) else []
        normalized_ranges = solver_metadata.get("normalized_ranges")
        if isinstance(normalized_ranges, list) and normalized_ranges:
            hero_range = str(normalized_ranges[0] or "").strip()
            villains = [str(item).strip() for item in normalized_ranges[1:] if str(item).strip()]
        else:
            hero_range = " ".join(str(card).strip() for card in hero_cards if str(card).strip())
            villain_hint = str(profile_metadata.get("range_hint", "") or "").strip()
            villains = [villain_hint] if villain_hint else []
        return {
            "hero": hero_range,
            "villains": villains,
        }

    @staticmethod
    def _runtime_ocr_payload(tracker: dict, history: dict) -> dict:
        ocr_metadata = dict(tracker.get("ocr_metadata", {}) or {})
        pot_ocr = dict(ocr_metadata.get("pot", {}) or {})
        loaded_engines = ocr_metadata.get("engines", [])
        requested_engines = ocr_metadata.get("requested_engines", [])
        selected_engine = str(
            pot_ocr.get("selected_engine")
            or pot_ocr.get("provider")
            or (loaded_engines[0] if isinstance(loaded_engines, list) and loaded_engines else "")
            or ""
        ).strip()
        return {
            "confidence": float(tracker.get("state_confidence", 0.0) or 0.0),
            "drift": str(pot_ocr.get("agreement") or "stable"),
            "frame_label": "live_runtime",
            "notes": [
                event.get("message", "")
                for event in history.get("events", [])[:3]
                if isinstance(event, dict) and str(event.get("message", "")).strip()
            ],
            "source": selected_engine or "ocr_runtime",
            "mode": str(ocr_metadata.get("mode") or "consensus_amounts"),
            "selected_engine": selected_engine,
            "loaded_engines": loaded_engines if isinstance(loaded_engines, list) else [],
            "requested_engines": requested_engines if isinstance(requested_engines, list) else [],
            "agreement": str(pot_ocr.get("agreement") or "stable"),
            "selected_confidence": float(
                pot_ocr.get("selected_confidence", tracker.get("state_confidence", 0.0)) or 0.0
            ),
            "engine_scores": dict(pot_ocr.get("engine_scores", {}) or {}),
            "candidates": list(pot_ocr.get("candidates", []) or []),
        }

    def _build_runtime_snapshot_payload(self) -> dict:
        runtime = self.runtime_status_provider() if self.runtime_status_provider else {}
        runtime = runtime or {}
        tracker = runtime.get("tracker", {}) or {}
        canonical_spot = runtime.get("canonical_spot") if isinstance(runtime.get("canonical_spot"), dict) else {}
        gate = runtime.get("gate", {}) or {}
        decision = runtime.get("decision", {}) or {}
        readiness = runtime.get("readiness", {}) or {}
        go_live_gate = runtime.get("go_live_gate", {}) or {}
        metrics = runtime.get("metrics", {}) or {}
        history = runtime.get("history", {}) or {}
        history_summary = runtime.get("history_summary", {}) or {}
        persistence = history_summary.get("persistence", {}) or {}
        operator = runtime.get("operator", {}) or {}
        observation = runtime.get("observation", {}) or {}
        if not isinstance(observation, dict) or not observation:
            observation = self._build_runtime_observation_payload(limit=5)
        hero_player, villains = self._runtime_hero_and_villains(canonical_spot)
        active_players = [
            player for player in self._runtime_players(canonical_spot)
            if bool(player.get("active", True)) and not bool(player.get("folded", False))
        ]
        player_count = len(active_players) or len(self._runtime_players(canonical_spot)) or int(
            tracker.get("detected_player_count", 0) or 0
        )
        effective_stack = self._runtime_effective_stack(hero_player, villains)
        hero_position = self._runtime_hero_position(hero_player, villains, tracker)
        spot_ranges = self._runtime_spot_ranges(decision, canonical_spot)
        ocr_payload = self._runtime_ocr_payload(tracker, history)

        state = "live" if runtime.get("is_running") else "offline"
        source = str(
            ((decision.get("metadata", {}) or {}).get("exploit", {}) or {}).get("source_slug")
            or decision.get("source")
            or "runtime"
        ).strip().lower() or "runtime"
        fallback_used = bool(decision.get("fallback_used", False))
        warnings = list(decision.get("warnings", []))
        if fallback_used and "fallback_used" not in warnings:
            warnings.append("fallback_used")

        incident_entries = list(history.get("incidents", []))
        incident_ids = [
            str(entry.get("id", ""))
            for entry in incident_entries
            if isinstance(entry, dict) and str(entry.get("id", "")).strip()
        ]
        incident_ids.extend(str(item) for item in decision.get("incidents", []) if str(item).strip())
        incident_ids = list(dict.fromkeys(incident_ids))

        latest_decision = history.get("decisions", [{}])
        latest_decision = latest_decision[0] if isinstance(latest_decision, list) and latest_decision else {}
        fallback_reason = decision.get("fallback_reason")
        fallback_history = [str(fallback_reason)] if fallback_reason else []
        combined_policy_compare = self._select_policy_compare_summary(history_summary, "combined")
        if not combined_policy_compare:
            combined_policy_compare = self._build_policy_compare_summary_from_records(
                self._select_history_entries(history, "combined").get("decisions", [])
            )

        solver_metadata = dict((decision.get("metadata", {}) or {}).get("solver", {}) or {})
        alternatives_raw = solver_metadata.get("alternatives_complete") or solver_metadata.get("alternatives") or []

        return {
            "state": "degraded" if warnings else state,
            "source": "local_rest",
            "message": "Local runtime snapshot from Python API.",
            "runtime": {
                "app_name": str(runtime.get("app_name") or runtime.get("service") or "PokerMaster"),
                "version": str(runtime.get("version") or "v2"),
                "runtime": "python_local_api",
                "healthy": state == "live",
                "status": "ok" if state == "live" else "offline",
                "http_fallback_enabled": True,
                "session_id": str(runtime.get("session_id") or ""),
                "metrics": metrics,
                "canonical_spot": canonical_spot if canonical_spot else None,
                "readiness": readiness,
                "go_live_gate": go_live_gate,
            },
            "tracker": tracker,
            "canonical_spot": canonical_spot if canonical_spot else None,
            "gate": gate,
            "readiness": readiness,
            "go_live_gate": go_live_gate,
            "decision": {
                **decision,
                "chosen_action": decision.get("action", ""),
                "source": source,
                "hero_ev": float(decision.get("ev", 0.0) or 0.0),
                "exploitability": float(decision.get("exploitability", 0.0) or 0.0),
                "latency_ms": decision.get("elapsed_ms", 0),
                "alternatives": [
                    {
                        "name": str(
                            item.get("action")
                            or item.get("raw_action")
                            or item.get("name")
                            or ""
                        ).strip().lower(),
                        "size": self._safe_float(item.get("size")),
                        "frequency": self._safe_float(item.get("freq", item.get("frequency"))) or 0.0,
                        "ev": self._safe_float(item.get("ev", item.get("hero_ev"))) or 0.0,
                        "is_recommended": str(
                            item.get("action")
                            or item.get("raw_action")
                            or item.get("name")
                            or ""
                        ).strip().upper() == str(decision.get("action", "")).strip().upper(),
                    }
                    for item in alternatives_raw
                    if isinstance(item, dict)
                    and str(item.get("action") or item.get("raw_action") or item.get("name") or "").strip()
                ],
                "gate_result": gate,
                "metadata": {
                    "gate_reason": decision.get("gate_reason", gate.get("reason", "ready")),
                    "gate_allowed": decision.get("gate_allowed", gate.get("allowed", True)),
                    "gate_confidence": decision.get("gate_confidence", gate.get("confidence", 0.0)),
                    "observed_hands": decision.get("observed_hands", 0),
                    "assisted": dict(decision.get("assisted", {}) or {}),
                    "profile": dict(decision.get("profile", {}) or {}),
                    "confidence_details": dict(decision.get("confidence_details", {}) or {}),
                    "execution": dict(decision.get("execution", {}) or {}),
                    "cache_hit": decision.get("cache_hit", False),
                    "fallback_used": fallback_used,
                    "fallback_history": fallback_history,
                    "warning_history": warnings,
                    "incidents": incident_ids,
                    "metrics": metrics,
                    "history_summary": history_summary,
                    "rl_ab": self._select_ab_summary(history_summary, "combined") or self._build_empty_ab_summary(),
                    "policy_compare": combined_policy_compare or self._build_empty_policy_compare_summary(),
                    "persistence": persistence,
                    "decision_trace_history": history.get("decisions", []),
                    "runtime_event_history": history.get("events", []),
                    "incident_log": incident_entries,
                    "persisted_history": self._runtime_persistence_payload(history, limit=5),
                    "action_history": list(
                        tracker.get("action_history", decision.get("action_history", latest_decision.get("action_history", [])))
                        or latest_decision.get("action_history", [])
                    ),
                    "explanation": latest_decision.get(
                        "explanation",
                        "Runtime decision trace collected locally from the Python control loop.",
                    ),
                },
            },
            "spot": {
                "street": str(canonical_spot.get("street", tracker.get("street", "PREFLOP"))).lower(),
                "board": list(canonical_spot.get("board", tracker.get("board", []))),
                "pot": float(tracker.get("pot", 0.0) or 0.0),
                "effective_stack": effective_stack,
                "num_players": max(player_count, 2 if hero_player or villains else 0),
                "hero_cards": list(canonical_spot.get("hero_cards", tracker.get("hero_cards", []))),
                "hero_position": hero_position,
                "hero_seat_id": tracker.get("hero_seat_id"),
                "legal_actions": list(tracker.get("legal_actions", [])),
                "action_history": list(decision.get("action_history", latest_decision.get("action_history", []))),
                "ranges": spot_ranges,
                "source": "python_runtime",
                "metadata": {
                    "state_confidence": float(tracker.get("state_confidence", 0.0) or 0.0),
                    "in_hand": bool(tracker.get("in_hand", False)),
                    "hero_position": hero_position,
                    "players": active_players,
                    "metrics": metrics,
                    "decision_trace_count": len(history.get("decisions", [])),
                    "incident_count": len(incident_ids),
                    "last_decision_at": latest_decision.get("timestamp", decision.get("trace_updated_at")),
                    "last_runtime_event_at": history_summary.get("latest_event_at"),
                },
                "ocr_metadata": {
                    "confidence": ocr_payload["confidence"],
                    "notes": list(ocr_payload.get("notes", [])),
                    **dict(tracker.get("ocr_metadata", {}) or {}),
                },
            },
            "ocr": ocr_payload,
            "operator": {
                "profile_name": str(operator.get("profile_name") or "live-runtime"),
                "surface": str(operator.get("surface") or "bot_cockpit"),
                "capture_source": str(operator.get("capture_source") or "ocr"),
                "auto_refresh_enabled": bool(operator.get("auto_refresh_enabled", True)),
                "assisted_mode_enabled": bool(operator.get("assisted_mode_enabled", False)),
                "observation_mode_enabled": bool(operator.get("observation_mode_enabled", False)),
                "shadow_mode_enabled": bool(operator.get("shadow_mode_enabled", False)),
                "manual_override_enabled": bool(operator.get("manual_override_enabled", False)),
                "paused": bool(operator.get("paused", False)),
                "status": str(operator.get("status") or ("ready" if runtime.get("is_running") else "offline")),
            },
            "observation": observation,
            "warnings": warnings,
            "notes": [event.get("message", "") for event in history.get("events", [])[:5] if isinstance(event, dict)],
            "history": self._build_runtime_history_payload(limit=5),
            "refreshed_at": self._now_iso(),
        }

    def _invalidate_runtime_snapshot_cache(self) -> None:
        self._runtime_snapshot_cache = None
        self._runtime_snapshot_cached_at = 0.0

    async def _build_runtime_snapshot_payload_async(self, force: bool = False) -> dict:
        now = time.monotonic()
        if (
            not force
            and self._runtime_snapshot_cache is not None
            and (now - self._runtime_snapshot_cached_at) <= self._runtime_snapshot_ttl_seconds
        ):
            return dict(self._runtime_snapshot_cache)

        async with self._runtime_snapshot_lock:
            now = time.monotonic()
            if (
                not force
                and self._runtime_snapshot_cache is not None
                and (now - self._runtime_snapshot_cached_at) <= self._runtime_snapshot_ttl_seconds
            ):
                return dict(self._runtime_snapshot_cache)

            payload = await asyncio.to_thread(self._build_runtime_snapshot_payload)
            self._runtime_snapshot_cache = dict(payload)
            self._runtime_snapshot_cached_at = time.monotonic()
            return payload
