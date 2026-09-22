# -*- coding: utf-8 -*-
"""Générateur offline de blueprint (Phase 0.6.3) + audit de couverture (0.6.7).

Usage (depuis la racine du projet, venv 3.11) :

    .venv\\Scripts\\python scripts\\blueprint_gen.py generate [--format heads_up_cash]
    .venv\\Scripts\\python scripts\\blueprint_gen.py audit [--format heads_up_cash] [--strict]

``generate`` énumère les spots de ``config/blueprint_matrix.json``, les résout
en mode strict (``epsilon_target`` de la matrice, solveur natif PyO3) et
n'écrit au blueprint **que** les spots convergés (``converged=True``). Les
échecs sont listés dans ``evidence/blueprint_gen_report.json`` et jamais
écrits au blueprint (Phase 0.5.2/0.6.3).

``audit`` compare la couverture réelle du store à la matrice (Phase 0.6.7) ;
``--strict`` rend le code de sortie non nul si la couverture du format courant
est < 1.0 (bloquant go-live).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

from src.solver.blueprint_store import (  # noqa: E402
    DEFAULT_BLUEPRINT_PATH,
    BlueprintStore,
    blueprint_key,
)

DEFAULT_MATRIX_PATH = Path("config/blueprint_matrix.json")
DEFAULT_REPORT_PATH = Path("evidence/blueprint_gen_report.json")
DEFAULT_MAX_WALLCLOCK_S = 600.0  # garde-fou offline par spot (plan, ouverture 3)

STATUS_OK = 0
STATUS_COVERAGE_BELOW_TARGET = 2


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_matrix(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _native_solver():
    """Accès direct au bridge PyO3 — le live reste lookup-only, mais le
    générateur est précisément l'endroit où le solve est autorisé (offline)."""
    try:
        import postflop_solver_py
    except ImportError:
        return None, "postflop_solver_py_not_importable"
    fn = getattr(postflop_solver_py, "solve_spot_v2", None)
    if not callable(fn):
        return None, "solve_spot_v2_missing"
    return fn, ""


def _solve_spot_strict(solver_fn, spot: dict, epsilon: float) -> dict:
    """Solve un spot de la matrice en mode strict (epsilon_target)."""
    raw = solver_fn(
        hero_range=str(spot.get("hero_hand") or ""),
        villain_ranges=[str(spot.get("villain_range") or "")],
        board=list(spot.get("board") or []),
        starting_pot=float(spot.get("starting_pot") or 0.0),
        effective_stack=float(spot.get("effective_stack") or 0.0),
        legal_actions=list(spot.get("legal_actions") or []),
        spot_id=str(spot.get("spot_id") or ""),
        hero_position=str(spot.get("hero_position") or "") or None,
        action_history=list(spot.get("action_history") or []),
        num_players=int(spot.get("num_players") or 2),
        use_cache=False,
        time_budget_ms=None,
        epsilon_target=float(epsilon),
        hero_hand=str(spot.get("hero_hand") or "") or None,
        sample_mixed=False,
        random_seed=None,
        rake=float(spot.get("rake") or 0.0),
        rake_cap=float(spot.get("rake_cap") or 0.0),
    )
    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        return dict(raw.to_dict())
    if isinstance(raw, dict):
        return dict(raw)
    return {"converged": False, "fallback_reason": "unreadable_native_response"}


