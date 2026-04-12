import json
import logging
import re
from collections import deque
from itertools import groupby
from pathlib import Path
from shutil import move
from typing import Iterable, Optional


logger = logging.getLogger("RuntimeHistoryStore")

KNOWN_STREAMS = ("events", "decisions", "incidents", "metrics")
ACTION_SHIFT_RE = re.compile(r"^\s*([A-Za-z_]+)\s*(?:->|=>|to)\s*([A-Za-z_]+)\s*$", re.IGNORECASE)
POLICY_COMPARE_BATCH_ARTIFACTS = {"policy_compare_batch", "policy_compare_corpus_batch", "review_pack"}
POLICY_COMPARE_SINGLE_ARTIFACTS = {"policy_compare_corpus"}


class RuntimeHistoryStore:
    def __init__(
        self,
        enabled: bool = True,
        file_path: str = "log/runtime_history.jsonl",
        max_size_bytes: int = 1_048_576,
        backup_count: int = 3,
        session_id: Optional[str] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.file_path = Path(file_path)
        self.max_size_bytes = max(0, int(max_size_bytes))
        self.backup_count = max(1, int(backup_count))
        self.session_id = self._normalize_session_id(session_id)
        self._write_failed = False

        if self.enabled:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, entry: dict) -> None:
        if not self.enabled:
            return

        record = {
            "stream": str(stream),
            **entry,
        }
        if self.session_id and not self._normalize_session_id(record.get("session_id")):
            record["session_id"] = self.session_id

        try:
            self._rotate_if_needed()
            with self.file_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
            self._write_failed = False
        except Exception as exc:
            if not self._write_failed:
                logger.warning("Unable to persist runtime history to %s: %s", self.file_path, exc)
            self._write_failed = True

    @staticmethod
    def _normalize_record(record: dict) -> Optional[dict]:
        if not isinstance(record, dict):
            return None

        stream = str(record.get("stream", "") or "").strip()
        if not stream:
            return None

        normalized = dict(record)
        normalized["stream"] = stream
        session_id = RuntimeHistoryStore._normalize_session_id(normalized.get("session_id"))
        if session_id:
            normalized["session_id"] = session_id
        return normalized

    @staticmethod
    def _normalize_session_id(session_id: object) -> Optional[str]:
        value = str(session_id or "").strip()
        return value or None

    def _iter_records(self) -> Iterable[dict]:
        if not self.enabled:
            return

        for path in self._record_paths():
            yield from self._iter_records_from_path(path)

    def _iter_records_from_path(self, path: Path) -> Iterable[dict]:
        if not self.enabled:
            return

        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    normalized = self._normalize_record(record)
                    if normalized is not None:
                        yield normalized
        except Exception as exc:
            logger.warning("Unable to read runtime history from %s: %s", path, exc)

    @staticmethod
    def _session_id_for_path(path: Path) -> str:
        suffixes = path.suffixes
        if suffixes[-2:] == [".bak", ".1"]:
            return "backup_1"
        if suffixes[-2:] == [".bak", ".2"]:
            return "backup_2"
        if suffixes[-2:] == [".bak", ".3"]:
            return "backup_3"
        if suffixes[-1:] == [".bak"]:
            return "backup_legacy"
        return "current"

    def _resolve_batch_session_id(self, record: dict, path: Path) -> str:
        explicit_session_id = self._normalize_session_id(record.get("session_id"))
        if explicit_session_id:
            return explicit_session_id
        return self._session_id_for_path(path)

    def _record_paths(self) -> list[Path]:
        paths = []
        for index in range(self.backup_count, 0, -1):
            backup_path = self._backup_path(index)
            if backup_path.exists():
                paths.append(backup_path)

        legacy_backup_path = self.file_path.with_suffix(self.file_path.suffix + ".bak")
        if legacy_backup_path.exists() and not self._backup_path(1).exists():
            paths.append(legacy_backup_path)

        if self.file_path.exists():
            paths.append(self.file_path)

        return paths

    def _rotate_if_needed(self) -> None:
        if self.max_size_bytes <= 0 or not self.file_path.exists():
            return

        try:
            if self.file_path.stat().st_size < self.max_size_bytes:
                return

            legacy_backup_path = self.file_path.with_suffix(self.file_path.suffix + ".bak")
            first_backup_path = self._backup_path(1)

            # Preserve an existing legacy .bak as the newest retained backup.
            if legacy_backup_path.exists() and not first_backup_path.exists():
                move(str(legacy_backup_path), str(first_backup_path))

            oldest_backup_path = self._backup_path(self.backup_count)
            if oldest_backup_path.exists():
                oldest_backup_path.unlink()

            for index in range(self.backup_count - 1, 0, -1):
                backup_path = self._backup_path(index)
                if backup_path.exists():
                    move(str(backup_path), str(self._backup_path(index + 1)))

            if legacy_backup_path.exists():
                legacy_backup_path.unlink()

            move(str(self.file_path), str(first_backup_path))
        except OSError as exc:
            logger.warning("Unable to rotate runtime history %s: %s", self.file_path, exc)

    def _backup_path(self, index: int) -> Path:
        return self.file_path.with_suffix(self.file_path.suffix + f".bak.{index}")

    def read_recent(self, stream: Optional[str] = None, limit: int = 10) -> list[dict]:
        if not self.enabled or limit <= 0:
            return []

        items: deque[dict] = deque(maxlen=limit)
        for record in self._iter_records() or ():
            if stream and record.get("stream") != stream:
                continue
            items.append(record)

        return list(reversed(items))

    def export_records(self, stream: Optional[str] = None) -> list[dict]:
        if not self.enabled:
            return []

        records = []
        for record in self._iter_records() or ():
            if stream and record.get("stream") != stream:
                continue
            records.append(record)
        return records

    def export_record_batches(self, stream: Optional[str] = None) -> list[dict]:
        if not self.enabled:
            return []

        batches = []
        for path in self._record_paths():
            records = []
            for record in self._iter_records_from_path(path) or ():
                if stream and record.get("stream") != stream:
                    continue
                records.append(record)

            if not records:
                continue

            grouped_records = []
            for session_id, session_items in groupby(
                records,
                key=lambda record: self._resolve_batch_session_id(record, path),
            ):
                session_records = list(session_items)
                if not session_records:
                    continue
                grouped_records.append(
                    {
                        "session_id": session_id,
                        "source_path": str(path),
                        "records": session_records,
                    }
                )

            batches.extend(grouped_records)

        return batches

    @staticmethod
    def _coerce_record_list(value) -> Optional[list[dict]]:
        if not isinstance(value, list):
            return None
        return value

    @staticmethod
    def _read_contract(payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        runtime_review = payload.get("runtime_review")
        if isinstance(runtime_review, dict):
            contract = runtime_review.get("contract")
            if isinstance(contract, dict):
                return {
                    **dict(contract),
                    "name": runtime_review.get("name", contract.get("name")),
                    "version": runtime_review.get("version", contract.get("version")),
                    "artifact_type": runtime_review.get("artifact_type", contract.get("artifact_type")),
                }
            if any(runtime_review.get(key) for key in ("name", "version", "artifact_type")):
                return {
                    "name": runtime_review.get("name"),
                    "version": runtime_review.get("version"),
                    "artifact_type": runtime_review.get("artifact_type"),
                }
        contract = payload.get("contract")
        if isinstance(contract, dict):
            return contract
        meta = payload.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("contract"), dict):
            return dict(meta["contract"])
        return {}

    @classmethod
    def _runtime_review_wrapper(cls, payload: dict) -> Optional[dict]:
        if not isinstance(payload, dict):
            return None
        wrapper = payload.get("runtime_review")
        if not isinstance(wrapper, dict):
            return None
        artifact = wrapper.get("artifact")
        if not isinstance(artifact, dict):
            return None
        return wrapper

    @classmethod
    def _runtime_review_artifact_type(cls, payload: dict) -> Optional[str]:
        wrapper = cls._runtime_review_wrapper(payload)
        if not isinstance(wrapper, dict):
            return None
        value = wrapper.get("artifact_type") or cls._read_contract(wrapper).get("artifact_type")
        normalized = str(value or "").strip().lower()
        return normalized or None

    @classmethod
    def _artifact_candidates(cls, payload: dict) -> tuple[str, ...]:
        if not isinstance(payload, dict):
            return ()
        contract = cls._read_contract(payload)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        candidates = [
            payload.get("kind"),
            payload.get("artifact_type"),
            (cls._runtime_review_wrapper(payload) or {}).get("artifact_type"),
            contract.get("artifact_type"),
            meta.get("artifact_type"),
            meta.get("kind"),
        ]
        return tuple(str(value or "").strip().lower() for value in candidates if str(value or "").strip())

    @staticmethod
    def _normalize_string(value: object) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _safe_float(value: object) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_actions_from_shift(cls, value: object) -> tuple[Optional[str], Optional[str]]:
        text = cls._normalize_string(value)
        if not text:
            return None, None
        match = ACTION_SHIFT_RE.match(text)
        if not match:
            return None, None
        return match.group(1).upper(), match.group(2).upper()

    @classmethod
    def _coerce_records_from_sessions(cls, sessions) -> Optional[list[dict]]:
        if not isinstance(sessions, list):
            return None

        records: list[dict] = []
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_records = cls._coerce_record_list(session.get("records"))
            if session_records:
                records.extend(session_records)
        return records if records else None

    @classmethod
    def _coerce_records_from_review_pack_current_replay(cls, current_replay, session_id: Optional[str] = None) -> Optional[list[dict]]:
        if not isinstance(current_replay, dict):
            return None

        timeline = current_replay.get("timeline")
        selected_spot = current_replay.get("selectedSpot", current_replay.get("selected_spot"))
        entries = timeline if isinstance(timeline, list) else []
        if not entries and isinstance(selected_spot, dict):
            entries = [selected_spot]

        records: list[dict] = []
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                continue

            action = cls._normalize_string(entry.get("action"))
            timestamp = cls._normalize_string(entry.get("timestamp"))
            spot_id = cls._normalize_string(entry.get("id")) or f"review-pack-{index:03d}"
            street = cls._normalize_string(entry.get("street"))
            hero_ev = cls._safe_float(entry.get("heroEv", entry.get("hero_ev")))
            confidence = cls._normalize_string(entry.get("confidence"))
            incidents = [str(item) for item in (entry.get("incidents") or []) if str(item).strip()]
            runtime_metrics = [str(item) for item in (entry.get("runtimeMetrics", entry.get("runtime_metrics")) or []) if str(item).strip()]
            decision_trace = [str(item) for item in (entry.get("decisionTrace", entry.get("decision_trace")) or []) if str(item).strip()]
            tags = [str(item) for item in (entry.get("tags") or []) if str(item).strip()]
            canonical_spot = cls._normalize_string(entry.get("canonicalSpot", entry.get("canonical_spot")))
            gate_result = cls._normalize_string(entry.get("gateResult", entry.get("gate_result")))
            title = cls._normalize_string(entry.get("title"))
            result = cls._normalize_string(entry.get("result"))
            note = cls._normalize_string(entry.get("note"))
            chosen_action_raw = cls._normalize_string(entry.get("chosenActionRaw", entry.get("chosen_action_raw")))
            backend = cls._normalize_string(entry.get("backend"))
            cache_hit = entry.get("cacheHit", entry.get("cache_hit"))
            ev_by_action = entry.get("evByAction", entry.get("ev_by_action"))
            alternatives_payload = entry.get("solverAlternatives", entry.get("solver_alternatives", entry.get("alternatives")))

            if not any((action, timestamp, incidents, runtime_metrics, decision_trace, title, note)):
                continue

            record = {
                "stream": "decisions",
                "spot_id": spot_id,
                "source": "review_pack",
                "metadata": {
                    "review_pack_title": title,
                    "canonical_spot": canonical_spot,
                    "gate_result": gate_result,
                    "runtime_metrics": runtime_metrics,
                    "decision_trace": decision_trace,
                    "tags": tags,
                    "note": note,
                },
            }
            if session_id:
                record["session_id"] = session_id
            if timestamp:
                record["timestamp"] = timestamp
            if street:
                record["street"] = street
            if action:
                record["chosen_action"] = action.upper()
            if hero_ev is not None:
                record["ev"] = hero_ev
            if confidence:
                record["confidence"] = confidence
            if incidents:
                record["incidents"] = incidents
            if result:
                record["result"] = result

            solver_metadata = record["metadata"]
            if chosen_action_raw:
                record["chosen_action_raw"] = chosen_action_raw
                solver_metadata["chosen_action_raw"] = chosen_action_raw
            if backend:
                record["backend"] = backend
            if isinstance(cache_hit, bool):
                record["cache_hit"] = cache_hit
                solver_metadata["cache_hit"] = cache_hit
            if isinstance(ev_by_action, dict) and ev_by_action:
                record["ev_by_action"] = dict(ev_by_action)
                solver_metadata["ev_by_action"] = dict(ev_by_action)
            freq_by_action = entry.get("freqByAction", entry.get("freq_by_action"))
            if isinstance(freq_by_action, dict) and freq_by_action:
                record["freq_by_action"] = dict(freq_by_action)
                solver_metadata["freq_by_action"] = dict(freq_by_action)
            action_metadata = entry.get("actionMetadata", entry.get("action_metadata"))
            if isinstance(action_metadata, dict) and action_metadata:
                record["action_metadata"] = dict(action_metadata)
                solver_metadata["action_metadata"] = dict(action_metadata)
            backend_details = entry.get("backendDetails", entry.get("backend_details"))
            if isinstance(backend_details, dict) and backend_details:
                record["backend_details"] = dict(backend_details)
                solver_metadata["backend_details"] = dict(backend_details)
            cache_details = entry.get("cacheDetails", entry.get("cache_details"))
            if isinstance(cache_details, dict) and cache_details:
                record["cache_details"] = dict(cache_details)
                solver_metadata["cache_details"] = dict(cache_details)
            solver_warnings = entry.get("solverWarnings", entry.get("solver_warnings", entry.get("warnings")))
            if isinstance(solver_warnings, list) and solver_warnings:
                solver_metadata["warnings"] = [str(item) for item in solver_warnings if str(item).strip()]
            if isinstance(alternatives_payload, list) and alternatives_payload:
                solver_metadata["alternatives"] = [
                    dict(item) for item in alternatives_payload if isinstance(item, dict)
                ]
                solver_metadata.setdefault("alternatives_complete", list(solver_metadata["alternatives"]))

            gto_action = cls._normalize_string(entry.get("gtoAction", entry.get("gto_action")))
            if gto_action:
                record["gto_action"] = gto_action.upper()
                solver_metadata["gto_action"] = gto_action.upper()
            final_action = cls._normalize_string(entry.get("finalAction", entry.get("final_action")))
            if final_action:
                record["final_action"] = final_action.upper()
                solver_metadata["final_action"] = final_action.upper()

            baseline_action, challenger_action = cls._extract_actions_from_shift(entry.get("actionShift", entry.get("action_shift")))
            if baseline_action or challenger_action:
                record["ab_decision"] = {
                    "comparison": {
                        "rl_off": {"action": baseline_action} if baseline_action else {},
                        "rl_on": {"action": challenger_action or action or ""},
                    }
                }

            records.append(record)

        return records if records else None

    @classmethod
    def _coerce_records_from_review_pack_like_payload(cls, payload: dict) -> Optional[list[dict]]:
        if not isinstance(payload, dict):
            return None

        looks_like_review_pack = isinstance(payload.get("review_pack"), dict) or payload.get("kind") == "review_pack"
        has_review_pack_timeline = any(key in payload for key in ("currentReplay", "current_replay"))
        has_nested_review_pack_raw = isinstance(payload.get("raw"), dict) and (
            isinstance(payload.get("review_pack"), dict)
            or payload.get("kind") == "review_pack"
            or isinstance(payload["raw"].get("review_pack"), dict)
            or payload["raw"].get("kind") == "review_pack"
        )
        if not (looks_like_review_pack or has_review_pack_timeline or has_nested_review_pack_raw):
            return None

        raw = payload.get("raw")
        if isinstance(raw, dict):
            try:
                return cls.coerce_records_payload(raw)
            except ValueError:
                pass

        current_replay = payload.get("currentReplay", payload.get("current_replay"))
        session_id = cls._normalize_string(payload.get("sessionLabel", payload.get("session_label")))
        records = cls._coerce_records_from_review_pack_current_replay(current_replay, session_id=session_id)
        if records is not None:
            return records

        review_pack = payload.get("review_pack")
        if isinstance(review_pack, dict):
            raw = review_pack.get("raw")
            if isinstance(raw, dict):
                try:
                    return cls.coerce_records_payload(raw)
                except ValueError:
                    pass
            current_replay = review_pack.get("currentReplay", review_pack.get("current_replay"))
            session_id = cls._normalize_string(review_pack.get("sessionLabel", review_pack.get("session_label")))
            records = cls._coerce_records_from_review_pack_current_replay(current_replay, session_id=session_id)
            if records is not None:
                return records
        return None

    @classmethod
    def coerce_records_payload(cls, payload) -> list[dict]:
        records = cls._coerce_record_list(payload)
        if records is not None:
            return records

        if not isinstance(payload, dict):
            raise ValueError("records payload must be a list or object")

        runtime_review = cls._runtime_review_wrapper(payload)
        runtime_review_artifact_type = cls._runtime_review_artifact_type(payload)
        if isinstance(runtime_review, dict):
            artifact = runtime_review.get("artifact")
            if isinstance(artifact, dict):
                artifact_type = runtime_review_artifact_type or ""

                if artifact_type in POLICY_COMPARE_BATCH_ARTIFACTS:
                    records = cls._coerce_records_from_sessions(artifact.get("sessions"))
                    if records is not None:
                        return records
                    records = cls._coerce_record_list(artifact.get("records"))
                    if records is not None:
                        return records
                    records = cls._coerce_records_from_review_pack_like_payload(artifact)
                    if records is not None:
                        return records

                if artifact_type in {"review_session", "runtime_replay_bundle"}:
                    bundle = artifact.get("bundle")
                    if isinstance(bundle, dict):
                        records = cls._coerce_record_list(bundle.get("records"))
                        if records is not None:
                            return records
                    records = cls._coerce_record_list(artifact.get("records"))
                    if records is not None:
                        return records

                if artifact_type in POLICY_COMPARE_SINGLE_ARTIFACTS:
                    records = cls._coerce_record_list(artifact.get("records"))
                    if records is not None:
                        return records

                records = cls._coerce_records_from_sessions(artifact.get("sessions"))
                if records is not None:
                    return records
                bundle = artifact.get("bundle")
                if isinstance(bundle, dict):
                    records = cls._coerce_record_list(bundle.get("records"))
                    if records is not None:
                        return records
                records = cls._coerce_record_list(artifact.get("records"))
                if records is not None:
                    return records

        if runtime_review_artifact_type is None:
            review_session = payload.get("review_session")
            if isinstance(review_session, dict):
                bundle = review_session.get("bundle")
                if isinstance(bundle, dict):
                    records = cls._coerce_record_list(bundle.get("records"))
                    if records is not None:
                        return records
                records = cls._coerce_record_list(review_session.get("records"))
                if records is not None:
                    return records

            review_pack = payload.get("review_pack")
            if isinstance(review_pack, dict):
                records = cls._coerce_records_from_sessions(review_pack.get("sessions"))
                if records is not None:
                    return records
                records = cls._coerce_record_list(review_pack.get("records"))
                if records is not None:
                    return records

        records = cls._coerce_records_from_review_pack_like_payload(payload)
        if records is not None:
            return records

        bundle = payload.get("bundle")
        if isinstance(bundle, dict) and isinstance(bundle.get("records"), list):
            return bundle["records"]

        if set(cls._artifact_candidates(payload)) & POLICY_COMPARE_BATCH_ARTIFACTS:
            sessions_records = cls._coerce_records_from_sessions(payload.get("sessions"))
            if sessions_records is not None:
                return sessions_records

        if set(cls._artifact_candidates(payload)) & POLICY_COMPARE_SINGLE_ARTIFACTS:
            records = cls._coerce_record_list(payload.get("records"))
            if records is not None:
                return records

        sessions_records = cls._coerce_records_from_sessions(payload.get("sessions"))
        if sessions_records is not None:
            return sessions_records

        records = cls._coerce_record_list(payload.get("records"))
        if records is not None:
            return records

        raise ValueError("records payload must include a records list")

    @classmethod
    def describe_records_payload(cls, payload) -> dict:
        try:
            records = cls.coerce_records_payload(payload)
        except ValueError:
            return {
                "detected": False,
                "record_count": 0,
                "counts": {name: 0 for name in KNOWN_STREAMS},
            }

        counts = {name: 0 for name in KNOWN_STREAMS}
        for record in records:
            if not isinstance(record, dict):
                continue
            stream = str(record.get("stream", "") or "")
            if stream in counts:
                counts[stream] += 1

        artifact_type = "records"
        if isinstance(payload, dict):
            runtime_review_artifact_type = cls._runtime_review_artifact_type(payload)
            if runtime_review_artifact_type:
                artifact_type = runtime_review_artifact_type
            artifact_candidates = set(cls._artifact_candidates(payload))
            if artifact_type == "records" and (artifact_candidates & POLICY_COMPARE_BATCH_ARTIFACTS or isinstance(payload.get("review_pack"), dict) or payload.get("kind") == "review_pack"):
                artifact_type = "review_pack"
            elif artifact_type == "records" and artifact_candidates & POLICY_COMPARE_SINGLE_ARTIFACTS:
                artifact_type = "policy_compare_corpus"
            elif artifact_type == "records" and isinstance(payload.get("review_session"), dict):
                artifact_type = "review_session"
            elif artifact_type == "records" and isinstance(payload.get("bundle"), dict):
                artifact_type = "bundle"

        return {
            "detected": True,
            "artifact_type": artifact_type,
            "record_count": len(records),
            "counts": counts,
        }

    def summarize_records(self, stream: Optional[str] = None) -> dict:
        records = self.export_records(stream=stream)
        counts = {name: 0 for name in KNOWN_STREAMS}
        latest_at = {name: None for name in KNOWN_STREAMS}

        for record in records:
            bucket = str(record.get("stream", "") or "")
            if bucket not in counts:
                continue
            counts[bucket] += 1
            timestamp = record.get("timestamp")
            if latest_at[bucket] is None and timestamp:
                latest_at[bucket] = timestamp

        return {
            "stream": stream or "all",
            "record_count": len(records),
            "counts": counts,
            "latest_at": latest_at,
        }

    def import_records(self, records: list[dict], replace: bool = False) -> dict:
        if not self.enabled:
            return {
                "enabled": False,
                "imported_count": 0,
                "rejected_count": len(records) if isinstance(records, list) else 0,
                "replaced": bool(replace),
            }

        if not isinstance(records, list):
            raise ValueError("records must be a list")

        normalized_records = []
        rejected_count = 0
        for record in records:
            normalized = self._normalize_record(record)
            if normalized is None:
                rejected_count += 1
                continue
            normalized_records.append(normalized)

        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "w" if replace else "a"
        try:
            with self.file_path.open(mode, encoding="utf-8") as handle:
                for record in normalized_records:
                    handle.write(json.dumps(record, ensure_ascii=True) + "\n")
            self._write_failed = False
        except Exception as exc:
            if not self._write_failed:
                logger.warning("Unable to import runtime history into %s: %s", self.file_path, exc)
            self._write_failed = True
            raise

        return {
            "enabled": True,
            "imported_count": len(normalized_records),
            "rejected_count": rejected_count,
            "replaced": bool(replace),
        }

    def summarize(self) -> dict:
        summary = {
            "enabled": self.enabled,
            "path": str(self.file_path),
            "available": self.enabled and self.file_path.exists(),
            "write_failed": self._write_failed,
            "max_size_bytes": self.max_size_bytes,
            "backup_count": self.backup_count,
            "session_id": self.session_id,
        }

        if not summary["available"]:
            summary["size_bytes"] = 0
            return summary

        try:
            summary["size_bytes"] = self.file_path.stat().st_size
        except OSError:
            summary["size_bytes"] = 0
        return summary
