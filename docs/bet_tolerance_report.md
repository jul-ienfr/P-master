# Rapport de calibration — tolérance de quantification des mises

Généré le 2026-09-03T09:11:07Z par `research/bet_tolerance_study.py`.

Observations : **23** mises adverses brutes (`evidence/bet_observations.jsonl`).

## Histogramme (buckets de 5% du pot)

| Fraction du pot | Occurrences |
|---|---|
| 0.25 | 3 |
| 0.30 | 1 |
| 0.35 | 2 |
| 0.40 | 1 |
| 0.50 | 4 |
| 0.60 | 1 |
| 0.65 | 3 |
| 0.70 | 2 |
| 0.75 | 2 |
| 0.80 | 1 |
| 1.00 | 2 |
| 1.50 | 1 |

## Par street

| Street | n | Fractions (top) |
|---|---|---|
| flop | 8 | 0.25×1, 0.26×1, 0.24×1, 0.33×1, 0.32×1, 0.50×1, 0.49×1, 0.70×1 |
| river | 8 | 0.67×1, 0.60×1, 0.75×1, 0.76×1, 1.00×1, 1.02×1, 0.80×1, 1.50×1 |
| turn | 6 | 0.34×1, 0.51×1, 0.40×1, 0.66×1, 0.65×1, 0.68×1 |
| unknown | 1 | 0.50×1 |

## Masse de refus par candidat (menu × tolérance)

Part des mises observées qui seraient **refusées** (au-delà de la
tolérance du nœud menu le plus proche) — à minimiser sous contrainte
de coût d'abstraction.

| Menu | Tolérance | Refus |
|---|---|---|
| compact | ±1% pot | 87.0% |
| compact | ±2% pot | 69.6% |
| compact | ±3% pot | 60.9% |
| compact | ±5% pot | 56.5% |
| standard (défaut provisoire) | ±1% pot | 65.2% |
| standard (défaut provisoire) | ±2% pot | 26.1% |
| standard (défaut provisoire) | ±3% pot | 17.4% |
| standard (défaut provisoire) | ±5% pot | 13.0% |
| dense | ±1% pot | 56.5% |
| dense | ±2% pot | 17.4% |
| dense | ±3% pot | 8.7% |
| dense | ±5% pot | 0.0% |

## Verdict

Recommandation automatique : choisir le menu le plus compact dont
la masse de refus à ±2% pot reste ≤ 5% des observations, puis
mesurer le coût d'abstraction (ΔEV taille exacte vs nœud menu)
avant fixation définitive. La mesure ΔEV requiert les contextes de
spot complets — cf. protocole Phase 0.6.5 du plan d'audit.
