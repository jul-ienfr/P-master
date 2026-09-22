"""Store blueprint offline (Phase 0.6) — lookup live zero-approximation.

Le blueprint est un fichier JSONL (`config/blueprint/blueprints.jsonl`) de
spots complets résolus **à convergence mesurée** (epsilon_target, mode strict
Phase 0.5). Une entrée n'est écrite que si ``converged=True`` : jamais de
spot à moitié convergé dans la base (Phase 0.5.6).

Le lookup live (``SolverProvider`` en mode ``POKER_LIVE_LOOKUP_ONLY=1``) et
le générateur offline utilisent exactement la même clé : ``spot_cache_key``
de ``src.solver.spot_key`` (sans ``state_confidence`` ni ``epsilon`` — le
blueprint couvre le *spot*, indépendamment du bruit OCR du moment).

Génération : ``scripts/blueprint_gen.py`` (sous-commandes ``generate`` /
``audit``). Le générateur pilote le solveur natif via ``postflop_solver_py``,
donc la parité de clé Python↔Rust est garantie par construction (même helper).

Télémétrie des MISS : append-only dans ``evidence/blueprint_misses.jsonl``
(Phase 0.6.8 — backlog priorisé de la prochaine génération offline).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

from src.solver.spot_key import spot_cache_key

logger = logging.getLogger(__name__)

DEFAULT_BLUEPRINT_PATH = Path("config/blueprint/blueprints.jsonl")
DEFAULT_MISS_LOG_PATH = Path("evidence/blueprint_misses.jsonl")
BLUEPRINT_FORMAT_VERSION = 1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def blueprint_key(
    *,
    hero_hand: str,
    villain_range: str,
    board: list[str],
    pot: float,
    effective_stack: float,
    legal_actions: list[str],
    spot_id: str,
    hero_position: str,
    action_history: list[str],
    rake: float = 0.0,
) -> str:
    """Clé canonique de lookup blueprint.

    Délègue à ``spot_cache_key`` sans ``state_confidence``/``epsilon`` : le
    spot couvert par le blueprint est indépendant de la confiance OCR du
    moment (le filtrage confiance se fait en amont, via les warnings
    ``OcrLowConfidence``) et l'epsilon est une constante de la matrice
    (vérifiée à l'écriture, cf. ``BlueprintStore.append``).
    """
    return spot_cache_key(
        hero_hand=hero_hand,
        villain_range=villain_range,
        board=board,
        pot=pot,
        effective_stack=effective_stack,
        legal_actions=legal_actions,
        spot_id=spot_id,
        hero_position=hero_position,
        action_history=action_history,
        rake=rake,
    )


class BlueprintStore:
    """Index mémoire du blueprint, rechargé quand le fichier change."""

    def __init__(
        self,
        path: str | Path = DEFAULT_BLUEPRINT_PATH,
        *,
        miss_log_path: str | Path = DEFAULT_MISS_LOG_PATH,
        autoload: bool = True,
    ) -> None:
        self.path = Path(path)
        self.miss_log_path = Path(miss_log_path)
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded_mtime: float | None = None
        self._missed_keys_seen: set[str] = set()
        if autoload:
            self.load()

    # ------------------------------------------------------------------ I/O
    def load(self, *, force: bool = False) -> None:
        """Charge/recharge le fichier blueprint si son mtime a changé."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            if self._entries:
                logger.warning("Blueprint file %s disparu — store vidé.", self.path)
            self._entries = {}
            self._loaded_mtime = None
            return
        if not force and self._loaded_mtime == mtime:
            return
        entries: dict[str, dict[str, Any]] = {}
        skipped = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_no, raw in enumerate(handle, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Blueprint %s ligne %d : JSON invalide, ignorée.", self.path, line_no
                        )
                        skipped += 1
                        continue
                    # Jamais de réponse non convergée en base (Phase 0.5.6/0.6.3).
                    if not entry.get("converged"):
                        skipped += 1
                        continue
                    key = str(entry.get("key") or "")
                    if not key:
                        skipped += 1
                        continue
                    entries[key] = entry
        except OSError as exc:
            logger.error("Lecture blueprint %s impossible : %s", self.path, exc)
            return
        self._entries = entries
        self._loaded_mtime = mtime
        logger.info(
            "Blueprint chargé : %d spots convergés (%d ignorés) depuis %s",
            len(entries),
            skipped,
            self.path,
        )

    def append(self, entry: dict[str, Any]) -> bool:
        """Ajoute une entrée au fichier. Refuse toute entrée non convergée."""
        if not entry.get("converged"):
            logger.error(
                "Refus d'écriture blueprint : entrée non convergée (%s).",
                entry.get("key", "?"),
            )
            return False
        entry = dict(entry)
        entry.setdefault("format_version", BLUEPRINT_FORMAT_VERSION)
        entry.setdefault("generated_at", _utc_now())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        key = str(entry.get("key") or "")
        if key:
            self._entries[key] = entry
        # Recalcule le mtime pour ne pas déclencher un reload inutile.
        try:
            self._loaded_mtime = self.path.stat().st_mtime
        except OSError:
            self._loaded_mtime = None
        return True

    # --------------------------------------------------------------- lookup
    def lookup(self, key: str) -> dict[str, Any] | None:
        """Retourne la réponse convergée du spot, ou None (MISS)."""
        self.load()  # hot-reload si le générateur a écrit entre-temps
        entry = self._entries.get(str(key))
        if entry is None:
            return None
        response = dict(entry.get("response") or {})
        response.setdefault("cache_hit", True)
        response["backend"] = "blueprint"
        response["fallback_used"] = False
        response.setdefault("metadata", {})
        if isinstance(response["metadata"], dict):
            response["metadata"].setdefault("blueprint_key", str(key))
            response["metadata"].setdefault(
                "blueprint_generated_at", str(entry.get("generated_at", ""))
            )
        return response

    def record_miss(self, key: str, spot: dict[str, Any], *, reason: str = "miss") -> None:
        """Télémétrie append-only des spots hors blueprint (Phase 0.6.8)."""
        key = str(key)
        if key in self._missed_keys_seen:
            return
        self._missed_keys_seen.add(key)
        record = {
            "ts": _utc_now(),
            "key": key,
            "reason": reason,
            "spot": spot,
        }
        try:
            self.miss_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.miss_log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            logger.warning("Écriture télémétrie miss impossible : %s", exc)

    # ---------------------------------------------------------------- audit
    def audit(self, matrix: dict[str, Any]) -> dict[str, Any]:
        """Couverture réelle vs matrice (Phase 0.6.7).

        ``matrix`` est le contenu de ``config/blueprint_matrix.json`` ; chaque
        format y déclare ses ``spots``. Une couverture de 1.0 signifie que
        chaque spot de la matrice a une entrée convergée en base.
        """
        self.load()
        report: dict[str, Any] = {
            "generated_at": _utc_now(),
            "blueprint_path": str(self.path),
            "blueprint_entries": len(self._entries),
            "formats": {},
        }
        keys_present = set(self._entries)
        for fmt_name, fmt_cfg in (matrix.get("formats") or {}).items():
            spots = fmt_cfg.get("spots") or []
            covered: list[str] = []
            missing: list[str] = []
            for spot in spots:
                key = blueprint_key(
                    hero_hand=str(spot.get("hero_hand") or ""),
                    villain_range=str(spot.get("villain_range") or ""),
                    board=list(spot.get("board") or []),
                    pot=float(spot.get("starting_pot") or 0.0),
                    effective_stack=float(spot.get("effective_stack") or 0.0),
                    legal_actions=list(spot.get("legal_actions") or []),
                    spot_id=str(spot.get("spot_id") or ""),
                    hero_position=str(spot.get("hero_position") or ""),
                    action_history=list(spot.get("action_history") or []),
                    rake=float(spot.get("rake") or 0.0),
                )
                (covered if key in keys_present else missing).append(key)
            total = len(spots)
            report["formats"][fmt_name] = {
                "spots_total": total,
                "spots_covered": len(covered),
                "spots_missing": len(missing),
                "missing_keys": missing[:50],
                "coverage": (len(covered) / total) if total else 1.0,
                "coverage_target": float(fmt_cfg.get("coverage_target", 1.0)),
            }
        return report


_default_store: BlueprintStore | None = None


def default_blueprint_store() -> BlueprintStore:
    """Singleton du store par défaut (chemins overridables par env)."""
    global _default_store
    if _default_store is None:
        path = os.getenv("POKER_BLUEPRINT_PATH") or DEFAULT_BLUEPRINT_PATH
        miss_log = os.getenv("POKER_BLUEPRINT_MISS_LOG") or DEFAULT_MISS_LOG_PATH
        _default_store = BlueprintStore(path, miss_log_path=miss_log)
    return _default_store


def miss_log_tail(limit: int = 100, *, path: str | Path = DEFAULT_MISS_LOG_PATH) -> list[dict]:
    """Dernières lignes du log de misses (debug/audit)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
