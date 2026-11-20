# Tasks: Preuve statistique de performance et réduction de variance

**Input**: `specs/011-scientific-validity/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, constat F-03, C11/C27 de `docs/etudes.md`

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test de non-biais : sur un jeu synthétique à vérité connue, l'IC de l'estimateur couvre la vérité au taux nominal.
- [x] T002 [P] [US1] Test de réduction : variance strictement inférieure sur contrôle corrélé ; identique à la moyenne brute sur contrôle constant.
- [x] T003 [P] [US1] Test de cas dégénérés : contrôle parfait → variance nulle ; β optimal ≥ β = 1 ; moyenne du contrôle estimée → `unbiased_inputs` faux.
- [x] T004 [P] [US1] Test MIVAT : un estimateur par joueur, sans biais, sur un jeu synthétique à N joueurs.
- [x] T005 [P] [US2] Test de puissance : `⌈(1,96·σ/demi-largeur)²⌉`, monotonie, σ = 0 → 0, demi-largeur ≤ 0 → erreur.
- [x] T006 [P] [US2] Test de verdict : les quatre verdicts et la complétude du protocole.
- [x] T007 [P] [US3] Test de harnais : effectif exact, artefact daté, `unmeasured` sans main, réduction mesurée non supposée.
- [x] T008 [P] [US3] Test d'honnêteté : une politique non-production porte `hero_policy_is_production = false`.
- [x] T009 [P] [US4] Test de contrat : `build_strategy_metrics` compose le payload ; artefacts absents → `{}`.
- [x] T010 [P] [US4] Test de gate : protocole complet, blocage sur IC négatif, non-régression sans artefact.

## Phase 2: Implémentation

- [x] T011 [US1] Créer `research/variance_reduction.py` : `VarianceReducedEstimate`, `control_variate_estimate`, `aivat_estimate`, `mivat_estimate`.
- [x] T012 [US2] Créer `research/sample_size.py` : `required_hands`, `WinrateVerdict`, `classify_winrate`.
- [x] T013 [US3] Créer `research/production_benchmark.py` : `ProductionBenchmarkReport`, `run_production_benchmark`, `preflop_equity_control`, `write_report`.
- [x] T014 [US4] Créer `src/runtime/strategy_metrics.py` : `build_strategy_metrics`, `strategy_metrics_from_artifacts`.
- [x] T015 [US4] Ajouter les checks stratégiques CI à `src/runtime/go_live_gate.py` (actifs seulement si les champs de protocole sont présents).
- [x] T016 [US4] Alimenter le gate depuis l'artefact dans `src/bot/operator_snapshot.py`.
- [x] T017 [US3] Créer `scripts/production_winrate_benchmark.py` : point d'entrée opérateur, politique étiquetée, artefact daté.

## Phase 3: Validation

- [x] T018 [US4] Exécuter les quatre fichiers de tests nouveaux (verts).
- [x] T019 [US4] Vérifier la non-régression du gate : `tests/test_main_decision_gate_replay.py` (vert).
- [x] T020 [US4] Exécuter la suite Python complète et `ruff check` (verts).
- [x] T021 [US3] Vérifier le script de bout en bout : sans main → `unmeasured` et message honnête ; politique heuristique → protocole non complet.
- [x] T022 [US4] Exécuter `cargo test --lib` et `cargo fmt --check` (inchangés, aucun code Rust touché).
- [x] T023 Mettre à jour l'audit §3.3/§5/§6.2/§8/§9 et le registre de migration (statut F-03, C11/C27).

## Dépendances

- T001–T010 avant T011–T017 (tests rouges d'abord).
- T011 avant T013 (le harnais agrège via les estimateurs).
- T012 avant T013 (le harnais déclare le nombre requis).
- T014 avant T015–T016 (le contrat précède son consommateur).
- T013 avant T017 (le harnais précède son point d'entrée).
- Indépendante des specs `001`, `002`, `004`, `005`, `010` ; consomme l'infrastructure existante (`monte_carlo_sim`, `best_response`, `go_live_gate`).

## Critère de fin

- [x] L'estimateur de winrate est sans biais et réduit la variance sur un contrôle corrélé — vérifié par test.
- [x] Le nombre de mains requis est calculé avant la mesure, et un verdict explicite est retourné.
- [x] Le harnais mesure le chemin de production et signale une mesure d'heuristique comme telle.
- [x] Sans main évaluable, le rapport est `unmeasured` avec des taux `None`.
- [x] Le gate bloque un winrate significativement négatif, signale un protocole incomplet, et reste neutralisé sans artefact.
- [x] `pytest`, `ruff` verts ; `cargo test`/`cargo fmt` inchangés ; comportement du gate sans artefact identique.
