# Tasks: Contrat de plateforme multi-site

**Input**: `specs/005-vision-multi-site/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, ADR-001, constat F-06

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test du registre : PokerStars et Winamax résolus, clé inconnue → `ValueError`, clé vide → défaut.
- [x] T002 [P] [US1] Test que les métadonnées de fenêtre Winamax non observées restent `None` (pas de valeur inventée).
- [x] T003 [P] [US1] Test de résolution de site depuis un titre, déterministe, titre inconnu → défaut.
- [x] T004 [P] [US4] Test de conformité : chaque adaptateur exposé satisfait le contrat (champs typés).
- [x] T005 [P] [US4] Test qu'un adaptateur sans manifeste présent retourne un tuple vide, sans lever.
- [x] T006 [P] [US2] Test des montants de fixture par site → valeur attendue.
- [x] T007 [P] [US2] Test de falsification : un format contredisant ses fixtures échoue la conformité.
- [x] T008 [P] [US3] Test des limites : refus sous minimum, minimum accepté, tapis, arrondi, entrée invalide.
- [x] T009 [P] [US1] Test de non-régression : comportement `PokerStarsAdapter` inchangé (play money sans décimales).

## Phase 2: Implémentation

- [x] T010 [US1] Étendre `SiteAdapterProtocol` : `window_profile`, `action_limits`, `amount_parser()`.
- [x] T011 [US1] Ajouter `WindowProfile` (titre, regex, classe, process, blinde, motif de limite) et `FormatProfile` conservé.
- [x] T012 [US1] Ajouter `WinamaxAdapter` (format européen, métadonnées de fenêtre `None`).
- [x] T013 [US1] Compléter `PokerStarsAdapter` avec `window_profile`, `action_limits`, `amount_parser()`.
- [x] T014 [US1] Créer le registre `SITE_ADAPTERS`, `available_site_keys()`, et lever sur clé inconnue.
- [x] T015 [US1] Ajouter `resolve_site_from_title()` à ordre déterministe.
- [x] T016 [US2] Construire le parseur depuis `FormatProfile` (`_parser_from_format`) — source unique du format.
- [x] T017 [US3] Créer `src/vision/action_limits.py` : `ActionLimits`, `BetAmountVerdict`, `validate_bet_amount`.
- [x] T018 [US1] Remplacer le littéral `"pokerstars"` dans `table_manager.py` et `frame_pipeline.py` par la configuration.
- [x] T019 [US1] Ajouter `bot.active_site` à `config.json` et la surcharge `POKER_ACTIVE_SITE` à `src/config.py` + `.env.example`.
- [x] T020 [US1] Résoudre le site dans `action_controller.py` via le registre, puis surcharge `site_profiles`.
- [x] T021 [US1] Aligner `src/scripts/capture_dataset.py` sur le registre (source unique).

## Phase 3: Validation

- [x] T022 [US4] Créer les fixtures `tests/fixtures/site_amounts/{pokerstars,winamax}.json`.
- [x] T023 [US4] Écrire `tests/test_site_adapter_registry.py` (21 tests).
- [x] T024 [US1] Vérifier l'absence de littéral de site dans le chemin d'exécution hors défaut de configuration.
- [x] T025 Exécuter la suite Python complète (1279 passés) et `ruff` (vert).
- [x] T026 Exécuter `cargo test --lib` (75 passés) et `cargo fmt --check` (propre).
- [x] T027 Mettre à jour `docs/rust-migration-ledger.md`, l'audit §3.6 et §9 (statut F-06).

## Dépendances

- T001–T009 avant T010–T021 (tests rouges d'abord).
- T014 avant T015, T018, T020 (le registre précède ses consommateurs).
- T022 avant T023 (les fixtures alimentent le test de conformité).
- Aucune dépendance sur les specs 001–004 ; cette spec est indépendante.

## Critère de fin

- [x] Deux sites livrés et résolus par un registre ; clé inconnue lève.
- [x] Le site n'est plus codé en dur dans le chemin d'exécution.
- [x] Le format de montants est déclaré une fois et consommé par le parseur.
- [x] Les limites d'action bornent une taille de mise avec un verdict explicite.
- [x] Les fixtures par site et le test de conformité sont versionnés et falsifiables.
- [x] `pytest`, `ruff`, `cargo test` et `cargo fmt` verts ; comportement PokerStars inchangé.
