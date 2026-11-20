"""Journal de décision canonique (Phase 1.2 / 1.3).

Un enregistrement contient tout ce qu'il faut pour auditer et rejouer une
décision sans dépendre du live :

- ``request`` : le spot normalisé (cartes, board, pot, stack, actions légales,
  historique, position, confiance) ;
- ``decision`` : l'action, le backend, la source, l'EV, la confiance, la
  latence, le fallback et les incidents ;
- ``gate`` : le second avis éventuel (Jev/Djev), en mode observer ou enforcing ;
- ``solver`` : le mode et le budget effectifs ;
- ``spot_hash`` : empreinte stable du spot, calculée avec la même
  normalisation que le cache solveur ;
- ``versions`` : le registre des versions qui ont produit la décision (schéma,
  blueprint préflop, modèle de range, tailles de mise) — une version
  indisponible vaut ``None``, jamais une valeur inventée ;
- ``decision.stages_ms`` : le temps par étage quand la trace le porte.

Le module est volontairement sans dépendance lourde : il est importable par
le runtime, les scripts d'audit et les tests. Les versions dont la source peut
manquer sont résolues **à l'appel**, pas à l'import.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.runtime.stage_timing import percentile, summarize_stage_timings
from src.solver.spot_key import spot_cache_key

SCHEMA_VERSION = 1

# Source unique des schémas lisibles (FR-008) : un schéma antérieur **connu**
# est lu avec sa version au lieu d'être rejeté en bloc, un schéma inconnu reste
# une erreur. Un journal de deux ans ne doit pas devenir illisible au premier
# changement de schéma.
KNOWN_SCHEMA_VERSIONS: tuple[int, ...] = (SCHEMA_VERSION,)

SCHEMA_STATUS_CURRENT = "current"
SCHEMA_STATUS_LEGACY = "legacy"
SCHEMA_STATUS_UNKNOWN = "unknown"

VERSION_FIELDS = (
    "schema_version",
    "blueprint_version",
    "range_model_version",
    "solver_bet_sizes",
    "solver_raise_sizes",
)

REQUEST_FIELDS = (
    "hero_hand",
    "board",
    "pot",
    "effective_stack",
    "legal_actions",
    "spot_id",
    "hero_position",
    "num_players",
    "active_positions",
    "hero_player_index",
    "villain_ranges",
    "multiway_mode",
    "villain_name",
    "action_history",
    "state_confidence",
    "villain_range",
    "hero_range",
    "hero_range_size",
    "hero_range_class_count",
    "hero_range_source",
    "hero_combo",
    "degenerate_range",
)

DECISION_FIELDS = (
    "action",
    "bet_size",
    "ev",
    "source",
    "backend",
    "confidence",
    "cache_hit",
    "elapsed_ms",
    "fallback_used",
    "fallback_reason",
    "warnings",
    "incidents",
    "details",
    "converged",
    "multiway",
    "stages_ms",
)

GATE_FIELDS = (
    "allowed",
    "reason",
    "source",
    "mode",
    "latency_ms",
    "go",
    "tier",
    "risky",
)

SOLVER_FIELDS = (
    "backend",
    "mode",
    "iterations",
    "budget_ms",
    "cache_hit",
    "num_players",
    "multiway_mode",
    "converged",
    "sampled",
)

REQUIRED_REQUEST = ("hero_hand", "board", "pot", "effective_stack", "legal_actions")
REQUIRED_DECISION = ("action", "backend", "source", "elapsed_ms", "fallback_used")


def _copy_fields(source: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in fields if key in source}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def spot_hash(request: dict[str, Any]) -> str:
    """Empreinte stable du spot, indépendante du résultat de la décision."""
    return spot_cache_key(
        hero_hand=str(request.get("hero_hand") or ""),
        villain_range=str(request.get("villain_range") or ""),
        board=_as_list(request.get("board")),
        pot=float(request.get("pot") or 0.0),
        effective_stack=float(request.get("effective_stack") or 0.0),
        legal_actions=[str(item) for item in _as_list(request.get("legal_actions"))],
        spot_id=str(request.get("spot_id") or ""),
        hero_position=str(request.get("hero_position") or ""),
        action_history=[str(item) for item in _as_list(request.get("action_history"))],
        state_confidence=(
            float(request["state_confidence"])
            if request.get("state_confidence") is not None
            else None
        ),
        hero_range=str(request.get("hero_range") or ""),
        num_players=_as_int(request.get("num_players")),
        active_positions=_as_list(request.get("active_positions")),
        villain_ranges=_as_list(request.get("villain_ranges")),
        hero_player_index=_as_int(request.get("hero_player_index")),
    )


def _as_optional_text(value: Any) -> str | None:
    """Texte non vide, sinon ``None`` — jamais une chaîne vide prise pour une version."""
    text = str(value).strip() if value is not None else ""
    return text or None


def _resolve_blueprint_version() -> int | None:
    """Version du blueprint préflop, ou ``None`` si la source est indisponible."""
    try:
        from src.solver.blueprint_store import BLUEPRINT_FORMAT_VERSION
    except Exception:  # source indisponible : ``None``, jamais une version inventée
        return None
    try:
        return int(BLUEPRINT_FORMAT_VERSION)
    except (TypeError, ValueError):
        return None


def _resolve_range_model_version() -> str | None:
    """Version par défaut du modèle de range (contrats V2), ou ``None``."""
    try:
        from src.contracts.v2_contracts import RangeModelVersion
    except Exception:  # source indisponible : ``None``, jamais une version inventée
        return None
    try:
        return str(RangeModelVersion.BOARD_AWARE_V2.value)
    except Exception:
        return None


def decision_versions(
    *,
    schema_version: int | None = None,
    blueprint_version: int | None = None,
    range_model_version: str | None = None,
    solver_bet_sizes: Any = None,
    solver_raise_sizes: Any = None,
) -> dict[str, Any]:
    """Registre des versions attaché à une décision (FR-007).

    Un champ non fourni est **résolu** depuis sa source ; une source
    indisponible vaut ``None``. Une taille de mise vide vaut ``None`` : une
    chaîne vide ferait croire à une version déclarée.
    """
    return {
        "schema_version": SCHEMA_VERSION if schema_version is None else schema_version,
        "blueprint_version": (
            _resolve_blueprint_version() if blueprint_version is None else blueprint_version
        ),
        "range_model_version": (
            _resolve_range_model_version() if range_model_version is None else range_model_version
        ),
        "solver_bet_sizes": _as_optional_text(solver_bet_sizes),
        "solver_raise_sizes": _as_optional_text(solver_raise_sizes),
    }


def versions_from_decision_maker(decision_maker: Any) -> dict[str, Any]:
    """Bloc ``versions`` d'un ``DecisionMaker`` : tailles de mise réellement effectives."""
    return decision_versions(
        solver_bet_sizes=getattr(decision_maker, "solver_bet_sizes", None),
        solver_raise_sizes=getattr(decision_maker, "solver_raise_sizes", None),
    )


