"""Offline policy comparison helpers for replay fixtures and corpora."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from poker.decisionmaker.v2_contracts import SpotSnapshot


def _normalize_action(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip().upper()


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _policy_slug(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lower()
    return text.replace(" ", "_") or fallback


def _read_contract(payload: dict[str, Any]) -> dict[str, Any]:
    runtime_review = payload.get("runtime_review") if isinstance(payload, dict) else None
    if isinstance(runtime_review, dict):
        nested_contract = runtime_review.get("contract")
        if isinstance(nested_contract, dict):
            return {
                **nested_contract,
                "name": runtime_review.get("name", nested_contract.get("name")),
                "version": runtime_review.get("version", nested_contract.get("version")),
                "artifact_type": runtime_review.get("artifact_type", nested_contract.get("artifact_type")),
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
    if isinstance(meta, dict):
        nested_contract = meta.get("contract")
        if isinstance(nested_contract, dict):
            return nested_contract

    return {}


def _artifact_candidates(payload: dict[str, Any]) -> tuple[str, ...]:
    contract = _read_contract(payload)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    runtime_review = payload.get("runtime_review") if isinstance(payload, dict) else None
    candidates = [
        payload.get("kind"),
        payload.get("artifact_type"),
        runtime_review.get("artifact_type") if isinstance(runtime_review, dict) else None,
        contract.get("artifact_type"),
        meta.get("artifact_type"),
        meta.get("kind"),
    ]
    normalized = [str(value or "").strip().lower() for value in candidates if str(value or "").strip()]
    return tuple(normalized)


def _nested_payloads(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    nested: list[dict[str, Any]] = []
    for key in ("runtime_review", "review_pack", "review_session", "raw", "bundle"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested.append(value)
    runtime_review = payload.get("runtime_review")
    if isinstance(runtime_review, dict) and isinstance(runtime_review.get("artifact"), dict):
        nested.append(runtime_review["artifact"])
    return tuple(nested)


def _extract_runtime_review_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    wrapper = payload.get("runtime_review")
    if not isinstance(wrapper, dict):
        return None
    artifact = wrapper.get("artifact")
    if not isinstance(artifact, dict):
        return None
    artifact_type = str(wrapper.get("artifact_type") or _read_contract(wrapper).get("artifact_type") or "").strip().lower()
    if not artifact_type:
        return None
    return artifact_type, artifact


def _runtime_review_artifact_type(payload: dict[str, Any]) -> str:
    runtime_review_payload = _extract_runtime_review_payload(payload)
    if not runtime_review_payload:
        return ""
    artifact_type, _artifact = runtime_review_payload
    return artifact_type


def _matches_contract_version(value: Any, expected: str = "v1") -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text == expected or text == expected.lstrip("v")


def _payload_version_matches(payload: dict[str, Any], expected: str = "v1") -> bool:
    contract = _read_contract(payload)
    candidates = [
        payload.get("format_version"),
        payload.get("version"),
        payload.get("version_tag"),
        contract.get("version"),
        (payload.get("meta") or {}).get("version") if isinstance(payload.get("meta"), dict) else None,
        (payload.get("meta") or {}).get("version_tag") if isinstance(payload.get("meta"), dict) else None,
    ]
    if any(_matches_contract_version(value, expected) for value in candidates):
        return True

    return any(_payload_version_matches(nested, expected) for nested in _nested_payloads(payload))


def _looks_like_review_pack(payload: dict[str, Any]) -> bool:
    review_pack = payload.get("review_pack")
    if isinstance(review_pack, dict):
        return True

    candidates = set(_artifact_candidates(payload))
    return bool(candidates & {"review_pack", "policy_compare_batch", "policy_compare_corpus_batch"})


def _looks_like_review_session(payload: dict[str, Any]) -> bool:
    review_session = payload.get("review_session")
    if isinstance(review_session, dict):
        return True

    candidates = set(_artifact_candidates(payload))
    return bool(candidates & {"review_session", "policy_compare_corpus"})


def _extract_runtime_bundle_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    review_session = payload.get("review_session")
    if isinstance(review_session, dict):
        bundle = review_session.get("bundle")
        if isinstance(bundle, dict):
            return {
                **payload,
                "bundle": bundle,
            }

    if isinstance(payload.get("bundle"), dict):
        return payload

    return None


def _extract_review_pack_payload(payload: dict[str, Any]) -> dict[str, Any]:
    review_pack = payload.get("review_pack")
    if isinstance(review_pack, dict):
        return {
            **payload,
            "kind": review_pack.get("kind", payload.get("kind", "review_pack")),
            "format": review_pack.get("format", payload.get("format")),
            "format_version": review_pack.get("format_version", payload.get("format_version")),
            "version": review_pack.get("version", payload.get("version")),
            "version_tag": review_pack.get("version_tag", payload.get("version_tag")),
            "meta": review_pack.get("meta", payload.get("meta")),
            "contract": review_pack.get("contract", payload.get("contract")),
            "sessions": review_pack.get("sessions", payload.get("sessions", [])),
            "records": review_pack.get("records", payload.get("records", [])),
            "raw": review_pack.get("raw", payload.get("raw")),
            "currentReplay": review_pack.get("currentReplay", payload.get("currentReplay")),
            "current_replay": review_pack.get("current_replay", payload.get("current_replay")),
            "sessionLabel": review_pack.get("sessionLabel", payload.get("sessionLabel")),
            "session_label": review_pack.get("session_label", payload.get("session_label")),
        }
    return payload


def _resolve_review_pack_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get("review_pack"), dict):
        return _extract_review_pack_payload(payload)

    if payload.get("kind") == "review_pack" or set(_artifact_candidates(payload)) & {"review_pack", "policy_compare_batch", "policy_compare_corpus_batch"}:
        return payload

    if any(key in payload for key in ("currentReplay", "current_replay")):
        return payload

    if isinstance(payload.get("raw"), dict) and (
        payload.get("kind") == "review_pack"
        or isinstance(payload.get("review_pack"), dict)
        or set(_artifact_candidates(payload)) & {"review_pack", "policy_compare_batch", "policy_compare_corpus_batch"}
    ):
        return payload

    return None


def _records_from_review_pack_payload(payload: dict[str, Any]) -> list[PolicyCompareRecord]:
    review_pack_payload = _resolve_review_pack_payload(payload)
    if not isinstance(review_pack_payload, dict):
        return []

    records = _records_from_policy_compare_batch(review_pack_payload)
    if records:
        return records

    runtime_bundle_payload = _extract_runtime_bundle_payload(review_pack_payload.get("raw", review_pack_payload))
    if isinstance(runtime_bundle_payload, dict):
        records = _records_from_runtime_bundle(runtime_bundle_payload)
        if records:
            return records

    raw_payload = review_pack_payload.get("raw")
    if isinstance(raw_payload, dict):
        records = _records_from_frontend_review_pack(raw_payload)
        if records:
            return records

    return _records_from_frontend_review_pack(review_pack_payload)


def _extract_actions_from_shift(value: Any) -> tuple[str, str] | tuple[None, None]:
    if value in (None, ""):
        return None, None
    text = str(value).strip()
    for separator in ("->", "=>", " to "):
        if separator in text:
            left, right = text.split(separator, 1)
            baseline = _normalize_action(left)
            challenger = _normalize_action(right)
            if baseline and challenger:
                return baseline, challenger
    return None, None


def _record_from_review_pack_spot(payload: dict[str, Any], index: int, session_label: str | None = None) -> PolicyCompareRecord | None:
    if not isinstance(payload, dict):
        return None

    replay_id = str(payload.get("id", f"review-pack-{index:03d}"))
    chosen_action = _normalize_action(payload.get("action"))
    baseline_action, challenger_action = _extract_actions_from_shift(payload.get("actionShift", payload.get("action_shift")))

    policy_actions: dict[str, str] = {}
    if baseline_action:
        policy_actions["review_pack_baseline"] = baseline_action
    if challenger_action:
        policy_actions["review_pack_challenger"] = challenger_action
    elif chosen_action:
        policy_actions["review_pack_selected"] = chosen_action

    if len(policy_actions) < 2:
        return None

    hero_ev = _safe_float(payload.get("heroEv", payload.get("hero_ev")))
    ev_by_action: dict[str, float] = {}
    if chosen_action and hero_ev is not None:
        ev_by_action[chosen_action] = hero_ev

    metadata = {
        "source": "review_pack",
        "title": payload.get("title"),
        "timestamp": payload.get("timestamp"),
        "canonical_spot": payload.get("canonicalSpot", payload.get("canonical_spot")),
        "gate_result": payload.get("gateResult", payload.get("gate_result")),
        "impact_label": payload.get("impactLabel", payload.get("impact_label")),
        "session_label": session_label,
    }

    return PolicyCompareRecord(
        replay_id=replay_id,
        spot=SpotSnapshot.from_dict(
            {
                "spot_id": replay_id,
                "source": "review_pack",
                "game_stage": str(payload.get("street", "") or "").lower(),
                "metadata": metadata,
            }
        ),
        policy_actions=policy_actions,
        ev_by_action=ev_by_action,
        tags=("review_pack",),
        metadata=metadata,
    )


def _records_from_frontend_review_pack(payload: dict[str, Any]) -> list[PolicyCompareRecord]:
    if not isinstance(payload, dict):
        return []

    raw = payload.get("raw")
    if isinstance(raw, dict):
        runtime_bundle_payload = _extract_runtime_bundle_payload(raw)
        if isinstance(runtime_bundle_payload, dict):
            return _records_from_runtime_bundle(runtime_bundle_payload)

    review_pack = payload.get("review_pack")
    if isinstance(review_pack, dict):
        raw = review_pack.get("raw")
        if isinstance(raw, dict):
            runtime_bundle_payload = _extract_runtime_bundle_payload(raw)
            if isinstance(runtime_bundle_payload, dict):
                return _records_from_runtime_bundle(runtime_bundle_payload)
        payload = review_pack

    current_replay = payload.get("currentReplay", payload.get("current_replay"))
    session_label = str(payload.get("sessionLabel", payload.get("session_label", "")) or "").strip() or None
    if not isinstance(current_replay, dict):
        return []

    timeline = current_replay.get("timeline")
    selected_spot = current_replay.get("selectedSpot", current_replay.get("selected_spot"))
    entries = timeline if isinstance(timeline, list) else []
    if not entries and isinstance(selected_spot, dict):
        entries = [selected_spot]

    records: list[PolicyCompareRecord] = []
    for index, entry in enumerate(entries, start=1):
        record = _record_from_review_pack_spot(entry, index, session_label=session_label)
        if record is not None:
            records.append(record)
    return records


def _extract_runtime_policy_actions(payload: dict[str, Any]) -> dict[str, str]:
    policy_actions: dict[str, str] = {}

    chosen_action = _normalize_action(payload.get("chosen_action", payload.get("action")))
    if chosen_action:
        policy_actions[_policy_slug(payload.get("source"), "runtime")] = chosen_action

    ab_decision = dict(payload.get("ab_decision", {}) or {})
    gto_action = _normalize_action(ab_decision.get("gto_action"))
    if gto_action:
        policy_actions.setdefault("gto_solver", gto_action)

    comparison = dict(ab_decision.get("comparison", {}) or {})
    for branch in ("rl_off", "rl_on"):
        branch_action = _normalize_action((comparison.get(branch, {}) or {}).get("action"))
        if branch_action:
            policy_actions.setdefault(branch, branch_action)

    return policy_actions


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_runtime_ev_by_action(payload: dict[str, Any]) -> dict[str, float]:
    ev_by_action: dict[str, float] = {}

    def remember(action_name: Any, ev_value: Any) -> None:
        action = _normalize_action(action_name)
        ev = _safe_float(ev_value)
        if action and ev is not None and action not in ev_by_action:
            ev_by_action[action] = ev

    metadata = dict(payload.get("metadata", {}) or {})
    solver = dict(payload.get("solver", metadata.get("solver", {})) or {})
    for item in solver.get("alternatives", []) or []:
        if not isinstance(item, dict):
            continue
        remember(item.get("action", item.get("raw_action")), item.get("ev", item.get("hero_ev")))

    ab_decision = dict(payload.get("ab_decision", {}) or {})
    comparison = dict(ab_decision.get("comparison", {}) or {})
    for branch in ("rl_off", "rl_on"):
        branch_snapshot = dict(comparison.get(branch, {}) or {})
        remember(branch_snapshot.get("action"), branch_snapshot.get("ev"))

    remember(payload.get("chosen_action", payload.get("action")), payload.get("ev"))

    return ev_by_action


@dataclass
class PolicyCompareRecord:
    replay_id: str
    spot: SpotSnapshot
    policy_actions: dict[str, str]
    ev_by_action: dict[str, float] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def _record_from_policy_compare_dict(payload: dict[str, Any], index: int) -> PolicyCompareRecord:
    raw_policy_actions = payload.get("policy_actions", {}) or {}
    metadata = dict(payload.get("metadata", {}) or {})
    contract = _read_contract(payload)
    if contract and "contract" not in metadata:
        metadata["contract"] = contract
    return PolicyCompareRecord(
        replay_id=str(payload.get("replay_id", payload.get("replayId", f"corpus-{index:03d}"))),
        spot=SpotSnapshot.from_dict(payload.get("spot", {})),
        policy_actions={
            _policy_slug(key, f"policy_{offset}"): _normalize_action(value)
            for offset, (key, value) in enumerate(raw_policy_actions.items())
            if _normalize_action(value)
        },
        ev_by_action={
            _normalize_action(key): float(value)
            for key, value in dict(payload.get("ev_by_action", {}) or {}).items()
            if _normalize_action(key)
        },
        tags=tuple(str(item) for item in (payload.get("tags", ()) or ())),
        metadata=metadata,
    )


def _records_from_policy_compare_batch(payload: dict[str, Any]) -> list[PolicyCompareRecord]:
    records: list[PolicyCompareRecord] = []
    sessions = payload.get("sessions")

    if isinstance(sessions, list):
        for session in sessions:
            if not isinstance(session, dict):
                continue
            for item in session.get("records", []) or []:
                if not isinstance(item, dict):
                    continue
                records.append(_record_from_policy_compare_dict(item, len(records) + 1))
        if records:
            return records

    return [
        _record_from_policy_compare_dict(item, index)
        for index, item in enumerate(payload.get("records", []) or [], start=1)
        if isinstance(item, dict)
    ]


def _record_from_decision_fixture(payload: dict[str, Any], fixture_name: str) -> PolicyCompareRecord:
    request = dict(payload.get("request", {}) or {})
    expected = dict(payload.get("expected", {}) or {})
    solver_response = dict(payload.get("solver_response", {}) or {})
    fixture_stem = Path(fixture_name).stem
    spot = SpotSnapshot(
        spot_id=str(request.get("spot_id", fixture_stem)),
        source="decision_fixture",
        game_stage=str(request.get("street", "")).lower(),
        hero_cards=tuple(str(request.get("hero_hand", ""))[offset : offset + 2] for offset in range(0, len(str(request.get("hero_hand", ""))), 2) if str(request.get("hero_hand", ""))[offset : offset + 2]),
        board=tuple(str(card) for card in (request.get("board", []) or [])),
        hero_position=str(request.get("hero_position", "")),
        pot=float(request.get("pot", 0.0) or 0.0),
        stack=float(request.get("effective_stack", 0.0) or 0.0),
        legal_actions=tuple(_normalize_action(item) for item in (request.get("legal_actions", []) or []) if _normalize_action(item)),
        hero_range=str(request.get("hero_range", "")),
        villain_ranges=tuple(),
        state_confidence=float(request.get("state_confidence", 0.0) or 0.0),
        metadata={"fixture_name": fixture_name},
    )

    ev_by_action: dict[str, float] = {}
    hero_ev = solver_response.get("hero_ev")
    chosen_action = _normalize_action(solver_response.get("chosen_action"))
    if chosen_action and hero_ev not in (None, ""):
        ev_by_action[chosen_action] = float(hero_ev)

    for item in solver_response.get("actions", []) or []:
        action_name = _normalize_action(item.get("action"))
        if action_name and action_name not in ev_by_action:
            ev_by_action[action_name] = float(item.get("ev", 0.0) or 0.0)

    policy_actions: dict[str, str] = {}
    if chosen_action:
        policy_actions["gto_solver"] = chosen_action

    expected_action = _normalize_action(expected.get("action"))
    expected_source = _policy_slug(expected.get("source"), "expected")
    if expected_action:
        policy_actions[expected_source] = expected_action

    if payload.get("enable_validated_rl") and expected_action:
        policy_actions.setdefault("rl_validated", expected_action)

    if not policy_actions:
        policy_actions["expected"] = "NO_ACTION"

    return PolicyCompareRecord(
        replay_id=fixture_stem,
        spot=spot,
        policy_actions=policy_actions,
        ev_by_action=ev_by_action,
        tags=("decision_fixture", fixture_stem),
        metadata={
            "fixture_name": fixture_name,
            "expected_source": expected.get("source"),
            "fallback_used": bool(expected.get("fallback_used")),
        },
    )


def _spot_from_runtime_bundle(bundle: dict[str, Any], decision_record: dict[str, Any]) -> SpotSnapshot:
    runtime = dict(bundle.get("runtime", {}) or {})
    canonical_spot = dict(runtime.get("canonical_spot", {}) or {})
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
            "spot_id": decision_record.get("spot_id", canonical_spot.get("spot_id", "")),
            "source": "runtime_replay_bundle",
            "game_stage": str(decision_record.get("street", canonical_spot.get("street", canonical_spot.get("game_stage", ""))) or "").lower(),
            "hero_cards": decision_record.get("hero_cards", canonical_spot.get("hero_cards", [])),
            "board": decision_record.get("board", canonical_spot.get("board", [])),
            "hero_position": hero_position,
            "pot": decision_record.get("pot", canonical_spot.get("pot", 0.0)),
            "stack": stack or 0.0,
            "legal_actions": decision_record.get("legal_actions", canonical_spot.get("legal_actions", [])),
            "action_history": decision_record.get("action_history", canonical_spot.get("action_history", [])),
            "state_confidence": canonical_spot.get("state_confidence", 0.0),
            "metadata": {
                **metadata,
                "runtime_timestamp": decision_record.get("timestamp"),
            },
        }
    )


def _records_from_runtime_bundle(payload: dict[str, Any]) -> list[PolicyCompareRecord]:
    bundle = dict(payload.get("bundle", payload) or {})
    records: list[PolicyCompareRecord] = []

    for index, item in enumerate(bundle.get("records", []) or [], start=1):
        if not isinstance(item, dict) or str(item.get("stream", "") or "") != "decisions":
            continue

        policy_actions = _extract_runtime_policy_actions(item)
        if not policy_actions:
            continue

        replay_id = str(item.get("spot_id", item.get("timestamp", f"runtime-{index:03d}")))
        records.append(
            PolicyCompareRecord(
                replay_id=replay_id,
                spot=_spot_from_runtime_bundle(bundle, item),
                policy_actions=policy_actions,
                ev_by_action=_extract_runtime_ev_by_action(item),
                tags=("runtime_replay_bundle", str(item.get("street", "")).strip().lower() or "unknown"),
                metadata={
                    "timestamp": item.get("timestamp"),
                    "stream": item.get("stream"),
                    "confidence": item.get("confidence"),
                    "latency_ms": item.get("latency_ms"),
                    "warnings": list(item.get("warnings", []) or []),
                    "incidents": list(item.get("incidents", []) or []),
                },
            )
        )

    return records


def load_policy_compare_records(input_path: str | Path) -> list[PolicyCompareRecord]:
    path = Path(input_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    runtime_review_payload = _extract_runtime_review_payload(payload) if isinstance(payload, dict) else None
    if runtime_review_payload and _payload_version_matches(payload):
        artifact_type, artifact = runtime_review_payload
        if artifact_type == "policy_compare_corpus":
            return [
                _record_from_policy_compare_dict(item, index)
                for index, item in enumerate(artifact.get("records", []) or [], start=1)
                if isinstance(item, dict)
            ]
        if artifact_type in {"policy_compare_batch", "review_pack", "policy_compare_corpus_batch"}:
            batch_payload = {"sessions": artifact.get("sessions", []), "records": artifact.get("records", [])}
            records = _records_from_policy_compare_batch(batch_payload)
            if records:
                return records
            records = _records_from_review_pack_payload(artifact)
            if records:
                return records
            raw_payload = artifact.get("raw")
            if isinstance(raw_payload, dict):
                records = _records_from_review_pack_payload(raw_payload)
                if records:
                    return records
        if artifact_type == "review_session":
            runtime_bundle_payload = _extract_runtime_bundle_payload(artifact)
            if isinstance(runtime_bundle_payload, dict):
                return _records_from_runtime_bundle(runtime_bundle_payload)
            if isinstance(artifact.get("bundle"), dict):
                return _records_from_runtime_bundle(artifact)

    runtime_review_artifact_type = _runtime_review_artifact_type(payload) if isinstance(payload, dict) else ""

    if isinstance(payload, dict) and not runtime_review_artifact_type and "policy_compare_corpus" in _artifact_candidates(payload):
        return [
            _record_from_policy_compare_dict(item, index)
            for index, item in enumerate(payload.get("records", []) or [], start=1)
        ]

    if isinstance(payload, dict) and not runtime_review_artifact_type and isinstance(payload.get("records"), list):
        direct_records = [
            _record_from_policy_compare_dict(item, index)
            for index, item in enumerate(payload.get("records", []) or [], start=1)
            if isinstance(item, dict) and isinstance(item.get("policy_actions"), dict)
        ]
        if direct_records:
            return direct_records

    if isinstance(payload, dict) and not runtime_review_artifact_type and set(_artifact_candidates(payload)) & {"policy_compare_batch", "policy_compare_corpus_batch"}:
        return _records_from_policy_compare_batch(payload)

    if isinstance(payload, dict) and not runtime_review_artifact_type and _looks_like_review_pack(payload) and _payload_version_matches(payload):
        records = _records_from_review_pack_payload(payload)
        if records:
            return records

    runtime_bundle_payload = _extract_runtime_bundle_payload(payload) if isinstance(payload, dict) else None
    if isinstance(runtime_bundle_payload, dict) and not runtime_review_artifact_type and (
        runtime_bundle_payload.get("kind") == "runtime_replay_bundle"
        or (_looks_like_review_session(runtime_bundle_payload) and _payload_version_matches(runtime_bundle_payload))
        or (
            runtime_bundle_payload.get("format") == "runtime_history_v1"
            and isinstance(runtime_bundle_payload.get("bundle"), dict)
        )
        or (
            isinstance(runtime_bundle_payload.get("bundle"), dict)
            and runtime_bundle_payload.get("bundle", {}).get("kind") == "runtime_replay_bundle"
        )
    ):
        return _records_from_runtime_bundle(runtime_bundle_payload)

    if isinstance(payload, dict) and (
        payload.get("kind") == "runtime_replay_bundle"
        or (payload.get("format") == "runtime_history_v1" and isinstance(payload.get("bundle"), dict))
        or (isinstance(payload.get("bundle"), dict) and payload.get("bundle", {}).get("kind") == "runtime_replay_bundle")
    ):
        return _records_from_runtime_bundle(payload)

    if isinstance(payload, dict) and not runtime_review_artifact_type and (
        payload.get("kind") == "review_pack"
        or "currentReplay" in payload
        or "current_replay" in payload
    ):
        records = _records_from_review_pack_payload(payload)
        if records:
            return records

    if isinstance(payload, dict) and "request" in payload and "expected" in payload:
        return [_record_from_decision_fixture(payload, path.name)]

    raise ValueError(f"unsupported comparison input format: {path}")


def load_policy_compare_corpus(paths: list[str | Path] | tuple[str | Path, ...]) -> list[PolicyCompareRecord]:
    records: list[PolicyCompareRecord] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            for child in sorted(path.glob("*.json")):
                records.extend(load_policy_compare_records(child))
            continue
        records.extend(load_policy_compare_records(path))
    return records


def discover_policies(records: list[PolicyCompareRecord] | tuple[PolicyCompareRecord, ...]) -> list[str]:
    return sorted({policy for record in records for policy in record.policy_actions})


def summarize_policy_matchup(
    records: list[PolicyCompareRecord] | tuple[PolicyCompareRecord, ...],
    *,
    baseline_policy: str,
    challenger_policy: str,
) -> dict[str, Any]:
    comparable_records = 0
    agreements = 0
    baseline_illegal = 0
    challenger_illegal = 0
    baseline_ev_sum = 0.0
    challenger_ev_sum = 0.0
    ev_samples = 0
    differing_samples: list[dict[str, Any]] = []
    action_pair_counts: dict[str, int] = {}

    for record in records:
        baseline_action = _normalize_action(record.policy_actions.get(baseline_policy))
        challenger_action = _normalize_action(record.policy_actions.get(challenger_policy))
        if not baseline_action or not challenger_action:
            continue

        comparable_records += 1
        legal_actions = {_normalize_action(item) for item in record.spot.legal_actions}
        if legal_actions and baseline_action not in legal_actions:
            baseline_illegal += 1
        if legal_actions and challenger_action not in legal_actions:
            challenger_illegal += 1

        if baseline_action == challenger_action:
            agreements += 1

        pair_key = f"{baseline_action}->{challenger_action}"
        action_pair_counts[pair_key] = action_pair_counts.get(pair_key, 0) + 1

        baseline_ev = record.ev_by_action.get(baseline_action)
        challenger_ev = record.ev_by_action.get(challenger_action)
        if baseline_ev is not None and challenger_ev is not None:
            baseline_ev_sum += float(baseline_ev)
            challenger_ev_sum += float(challenger_ev)
            ev_samples += 1

        if baseline_action != challenger_action and len(differing_samples) < 12:
            differing_samples.append(
                {
                    "replay_id": record.replay_id,
                    "spot_id": record.spot.spot_id,
                    "baseline_action": baseline_action,
                    "challenger_action": challenger_action,
                    "legal_actions": list(record.spot.legal_actions),
                    "baseline_ev": baseline_ev,
                    "challenger_ev": challenger_ev,
                    "tags": list(record.tags),
                }
            )

    return {
        "kind": "policy_matchup",
        "baseline_policy": baseline_policy,
        "challenger_policy": challenger_policy,
        "records": len(records),
        "comparable_records": comparable_records,
        "agreements": agreements,
        "disagreements": comparable_records - agreements,
        "agreement_rate": _safe_ratio(agreements, comparable_records),
        "baseline_illegal_actions": baseline_illegal,
        "challenger_illegal_actions": challenger_illegal,
        "baseline_ev_sum": round(baseline_ev_sum, 4),
        "challenger_ev_sum": round(challenger_ev_sum, 4),
        "challenger_ev_delta": round(challenger_ev_sum - baseline_ev_sum, 4),
        "ev_coverage_rate": _safe_ratio(ev_samples, comparable_records),
        "action_pair_counts": dict(sorted(action_pair_counts.items(), key=lambda item: (-item[1], item[0]))),
        "differing_samples": differing_samples,
    }


def build_policy_compare_summary(
    records: list[PolicyCompareRecord] | tuple[PolicyCompareRecord, ...],
    *,
    baseline_policy: str | None = None,
    challenger_policy: str | None = None,
) -> dict[str, Any]:
    available_policies = discover_policies(records)
    pairwise: list[dict[str, Any]] = []

    if baseline_policy and challenger_policy:
        pairwise.append(
            summarize_policy_matchup(
                records,
                baseline_policy=baseline_policy,
                challenger_policy=challenger_policy,
            )
        )
    else:
        for index, policy in enumerate(available_policies):
            for challenger in available_policies[index + 1 :]:
                pairwise.append(
                    summarize_policy_matchup(
                        records,
                        baseline_policy=policy,
                        challenger_policy=challenger,
                    )
                )

    return {
        "kind": "policy_compare_summary",
        "records": len(records),
        "available_policies": available_policies,
        "pairwise": pairwise,
    }


def write_policy_compare_summary(
    input_paths: list[str | Path] | tuple[str | Path, ...],
    output_path: str | Path,
    *,
    baseline_policy: str | None = None,
    challenger_policy: str | None = None,
) -> Path:
    records = load_policy_compare_corpus(input_paths)
    payload = build_policy_compare_summary(
        records,
        baseline_policy=baseline_policy,
        challenger_policy=challenger_policy,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
