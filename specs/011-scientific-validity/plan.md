# Implementation Plan: Preuve statistique de performance et réduction de variance

**Branch**: `011-scientific-validity` | **Date**: 2026-11-20 | **Spec**: `specs/011-scientific-validity/spec.md`

## Summary

Rendre une mesure de winrate **interprétable** au lieu d'un chiffre nu : des estimateurs à variance réduite (C11 AIVAT, C27 MIVAT) vérifiés sans biais sur des jeux synthétiques à vérité connue, un calcul de **puissance statistique déclaré à l'avance**, un harnais qui mesure le **chemin de production** et ne peut pas se faire passer pour l'heuristique, et le câblage du **gate go-live** sur un artefact honnête (aujourd'hui mort : `strategy_metrics` n'est jamais fourni).

## Technical Context

**Language/Version**: Python 3.11 (venv du projet) ; aucun changement Rust
**Primary Dependencies**: aucune nouvelle — `statistics`, `math`, `json`, `dataclasses` ; `research/monte_carlo_sim.py` (simulateur pokerkit, `monte_carlo_equity`) est réutilisé
**Storage**: `research/results/production_winrate_<site>.json` (artefact daté, versionnable)
**Testing**: `pytest tests/test_variance_reduction.py tests/test_sample_size.py tests/test_production_benchmark.py tests/test_strategy_metrics.py`
**Target Platform**: Windows, runtime local
**Project Type**: outillage d'évaluation Python (`research/`) + un module de contrat runtime (`src/runtime/`)
**Performance Goals**: aucun impact dans la boucle chaude — les estimateurs tournent hors ligne, sur des résultats déjà collectés
**Constraints**: le gate doit conserver exactement son comportement actuel quand `strategy_metrics` est absent (3 tests existants) ; l'estimateur ne doit jamais présenter un taux de réduction supposé ; une mesure d'heuristique ne doit jamais satisfaire le protocole de production
**Scale/Scope**: deux sites livrés, estimateurs génériques (HU et N joueurs), harnais indépendant de la politique mesurée

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | C'est le principe que la spec sert directement : un winrate nu n'est pas une preuve ; la spec impose IC, effectif, puissance déclarée et verdict explicite. Les estimateurs sont rattachés à C11/C27 et vérifiés sans biais sur vérité connue |
| II. Rust-first | Aucun calcul chaud ajouté. L'estimation tourne hors boucle, dans `research/` (principe II : « notebooks de recherche », « outillage de développement ») ; l'équité et le solveur restent en Rust et ne sont pas dupliqués. Le registre §7 n'a pas de ligne à ouvrir |
| III. Latence et reproductibilité | Aucune latence de décision touchée. La reproductibilité est renforcée : graine, effectif requis et politique mesurée sont enregistrés dans l'artefact |
| IV. Fail-closed | Un artefact absent neutralise les checks stratégiques (comportement historique) ; un IC entièrement négatif bloque le go-live ; un protocole incomplet est signalé, jamais comblé par un chiffre inventé |
| V. Modularité | L'estimateur est indépendant du simulateur (il reçoit des résultats et des contrôles) ; le harnais est indépendant de la politique (il reçoit un callable) ; le gate consomme un contrat de métriques, pas des internes |
| VI. Tests | 4 fichiers de tests nouveaux ; la non-régression du gate (3 tests existants) est explicitement vérifiée |
| IX. Source unique | `compute_validation_status` (spec 010) reste la source unique du statut de preset ; ici, le verdict de winrate est un type unique, et le gate n'a plus de condition `winrate >= 0` seule |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Estimateurs à variance réduite (`research/variance_reduction.py`, nouveau)

`control_variate_estimate(payoffs, controls, *, mean_control, beta)` : `X = u − β·(C − E[C])`, sans biais pour toute `C` et toute `E[C]` connue. `beta="optimal"` estime `β* = Cov(u,C)/Var(C)`. `mean_control=None` estime la moyenne sur l'échantillon et marque le résultat comme non garanti sans biais (il faut un échantillon de calibration distinct).

`aivat_estimate(payoffs, controls)` : cas AIVAT où `E[C] = 0` par construction (variable de contrôle centrée), `β = 1`.

`mivat_estimate(per_player_payoffs, per_player_controls)` : un `EstimatorResult` par joueur, chacun sans biais à partir de sa propre variable de contrôle.

`EstimatorResult` porte l'estimation réduite et brute (en bb/100), leurs demi-largeurs d'IC 95 %, le taux de réduction de variance **mesuré**, β et la moyenne du contrôle.

### 2. Puissance statistique (`research/sample_size.py`, nouveau)

`required_hands(sigma_bb100, target_half_width_bb100, *, z=1.96)` : `⌈(z·σ/demi-largeur)²⌉`. `classify_winrate(winrate_bb100, ci95_bb100, evaluated_hands, required_hands)` retourne un `WinrateVerdict` : `significant_positive` (borne basse > 0), `significant_negative` (borne haute < 0), `not_significant` (IC contient 0), `underpowered` (effectif < requis). `protocol_complete` exige un effectif ≥ requis et un IC fourni.

### 3. Harnais de benchmark de production (`research/production_benchmark.py`, nouveau)