def build_decision_record(
    request: dict[str, Any],
    decision: dict[str, Any],
    *,
    gate: dict[str, Any] | None = None,
    solver: dict[str, Any] | None = None,
    timestamp: str | None = None,
    versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construit un enregistrement canonique, sans secret ni donnée de table."""
    request_payload = _copy_fields(request, REQUEST_FIELDS)
    decision_payload = _copy_fields(decision, DECISION_FIELDS)
    record = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp or datetime.now(UTC).isoformat(timespec="seconds"),
        "spot_hash": spot_hash(request_payload),
        "versions": dict(versions) if versions else decision_versions(),
        "request": request_payload,
        "decision": decision_payload,
        "gate": _copy_fields(gate, GATE_FIELDS) if gate else None,
        "solver": _copy_fields(solver, SOLVER_FIELDS) if solver else None,
    }
    return record


def record_from_runtime_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Convertit une trace ``live_execution._record_decision_trace``.

    La trace runtime utilise ``chosen_action``/``hero_cards``/``latency_ms`` ;
    on la ramène au format canonique sans perdre le hash déjà calculé.
    """
    metadata = trace.get("metadata") if isinstance(trace.get("metadata"), dict) else {}
    gate = trace.get("gate_result") if isinstance(trace.get("gate_result"), dict) else None
    warnings = _as_list(trace.get("warnings"))
    fallback_used = bool(
        metadata.get("fallback_used")
        or trace.get("fallback_used")
        or "fallback_used" in warnings
        or "fallback" in str(trace.get("source") or "").lower()
    )
    multiway = metadata.get("multiway") if isinstance(metadata.get("multiway"), dict) else {}
    multiway_mode = str(
        trace.get("multiway_mode") or multiway.get("mode") or ("multiway" if multiway else "")
    )
    trace_hero_player_index = trace.get("hero_player_index")
    request = {
        "hero_hand": "".join(str(card) for card in _as_list(trace.get("hero_cards"))),
        "board": _as_list(trace.get("board")),
        "pot": trace.get("pot", 0.0),
        "effective_stack": metadata.get("effective_stack", 0.0),
        "legal_actions": _as_list(trace.get("legal_actions")),
        "spot_id": trace.get("spot_id", ""),
        "hero_position": metadata.get("hero_position", ""),
        "num_players": trace.get("num_players") or multiway.get("num_players"),
        "active_positions": _as_list(
            trace.get("active_positions") or multiway.get("active_positions")
        ),
        "hero_player_index": (
            trace_hero_player_index
            if trace_hero_player_index is not None
            else multiway.get("hero_player_index")
        ),
        "villain_ranges": _as_list(trace.get("villain_ranges") or multiway.get("villain_ranges")),
        "multiway_mode": multiway_mode,
        "villain_name": metadata.get("villain_name", ""),
        "action_history": _as_list(trace.get("action_history")),
        "state_confidence": metadata.get("state_confidence"),
        "villain_range": metadata.get("villain_range", ""),
        "hero_range": metadata.get("hero_range", ""),
        "hero_range_size": metadata.get("hero_range_size"),
        "hero_range_class_count": metadata.get("hero_range_class_count"),
        "hero_range_source": metadata.get("hero_range_source", ""),
        "hero_combo": metadata.get("hero_combo", ""),
        "degenerate_range": metadata.get("degenerate_range"),
    }
    decision = {
        "action": trace.get("chosen_action", ""),
        "ev": trace.get("ev", 0.0),
        "source": trace.get("source", ""),
        "backend": trace.get("backend", ""),
        "confidence": trace.get("confidence", 0.0),
        "cache_hit": trace.get("cache_hit", False),
        "elapsed_ms": trace.get("latency_ms", 0.0),
        "fallback_used": fallback_used,
        "fallback_reason": metadata.get("fallback_reason") or trace.get("fallback_reason"),
        "warnings": warnings,
        "incidents": _as_list(trace.get("incidents")),
        "details": _as_list(trace.get("details")),
        "converged": (
            trace.get("converged")
            if trace.get("converged") is not None
            else multiway.get("converged")
        ),
        "multiway": multiway or None,
    }
    # Un étage non mesuré n'ajoute pas de clé : le journal d'un schéma antérieur
    # ne gagne pas un `stages_ms: None` qui ferait croire à une mesure absente.
    stages_ms = metadata.get("stages_ms") if isinstance(metadata, dict) else None
    if isinstance(stages_ms, dict) and stages_ms:
        decision["stages_ms"] = stages_ms
    record = build_decision_record(
        request,
        decision,
        gate=gate,
        solver=metadata.get("solver") if isinstance(metadata.get("solver"), dict) else None,
        timestamp=str(trace.get("timestamp") or "") or None,
    )
    trace_versions = trace.get("versions")
    if isinstance(trace_versions, dict) and trace_versions:
        record["versions"] = {**record["versions"], **trace_versions}
    if trace.get("spot_hash"):
        record["spot_hash"] = str(trace["spot_hash"])
    if trace.get("schema_version"):
        record["schema_version"] = int(trace["schema_version"])
    return record


def coerce_decision_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Accepte un enregistrement canonique ou une trace runtime."""
    if isinstance(payload.get("request"), dict) and isinstance(payload.get("decision"), dict):
        return payload
    if "chosen_action" in payload or "hero_cards" in payload:
        return record_from_runtime_trace(payload)
    return payload


def schema_status(record: Any) -> str:
    """``current``, ``legacy`` (connu mais antérieur) ou ``unknown``.

    Un schéma inconnu n'est jamais accepté silencieusement : il est nommé
    ``unknown`` et reste une erreur de validation.
    """
    value = record.get("schema_version") if isinstance(record, dict) else None
    try:
        version = int(value)
    except (TypeError, ValueError):
        return SCHEMA_STATUS_UNKNOWN
    if version not in KNOWN_SCHEMA_VERSIONS:
        return SCHEMA_STATUS_UNKNOWN
    return SCHEMA_STATUS_CURRENT if version == SCHEMA_VERSION else SCHEMA_STATUS_LEGACY


def _schema_errors(record: dict[str, Any]) -> list[str]:
    """Erreurs de schéma — accepte tout schéma connu, signale sa version.

    Un schéma connu (courant **ou** antérieur) ne produit aucune erreur : le
    journal d'un schéma antérieur reste lisible. Seul un schéma inconnu est une
    erreur, et le message nomme les schémas connus.
    """
    if schema_status(record) == SCHEMA_STATUS_UNKNOWN:
        return [
            f"schema_version: {record.get('schema_version')!r} inconnu "
            f"(connus : {list(KNOWN_SCHEMA_VERSIONS)})"
        ]
    return []


def validate_decision_record(record: Any) -> list[str]:
    """Retourne la liste des erreurs ; liste vide = enregistrement valide."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record: objet attendu"]
    errors.extend(_schema_errors(record))
    spot_hash_value = record.get("spot_hash")
    if not isinstance(spot_hash_value, str) or len(spot_hash_value) != 64:
        errors.append("spot_hash: SHA-256 hex attendu")
    request = record.get("request")
    decision = record.get("decision")
    if not isinstance(request, dict):
        errors.append("request: objet attendu")
        request = {}
    if not isinstance(decision, dict):
        errors.append("decision: objet attendu")
        decision = {}
    for field in REQUIRED_REQUEST:
        if request.get(field) in (None, ""):
            errors.append(f"request.{field}: valeur requise")
    for field in REQUIRED_DECISION:
        if decision.get(field) in (None, ""):
            errors.append(f"decision.{field}: valeur requise")
    for field in ("pot", "effective_stack"):
        value = request.get(field)
        if not isinstance(value, (int, float)) or float(value) < 0:
            errors.append(f"request.{field}: nombre >= 0 attendu")
    elapsed = decision.get("elapsed_ms")
    if not isinstance(elapsed, (int, float)) or float(elapsed) < 0:
        errors.append("decision.elapsed_ms: nombre >= 0 attendu")
    confidence = decision.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0
    ):
        errors.append("decision.confidence: nombre dans [0, 1] attendu")
    if not isinstance(decision.get("fallback_used"), bool):
        errors.append("decision.fallback_used: booléen attendu")
    if record.get("gate") is not None and not isinstance(record.get("gate"), dict):
        errors.append("gate: objet ou null attendu")
    if record.get("solver") is not None and not isinstance(record.get("solver"), dict):
        errors.append("solver: objet ou null attendu")
    return errors


