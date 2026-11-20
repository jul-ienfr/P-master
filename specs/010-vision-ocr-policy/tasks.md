# Tasks: Politique OCR par site et preuve de vision

**Input**: `specs/010-vision-ocr-policy/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, ADR-001, constat F-08

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test de politique : défaut à deux moteurs ; politique par site ; site inconnu → défaut.
- [x] T002 [P] [US1] Test de rejet : moteur inconnu (principal et fallback) lève ; plus de deux moteurs lève.
- [x] T003 [P] [US1] Test d'alignement : `SUPPORTED_ENGINES` == `SUPPORTED_OCR_ENGINES`.
- [x] T004 [P] [US1] Test de repli : principal indisponible → fallback ; les deux indisponibles → sélection vide.
- [x] T005 [P] [US2] Test de statut : zéro échantillon → `unmeasured` avec taux `None` ; tous réussis → `green` ; un échec → `red`/`yellow`.
- [x] T006 [P] [US2] Test de non-régression : les manifestes livrés ne sont plus `green` sans échantillon.
- [x] T007 [P] [US3] Test de harnais : sans capture → `unmeasured`/`None` ; étiquettes absentes → non évaluable.
- [x] T008 [P] [US3] Test de comptage : champ illisible et exception du lecteur comptés comme échecs, jamais exclus.
- [x] T009 [P] [US3] Test d'exactitude : précision et effectif exacts sur échantillons étiquetés, par champ.
- [x] T010 [P] [US4] Test de câblage : quatre moteurs ramenés à la politique du site ; surcharge explicite à deux moteurs honorée.

## Phase 2: Implémentation

- [x] T011 [US1] Créer `src/vision/ocr_policy.py` : `OCREnginePolicy`, `SITE_OCR_POLICIES`, `policy_for_site`, `validate_engine_selection`, `clamp_to_policy`.
- [x] T012 [US1] Ajouter `site_key` à `PokerOCR.__init__` et `_apply_ocr_policy` (réduction tracée, jamais silencieuse).
- [x] T013 [US1] Propager `site_key` à `PokerOCR.from_config`.
- [x] T014 [US1] Exposer la politique et les moteurs indisponibles dans les métadonnées (FR-011).
- [x] T015 [US1] Transmettre `bot.active_site` aux trois instances OCR dans `src/main.py`.
- [x] T016 [US2] Créer `src/vision/preset_validation.py` : `ValidationOutcome`, `compute_validation_status` (`unmeasured` avec taux `None`).
- [x] T017 [US2] Faire consommer la source unique par `poker/tools/room_manager.py` ; supprimer le type homonyme du laboratoire.
- [x] T018 [US2] Corriger les deux manifestes livrés : `green`/`1.0`/`0` → `unmeasured`/`null`/`0`.
- [x] T019 [US3] Créer `src/vision/vision_benchmark.py` : mesure par champ, échecs jamais exclus, `unmeasured` sans capture.
- [x] T020 [US3] Créer `scripts/vision_benchmark.py` : point d'entrée opérateur, artefact daté, message honnête si non mesuré.

## Phase 3: Validation

- [x] T021 [US4] Exécuter la suite Python complète (1318 passés, 5 ignorés) et `ruff check` (vert).
- [x] T022 [US4] Exécuter `cargo test --lib` (75 passés) et `cargo fmt --check` (propre) — aucun code Rust touché.
- [x] T023 [US3] Vérifier le harnais de bout en bout : sans capture → `unmeasured` ; avec captures synthétiques → `measured`, effectif exact, capture manquante non évaluable.
- [x] T024 [US4] Vérifier la non-régression du laboratoire : `poker/tests/test_room_manager.py` (5 passés).
- [x] T025 Mettre à jour l'audit §3.1, §3.6, §9 et le registre de migration (statut F-08).

## Dépendances

- T001–T010 avant T011–T020 (tests rouges d'abord).
- T011 avant T012–T015 (la politique précède son câblage).
- T016 avant T017–T018 (la source unique précède ses consommateurs).
- T019 avant T020 (le harnais précède son point d'entrée).
- Dépend de la spec `005` (site actif en configuration) ; indépendante des specs `001`, `002`, `004`.

## Critère de fin

- [x] Le runtime charge au plus un principal et un fallback, choisis par la politique du site.
- [x] Une politique invalide est rejetée ou réduite avec trace, jamais chargée en silence.
- [x] Un preset sans échantillon évalué est `unmeasured` avec taux `None`, jamais `green`.
- [x] Le harnais mesure la précision par site sur captures étiquetées et dit « non mesuré » sans capture.
- [x] Un champ illisible est un échec compté, pas une exclusion silencieuse.
- [x] `pytest`, `ruff`, `cargo test` et `cargo fmt` verts ; comportement PokerStars inchangé.
