# -*- coding: utf-8 -*-
"""Étude de calibration de la quantification des mises (Phase 0.7.2).

Entrées :
- ``evidence/bet_observations.jsonl`` (logger ``src/runtime/bet_logger.py``)

Sorties :
- ``docs/bet_tolerance_report.md`` : histogramme des mises observées par
  street, masse de refus par (menu, tolérance) candidats, recommandation.

Protocole ΔEV (coût d'abstraction) : pour les tailles récurrentes, le coût de
quantification se mesure en résolvant le spot avec la taille exacte puis avec
le nœud du menu (même arbre). Sans observations exploitables *avec contexte de
spot complet*, cette section reste « non exécutée » et le rapport dit
explicitement que les constantes restent PROVISOIRES — jamais de chiffre
inventé.

Usage :
    .venv\\Scripts\\python research\\bet_tolerance_study.py \
        [--obs evidence/bet_observations.jsonl] [--out docs/bet_tolerance_report.md]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from datetime import UTC, datetime
except ImportError:  # Python 3.10 compatibility
    from datetime import datetime, timezone

    UTC = timezone.utc  # type: ignore[no-redef]  # noqa: UP017 - 3.10 compat fallback

DEFAULT_OBS_PATH = Path("evidence/bet_observations.jsonl")
DEFAULT_OUT_PATH = Path("docs/bet_tolerance_report.md")

CANDIDATE_MENUS = {
    "compact": (0.33, 0.66, 1.0),
    "standard (défaut provisoire)": (0.25, 0.33, 0.5, 0.66, 0.75, 1.0, 1.5),
    "dense": (0.2, 0.25, 0.33, 0.4, 0.5, 0.6, 0.66, 0.75, 0.85, 1.0, 1.25, 1.5, 2.0),
}
CANDIDATE_TOLERANCES = (0.01, 0.02, 0.03, 0.05)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_observations(path: Path) -> list[dict]:
    records = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def refuse_mass(fractions: list[float], menu: tuple[float, ...], tolerance: float) -> float:
    """Part des mises observées refusées par (menu, tolérance)."""
    if not fractions:
        return 0.0
    refused = 0
    for frac in fractions:
        nearest = min(menu, key=lambda node: abs(node - frac))
        if abs(nearest - frac) > tolerance:
            refused += 1
    return refused / len(fractions)


def build_report(observations: list[dict]) -> str:
    now = _utc_now_iso()
    by_street: dict[str, list[float]] = {}
    histogram: Counter = Counter()
    for obs in observations:
        frac = obs.get("pot_fraction")
        if frac is None:
            pot = float(obs.get("pot") or 0.0)
            amount = float(obs.get("amount") or 0.0)
            if pot <= 0 or amount <= 0:
                continue
            frac = amount / pot
        frac = round(float(frac), 4)
        street = str(obs.get("street") or "unknown") or "unknown"
        by_street.setdefault(street, []).append(frac)
        bucket = round(frac / 0.05) * 0.05
        histogram[round(bucket, 2)] += 1

    lines = [
        "# Rapport de calibration — tolérance de quantification des mises",
        "",
        f"Généré le {now} par `research/bet_tolerance_study.py`.",
        "",
        f"Observations : **{len(observations)}** mises adverses brutes "
        f"(`evidence/bet_observations.jsonl`).",
        "",
        "## Histogramme (buckets de 5% du pot)",
        "",
        "| Fraction du pot | Occurrences |",
        "|---|---|",
    ]
    for bucket in sorted(histogram):
        lines.append(f"| {bucket:.2f} | {histogram[bucket]} |")
    if not histogram:
        lines.append("| — | aucune donnée |")

    lines += ["", "## Par street", "", "| Street | n | Fractions (top) |", "|---|---|---|"]
    for street, fractions in sorted(by_street.items()):
        top = Counter(round(f, 2) for f in fractions).most_common(8)
        pretty = ", ".join(f"{frac:.2f}×{count}" for frac, count in top)
        lines.append(f"| {street} | {len(fractions)} | {pretty} |")

    lines += [
        "",
        "## Masse de refus par candidat (menu × tolérance)",
        "",
        "Part des mises observées qui seraient **refusées** (au-delà de la",
        "tolérance du nœud menu le plus proche) — à minimiser sous contrainte",
        "de coût d'abstraction.",
        "",
        "| Menu | Tolérance | Refus |",
        "|---|---|---|",
    ]
    all_fractions = [frac for fractions in by_street.values() for frac in fractions]
    for menu_name, menu in CANDIDATE_MENUS.items():
        for tolerance in CANDIDATE_TOLERANCES:
            mass = refuse_mass(all_fractions, menu, tolerance)
            lines.append(f"| {menu_name} | ±{tolerance:.0%} pot | {mass:.1%} |")

    lines += [
        "",
        "## Verdict",
        "",
    ]
    if not observations:
        lines += [
            "**Données insuffisantes** : aucune mise observée. Les constantes",
            "de `src/solver/bet_quantization.py` (menu 7 nœuds, tolérance",
            "±2% pot) restent **PROVISOIRES** et ne fondent pas un go-live :",
            "le verrou `go_live_gate` exige un rapport basé sur un échantillon",
            "réel avant de lever ce drapeau.",
        ]
    else:
        lines += [
            "Recommandation automatique : choisir le menu le plus compact dont",
            "la masse de refus à ±2% pot reste ≤ 5% des observations, puis",
            "mesurer le coût d'abstraction (ΔEV taille exacte vs nœud menu)",
            "avant fixation définitive. La mesure ΔEV requiert les contextes de",
            "spot complets — cf. protocole Phase 0.6.5 du plan d'audit.",
        ]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibration tolérance quantification mises.")
    parser.add_argument("--obs", default=str(DEFAULT_OBS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH))
    args = parser.parse_args(argv)

    observations = load_observations(Path(args.obs))
    report = build_report(observations)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Rapport écrit : {out_path} ({len(observations)} observations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