def load_decision_records(path: str | Path) -> list[dict[str, Any]]:
    """Charge un JSONL, en ignorant les lignes vides."""
    records: list[dict[str, Any]] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"ligne non-objet dans {path}")
        records.append(payload)
    return records


def summarize_decision_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Résumé exploitable : latences, fallback, actions, backends, étages."""
    latencies: list[float] = []
    actions: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    backends: Counter[str] = Counter()
    schema_statuses: Counter[str] = Counter()
    fallback = 0
    invalid = 0
    for record in records:
        schema_statuses[schema_status(record)] += 1
        if validate_decision_record(record):
            invalid += 1
            continue
        decision = record["decision"]
        latencies.append(float(decision.get("elapsed_ms") or 0.0))
        actions[str(decision.get("action") or "?")] += 1
        sources[str(decision.get("source") or "?")] += 1
        backends[str(decision.get("backend") or "?")] += 1
        if decision.get("fallback_used"):
            fallback += 1
    ordered = sorted(latencies)
    total = len(ordered)
    return {
        "count": len(records),
        "valid": total,
        "invalid": invalid,
        "fallback_count": fallback,
        "fallback_rate": round(fallback / total, 4) if total else 0.0,
        "latency_ms": {
            "p50": round(statistics.median(ordered), 1) if ordered else 0.0,
            "p95": round(percentile(ordered, 0.95), 1),
            "p99": round(percentile(ordered, 0.99), 1),
            "max": round(ordered[-1], 1) if ordered else 0.0,
        },
        "stages_ms": summarize_stage_timings(records),
        "schema_versions": dict(schema_statuses),
        "actions": dict(actions.most_common()),
        "sources": dict(sources.most_common()),
        "backends": dict(backends.most_common()),
    }
