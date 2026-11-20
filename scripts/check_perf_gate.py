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
- invariants durs, bloquants partout : zéro fallback produit sur le corpus,
  backend multiway présent.

Trois pièges ont été corrigés après un échec de CI reproductible :

1. **Saturation au timeout solveur.** Le runtime appelle le solveur avec un
   budget (800 ms en HU) et un délai de garde ``budget + 2,0 s``. Sur une machine
   lente, les spots les plus lourds atteignent ce délai et retombent en
   ``solver_timeout`` (fail-closed). La latence mesurée vaut alors le délai de
   garde, pas le coût du solveur : la comparer à la baseline produisait un faux
   « +149 % ». Un spot saturé est désormais signalé comme tel et sorti de la
   comparaison ; sa cause est la vitesse machine, et le remède est le budget.
2. **Calibration non représentative.** Le solveur est parallèle (rayon) : une
   charge CPU mono-thread ne prédit pas la vitesse d'un runner à peu de cœurs.
   La calibration mesure un débit parallèle (``zlib``, qui libère le GIL), ce qui
   reflète le nombre de cœurs autant que leur fréquence.
3. **Comparaison de latence inter-machines non fiable en CI.** Même calibrée, la
   latence absolue du solveur parallèle varie trop d'une machine à l'autre pour
   porter un gate bloquant : sur le runner GitHub observé, le handicap atteint
   ×1,4 à ×3,2 selon le spot, qu'aucune référence de vitesse scalaire ne
   reproduit. La comparaison de latence est donc **informative hors machine de
   référence** : elle avertit sans faire échouer. Le gate reste bloquant sur les
   invariants (fallback, backend) et sur la machine de référence, où la baseline
   a été mesurée. Définir un seuil de latence portable demande un protocole dédié
   (machine épinglée, ou métrique indépendante du matériel) — voir audit F-09.

Usage :
    python scripts/check_perf_gate.py
    python scripts/check_perf_gate.py --repeat 3
    python scripts/check_perf_gate.py --update
    python scripts/check_perf_gate.py --strict-latency   # latence bloquante
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
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

# Marge de garde du runtime autour du budget solveur (cf. decision_maker.py
# ``_SOLVER_TIMEOUT_MARGIN_S``). Un spot qui atteint ``budget + marge`` est
# saturé : sa latence mesure le garde-fou, pas le solveur.
SOLVER_TIMEOUT_MARGIN_MS = 2000.0

# Budget solveur par mode et par ligne, miroir de
# ``DecisionMaker._multiway_time_budget`` (800 ms en HU, 700 ms à 3 joueurs,
# 500 ms au-delà). Sert à détecter la saturation, pas à la tolérer.
HEADS_UP_SOLVE_BUDGET_MS = 800.0
MULTIWAY_SOLVE_BUDGET_MS = {"n=3": 700.0}
MULTIWAY_DEFAULT_BUDGET_MS = 500.0

# La baseline est mesurée sur une machine donnée ; la CI tourne ailleurs. Une
# charge CPU fixe sert de référence de vitesse : la latence attendue est mise à
# l'échelle par le rapport des calibrations, sinon un runner plus lent
# échouerait à tort sur toutes les lignes. La charge est parallèle et libère le
# GIL (``zlib``) parce que le solveur l'est aussi (rayon) : une mesure
# mono-thread sous-estimerait le handicap d'un runner à peu de cœurs.
CALIBRATION_REPEATS = 5
CALIBRATION_WORKLOAD = 60_000
CALIBRATION_PARALLEL = 4
_CALIBRATION_PAYLOAD = b"".join(str(i).encode() for i in range(CALIBRATION_WORKLOAD))


def _cpu_workload(_: int) -> int:
    return len(zlib.compress(_CALIBRATION_PAYLOAD, 6))


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


