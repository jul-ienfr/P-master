"""Gate de performance F-09 — régression bornée sur le runtime de production.

Le benchmark ``scripts/bench_production_runtime.py`` mesurait sans bloquer :
une régression de 10 % passait inaperçue. Ce script exécute les deux modes
(heads-up et multiway) et compare les latences mesurées à la baseline
versionnée ``research/results/perf_baseline.json``.

Protocole de mesure :
- chaque répétition tourne dans un **processus neuf** (``--repeat 1``) : dans un
  processus déjà chaud, le second passage « froid » est en réalité un hit de
  cache et ne mesure plus rien ;
- seule la latence **froide** est retenue : c'est le coût réel du premier appel
  (store préflop, solveur Rust, écriture cache compris) ;
- la valeur comparée est le **minimum par spot** sur les répétitions : le bruit
  de charge ne fait qu'ajouter du temps, jamais en retirer, donc le minimum
  estime la vraie capacité de la machine sans faux positifs ; une régression
  réelle remonte aussi le minimum.

Seuils :
- régression tolérée : 10 % (constat F-09) plus 25 % de bruit machine, mesuré à
  5–17 % sur cinq passes ;
- les lignes de référence inférieures à 5 ms (chemins rapides : préflop
  pré-calculé, cache) sont comparées avec un plancher absolu, une variation
  relative sous la milliseconde n'ayant pas de sens ;
- invariants durs : zéro fallback sur le corpus, backend multiway présent.

Usage :
    python scripts/check_perf_gate.py
    python scripts/check_perf_gate.py --repeat 3
    python scripts/check_perf_gate.py --update
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCH_SCRIPT = ROOT / "scripts" / "bench_production_runtime.py"
BASELINE_PATH = ROOT / "research" / "results" / "perf_baseline.json"

# Constat F-09 : seuil de régression 10 %. La tolérance machine (25 %) couvre le
# bruit de mesure observé ; au-delà, la régression est considérée réelle.
REGRESSION_THRESHOLD_PCT = 10.0
MACHINE_NOISE_PCT = 25.0
EFFECTIVE_LIMIT_PCT = REGRESSION_THRESHOLD_PCT + MACHINE_NOISE_PCT

# Sous ce seuil de référence, la comparaison relative est remplacée par un
# plancher absolu : 0,2 ms contre 0,3 ms n'est pas une régression de 50 %.
ABSOLUTE_FLOOR_MS = 5.0

# La baseline est mesurée sur une machine donnée ; la CI tourne ailleurs. Une
# charge CPU fixe (hachage, code C) sert de référence de vitesse : la latence
# attendue est mise à l'échelle par le rapport des calibrations, sinon un runner
# deux fois plus lent échouerait à tort sur toutes les lignes.
CALIBRATION_REPEATS = 5
CALIBRATION_WORKLOAD = 120_000


def _run_bench(mode: str) -> dict[str, Any]:
    """Exécute le benchmark dans un processus neuf et renvoie son payload."""
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "bench.json"
        result = subprocess.run(
            [
                sys.executable,
                str(BENCH_SCRIPT),
                "--mode",
                mode,
                "--repeat",
                "1",
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if result.returncode != 0 or not output.exists():
            raise RuntimeError(
                f"benchmark {mode} en échec (code {result.returncode}):\n{result.stderr[-2000:]}"
            )
        return json.loads(output.read_text(encoding="utf-8"))


def _cold_by_spot(payload: dict[str, Any]) -> dict[str, float]:
    """Latence froide par ligne, pour un payload de processus neuf."""
    cold: dict[str, float] = {}
    for row in payload["results"]:
        if row["pass"] != "cold":
            continue
        key = f"n={row['num_players']}" if "num_players" in row else str(row["spot_id"])
        cold[key] = float(row["elapsed_ms"])
    return cold


def _calibration_ms() -> float:
    """Charge CPU fixe : référence de vitesse pour comparer deux machines."""
    samples = []
    for _ in range(CALIBRATION_REPEATS):
        started = time.perf_counter()
        _ = hash("".join(str(i) for i in range(CALIBRATION_WORKLOAD)))
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def _measure(*, repeat: int) -> dict[str, Any]:
    heads_up: dict[str, list[float]] = {}
    multiway: dict[str, list[float]] = {}
    hu_fallbacks = 0
    mw_fallbacks = 0
    hu_backends: set[str] = set()
    mw_backends: set[str] = set()

    for _ in range(repeat):
        hu_payload = _run_bench("heads-up")
        for key, value in _cold_by_spot(hu_payload).items():
            heads_up.setdefault(key, []).append(value)
        hu_fallbacks += sum(1 for row in hu_payload["results"] if row.get("fallback_used"))
        hu_backends.update(
            str(row.get("backend")) for row in hu_payload["results"] if row.get("backend")
        )

        mw_payload = _run_bench("multiway")
        for key, value in _cold_by_spot(mw_payload).items():
            multiway.setdefault(key, []).append(value)
        mw_fallbacks += sum(1 for row in mw_payload["results"] if row.get("fallback_used"))
        mw_backends.update(
            str(row.get("backend")) for row in mw_payload["results"] if row.get("backend")
        )

    return {
        "kind": "perf_baseline",
        "repeat": repeat,
        "calibration_ms": round(_calibration_ms(), 3),
        "heads_up": {
            "cold_ms": {k: round(min(v), 1) for k, v in sorted(heads_up.items())},
            "fallbacks": hu_fallbacks,
            "backends": sorted(hu_backends),
        },
        "multiway": {
            "cold_ms": {k: round(min(v), 1) for k, v in sorted(multiway.items())},
            "fallbacks": mw_fallbacks,
            "backends": sorted(mw_backends),
        },
    }


def _compare(
    label: str,
    current: float,
    reference: float,
    failures: list[str],
    *,
    scale: float = 1.0,
) -> str:
    # La référence est ramenée à la vitesse de la machine courante : une
    # machine deux fois plus lente a le droit à deux fois le temps.
    scaled = reference * scale
    if scaled <= 0:
        return f"  {label:<22} {current:>9.1f}ms  (pas de référence)"
    if scaled < ABSOLUTE_FLOOR_MS:
        ceiling = scaled + ABSOLUTE_FLOOR_MS
        verdict = "OK" if current <= ceiling else "REGRESSION"
        if verdict != "OK":
            failures.append(
                f"{label}: {current:.1f}ms contre {scaled:.1f}ms (plancher {ceiling:.1f}ms)"
            )
        return f"  {label:<22} {current:>9.1f}ms  ref={scaled:>7.1f}ms  (plancher)  {verdict}"
    delta_pct = (current - scaled) / scaled * 100.0
    verdict = "OK" if delta_pct <= EFFECTIVE_LIMIT_PCT else "REGRESSION"
    if verdict != "OK":
        failures.append(
            f"{label}: {current:.1f}ms contre {scaled:.1f}ms "
            f"(+{delta_pct:.0f}% > {EFFECTIVE_LIMIT_PCT:.0f}%)"
        )
    return f"  {label:<22} {current:>9.1f}ms  ref={scaled:>7.1f}ms  {delta_pct:+6.0f}%  {verdict}"


def check(current: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    ref_cal = float(reference.get("calibration_ms") or 0.0)
    cur_cal = float(current.get("calibration_ms") or 0.0)
    scale = 1.0
    calibration_note = "calibration absente — comparaison brute"
    if ref_cal > 0 and cur_cal > 0:
        # Bornes [0.5, 3.0] : un rapport aberrant (VM saturée) ne doit pas
        # desserrer le gate au point de le rendre aveugle.
        scale = min(3.0, max(0.5, cur_cal / ref_cal))
        calibration_note = f"calibration {cur_cal:.2f}ms / {ref_cal:.2f}ms -> échelle ×{scale:.2f}"

    print(
        f"Seuil de régression : {REGRESSION_THRESHOLD_PCT:.0f}% "
        f"+ bruit machine {MACHINE_NOISE_PCT:.0f}% = {EFFECTIVE_LIMIT_PCT:.0f}%\n"
        f"{calibration_note}\n"
    )

    for mode in ("heads_up", "multiway"):
        cur, ref = current[mode], reference[mode]
        print(f"[{mode}] latence froide (médiane par ligne)")
        for key, value in cur["cold_ms"].items():
            print(_compare(key, value, ref["cold_ms"].get(key, 0.0), failures, scale=scale))
        if cur["fallbacks"] > 0:
            failures.append(f"{mode}: {cur['fallbacks']} fallback(s) sur le corpus de référence")
        print()

    if not any(b.startswith("multiway") for b in current["multiway"]["backends"]):
        failures.append(f"multiway: backend multiway absent ({current['multiway']['backends']})")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="processus neufs par mode")
    parser.add_argument("--update", action="store_true", help="réécrit la baseline")
    args = parser.parse_args()

    current = _measure(repeat=max(1, args.repeat))

    if args.update:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"baseline mise à jour : {BASELINE_PATH}")
        print(json.dumps(current, indent=2, sort_keys=True))
        return 0

    if not BASELINE_PATH.exists():
        print(f"baseline absente : {BASELINE_PATH} (lancer avec --update)")
        return 1

    reference = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    failures = check(current, reference)

    if failures:
        print("GATE PERF : ÉCHEC")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("GATE PERF : OK — aucune régression au-delà du seuil.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