`run_production_benchmark(hero_action_fn, *, policy_label, is_production, opponents, hands, seed, target_half_width, control_fn, mean_control)` réutilise le simulateur (`new_state`, `build_view`, `apply_action`, `make_archetype_policy`) pour jouer le pool synthétique, enregistre le résultat **et** la variable de contrôle par main, puis agrège via les estimateurs. Sans main évaluable : `unmeasured`, taux `None`.

`preflop_equity_control(hole_cards, rng)` : variable de contrôle `équité − 0,5`, de moyenne **exactement** 0 par symétrie (deux mains tirées uniformément), réutilisant `monte_carlo_equity`. C'est le contrôle AIVAT concret du harnais.

`write_report(report, path)` écrit l'artefact JSON daté ; le rapport porte `hero_policy`, `hero_policy_is_production` et la réduction de variance mesurée.

### 4. Contrat de métriques et câblage du gate (`src/runtime/strategy_metrics.py`, `src/runtime/go_live_gate.py`, `src/bot/operator_snapshot.py`)

`build_strategy_metrics(winrate_report, mes_report=None)` compose le payload attendu par le gate : `winrate_bb100`, `best_response_gap`, et — seulement s'ils sont fournis — `winrate_ci_low`, `winrate_ci_high`, `evaluated_hands`, `required_hands`, `hero_policy_is_production`, `artifact_generated_at`.

`strategy_metrics_from_artifacts(...)` lit les artefacts (chemin surchargeable par `POKER_STRATEGY_METRICS_PATH`), et retourne `{}` si absents ou illisibles — jamais un chiffre inventé.

`evaluate_go_live_gate` gagne deux checks **actifs seulement quand les champs de protocole sont présents** : `strategy_protocol` (effectif ≥ requis, IC fourni, politique de production) et `strategy_winrate_significant` (borne haute ≥ 0). Sans ces champs, les checks sont neutralisés : les trois tests existants gardent leur comportement exact.

`operator_snapshot.py` charge les métriques d'artefacts et les passe au gate, comme il passe déjà `blueprint_metrics` ailleurs.

### 5. Point d'entrée opérateur (`scripts/production_winrate_benchmark.py`, nouveau)

Construit la politique mesurée (`--policy heuristic|production`), lance le harnais, écrit l'artefact daté, et imprime un message honnête quand rien n'est mesuré ou quand le protocole est incomplet. `--policy heuristic` est explicitement étiqueté non-production.

## Structure des fichiers

```text
research/variance_reduction.py        # estimateurs AIVAT/MIVAT (nouveau)
research/sample_size.py               # puissance statistique et verdict (nouveau)
research/production_benchmark.py      # harnais de benchmark de production (nouveau)
src/runtime/strategy_metrics.py       # contrat de métriques pour le gate (nouveau)
src/runtime/go_live_gate.py           # checks stratégiques CI (modifié)
src/bot/operator_snapshot.py          # alimente le gate (modifié)
scripts/production_winrate_benchmark.py  # point d'entrée opérateur (nouveau)
tests/test_variance_reduction.py      # estimateurs (nouveau)
tests/test_sample_size.py             # puissance et verdict (nouveau)
tests/test_production_benchmark.py    # harnais (nouveau)
tests/test_strategy_metrics.py        # contrat + gate (nouveau)
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Régression du gate quand `strategy_metrics` est absent | Les nouveaux checks ne s'activent que si les champs de protocole sont présents ; test de non-régression explicite sur les 3 cas existants |
| Estimateur présenté sans biais alors que la moyenne du contrôle est estimée | `mean_control=None` marque `unbiased_inputs=False` ; la docstring et le test l'exigent |
| Réduction de variance nulle ou négative | Rapportée telle quelle (le taux peut être ≤ 0), jamais forcée ; test sur contrôle constant (0) et contrôle parfait (variance nulle) |
| Un artefact d'heuristique satisfaisant le protocole | `hero_policy_is_production` fait partie du check `strategy_protocol` ; test dédié |
| Campagne réelle trop lente pour un tour | Le harnais est testé sur des politiques déterministes ; le script est le point d'entrée opérateur, comme pour la vision (spec 010) |
| Calcul de puissance sur entrée dégénérée | σ ≤ 0 → 0 main ; demi-largeur ≤ 0 → erreur explicite ; jamais de division par zéro |

## Portes de qualité

- `uv run pytest tests/test_variance_reduction.py tests/test_sample_size.py tests/test_production_benchmark.py tests/test_strategy_metrics.py`.
- `uv run pytest tests/test_main_decision_gate_replay.py` (non-régression du gate).
- `uv run ruff check src tests scripts research poker/tools`.
- Suite Python complète verte (non-régression).
- `cargo test --lib` et `cargo fmt --check` inchangés (aucun code Rust touché).

## Complexity Tracking

Aucune complexité algorithmique ajoutée. Les trois structures nouvelles (`EstimatorResult`, `WinrateVerdict`, `ProductionBenchmarkReport`) remplacent des pratiques implicites : une moyenne brute sans puissance déclarée, un `strategy_metrics` mort, et une condition `winrate >= 0` qui accepte un résultat non significatif. Sans elles, une mesure reste un chiffre nu, et le gate stratégique reste inopérant.