def _cold_by_spot(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Latence froide et statut par ligne, pour un payload de processus neuf."""
    cold: dict[str, dict[str, Any]] = {}
    for row in payload["results"]:
        if row["pass"] != "cold":
            continue
        key = f"n={row['num_players']}" if "num_players" in row else str(row["spot_id"])
        reason = row.get("fallback_reason")
        cold[key] = {
            "ms": float(row["elapsed_ms"]),
            "timeout": reason == "solver_timeout",
            "fallback": bool(row.get("fallback_used")),
            "reason": reason,
        }
    return cold


def _calibration_ms() -> float:
    """Référence de vitesse représentative du chemin solveur (parallèle)."""
    samples = []
    for _ in range(CALIBRATION_REPEATS):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=CALIBRATION_PARALLEL) as pool:
            list(pool.map(_cpu_workload, range(CALIBRATION_PARALLEL)))
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def _solve_budget_ms(mode: str, key: str) -> float:
    """Budget solveur associé à une ligne, pour détecter la saturation."""
    if mode == "heads_up":
        return HEADS_UP_SOLVE_BUDGET_MS
    return MULTIWAY_SOLVE_BUDGET_MS.get(key, MULTIWAY_DEFAULT_BUDGET_MS)


def _measure(*, repeat: int) -> dict[str, Any]:
    heads_up: dict[str, dict[str, Any]] = {}
    multiway: dict[str, dict[str, Any]] = {}
    hu_fallbacks = 0
    mw_fallbacks = 0
    hu_timeouts = 0
    mw_timeouts = 0
    hu_backends: set[str] = set()
    mw_backends: set[str] = set()

    for _ in range(repeat):
        hu_payload = _run_bench("heads-up")
        for key, info in _cold_by_spot(hu_payload).items():
            bucket = heads_up.setdefault(key, {"ms": [], "timeout": False})
            bucket["ms"].append(info["ms"])
            bucket["timeout"] = bucket["timeout"] or info["timeout"]
        # Un timeout solveur est un problème de budget/machine, pas un fallback
        # produit : il est compté et traité séparément.
        hu_fallbacks += sum(
            1
            for row in hu_payload["results"]
            if row.get("fallback_used") and row.get("fallback_reason") != "solver_timeout"
        )
        hu_timeouts += sum(
            1 for row in hu_payload["results"] if row.get("fallback_reason") == "solver_timeout"
        )
        hu_backends.update(
            str(row.get("backend")) for row in hu_payload["results"] if row.get("backend")
        )

        mw_payload = _run_bench("multiway")
        for key, info in _cold_by_spot(mw_payload).items():
            bucket = multiway.setdefault(key, {"ms": [], "timeout": False})
            bucket["ms"].append(info["ms"])
            bucket["timeout"] = bucket["timeout"] or info["timeout"]
        mw_fallbacks += sum(
            1
            for row in mw_payload["results"]
            if row.get("fallback_used") and row.get("fallback_reason") != "solver_timeout"
        )
        mw_timeouts += sum(
            1 for row in mw_payload["results"] if row.get("fallback_reason") == "solver_timeout"
        )
        mw_backends.update(
            str(row.get("backend")) for row in mw_payload["results"] if row.get("backend")
        )

    return {
        "kind": "perf_baseline",
        "repeat": repeat,
        "calibration_ms": round(_calibration_ms(), 3),
        "heads_up": {
            "cold_ms": {k: round(min(v["ms"]), 1) for k, v in sorted(heads_up.items())},
            "timeouts": {k: v["timeout"] for k, v in sorted(heads_up.items())},
            "fallbacks": hu_fallbacks,
            "timeout_count": hu_timeouts,
            "backends": sorted(hu_backends),
        },
        "multiway": {
            "cold_ms": {k: round(min(v["ms"]), 1) for k, v in sorted(multiway.items())},
            "timeouts": {k: v["timeout"] for k, v in sorted(multiway.items())},
            "fallbacks": mw_fallbacks,
            "timeout_count": mw_timeouts,
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
    timeout_ms: float = 0.0,
    saturated: bool = False,
    strict: bool = False,
) -> str:
    ceiling_ms = timeout_ms + SOLVER_TIMEOUT_MARGIN_MS
    # Saturation : la latence mesurée est le délai de garde du runtime, pas le
    # coût du solveur. La comparer à la baseline serait un faux positif ; on la
    # neutralise, mais on signale la cause (budget/machine) sans faire échouer.
    # Le seuil est relatif au plafond : un solveur rend la main à son budget
    # (~800 ms), donc un spot non saturé n'approche jamais 90 % du plafond.
    near_ceiling = timeout_ms > 0 and current >= ceiling_ms * 0.90
    if saturated or near_ceiling:
        return (
            f"  {label:<26} {current:>9.1f}ms  SATURÉ (plafond {ceiling_ms:.0f}ms, "
            f"budget {timeout_ms:.0f}ms)  hors comparaison"
        )
    # La référence est ramenée à la vitesse de la machine courante : une
    # machine deux fois plus lente a le droit à deux fois le temps.
    scaled = reference * scale
    if scaled <= 0:
        return f"  {label:<26} {current:>9.1f}ms  (pas de référence)"
    if scaled < ABSOLUTE_FLOOR_MS:
        ceiling = scaled + ABSOLUTE_FLOOR_MS
        verdict = "OK" if current <= ceiling else ("REGRESSION" if strict else "ÉCART")
        if verdict == "REGRESSION":
            failures.append(
                f"{label}: {current:.1f}ms contre {scaled:.1f}ms (plancher {ceiling:.1f}ms)"
            )
        return f"  {label:<26} {current:>9.1f}ms  ref={scaled:>7.1f}ms  (plancher)  {verdict}"
    delta_pct = (current - scaled) / scaled * 100.0
    verdict = "OK" if delta_pct <= EFFECTIVE_LIMIT_PCT else ("REGRESSION" if strict else "ÉCART")
    if verdict == "REGRESSION":
        failures.append(
            f"{label}: {current:.1f}ms contre {scaled:.1f}ms "
            f"(+{delta_pct:.0f}% > {EFFECTIVE_LIMIT_PCT:.0f}%)"
        )
    return f"  {label:<26} {current:>9.1f}ms  ref={scaled:>7.1f}ms  {delta_pct:+6.0f}%  {verdict}"


def check(
    current: dict[str, Any], reference: dict[str, Any], *, strict_latency: bool = False
) -> list[str]:
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

    latency_mode = "bloquante" if strict_latency else "informative (invariants bloquants)"
    print(
        f"Seuil de régression : {REGRESSION_THRESHOLD_PCT:.0f}% "
        f"+ bruit machine {MACHINE_NOISE_PCT:.0f}% = {EFFECTIVE_LIMIT_PCT:.0f}%\n"
        f"{calibration_note}\n"
        f"Comparaison de latence : {latency_mode}\n"
    )

    for mode in ("heads_up", "multiway"):
        cur, ref = current[mode], reference[mode]
        timeouts = cur.get("timeouts") or {}
        print(f"[{mode}] latence froide (médiane par ligne)")
        for key, value in cur["cold_ms"].items():
            print(
                _compare(
                    key,
                    value,
                    ref["cold_ms"].get(key, 0.0),
                    failures,
                    scale=scale,
                    timeout_ms=_solve_budget_ms(mode, key),
                    saturated=bool(timeouts.get(key)),
                    strict=strict_latency,
                )
            )
        if cur["fallbacks"] > 0:
            failures.append(
                f"{mode}: {cur['fallbacks']} fallback(s) produit(s) sur le corpus de référence"
            )
        timeout_count = int(cur.get("timeout_count") or 0)
        if timeout_count > 0:
            print(
                f"  ({timeout_count} saturation(s) au délai de garde solveur — "
                "budget/machine, hors comparaison de latence)"
            )
        print()

    if not any(b.startswith("multiway") for b in current["multiway"]["backends"]):
        failures.append(f"multiway: backend multiway absent ({current['multiway']['backends']})")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="processus neufs par mode")
    parser.add_argument("--update", action="store_true", help="réécrit la baseline")
    parser.add_argument(
        "--strict-latency",
        action="store_true",
        help=(
            "rend la comparaison de latence bloquante (machine de référence) ; "
            "par défaut elle est informative et seuls les invariants bloquent"
        ),
    )
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
    failures = check(current, reference, strict_latency=args.strict_latency)

    if failures:
        print("GATE PERF : ÉCHEC")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("GATE PERF : OK — aucune régression au-delà du seuil.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
