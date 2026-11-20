# Tasks: Schedules d'hyperparamètres CFR et mesure de convergence

**Input**: `specs/012-cfr-hyperparameter-schedules/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, audit constat F-12, traçabilité C16

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test de non-régression du défaut : `DiscountParams::new(t)` produit les valeurs d'avant la spec pour `t` = 0, 1, 2, 10, 100 (le défaut ne bouge pas).
- [x] T002 [P] [US1] Test de sélection : `DiscountSchedule::from_str` accepte `dcfr`, `hs_dcfr_30`, `hs_dcfr_15` (casse/espaces tolérés) et **rejette** un nom inconnu avec une erreur explicite.
- [x] T003 [P] [US1] Test de formule : `for_schedule(HsDcfr30, t, n)` vaut `α = 1 + 3t/n`, `β = −1 − 2t/n`, `γ = 30 − 5t/n` ; `HsDcfr15` vaut `γ = 15 − 5t/n` (points de contrôle numériques).
- [x] T004 [P] [US1] Test de finitude : pour tout `t` dans `0..=n` et tout schedule, `alpha_t`/`beta_t`/`gamma_t` sont finis et dans une plage bornée ; `t = 0` ne produit ni `NaN` ni `∞`.
- [x] T005 [P] [US1] Test de parité compressé/non compressé : un même petit jeu résolu avec un schedule HS donne la même stratégie dans les deux modes.
- [x] T006 [P] [US2] Test de convergence Kuhn : pour chaque schedule, la valeur de jeu atteint `−1/18` à la tolérance du test existant.
- [x] T007 [P] [US2] Test de convergence Leduc : pour chaque schedule, la valeur de jeu atteint `−0,0856` à la tolérance du test existant.
- [x] T008 [P] [US2] Test de rapport : le rapport de mesure porte date, itérations, tolérance, valeur de référence, échantillons par palier, et un verdict qui ne dépasse pas ce qui a été mesuré.
- [x] T009 [P] [US1] Test de propagation Python : `discount_schedule` traverse `_NATIVE_SOLVE_KEYS` et n'est pas supprimé avant l'appel natif.
- [x] T010 [P] [US1] Test de traçabilité : le schedule appliqué apparaît dans `metadata["discount_schedule"]` de la réponse.

## Phase 2: Implémentation

- [x] T011 [US1] `src/solver.rs` : ajouter `DiscountSchedule` (énumération + `from_str` + `Display`) sans toucher `DiscountParams::new`.
- [x] T012 [US1] `src/solver.rs` : ajouter `DiscountParams::for_schedule(schedule, t, n)` ; `Dcfr` délègue à `new(t)` ; `t = 0` traité explicitement.
- [x] T013 [US1] `src/solver.rs` : `solve_with_deadline_storing` et `solve_step` prennent le schedule (défaut `Dcfr`) et passent `n = max_num_iterations`.
- [x] T014 [US1] `src/gto_api.rs` : champ `discount_schedule: Option<String>` sur `SolveRequest`, transmis à l'appel solveur.
- [x] T015 [US1] `src/v2_api.rs` : champ sur `SolveRequestV2`, propagation dans `to_legacy_solve_request`, et pose dans `metadata["discount_schedule"]`.
- [x] T016 [US1] `python_bindings/src/lib.rs` : paramètre `discount_schedule` dans la signature PyO3 et la construction de la requête.
- [x] T017 [US1] `src/solver/provider.py` : `discount_schedule` dans `_NATIVE_SOLVE_KEYS`.
- [x] T018 [US1] `src/bot/decision_maker.py` : transmission depuis la configuration, défaut `None`.
- [x] T019 [US2] `tests/cfr_schedule_convergence.rs` : harnais de mesure à paliers d'itérations sur Kuhn et Leduc.
- [x] T020 [US2] `examples/cfr_schedule_benchmark.rs` : point d'entrée opérateur qui écrit `research/results/cfr_schedule_benchmark.json`.
- [x] T021 [US3] `docs/etudes.md` : corriger la fiche C16 (arXiv 2404.09097, Zhang/McAleer/Sandholm, AAAI 2026 ; chiffres réels ; recommandation HS-DCFR(30) pour les grands jeux de poker).
- [x] T022 [US3] `config.json` : retirer la clé inerte `solver.hs_pcf_30_enabled`.
- [x] T023 [US3] `docs/AUDIT_COMPLET_2026-11-17.md` : mettre à jour F-12 et la table de traçabilité §5.

## Phase 3: Validation

- [x] T024 [US1] `cargo test` (lib + intégration) vert, y compris Kuhn/Leduc sous chaque schedule.
- [x] T025 [US1] `cargo fmt --check` et `cargo clippy` verts sur le code modifié.
- [x] T026 [US1] `uv run pytest` complet vert (non-régression) et `uv run ruff check src tests scripts poker/tools`.
- [x] T027 [US1] Gate de performance F-09 vert (`scripts/check_perf_gate.py`), défaut inchangé.
- [x] T028 [US2] Produire l'artefact `research/results/cfr_schedule_benchmark.json` et vérifier qu'il est lisible et daté.

## Phase 4: Défauts trouvés en validation (ajoutés en cours de route)

- [x] T029 [US1] `src/gto_api.rs` : `solve_cache_key` inclut le schedule — sans quoi le cache natif sert une stratégie DCFR à une requête HS-DCFR (défaut de fond, même classe que la clé de cache Python). Test rouge d'abord : `tests/gto_api.rs::gto_cache_key_separates_discount_schedules`.
- [x] T030 [US1] FR-016 : définir l'interaction mode strict × schedule non défaut (neutre : le schedule change la vitesse, jamais le critère de verdict) et la verrouiller par `tests/v2_api.rs::strict_mode_accepts_a_non_default_schedule_with_an_honest_verdict`. Définition reportée dans `spec.md` (Edge Cases) et `plan.md` (§2).
- [x] T031 [US1] T005 renforcé : la parité compressé/non compressé compare la **stratégie** normalisée par main (ce que T005 demande), pas seulement la valeur de jeu — deux stratégies distinctes peuvent partager une valeur de jeu à la racine.

## Dépendances

- T001–T010 avant T011–T020 (tests rouges d'abord).
- T011 avant T012 (l'énumération précède la fabrique de paramètres).
- T012 avant T013 (les paramètres avant la boucle).
- T013 avant T014–T016 (le cœur avant la propagation).
- T014/T015 avant T016 (le contrat Rust avant le binding).
- T016/T017 avant T009/T018 (le câblage avant le test de traversée).
- T019 avant T020 (le harnais avant le point d'entrée).
- T024–T028 après l'implémentation complète.
- Indépendante des specs `001`, `002`, `004`, `005`, `008`, `010`, `011`.

## Critère de fin

- [x] Sans sélection, le solveur produit exactement les sorties d'avant la spec (test de non-régression sur un spot rejoué).
- [x] `hs_dcfr_30` et `hs_dcfr_15` sont sélectionnables par la requête, rejetés s'ils sont inconnus, tracés dans les métadonnées, et atteignent les valeurs de référence de Kuhn et Leduc.
- [x] Un artefact daté rapporte l'exploitabilité par palier pour le défaut et HS-DCFR(30) sur Kuhn et Leduc, sans affirmer de gain non mesuré.
- [x] La fiche C16 ne cite plus d'identifiant arXiv invalide et recommande la variante que l'article recommande pour le poker.
- [x] `config.json` ne contient plus de clé de schedule sans effet.
- [x] `cargo test`, `cargo fmt --check`, `pytest`, `ruff` et le gate F-09 sont verts.