def run_generate(
    matrix_path: Path = DEFAULT_MATRIX_PATH,
    blueprint_path: Path = DEFAULT_BLUEPRINT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    *,
    fmt: str | None = None,
    epsilon: float | None = None,
    max_wallclock_s: float = DEFAULT_MAX_WALLCLOCK_S,
    solver_fn=None,
) -> dict:
    """Génère le blueprint pour les spots de la matrice (ou d'un format)."""
    started = time.monotonic()
    matrix = _load_matrix(matrix_path)
    epsilon = float(epsilon if epsilon is not None else matrix.get("epsilon_target", 0.001))
    store = BlueprintStore(blueprint_path)
    if solver_fn is None:
        solver_fn, solver_err = _native_solver()
    else:
        solver_err = ""

    summary = {
        "started_at": _utc_now(),
        "matrix": str(matrix_path),
        "blueprint": str(blueprint_path),
        "epsilon_target": epsilon,
        "solver_available": solver_fn is not None,
        "solver_error": solver_err,
        "written": 0,
        "refused_non_converged": 0,
        "errors": [],
        "misses": [],
    }
    if solver_fn is None:
        _write_report(report_path, summary)
        return summary

    for fmt_name, fmt_cfg in (matrix.get("formats") or {}).items():
        if fmt and fmt_name != fmt:
            continue
        for spot in fmt_cfg.get("spots") or []:
            spot_started = time.monotonic()
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
            if store.lookup(key) is not None:
                continue  # déjà convergé en base
            if (time.monotonic() - started) > max_wallclock_s:
                summary["errors"].append(
                    {"format": fmt_name, "error": "max_wallclock_reached — generation stoppée"}
                )
                _write_report(report_path, summary)
                return summary
            try:
                response = _solve_spot_strict(solver_fn, spot, epsilon)
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(
                    {"format": fmt_name, "spot_id": spot.get("spot_id"), "error": str(exc)}
                )
                continue
            if not response.get("converged"):
                # Jamais de spot à moitié convergé dans le blueprint (0.5.2).
                summary["refused_non_converged"] += 1
                summary["misses"].append(
                    {
                        "format": fmt_name,
                        "spot_id": spot.get("spot_id"),
                        "key": key,
                        "fallback_reason": response.get("fallback_reason"),
                        "exploitability": response.get("exploitability"),
                    }
                )
                continue
            entry = {
                "key": key,
                "format": fmt_name,
                "spot": spot,
                "epsilon": epsilon,
                "converged": True,
                "exploitability": response.get("exploitability"),
                "response": response,
            }
            if store.append(entry):
                summary["written"] += 1
            _ = spot_started  # conservé pour instrumentation future

    _write_report(report_path, summary)
    return summary


def _write_report(report_path: Path, summary: dict) -> None:
    summary["finished_at"] = _utc_now()
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def run_audit(
    matrix_path: Path = DEFAULT_MATRIX_PATH,
    blueprint_path: Path = DEFAULT_BLUEPRINT_PATH,
    *,
    fmt: str | None = None,
) -> dict:
    """Rapport de couverture réelle vs matrice (Phase 0.6.7)."""
    matrix = _load_matrix(matrix_path)
    store = BlueprintStore(blueprint_path)
    report = store.audit(matrix)
    report["current_format"] = fmt
    if fmt:
        fmt_report = report["formats"].get(fmt, {})
        report["current_format_coverage"] = float(fmt_report.get("coverage", 0.0))
        report["current_format_target"] = float(fmt_report.get("coverage_target", 1.0))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Génération/audit du blueprint pré-calculé.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "audit"):
        p = sub.add_parser(name)
        p.add_argument("--matrix", default=str(DEFAULT_MATRIX_PATH))
        p.add_argument("--blueprint", default=str(DEFAULT_BLUEPRINT_PATH))
        p.add_argument("--format", dest="fmt", default=None)
        if name == "generate":
            p.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
            p.add_argument("--epsilon", type=float, default=None)
            p.add_argument("--max-wallclock-s", type=float, default=DEFAULT_MAX_WALLCLOCK_S)
        if name == "audit":
            p.add_argument("--strict", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "generate":
        summary = run_generate(
            Path(args.matrix),
            Path(args.blueprint),
            Path(args.report),
            fmt=args.fmt,
            epsilon=args.epsilon,
            max_wallclock_s=args.max_wallclock_s,
        )
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        if not summary["solver_available"]:
            print(f"ERREUR: solveur natif indisponible — {summary['solver_error']}", file=sys.stderr)
            return 1
        return 0

    report = run_audit(Path(args.matrix), Path(args.blueprint), fmt=args.fmt)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if args.strict and args.fmt:
        coverage = float(report.get("current_format_coverage", 0.0))
        target = float(report.get("current_format_target", 1.0))
        if coverage < target:
            print(
                f"Couverture {args.fmt}={coverage:.3f} < cible {target} — go-live bloqué.",
                file=sys.stderr,
            )
            return STATUS_COVERAGE_BELOW_TARGET
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
