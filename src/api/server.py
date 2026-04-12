import logging
import asyncio
import json
from aiohttp import web
import aiohttp_cors
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Optional

from poker.decisionmaker.v2_contracts import SpotSnapshot

logger = logging.getLogger("BotAPI")

EXPORT_CONTRACT_NAME = "runtime_review"
EXPORT_CONTRACT_VERSION = "v1"
POLICY_COMPARE_ARTIFACT = "policy_compare_corpus"
POLICY_COMPARE_BATCH_ARTIFACT = "policy_compare_batch"

class BotAPI:
    def __init__(
        self,
        hitl_module,
        runtime_status_provider: Optional[Callable[[], dict]] = None,
        runtime_operator_handler: Optional[Callable[[dict], dict]] = None,
        host: str = "127.0.0.1",
        port: int = 8080,
        runtime_history_store=None,
    ):
        """
        Serveur API asynchrone (aiohttp) permettant à l'interface React/Tauri
        de communiquer avec le bot Python en temps réel.
        """
        self.hitl = hitl_module
        self.runtime_status_provider = runtime_status_provider
        self.runtime_operator_handler = runtime_operator_handler
        self.runtime_history_store = runtime_history_store
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        
        self._setup_routes()
        self._setup_cors()

    def _setup_routes(self):
        self.app.router.add_get('/api/hitl/status', self.handle_get_status)
        self.app.router.add_post('/api/hitl/resolve', self.handle_resolve)
        self.app.router.add_get('/runtime-snapshot', self.handle_runtime_snapshot)
        self.app.router.add_get('/runtime-history', self.handle_runtime_history)
        self.app.router.add_get('/runtime-history/export', self.handle_runtime_history_export)
        self.app.router.add_post('/runtime-history/import', self.handle_runtime_history_import)
        self.app.router.add_get('/bot-cockpit/payload', self.handle_runtime_snapshot)
        self.app.router.add_get('/bot-cockpit/refresh', self.handle_runtime_snapshot)
        self.app.router.add_post('/bot-cockpit/operator', self.handle_operator_control)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_limit(raw_limit: Optional[str], default: int = 10, maximum: int = 50) -> int:
        try:
            limit = int(raw_limit) if raw_limit is not None else default
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, maximum))

    @staticmethod
    def _slice_history_entries(entries, limit: int) -> list:
        return list(entries[:limit]) if isinstance(entries, list) else []

    @staticmethod
    def _history_bucket_payload(entries: dict, limit: int) -> dict:
        return {
            "events": BotAPI._slice_history_entries(entries.get("events", []), limit),
            "decisions": BotAPI._slice_history_entries(entries.get("decisions", []), limit),
            "incidents": BotAPI._slice_history_entries(entries.get("incidents", []), limit),
            "metrics": BotAPI._slice_history_entries(entries.get("metrics", []), limit),
        }

    @staticmethod
    def _runtime_persistence_payload(history: dict, limit: int) -> dict:
        return BotAPI._history_bucket_payload(history.get("persisted", {}) or {}, limit)

    @staticmethod
    def _build_history_counts(entries: dict) -> dict:
        return {
            "event_count": len(entries.get("events", [])) if isinstance(entries.get("events", []), list) else 0,
            "decision_count": len(entries.get("decisions", [])) if isinstance(entries.get("decisions", []), list) else 0,
            "incident_count": len(entries.get("incidents", [])) if isinstance(entries.get("incidents", []), list) else 0,
            "metrics_count": len(entries.get("metrics", [])) if isinstance(entries.get("metrics", []), list) else 0,
        }

    @staticmethod
    def _build_history_timestamps(entries: dict) -> dict:
        def latest(items) -> Optional[str]:
            if isinstance(items, list) and items and isinstance(items[0], dict):
                return items[0].get("timestamp")
            return None

        return {
            "latest_event_at": latest(entries.get("events", [])),
            "latest_decision_at": latest(entries.get("decisions", [])),
            "latest_incident_at": latest(entries.get("incidents", [])),
            "latest_metrics_at": latest(entries.get("metrics", [])),
        }

    @staticmethod
    def _parse_history_source(raw_source: Optional[str]) -> str:
        source = str(raw_source or "combined").strip().lower()
        aliases = {
            "all": "combined",
            "combined": "combined",
            "both": "combined",
            "runtime": "runtime",
            "live": "runtime",
            "persisted": "persisted",
            "persisted-only": "persisted",
            "persisted_only": "persisted",
            "storage": "persisted",
        }
        return aliases.get(source, "combined")

    @staticmethod
    def _parse_bool(raw_value: Optional[str], default: bool = False) -> bool:
        if raw_value is None:
            return default
        return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_history_stream(raw_stream: Optional[str]) -> Optional[str]:
        stream = str(raw_stream or "").strip().lower()
        if stream in {"events", "decisions", "incidents", "metrics"}:
            return stream
        return None

    @staticmethod
    def _export_filename(stream: Optional[str]) -> str:
        suffix = stream or "all"
        return f"runtime_history_{suffix}.json"

    @staticmethod
    def _review_pack_filename(stream: Optional[str]) -> str:
        suffix = stream or "all"
        return f"runtime_review_pack_{suffix}.json"

    @staticmethod
    def _review_session_filename(stream: Optional[str]) -> str:
        suffix = stream or "all"
        return f"runtime_review_session_{suffix}.json"

    @classmethod
    def _contract_metadata(cls, artifact_type: str, stream: Optional[str], record_count: int) -> dict:
        return {
            "name": EXPORT_CONTRACT_NAME,
            "version": EXPORT_CONTRACT_VERSION,
            "artifact_type": artifact_type,
            "stream": stream or "all",
            "record_count": int(record_count),
            "exported_at": cls._now_iso(),
            "compatibility": {
                "imports_records_from": [
                    "runtime_review.artifact.records",
                    "runtime_review.artifact.bundle.records",
                    "runtime_review.artifact.sessions[*].records",
                    "records",
                    "bundle.records",
                    "sessions[*].records",
                    "review_session.records",
                    "review_session.bundle.records",
                    "review_pack.sessions[*].raw.records",
                    "review_pack.records",
                    "review_pack.sessions[*].records",
                    "review_pack.raw.*",
                    "review_pack.currentReplay.timeline[*]",
                    "review_pack.current_replay.timeline[*]",
                ],
            },
        }

    @classmethod
    def _build_runtime_review_wrapper(
        cls,
        artifact_type: str,
        stream: Optional[str],
        record_count: int,
        artifact: dict,
        *,
        exported_at: Optional[str] = None,
    ) -> dict:
        contract = cls._contract_metadata(artifact_type, stream=stream, record_count=record_count)
        if exported_at:
            contract["exported_at"] = exported_at
        return {
            "name": EXPORT_CONTRACT_NAME,
            "version": EXPORT_CONTRACT_VERSION,
            "format": EXPORT_CONTRACT_NAME,
            "format_version": EXPORT_CONTRACT_VERSION,
            "artifact_type": artifact_type,
            "stream": stream or "all",
            "record_count": int(record_count),
            "exported_at": contract["exported_at"],
            "contract": contract,
            "artifact": artifact,
        }

    @classmethod
    def _build_contract_aliases(cls, artifact_type: str) -> dict:
        contract = cls._contract_metadata(artifact_type, stream=None, record_count=0)
        aliases = {
            "format": EXPORT_CONTRACT_NAME,
            "format_version": EXPORT_CONTRACT_VERSION,
            "name": EXPORT_CONTRACT_NAME,
            "version": EXPORT_CONTRACT_VERSION,
            "contract_name": EXPORT_CONTRACT_NAME,
            "contract_version": EXPORT_CONTRACT_VERSION,
            "artifact_type": artifact_type,
            "contract": {
                "name": contract["name"],
                "version": contract["version"],
                "artifact_type": contract["artifact_type"],
            },
        }
        # Keep legacy envelope aliases explicit while runtime_review stays canonical.
        if artifact_type == "review_session":
            aliases["kind"] = "runtime_replay_bundle"
        elif artifact_type == "review_pack":
            aliases["kind"] = "policy_compare_corpus_batch"
        elif artifact_type == POLICY_COMPARE_ARTIFACT:
            aliases["kind"] = "policy_compare_corpus"
        elif artifact_type == POLICY_COMPARE_BATCH_ARTIFACT:
            aliases["kind"] = "policy_compare_corpus_batch"
        return aliases

    @staticmethod
    def _policy_slug(value: object, fallback: str = "runtime") -> str:
        text = str(value or fallback).strip().lower()
        return text.replace(" ", "_") or fallback

    @classmethod
    def _normalize_action_name(cls, value: object) -> str:
        if value in (None, ""):
            return ""
        return str(value).strip().upper()

    @staticmethod
    def _safe_float(value: object) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_policy_actions(cls, record: dict) -> dict:
        policy_actions: dict[str, str] = {}

        chosen_action = cls._normalize_action_name(record.get("chosen_action", record.get("action", "")))
        if chosen_action:
            policy_actions[cls._policy_slug(record.get("source"), "runtime")] = chosen_action

        ab_decision = dict(record.get("ab_decision", {}) or {})
        gto_action = cls._normalize_action_name(ab_decision.get("gto_action"))
        if gto_action:
            policy_actions.setdefault("gto_solver", gto_action)

        comparison = dict(ab_decision.get("comparison", {}) or {})
        for branch in ("rl_off", "rl_on"):
            branch_action = cls._normalize_action_name((comparison.get(branch, {}) or {}).get("action"))
            if branch_action:
                policy_actions.setdefault(branch, branch_action)

        return policy_actions

    @classmethod
    def _extract_ev_by_action(cls, record: dict) -> dict:
        existing = record.get("ev_by_action")
        if isinstance(existing, dict):
            normalized_existing: dict[str, float] = {}
            for action_name, ev_value in existing.items():
                action = cls._normalize_action_name(action_name)
                ev = cls._safe_float(ev_value)
                if action and ev is not None and action not in normalized_existing:
                    normalized_existing[action] = ev
            if normalized_existing:
                return normalized_existing

        ev_by_action: dict[str, float] = {}

        def remember(action_name: object, ev_value: object) -> None:
            action = cls._normalize_action_name(action_name)
            ev = cls._safe_float(ev_value)
            if action and ev is not None and action not in ev_by_action:
                ev_by_action[action] = ev

        metadata = dict(record.get("metadata", {}) or {})
        solver = dict(metadata.get("solver", record.get("solver", {})) or {})
        for item in solver.get("alternatives", []) or []:
            if not isinstance(item, dict):
                continue
            remember(item.get("action", item.get("raw_action")), item.get("ev", item.get("hero_ev")))

        ab_decision = dict(record.get("ab_decision", {}) or {})
        comparison = dict(ab_decision.get("comparison", {}) or {})
        for branch in ("rl_off", "rl_on"):
            branch_snapshot = dict(comparison.get(branch, {}) or {})
            remember(branch_snapshot.get("action"), branch_snapshot.get("ev"))

        remember(record.get("chosen_action", record.get("action")), record.get("ev"))

        return ev_by_action

    @classmethod
    def _extract_solver_compact_payload(cls, record: dict) -> dict:
        if not isinstance(record, dict):
            return {}

        metadata = dict(record.get("metadata", {}) or {})
        solver = dict(metadata.get("solver", record.get("solver", {})) or {})
        payload: dict[str, object] = {}

        chosen_action_raw = solver.get("chosen_action_raw", record.get("chosen_action_raw"))
        if chosen_action_raw not in (None, ""):
            payload["chosen_action_raw"] = chosen_action_raw

        backend = record.get("backend", solver.get("backend"))
        if backend not in (None, ""):
            payload["backend"] = backend

        cache_hit = record.get("cache_hit", solver.get("cache_hit"))
        if isinstance(cache_hit, bool):
            payload["cache_hit"] = cache_hit

        for float_key in ("elapsed_ms", "exploitability", "solver_elapsed_ms"):
            value = cls._safe_float(solver.get(float_key, record.get(float_key)))
            if value is not None:
                payload[float_key] = value

        node_count = solver.get("node_count", record.get("node_count"))
        if isinstance(node_count, (int, float)):
            payload["node_count"] = int(node_count)

        for string_key in ("solver_id", "preset_id"):
            value = solver.get(string_key, record.get(string_key))
            if value not in (None, ""):
                payload[string_key] = str(value)

        for map_key in ("ev_by_action", "freq_by_action", "action_metadata", "backend_details", "cache_details"):
            map_value = solver.get(map_key, record.get(map_key))
            if isinstance(map_value, dict) and map_value:
                payload[map_key] = dict(map_value)

        warnings = solver.get("warnings", record.get("solver_warnings"))
        if isinstance(warnings, list) and warnings:
            payload["warnings"] = [str(item) for item in warnings if str(item).strip()]

        warning_details = solver.get("warning_details", record.get("solver_warning_details"))
        if isinstance(warning_details, list) and warning_details:
            payload["warning_details"] = [dict(item) if isinstance(item, dict) else str(item) for item in warning_details]

        action_buckets = solver.get("action_buckets", record.get("action_buckets"))
        if isinstance(action_buckets, list) and action_buckets:
            payload["action_buckets"] = [dict(item) if isinstance(item, dict) else str(item) for item in action_buckets]

        for action_key in ("gto_action", "final_action"):
            action_value = cls._normalize_action_name(solver.get(action_key, record.get(action_key)))
            if action_value:
                payload[action_key] = action_value

        alternatives = []
        for item in solver.get("alternatives", []) or []:
            if not isinstance(item, dict):
                continue
            compact_item: dict[str, object] = {}
            action = cls._normalize_action_name(item.get("action"))
            raw_action = item.get("raw_action")
            freq = cls._safe_float(item.get("freq"))
            ev = cls._safe_float(item.get("ev", item.get("hero_ev")))
            source = item.get("source")

            if action:
                compact_item["action"] = action
            if raw_action not in (None, ""):
                compact_item["raw_action"] = raw_action
            if freq is not None:
                compact_item["freq"] = freq
            if ev is not None:
                compact_item["ev"] = ev
            if source not in (None, ""):
                compact_item["source"] = source
            if compact_item:
                alternatives.append(compact_item)

        if alternatives:
            payload["alternatives"] = alternatives

        alternatives_complete = []
        for item in solver.get("alternatives_complete", []) or []:
            if not isinstance(item, dict):
                continue
            compact_item = dict(item)
            action = cls._normalize_action_name(compact_item.get("action"))
            if action:
                compact_item["action"] = action
            if compact_item:
                alternatives_complete.append(compact_item)

        if alternatives_complete:
            payload["alternatives_complete"] = alternatives_complete

        ev_by_action = cls._extract_ev_by_action(record)
        if ev_by_action:
            payload["ev_by_action"] = ev_by_action

        return payload

    @staticmethod
    def _canonical_spot_to_policy_compare_spot(canonical_spot: dict) -> dict:
        if not isinstance(canonical_spot, dict):
            return SpotSnapshot().to_dict()

        metadata = dict(canonical_spot.get("metadata", {}) or {})
        hero_position = str(
            canonical_spot.get("hero_position")
            or metadata.get("hero_position")
            or metadata.get("hero_seat_id")
            or ""
        )
        stack = canonical_spot.get("stack")
        if stack in (None, ""):
            for player in canonical_spot.get("players", []) or []:
                if isinstance(player, dict) and player.get("is_hero"):
                    stack = player.get("stack")
                    break

        return SpotSnapshot.from_dict(
            {
                "spot_id": canonical_spot.get("spot_id", ""),
                "source": "runtime_replay_bundle",
                "game_stage": str(canonical_spot.get("street", canonical_spot.get("game_stage", "")) or "").lower(),
                "hero_cards": canonical_spot.get("hero_cards", []),
                "board": canonical_spot.get("board", []),
                "hero_position": hero_position,
                "pot": canonical_spot.get("pot", 0.0),
                "stack": stack or 0.0,
                "legal_actions": canonical_spot.get("legal_actions", []),
                "action_history": canonical_spot.get("action_history", []),
                "state_confidence": canonical_spot.get("state_confidence", 0.0),
                "metadata": metadata,
            }
        ).to_dict()

    def _get_runtime_history_store(self):
        if self.runtime_history_store is not None:
            return self.runtime_history_store

        runtime = self.runtime_status_provider() if self.runtime_status_provider else {}
        runtime = runtime or {}
        persistence = ((runtime.get("history_summary", {}) or {}).get("persistence", {}) or {})
        file_path = str(persistence.get("path", "") or "").strip()
        if not file_path:
            return None

        try:
            from src.runtime.history_store import RuntimeHistoryStore

            return RuntimeHistoryStore(
                enabled=bool(persistence.get("enabled", True)),
                file_path=file_path,
                max_size_bytes=int(persistence.get("max_size_bytes", 1_048_576) or 1_048_576),
            )
        except Exception as exc:
            logger.warning("Unable to access runtime history store from %s: %s", file_path, exc)
            return None

    def _build_export_payload(self, records: list[dict], stream: Optional[str]) -> dict:
        contract = self._contract_metadata("review_session", stream=stream, record_count=len(records))
        counts = {
            "events": 0,
            "decisions": 0,
            "incidents": 0,
            "metrics": 0,
        }
        for record in records:
            bucket = str(record.get("stream", "") or "")
            if bucket in counts:
                counts[bucket] += 1

        return {
            "format": "runtime_history_v1",
            "format_version": "v1",
            "meta": {
                **self._build_contract_aliases("review_session"),
                "stream": stream or "all",
                "record_count": len(records),
            },
            "stream": stream or "all",
            "exported_at": contract["exported_at"],
            "counts": counts,
            "contract": contract,
            "records": records,
        }

    def _build_replay_bundle_payload(self, records: list[dict], stream: Optional[str]) -> dict:
        runtime = self.runtime_status_provider() if self.runtime_status_provider else {}
        runtime = runtime or {}
        history = runtime.get("history", {}) or {}
        history_summary = runtime.get("history_summary", {}) or {}
        canonical_spot = runtime.get("canonical_spot")
        tracker = runtime.get("tracker", {}) or {}
        gate = runtime.get("gate", {}) or {}
        decision = runtime.get("decision", {}) or {}
        metrics = runtime.get("metrics", {}) or {}

        export_payload = self._build_export_payload(records, stream)
        stream_name = stream or "all"
        persistence = history_summary.get("persistence", {}) or {}

        review_session_payload = {
            "format": EXPORT_CONTRACT_NAME,
            "version": EXPORT_CONTRACT_VERSION,
            "meta": {
                **self._build_contract_aliases("review_session"),
                "stream": stream_name,
                "record_count": len(records),
            },
            "contract": self._contract_metadata("review_session", stream=stream, record_count=len(records)),
            "stream": stream_name,
            "record_count": len(records),
            "bundle": {
                "kind": "runtime_replay_bundle",
                "version": "v1",
                "stream": stream_name,
                "exported_at": export_payload["exported_at"],
                "records": records,
            },
        }
        bundle_payload = {
            "kind": "runtime_replay_bundle",
            "version": "v1",
            "stream": stream_name,
            "exported_at": export_payload["exported_at"],
            "summary": {
                "record_count": len(records),
                "counts": export_payload["counts"],
                "history_summary": history_summary,
            },
            "runtime": {
                "tracker": tracker,
                "canonical_spot": canonical_spot if isinstance(canonical_spot, dict) and canonical_spot else None,
                "gate": gate,
                "decision": decision,
                "metrics": metrics,
            },
            "metadata": {
                "persistence": persistence,
                "available_streams": {
                    "runtime": self._build_history_counts({
                        "events": history.get("events", []),
                        "decisions": history.get("decisions", []),
                        "incidents": history.get("incidents", []),
                    }),
                    "persisted": self._build_history_counts(history.get("persisted", {}) or {}),
                },
            },
            "records": records,
        }

        return {
            **export_payload,
            "runtime_review": self._build_runtime_review_wrapper(
                "review_session",
                stream,
                len(records),
                artifact={
                    "records": records,
                    "bundle": bundle_payload,
                    "summary": {
                        "counts": export_payload["counts"],
                        "history_summary": history_summary,
                    },
                },
                exported_at=export_payload["exported_at"],
            ),
            "review_session": review_session_payload,
            "bundle": bundle_payload,
        }

    def _build_policy_compare_corpus_payload(self, records: list[dict], stream: Optional[str]) -> dict:
        runtime = self.runtime_status_provider() if self.runtime_status_provider else {}
        runtime = runtime or {}
        canonical_spot = runtime.get("canonical_spot")
        runtime_session_id = str(runtime.get("session_id", "") or "").strip()
        spot_payload = self._canonical_spot_to_policy_compare_spot(canonical_spot)
        corpus_records = []

        for index, record in enumerate(records, start=1):
            if str(record.get("stream", "") or "") != "decisions":
                continue

            policy_actions = self._extract_policy_actions(record)
            if not policy_actions:
                continue

            replay_id = str(record.get("spot_id", "") or record.get("timestamp", f"runtime-{index:03d}"))
            spot = dict(spot_payload)
            spot.update(
                {
                    "spot_id": str(record.get("spot_id", spot.get("spot_id", replay_id)) or replay_id),
                    "game_stage": str(record.get("street", spot.get("game_stage", "")) or spot.get("game_stage", "")).lower(),
                    "hero_cards": list(record.get("hero_cards", spot.get("hero_cards", [])) or []),
                    "board": list(record.get("board", spot.get("board", [])) or []),
                    "pot": float(record.get("pot", spot.get("pot", 0.0)) or 0.0),
                    "legal_actions": list(record.get("legal_actions", spot.get("legal_actions", [])) or []),
                    "action_history": list(record.get("action_history", spot.get("action_history", [])) or []),
                    "metadata": {
                        **dict(spot.get("metadata", {}) or {}),
                        "runtime_timestamp": record.get("timestamp"),
                    },
                }
            )
            corpus_records.append(
                {
                    "replay_id": replay_id,
                    "spot": spot,
                    "policy_actions": policy_actions,
                    "ev_by_action": self._extract_ev_by_action(record),
                    "tags": ["runtime_replay_bundle", str(record.get("street", "")).strip().lower() or "unknown"],
                    **self._extract_solver_compact_payload(record),
                    "metadata": {
                        "timestamp": record.get("timestamp"),
                        "stream": record.get("stream"),
                        "session_id": record.get("session_id") or runtime_session_id or None,
                        "confidence": record.get("confidence"),
                        "latency_ms": record.get("latency_ms"),
                        "warnings": list(record.get("warnings", []) or []),
                        "incidents": list(record.get("incidents", []) or []),
                        **self._extract_solver_compact_payload(record),
                    },
                }
            )

        exported_at = self._now_iso()
        payload = {
            "kind": "policy_compare_corpus",
            "format": EXPORT_CONTRACT_NAME,
            "format_version": EXPORT_CONTRACT_VERSION,
            "version": EXPORT_CONTRACT_VERSION,
            "meta": {
                **self._build_contract_aliases(POLICY_COMPARE_ARTIFACT),
                "stream": stream or "all",
                "record_count": len(corpus_records),
                "source_format": "runtime_replay_bundle",
            },
            "source_format": "runtime_replay_bundle",
            "stream": stream or "all",
            "exported_at": exported_at,
            "contract": self._contract_metadata(POLICY_COMPARE_ARTIFACT, stream=stream, record_count=len(corpus_records)),
            "records": corpus_records,
        }
        payload["runtime_review"] = self._build_runtime_review_wrapper(
            POLICY_COMPARE_ARTIFACT,
            stream,
            len(corpus_records),
            artifact={
                "records": corpus_records,
                "summary": {
                    "source_format": "runtime_replay_bundle",
                },
            },
            exported_at=exported_at,
        )
        return payload

    def _build_policy_compare_batch_payload(self, record_batches: list[dict], stream: Optional[str]) -> dict:
        sessions = []
        flattened_records = []

        for index, batch in enumerate(record_batches, start=1):
            if not isinstance(batch, dict):
                continue

            session_id = str(batch.get("session_id", f"session_{index:03d}") or f"session_{index:03d}")
            source_path = str(batch.get("source_path", "") or "")
            session_payload = self._build_policy_compare_corpus_payload(list(batch.get("records", []) or []), stream=stream)
            session_records = []

            for record in session_payload.get("records", []) or []:
                if not isinstance(record, dict):
                    continue
                enriched_record = {
                    **record,
                    "metadata": {
                        **dict(record.get("metadata", {}) or {}),
                        "session_id": session_id,
                        "source_path": source_path,
                    },
                }
                flattened_records.append(enriched_record)
                session_records.append(enriched_record)

            sessions.append(
                {
                    "session_id": session_id,
                    "source_path": source_path,
                    "record_count": len(session_records),
                    "records": session_records,
                }
            )

        total_records = len(flattened_records)

        exported_at = self._now_iso()
        review_pack_payload = {
            "format": EXPORT_CONTRACT_NAME,
            "version": EXPORT_CONTRACT_VERSION,
            "meta": {
                **self._build_contract_aliases("review_pack"),
                "stream": stream or "all",
                "record_count": total_records,
            },
            "contract": self._contract_metadata("review_pack", stream=stream, record_count=total_records),
            "stream": stream or "all",
            "record_count": total_records,
            "sessions": sessions,
        }

        return {
            "kind": "policy_compare_corpus_batch",
            "format": EXPORT_CONTRACT_NAME,
            "format_version": EXPORT_CONTRACT_VERSION,
            "version": EXPORT_CONTRACT_VERSION,
            "meta": {
                **self._build_contract_aliases(POLICY_COMPARE_BATCH_ARTIFACT),
                "stream": stream or "all",
                "record_count": total_records,
                "source_format": "runtime_replay_bundle",
            },
            "source_format": "runtime_replay_bundle",
            "stream": stream or "all",
            "exported_at": exported_at,
            "contract": self._contract_metadata(POLICY_COMPARE_BATCH_ARTIFACT, stream=stream, record_count=total_records),
            "runtime_review": self._build_runtime_review_wrapper(
                POLICY_COMPARE_BATCH_ARTIFACT,
                stream,
                total_records,
                artifact={
                    "records": flattened_records,
                    "sessions": sessions,
                    "summary": {
                        "source_format": "runtime_replay_bundle",
                    },
                },
                exported_at=exported_at,
            ),
            "review_pack": review_pack_payload,
            "records": flattened_records,
            "sessions": sessions,
        }

    @staticmethod
    def _resolve_export_filename(export_format: str, stream: Optional[str]) -> str:
        normalized = str(export_format or "bundle").strip().lower()
        if normalized in {"policy_compare_batch", "policy-compare-batch", "corpus_batch"}:
            return BotAPI._review_pack_filename(stream)
        if normalized in {"policy_compare", "policy-compare", "corpus", "bundle"}:
            return BotAPI._review_session_filename(stream)
        return BotAPI._export_filename(stream)

    def _select_history_entries(self, history: dict, source: str) -> dict:
        runtime_entries = {
            "events": history.get("events", []),
            "decisions": history.get("decisions", []),
            "incidents": history.get("incidents", []),
            "metrics": history.get("metrics", []),
        }
        persisted_entries = history.get("persisted", {}) or {}

        if source == "runtime":
            return runtime_entries
        if source == "persisted":
            return persisted_entries
        return {
            "events": self._merge_history_entries("events", runtime_entries.get("events", []), persisted_entries.get("events", [])),
            "decisions": self._merge_history_entries("decisions", runtime_entries.get("decisions", []), persisted_entries.get("decisions", [])),
            "incidents": self._merge_history_entries("incidents", runtime_entries.get("incidents", []), persisted_entries.get("incidents", [])),
            "metrics": self._merge_history_entries("metrics", runtime_entries.get("metrics", []), persisted_entries.get("metrics", [])),
        }

    @staticmethod
    def _history_entry_key(stream: str, entry: dict) -> Optional[tuple]:
        if not isinstance(entry, dict):
            return None

        timestamp = str(entry.get("timestamp", "") or "").strip()

        if stream == "decisions":
            spot_id = str(entry.get("spot_id", "") or "").strip()
            if spot_id and timestamp:
                return ("spot_id_timestamp", spot_id, timestamp)

            street = str(entry.get("street", "") or "").strip().upper()
            chosen_action = str(entry.get("chosen_action", entry.get("action", "")) or "").strip().upper()
            source = str(entry.get("source", "") or "").strip().lower()
            if timestamp and street and chosen_action:
                return ("timestamp_street_action", timestamp, street, chosen_action, source)

        if stream == "events":
            kind = str(entry.get("kind", "") or "").strip().lower()
            message = str(entry.get("message", "") or "").strip()
            if timestamp and (kind or message):
                return ("timestamp_kind_message", timestamp, kind, message)

        if stream == "incidents":
            incident_id = str(entry.get("id", "") or "").strip().lower()
            severity = str(entry.get("severity", "") or "").strip().lower()
            if timestamp and incident_id:
                return ("timestamp_id_severity", timestamp, incident_id, severity)

        if stream == "metrics":
            if timestamp:
                return ("timestamp", timestamp)

        return None

    @classmethod
    def _merge_history_entries(cls, stream: str, runtime_entries, persisted_entries) -> list:
        merged: list[dict] = []
        seen_keys: set[tuple] = set()

        for entry in list(runtime_entries or []) + list(persisted_entries or []):
            if not isinstance(entry, dict):
                continue

            entry_key = cls._history_entry_key(stream, entry)
            if entry_key is not None:
                if entry_key in seen_keys:
                    continue
                seen_keys.add(entry_key)

            merged.append(entry)

        return merged

    @staticmethod
    def _build_empty_ab_summary() -> dict:
        return {
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
    def _policy_compare_sample_id(cls, record: dict, fallback: str) -> str:
        if not isinstance(record, dict):
            return fallback
        spot_id = str(record.get("spot_id", "") or "").strip()
        timestamp = str(record.get("timestamp", "") or "").strip()
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
        record: dict,
        sample_id: str,
        baseline_action: str,
        challenger_action: str,
        ev_by_action: dict,
    ) -> dict:
        example = {
            "sample_id": sample_id,
            "spot_id": str(record.get("spot_id", "") or "").strip() or sample_id,
            "street": str(record.get("street", "UNKNOWN") or "UNKNOWN").strip().upper() or "UNKNOWN",
            "baseline_action": baseline_action,
            "challenger_action": challenger_action,
            "action_pair": f"{baseline_action}->{challenger_action}",
        }
        hero_cards = list(record.get("hero_cards", []) or [])
        board = list(record.get("board", []) or [])
        if hero_cards:
            example["hero_cards"] = hero_cards[:2]
        if board:
            example["board"] = board[:5]
        pot = cls._safe_float(record.get("pot"))
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

    @staticmethod
    def _select_ab_summary(summary: dict, source: str) -> dict:
        rl_ab = dict(summary.get("rl_ab", {}) or {}) if isinstance(summary, dict) else {}
        if source == "runtime":
            return dict(rl_ab.get("runtime", {}) or {})
        if source == "persisted":
            return dict(rl_ab.get("persisted", {}) or {})
        return dict(rl_ab.get("combined", {}) or {})

    @staticmethod
    def _select_policy_compare_summary(summary: dict, source: str) -> dict:
        policy_compare = dict(summary.get("policy_compare", {}) or {}) if isinstance(summary, dict) else {}
        if source == "runtime":
            return dict(policy_compare.get("runtime", {}) or {})
        if source == "persisted":
            return dict(policy_compare.get("persisted", {}) or {})
        return dict(policy_compare.get("combined", {}) or {})

    @staticmethod
    def _build_policy_compare_summary_from_records(decisions: list[dict]) -> dict:
        try:
            from research.policy_compare import PolicyCompareRecord, build_policy_compare_summary

            records = []
            pair_examples: dict[tuple[str, str], dict] = {}
            spot_counts: dict[str, dict] = {}
            for index, item in enumerate(decisions or [], start=1):
                if not isinstance(item, dict):
                    continue
                policy_actions = BotAPI._extract_policy_actions(item)
                if len(policy_actions) < 2:
                    continue
                sample_id = BotAPI._policy_compare_sample_id(item, f"sample-{index:03d}")
                street = str(item.get("street", "UNKNOWN") or "UNKNOWN").strip().upper() or "UNKNOWN"
                spot_id = str(item.get("spot_id", "") or "").strip() or sample_id
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

                ev_by_action = BotAPI._extract_ev_by_action(item)
                policies = sorted(policy_actions)
                for policy_index, baseline in enumerate(policies):
                    for challenger in policies[policy_index + 1 :]:
                        baseline_action = policy_actions.get(baseline, "")
                        challenger_action = policy_actions.get(challenger, "")
                        if not baseline_action or not challenger_action:
                            continue
                        key = (baseline, challenger)
                        example_summary = pair_examples.setdefault(
                            key,
                            {
                                "sample_ids": [],
                                "spot_examples": [],
                                "divergence_examples": [],
                            },
                        )
                        if sample_id not in example_summary["sample_ids"] and len(example_summary["sample_ids"]) < 3:
                            example_summary["sample_ids"].append(sample_id)
                        example = BotAPI._policy_compare_spot_example(
                            item,
                            sample_id,
                            baseline_action,
                            challenger_action,
                            ev_by_action,
                        )
                        example_summary["spot_examples"].append(example)
                        if baseline_action != challenger_action:
                            example_summary["divergence_examples"].append(example)
                records.append(
                    PolicyCompareRecord(
                        replay_id=str(item.get("spot_id", item.get("timestamp", f"runtime-{index:03d}"))),
                        spot=SpotSnapshot.from_dict(
                            {
                                "spot_id": item.get("spot_id", ""),
                                "source": "runtime_api",
                                "game_stage": str(item.get("street", "") or "").lower(),
                                "hero_cards": list(item.get("hero_cards", []) or []),
                                "board": list(item.get("board", []) or []),
                                "pot": float(item.get("pot", 0.0) or 0.0),
                                "legal_actions": list(item.get("legal_actions", []) or []),
                                "action_history": list(item.get("action_history", []) or []),
                            }
                        ),
                        policy_actions=policy_actions,
                        ev_by_action=BotAPI._extract_ev_by_action(item),
                        tags=("runtime_api", str(item.get("street", "")).strip().lower() or "unknown"),
                        metadata={
                            "timestamp": item.get("timestamp"),
                            "source": item.get("source"),
                        },
                    )
                )

            if not records:
                return BotAPI._build_empty_policy_compare_summary()

            summary = build_policy_compare_summary(records)
            pairwise = list(summary.get("pairwise", []) or [])
            comparable_records = [
                item
                for item in decisions or []
                if isinstance(item, dict) and len(BotAPI._extract_policy_actions(item)) >= 2
            ]
            total_comparable = len(comparable_records)
            total_pair_samples = sum(int(item.get("comparable_records", 0) or 0) for item in pairwise)
            agreement_count = 0
            for item in comparable_records:
                policy_actions = BotAPI._extract_policy_actions(item)
                if len(set(policy_actions.values())) == 1:
                    agreement_count += 1
            ev_coverage_count = sum(
                int(round(float(item.get("ev_coverage_rate", 0.0) or 0.0) * int(item.get("comparable_records", 0) or 0)))
                for item in pairwise
            )
            policy_counts: dict[str, int] = {}
            street_counts: dict[str, int] = {}
            source_counts: dict[str, int] = {}
            for item in decisions or []:
                if not isinstance(item, dict):
                    continue
                extracted_actions = BotAPI._extract_policy_actions(item)
                if len(extracted_actions) < 2:
                    continue
                street = str(item.get("street", "UNKNOWN") or "UNKNOWN").strip().upper() or "UNKNOWN"
                street_counts[street] = street_counts.get(street, 0) + 1
                source = BotAPI._policy_slug(item.get("source"), "runtime")
                source_counts[source] = source_counts.get(source, 0) + 1
                for policy in extracted_actions:
                    policy_counts[policy] = policy_counts.get(policy, 0) + 1

            comparisons = []
            for item in pairwise[:6]:
                key = (
                    str(item.get("baseline_policy", "") or ""),
                    str(item.get("challenger_policy", "") or ""),
                )
                example_summary = pair_examples.get(
                    key,
                    {"sample_ids": [], "spot_examples": [], "divergence_examples": []},
                )
                top_action_pairs = [
                    {"actions": action_pair, "count": count}
                    for action_pair, count in list((item.get("action_pair_counts", {}) or {}).items())[:3]
                ]
                comparisons.append(
                    {
                        "baseline_policy": item.get("baseline_policy"),
                        "challenger_policy": item.get("challenger_policy"),
                        "sample_count": int(item.get("comparable_records", 0) or 0),
                        "agreement_count": int(item.get("agreements", 0) or 0),
                        "disagreement_count": int(item.get("disagreements", 0) or 0),
                        "agreement_rate": float(item.get("agreement_rate", 0.0) or 0.0),
                        "ev_coverage_count": int(round(float(item.get("ev_coverage_rate", 0.0) or 0.0) * int(item.get("comparable_records", 0) or 0))),
                        "ev_coverage_rate": float(item.get("ev_coverage_rate", 0.0) or 0.0),
                        "challenger_ev_delta": float(item.get("challenger_ev_delta", 0.0) or 0.0),
                        "sample_ids": list(example_summary.get("sample_ids", [])),
                        "top_action_pairs": top_action_pairs,
                        "top_spots": BotAPI._compact_policy_compare_examples(example_summary.get("spot_examples", [])),
                        "divergence_examples": BotAPI._compact_policy_compare_examples(
                            example_summary.get("divergence_examples", []),
                        ),
                    }
                )

            most_compared = comparisons[0] if comparisons else None
            most_divergent = min(
                comparisons,
                key=lambda item: (item["agreement_rate"], -item["sample_count"], item["baseline_policy"], item["challenger_policy"]),
            ) if comparisons else None
            top_spots = sorted(
                spot_counts.values(),
                key=lambda entry: (-entry["sample_count"], entry["spot_id"]),
            )[:3]
            return {
                "sample_count": len(comparable_records),
                "comparable_count": total_comparable,
                "agreement_count": agreement_count,
                "disagreement_count": total_comparable - agreement_count,
                "agreement_rate": round(agreement_count / total_comparable, 4) if total_comparable else 0.0,
                "changed_action_count": total_comparable - agreement_count,
                "changed_action_rate": round((total_comparable - agreement_count) / total_comparable, 4) if total_comparable else 0.0,
                "ev_coverage_count": ev_coverage_count,
                "ev_coverage_rate": round(ev_coverage_count / total_pair_samples, 4) if total_pair_samples else 0.0,
                "policies": list(summary.get("available_policies", []) or []),
                "policy_counts": {policy: policy_counts[policy] for policy in sorted(policy_counts)},
                "street_counts": {street: street_counts[street] for street in sorted(street_counts)},
                "source_counts": {name: source_counts[name] for name in sorted(source_counts)},
                "comparisons": comparisons,
                "highlights": {
                    "most_compared_pair": None if not most_compared else {
                        "baseline_policy": most_compared["baseline_policy"],
                        "challenger_policy": most_compared["challenger_policy"],
                        "sample_count": most_compared["sample_count"],
                        "sample_ids": list(most_compared.get("sample_ids", [])),
                        "top_spots": list(most_compared.get("top_spots", [])),
                    },
                    "most_divergent_pair": None if not most_divergent else {
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
                },
            }
        except Exception:
            return BotAPI._build_empty_policy_compare_summary()

    def _build_runtime_history_payload(self, kind: str = 'all', limit: int = 10, source: str = 'combined') -> dict:
        runtime = self.runtime_status_provider() if self.runtime_status_provider else {}
        runtime = runtime or {}
        history = runtime.get("history", {}) or {}
        summary = runtime.get("history_summary", {}) or {}
        selected_history = self._select_history_entries(history, source)

        events = self._slice_history_entries(selected_history.get("events", []), limit)
        decisions = self._slice_history_entries(selected_history.get("decisions", []), limit)
        incidents = self._slice_history_entries(selected_history.get("incidents", []), limit)
        metrics_entries = self._slice_history_entries(selected_history.get("metrics", []), limit)
        runtime_counts = self._build_history_counts({
            "events": history.get("events", []),
            "decisions": history.get("decisions", []),
            "incidents": history.get("incidents", []),
            "metrics": history.get("metrics", []),
        })
        persisted_counts = self._build_history_counts(history.get("persisted", {}) or {})
        runtime_timestamps = self._build_history_timestamps({
            "events": history.get("events", []),
            "decisions": history.get("decisions", []),
            "incidents": history.get("incidents", []),
            "metrics": history.get("metrics", []),
        })
        persisted_timestamps = self._build_history_timestamps(history.get("persisted", {}) or {})
        selected_counts = runtime_counts if source == "runtime" else persisted_counts if source == "persisted" else {
            "event_count": int(summary.get("event_count", runtime_counts["event_count"])),
            "decision_count": int(summary.get("decision_count", runtime_counts["decision_count"])),
            "incident_count": int(summary.get("incident_count", runtime_counts["incident_count"])),
            "metrics_count": int(summary.get("metrics_count", runtime_counts["metrics_count"])),
        }
        selected_timestamps = runtime_timestamps if source == "runtime" else persisted_timestamps if source == "persisted" else {
            "latest_event_at": summary.get("latest_event_at"),
            "latest_decision_at": summary.get("latest_decision_at"),
            "latest_incident_at": summary.get("latest_incident_at"),
            "latest_metrics_at": summary.get("latest_metrics_at"),
        }
        policy_compare_summary = self._select_policy_compare_summary(summary, source)
        if not policy_compare_summary:
            policy_compare_summary = self._build_policy_compare_summary_from_records(
                selected_history.get("decisions", [])
            )

        payload = {
            "kind": kind,
            "limit": limit,
            "source": source,
            "summary": {
                "event_count": selected_counts["event_count"],
                "decision_count": selected_counts["decision_count"],
                "incident_count": selected_counts["incident_count"],
                "metrics_count": selected_counts["metrics_count"],
                "latest_event_at": selected_timestamps["latest_event_at"],
                "latest_decision_at": selected_timestamps["latest_decision_at"],
                "latest_incident_at": selected_timestamps["latest_incident_at"],
                "latest_metrics_at": selected_timestamps["latest_metrics_at"],
                "persistence": summary.get("persistence", {}),
                "rl_ab": self._select_ab_summary(summary, source) or self._build_empty_ab_summary(),
                "policy_compare": policy_compare_summary or self._build_empty_policy_compare_summary(),
                "sources": {
                    "runtime": {
                        **runtime_counts,
                        **runtime_timestamps,
                    },
                    "persisted": {
                        **persisted_counts,
                        **persisted_timestamps,
                    },
                },
            },
            "refreshed_at": self._now_iso(),
        }

        if kind == 'events':
            payload["entries"] = events
        elif kind == 'decisions':
            payload["entries"] = decisions
        elif kind == 'incidents':
            payload["entries"] = incidents
        elif kind == 'metrics':
            payload["entries"] = metrics_entries
        else:
            payload["events"] = events
            payload["decisions"] = decisions
            payload["incidents"] = incidents
            payload["metrics"] = metrics_entries
            if source == 'combined':
                payload["persisted"] = self._runtime_persistence_payload(history, limit)

        return payload

    @staticmethod
    def _runtime_players(canonical_spot: dict) -> list[dict]:
        players = canonical_spot.get("players", []) if isinstance(canonical_spot, dict) else []
        return [dict(player) for player in players if isinstance(player, dict)]

    @classmethod
    def _runtime_hero_and_villains(cls, canonical_spot: dict) -> tuple[Optional[dict], list[dict]]:
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
    def _runtime_effective_stack(hero_player: Optional[dict], villains: list[dict]) -> float:
        hero_stack = BotAPI._safe_float((hero_player or {}).get("stack"))
        villain_stacks = [
            stack
            for stack in (BotAPI._safe_float(player.get("stack")) for player in villains)
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
    def _runtime_hero_position(hero_player: Optional[dict], villains: list[dict], tracker: dict) -> Optional[str]:
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
        metrics = runtime.get("metrics", {}) or {}
        history = runtime.get("history", {}) or {}
        history_summary = runtime.get("history_summary", {}) or {}
        persistence = history_summary.get("persistence", {}) or {}
        operator = runtime.get("operator", {}) or {}
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
                "metrics": metrics,
            },
            "tracker": tracker,
            "gate": gate,
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
                "shadow_mode_enabled": bool(operator.get("shadow_mode_enabled", False)),
                "manual_override_enabled": bool(operator.get("manual_override_enabled", False)),
                "paused": bool(operator.get("paused", False)),
                "status": str(operator.get("status") or ("ready" if runtime.get("is_running") else "offline")),
            },
            "warnings": warnings,
            "notes": [event.get("message", "") for event in history.get("events", [])[:5] if isinstance(event, dict)],
            "history": self._build_runtime_history_payload(limit=5),
            "refreshed_at": self._now_iso(),
        }

    def _setup_cors(self):
        # Configuration CORS très permissive pour autoriser le frontend Tauri/React local
        cors = aiohttp_cors.setup(self.app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
        })
        for route in list(self.app.router.routes()):
            cors.add(route)

    async def handle_get_status(self, request):
        """
        L'interface GUI interroge cette route toutes les secondes.
        Renvoie l'état actuel du bot (en train de jouer, bloqué, ou prêt à être ré-entraîné).
        """
        response_data = {
            "status": "playing",
            "ready_for_training": self.hitl.check_convergence(),
            "collected_samples": self.hitl.annotations_count,
            "target_samples": self.hitl.target_dataset_size
        }

        if self.runtime_status_provider:
            try:
                runtime = self.runtime_status_provider() or {}
                response_data["runtime"] = runtime
                response_data["tracker"] = runtime.get("tracker", {}) or {}
                response_data["gate"] = runtime.get("gate", {}) or {}
                response_data["decision"] = runtime.get("decision", {}) or {}
                response_data["operator"] = runtime.get("operator", {}) or {}
            except Exception as e:
                logger.error(f"Erreur lors de la lecture du runtime status: {e}")
                response_data["runtime"] = {
                    "gate": {
                        "allowed": False,
                        "status": "error",
                        "reasons": [{"code": "RUNTIME_STATUS_ERROR", "message": str(e), "context": {}}],
                        "action_intent": None,
                    }
                }
                response_data["tracker"] = {}
                response_data["gate"] = response_data["runtime"]["gate"]
                response_data["decision"] = {}
                response_data["operator"] = {}

        if self.hitl.is_waiting_for_human and self.hitl.current_issue:
            response_data["status"] = "waiting_for_human"
            response_data["issue"] = {
                "type": self.hitl.current_issue["type"],
                "reason": self.hitl.current_issue["reason"],
                "image_base64": self.hitl.current_issue["image_base64"],
                "width": self.hitl.current_issue["width"],
                "height": self.hitl.current_issue["height"]
            }

        return web.json_response(response_data)

    async def handle_runtime_snapshot(self, request):
        try:
            return web.json_response(self._build_runtime_snapshot_payload())
        except Exception as e:
            logger.error(f"Erreur lors de la construction du runtime snapshot: {e}")
            return web.json_response({"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500)

    async def handle_operator_control(self, request):
        if self.runtime_operator_handler is None:
            return web.json_response(
                {"state": "error", "message": "Operator controls are unavailable.", "refreshed_at": self._now_iso()},
                status=503,
            )

        try:
            payload = await request.json()
        except Exception as e:
            return web.json_response(
                {"state": "error", "message": f"Invalid operator payload: {e}", "refreshed_at": self._now_iso()},
                status=400,
            )

        if not isinstance(payload, dict):
            return web.json_response(
                {"state": "error", "message": "Operator payload must be a JSON object.", "refreshed_at": self._now_iso()},
                status=400,
            )

        operator_patch = payload.get("operator") if isinstance(payload.get("operator"), dict) else payload
        try:
            self.runtime_operator_handler(dict(operator_patch))
            return web.json_response(self._build_runtime_snapshot_payload())
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des contrôles opérateur: {e}")
            return web.json_response(
                {"state": "error", "message": str(e), "refreshed_at": self._now_iso()},
                status=500,
            )

    async def handle_runtime_history(self, request):
        try:
            kind = str(request.query.get('kind', 'all') or 'all').lower()
            if kind not in {'all', 'events', 'decisions', 'incidents', 'metrics'}:
                kind = 'all'
            limit = self._parse_limit(request.query.get('limit'), default=10, maximum=50)
            source = self._parse_history_source(request.query.get('source') or request.query.get('mode'))
            return web.json_response(self._build_runtime_history_payload(kind=kind, limit=limit, source=source))
        except Exception as e:
            logger.error(f"Erreur lors de la construction du runtime history: {e}")
            return web.json_response({"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500)

    async def handle_runtime_history_export(self, request):
        store = self._get_runtime_history_store()
        if store is None:
            return web.json_response({"error": "Runtime history store unavailable.", "refreshed_at": self._now_iso()}, status=503)

        try:
            stream = self._parse_history_stream(request.query.get('stream') or request.query.get('kind'))
            export_format = str(request.query.get('format', 'bundle') or 'bundle').strip().lower()
            records = store.export_records(stream=stream)
            if export_format in {'policy_compare_batch', 'policy-compare-batch', 'corpus_batch'}:
                record_batches = store.export_record_batches(stream=stream) if hasattr(store, 'export_record_batches') else [
                    {"session_id": "current", "source_path": "", "records": records}
                ]
                payload = self._build_policy_compare_batch_payload(record_batches, stream=stream)
            elif export_format in {'policy_compare', 'policy-compare', 'corpus'}:
                payload = self._build_policy_compare_corpus_payload(records, stream=stream)
            else:
                payload = self._build_replay_bundle_payload(records, stream=stream)
            return web.Response(
                text=json.dumps(payload, ensure_ascii=True),
                content_type='application/json',
                headers={
                    'Content-Disposition': f'attachment; filename="{self._resolve_export_filename(export_format, stream)}"',
                },
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'export runtime history: {e}")
            return web.json_response({"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500)

    async def handle_runtime_history_import(self, request):
        store = self._get_runtime_history_store()
        if store is None:
            return web.json_response({"error": "Runtime history store unavailable.", "refreshed_at": self._now_iso()}, status=503)

        try:
            payload = await request.json()
        except Exception as e:
            return web.json_response({"error": f"Invalid JSON payload: {e}"}, status=400)

        try:
            from src.runtime.history_store import RuntimeHistoryStore

            payload_summary = RuntimeHistoryStore.describe_records_payload(payload)
            records = RuntimeHistoryStore.coerce_records_payload(payload)
            replace = self._parse_bool(request.query.get('replace'))
            result = store.import_records(records, replace=replace)
            summary = store.summarize()
            return web.json_response({
                "success": True,
                "contract": {
                    "name": EXPORT_CONTRACT_NAME,
                    "version": EXPORT_CONTRACT_VERSION,
                    "artifact_type": payload_summary.get("artifact_type", "records"),
                    "coerced_record_count": len(records),
                    "replace": replace,
                },
                "payload_summary": payload_summary,
                "import": result,
                "persistence": summary,
                "refreshed_at": self._now_iso(),
            })
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except Exception as e:
            logger.error(f"Erreur lors de l'import runtime history: {e}")
            return web.json_response({"state": "error", "message": str(e), "refreshed_at": self._now_iso()}, status=500)

    async def handle_resolve(self, request):
        """
        L'interface GUI envoie la réponse de l'utilisateur (les Bounding Boxes).
        Le bot enregistre la réponse et reprend la partie.
        """
        try:
            data = await request.json()
            boxes = data.get("boxes", [])
            
            if not boxes:
                return web.json_response({"error": "Aucune boîte fournie."}, status=400)
                
            if not self.hitl.is_waiting_for_human:
                return web.json_response({"error": "Le bot ne demande aucune intervention humaine actuellement."}, status=400)

            # Transmet la réponse à la logique HITL qui va débloquer le bot
            self.hitl.resolve_human_intervention(boxes)
            
            return web.json_response({"success": True, "message": "Intervention enregistrée. Le bot reprend la partie."})
            
        except Exception as e:
            logger.error(f"Erreur API lors de la résolution HITL : {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def start(self):
        """Démarre le serveur API en arrière-plan."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"API Locale démarrée sur http://{self.host}:{self.port}")

    async def stop(self):
        """Arrête le serveur proprement."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("API Locale arrêtée.")
