# -*- coding: utf-8 -*-
"""Seed de calibration Phase 0.7 : exerce le VRAI chemin de télémétrie live.

Appelle `src.runtime.bet_logger.log_action_history_bets` (exactement la fonction
utilisée par `DecisionMaker._call_solver_backend`) avec des historiques
d'actions réalistes (fractions du pot autour des nœuds du menu + tailles
hors-menu fréquentes en pratique).

⚠ Échantillon de calibration SYNTHÉTIQUE — pas des observations live réelles.
Les constantes menu/tolérance restent PROVISOIRES jusqu'à collecte live ;
le rapport le reflète via son verdict (n observations, pas de ΔEV mesuré).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime.bet_logger import log_action_history_bets

# (fraction_du_pot, street, répétitions) — distribution plausible :
# masses sur les nœuds du menu + bruit ±1-2% + tailles hors-menu récurrentes.
SAMPLES = [
    (0.25, "flop", 6), (0.26, "flop", 2), (0.24, "flop", 1),
    (0.33, "flop", 8), (0.34, "turn", 3), (0.32, "flop", 2),
    (0.50, "flop", 10), (0.51, "turn", 4), (0.49, "flop", 3),
    (0.40, "turn", 3),   # hors-menu récurrent (40%)
    (0.66, "turn", 6), (0.67, "river", 3), (0.65, "turn", 2),
    (0.60, "river", 2),  # hors-menu récurrent (60%)
    (0.75, "river", 5), (0.76, "river", 2),
    (1.00, "river", 7), (1.02, "river", 2),
    (0.80, "river", 2),  # hors-menu récurrent (80%)
    (1.50, "river", 2),
    (0.68, "turn", 2),   # bord de tolérance du nœud 0.66 (+2%)
    (0.70, "flop", 1),   # 0.70 : entre 0.66 et 0.75, hors tol ±2% des deux
]

POT = 10.0
logged = 0
for frac, street, reps in SAMPLES:
    for _ in range(reps):
        logged += log_action_history_bets(
            [{"player": "Villain", "action": "bet", "amount": round(frac * POT, 2)}],
            pot=POT,
            street=street,
        )
print(f"seed termine : {logged} observations loggees via log_action_history_bets")
