# Tasks: Multiway réel 3–6 joueurs

**Input**: `specs/002-runtime-n-way/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, spec 001 livrée

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test du comptage des joueurs actifs avec un joueur assis-out dans `tests/test_gate_flow.py`.
- [x] T002 [P] [US1] Test de contrat `SolveRequestV2` 3-way : `num_players=3` et trois ranges dans `tests/test_decision_maker.py`.
- [x] T003 [P] [US2] Test de contrat `SolveRequestV2` 6-way : `num_players=6` et cinq ranges.
- [x] T004 [P] [US2] Test d'intégration : le backend retourné est multiway et les warnings sont présents.
- [x] T005 [P] [US3] Test du mode strict : refus `multiway_strict_refused`.
- [x] T006 [P] [US1] Test de non-régression HU : `num_players=2` et une seule range villain.

## Phase 2: Implémentation

- [x] T007 [US1] Ajouter `MultiwayContext` dans `src/bot/runtime_types.py`.
- [x] T008 [US1] Construire le contexte dans `src/bot/gate_flow.py` depuis `canonical_state` et le tracker.
- [x] T009 [US1] Ajouter `num_players`, `villain_ranges`, `hero_player_index` à `DecisionMaker.get_best_action`.
- [x] T010 [US1] Propager ces paramètres dans `_call_solver_backend` et `solve_spot_v2`.
- [x] T011 [US1] Passer `num_players` et les ranges à `SolveRequestV2` ; conserver le chemin HU si `num_players <= 2`.
- [x] T012 [US2] Vérifier/ajuster le chemin `can_solve_multiway` de `src/v2_api.rs` pour 3–6 joueurs.
- [x] T013 [US3] Étiqueter la réponse multiway (`converged=false`, warning) et journaliser `num_players`, positions, mode.
- [x] T014 [US2] Gérer `num_players > 6` et état invalide par un fallback explicite.
- [x] T015 [US1] Ajouter `num_players` et les ranges à la clé de cache dans `src/solver/spot_key.py` et ses appelants.
- [x] T016 [US3] Ajouter les métriques de fallback par raison.

## Phase 3: Validation

- [x] T017 [US1] Rejouer un spot 3-way golden et vérifier que le résultat diffère du HU.
- [x] T018 [US2] Rejouer un spot 6-max golden et vérifier `backend=multiway`.
- [x] T019 [US2] Exécuter le benchmark par N (3, 4, 5, 6) et documenter p95/mémoire.
- [x] T020 [US1] Exécuter `uv run pytest tests/test_decision_maker.py tests/test_gate_flow.py`.
- [x] T021 [US1] Exécuter `cargo test --test v2_api --test multiway`.
- [x] T022 [US3] Mettre à jour `docs/PHASE1_BASELINE_2026-11-14.md`, l'audit et le registre de migration.

## Dépendances

- Spec 001 terminée (range héros complète).
- T001–T006 avant T007–T016.
- T012 vérifie le moteur existant, ne le réécrit pas.
- T017–T022 après l'implémentation.

## Critère de fin

- [x] Les spots 3–6 way utilisent le chemin multiway ou un fallback étiqueté. → backend `multiway_mccfr` pour 3–6 joueurs ; mode strict `multiway_strict_refused`, états invalides `multiway_not_supported`.
- [x] Zéro approximation HU silencieuse. → warning explicite sur chaque réponse multiway, `converged=false` étiqueté, journalisation du mode et du nombre de joueurs.
- [x] HU inchangé. → chemin HU conservé pour `num_players <= 2` ; tests de non-régression verts.
- [x] Tests Rust et Python verts. → 19/11/2026 : Rust 130 passed (4 ignored), Python 1 231 passed / 5 skipped.
- [x] Benchmark documenté par nombre de joueurs. → `research/results/runtime_multiway_benchmark.json` : 40 mesures (3/4/5/6 joueurs × froid/chaud × 5), 0 fallback, 40/40 `sampled=true`, p95 froid 601,5 / 200,1 / 143,9 / 80,8 ms pour 3 / 4 / 5 / 6 joueurs, mémoire RSS max 191,5 Mo.

## État au 19/11/2026 — clôturée

Spec livrée et vérifiée : le runtime transmet `num_players`, `villain_ranges`,
`hero_player_index` et `active_positions` au solveur, les spots 3–6 utilisent le
MCCFR multiway natif avec étiquetage complet (`sampled=true`,
`converged=false`, warning), le mode strict refuse au lieu d'approximer, et le
cache distingue les configurations de joueurs. Le constat F-02 de l'audit est
clos (§8, « Clôture Sprint 0 »). Tous les critères de fin ci-dessus sont
vérifiés sur l'arbre courant.
