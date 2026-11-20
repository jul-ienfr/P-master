# Tasks: Observabilité — traces par étage, SLO et registre de versions

**Input**: `specs/008-observability-slo/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, audit §3.8, constat F-10

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test de timer : étages mesurés ≥ 0, total cohérent, étages imbriqués rapportés tels quels.
- [x] T002 [P] [US1] Test d'instrumentation : une décision du chemin instrumenté porte `stages_ms` non vide et **aucune clé ajoutée** au payload de décision comparé par les rejeux.
- [x] T003 [P] [US1] Test de résumé : percentiles par étage ; enregistrement sans `stages_ms` toujours valide et aucun étage inventé.
- [x] T004 [P] [US2] Test de SLO : objectif tenu `ok`, objectif franchi `breached` avec alerte nommée (objectif, valeur, cible, sévérité).
- [x] T005 [P] [US2] Test d'effectif : effectif nul ou sous `min_samples` → `insufficient_data`, jamais `ok` ; cible absente → `ignored` avec raison.
- [x] T006 [P] [US2] Test de vacuité : aucun objectif configuré → ensemble vide, aucune fausse alerte.
- [x] T007 [P] [US3] Test de versions : bloc `versions` présent, version indisponible à `None`, tailles de mise distinguées.
- [x] T008 [P] [US3] Test de schéma : schéma courant accepté, schéma antérieur connu accepté et signalé, schéma inconnu signalé.
- [x] T009 [P] [US4] Test d'indépendance : un SLO franchi ne change pas le verdict du gate go-live (non-régression).
- [x] T010 [P] [US1] Test de coût : le timer est mesuré (< 1 µs par étage) — le surcoût est mesuré, pas supposé.

## Phase 2: Implémentation

- [x] T011 [US1] Créer `src/runtime/stage_timing.py` : `StageTimer`, `percentile`, `summarize_stage_timings`.
- [x] T012 [US1] Instrumenter les six étages de `DecisionMaker.get_best_action` (`profile`, `ranges`, `rl`, `solver`, `exploit`, `assemble`) dans `metadata`.
- [x] T013 [US1] Ajouter `stages_ms` à `DECISION_FIELDS`, `record_from_runtime_trace` et au résumé (`summarize_decision_records`).
- [x] T014 [US2] Créer `src/runtime/slo.py` : `SloObjective`, `DEFAULT_SLO_OBJECTIVES`, `evaluate_slo`, `slo_metrics_from_history`, `breached_names`.
- [x] T015 [US2] Exposer le bloc `slo` dans `_build_runtime_bridge_state` et `_get_runtime_status` ; alerte de transition `slo_breached`/`slo_recovered`.
- [x] T016 [US3] Ajouter le bloc `versions` à `build_decision_record` (schéma, blueprint, modèle de range, tailles de mise), indisponible → `None`.
- [x] T017 [US3] Ajouter `KNOWN_SCHEMA_VERSIONS` et `schema_status` ; accepter tout schéma connu dans `validate_decision_record`.

## Phase 3: Validation

- [x] T018 [US1] Exécuter les trois fichiers de tests nouveaux (verts).
- [x] T019 [US1] Vérifier la non-régression des rejeux golden : `tests/test_runtime_decision_replays.py` (vert, payload inchangé).
- [x] T020 [US2] Vérifier la non-régression du gate et du snapshot : `tests/test_main_decision_gate_replay.py`, `tests/test_operator_snapshot_full.py` (verts).
- [x] T021 [US3] Exécuter la suite Python complète et `ruff check` (verts).
- [x] T022 [US4] Exécuter `cargo test --lib` et `cargo fmt --check` (inchangés, aucun code Rust touché).
- [x] T023 Mettre à jour l'audit §3.8/§6.2/§8/§9 et le registre de migration (statut F-10).

## Dépendances

- T001–T010 avant T011–T017 (tests rouges d'abord).
- T011 avant T012–T013 (le timer précède son usage).
- T014 avant T015 (l'évaluation précède son exposition).
- T016 avant T017 (le bloc précède sa validation).
- Indépendante des specs `001`, `002`, `004`, `005`, `010`, `011` ; consomme les métriques et le journal existants.

## Critère de fin

- [ ] Une décision du chemin instrumenté porte `stages_ms` avec les étages traversés, sans clé ajoutée au payload comparé par les rejeux.
- [ ] Le résumé d'un journal rapporte les percentiles par étage et reste valide sans `stages_ms`.
- [ ] Un SLO franchi produit une alerte nommée ; des métriques dans les cibles n'en produisent aucune ; un effectif insuffisant donne `insufficient_data`.
- [ ] Chaque enregistrement porte un bloc `versions` ; un schéma antérieur connu est accepté et signalé, un schéma inconnu reste une erreur.
- [ ] Le gate go-live reste inchangé ; `pytest`, `ruff`, `cargo test` et `cargo fmt` verts.
