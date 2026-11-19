#!/usr/bin/env python
"""Audit d'un journal de décision JSONL (Phase 1.2).

Valide chaque enregistrement avec ``src.runtime.decision_log`` et affiche un
résumé (latences p50/p95/p99, taux de fallback, actions, backends). Utilisable
pour les logs de session live, les rejeux et les corpus de benchmark.

Exemples :
    python scripts/decision_log_audit.py log/decisions.jsonl
    python scripts/decision_log_audit.py log/decisions.jsonl --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.decision_log import (  # noqa: E402
    coerce_decision_record,
    load_decision_records,
    summarize_decision_records,
    validate_decision_record,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="fichier JSONL de décisions")
    parser.add_argument("--json", action="store_true", help="sortie JSON")
    parser.add_argument(
        "--max-errors",
        type=int,
        default=20,
        help="nombre maximum d'erreurs détaillées (défaut 20)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = Path(args.path)
    if not path.is_file():
        print(f"decision_log_audit: fichier introuvable: {path}", file=sys.stderr)
        return 2
    try:
        records = [coerce_decision_record(record) for record in load_decision_records(path)]
    except Exception as exc:
        print(f"decision_log_audit: lecture impossible: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    errors: list[dict[str, object]] = []
    for index, record in enumerate(records, 1):
        issues = validate_decision_record(record)
        if issues:
            errors.append({"line": index, "errors": issues})
    summary = summarize_decision_records(records)
    summary["path"] = str(path)
    summary["invalid_records"] = len(errors)

    if args.json:
        print(json.dumps({**summary, "errors": errors[: args.max_errors]},
                         ensure_ascii=False, sort_keys=True))
    else:
        print(f"journal: {path}")
        print(
            f"enregistrements: {summary['count']} "
            f"(valides {summary['valid']}, invalides {summary['invalid']})"
        )
        latency = summary["latency_ms"]
        print(
            f"latence: p50 {latency['p50']} ms, p95 {latency['p95']} ms, "
            f"p99 {latency['p99']} ms, max {latency['max']} ms"
        )
        print(
            f"fallback: {summary['fallback_count']} "
            f"({summary['fallback_rate'] * 100:.1f} %)"
        )
        print(f"actions: {summary['actions']}")
        print(f"backends: {summary['backends']}")
        for entry in errors[: args.max_errors]:
            print(f"  ligne {entry['line']}: {entry['errors']}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
