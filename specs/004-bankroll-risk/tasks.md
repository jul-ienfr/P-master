# Tasks: Moteur de bankroll et de risque

**Input**: `specs/004-bankroll-risk/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md, `docs/probabilites.md` §2/§6, `docs/ordre-conseille.md`

## Phase 1: Tests rouges

- [x] T001 [P] [US1] Test de `Φ` contre les points connus et la symétrie dans `src/bankroll.rs`.
- [x] T002 [P] [US1] Test RoR cash 6-max WR7/σ90/40BI = 0,10 % (§6.2).
- [x] T003 [P] [US1] Test RoR cash HU WR5/σ70/20BI = 1,69 % (§6.1) et 6-max WR5/20BI = 8,49 % (§6.2).
- [x] T004 [P] [US1] Test RoR MTT ROI15 %/σ1,9BI/50BI = 1,57 % (§6.3).
- [x] T005 [P] [US1] Test des entrées dégénérées → `None` ; edge nul/négatif → 1,0.
- [x] T006 [P] [US1] Test de monotonie en bankroll et en edge.
- [x] T007 [P] [US1] Test de l'inverse du RoR (aller-retour 10⁻⁵) et du seuil 40 BI < 1 %.
- [x] T008 [P] [US4] Test P(profit) 6-max 50k = 96 %, 10k = 78 %, HU 10k = 76 % (§2).
- [x] T009 [P] [US4] Test de croissance de P(profit) avec le nombre de mains.
- [x] T010 [P] [US1] Test Kelly : valeur, bornes, cas invalides.
- [x] T011 [P] [US2] Test move-up/down : zone morte, bornes d'échelle, règle invalide.
- [x] T012 [P] [US3] Test des limites de session : chaque motif et la priorité.

## Phase 2: Implémentation

- [x] T013 [US1] Créer `src/bankroll.rs` : `risk_of_ruin`, `_cash`, `_mtt`, `bankroll_for_target_ror`.
- [x] T014 [US4] Implémenter `norm_cdf` (erf A&S 7.1.26) et `probability_of_profit_cash`/`_mtt`.
- [x] T015 [US1] Implémenter `kelly_fraction` et `risk_band`.
- [x] T016 [US2] Implémenter `MoveRule` et `decide_move` (hystérésis + bornes).
- [x] T017 [US3] Implémenter `SessionLimits`, `session_verdict`, `StopReason`, `SessionVerdict`.
- [x] T018 [US1] Implémenter `assess` / `assess_cash` (enregistrement journalisable).
- [x] T019 [US1] Enregistrer `pub mod bankroll` et les réexports dans `src/lib.rs`.
- [x] T020 [US1] Exposer les fonctions via PyO3 dans `python_bindings/src/lib.rs`.
- [x] T021 [US1] Créer `src/bot/bankroll.py` : enveloppe runtime + journal d'audit JSONL.
- [x] T022 [US3] Faire lire les seuils de `session_manager.py` depuis `SessionLimits`.

## Phase 3: Validation

- [x] T023 [US1] Test de parité Python ↔ Rust sur le jeu de valeurs de référence dans `tests/test_bankroll.py`.
- [x] T024 [US1] Test du schéma du journal d'audit (tous les champs présents et sérialisables).
- [x] T025 [US3] Test de non-régression : les seuils par défaut de session sont inchangés (4 h, −3 BI, +10 BI).
- [x] T026 Exécuter `cargo test --lib bankroll` et `cargo clippy -- -D warnings`.
- [x] T027 Exécuter `uv run pytest tests/test_bankroll.py` et `uv run ruff check`.
- [x] T028 Mettre à jour `docs/rust-migration-ledger.md` et l'audit §3.5 (statut F-07).

## Dépendances

- T001–T012 avant T013–T018 (tests rouges d'abord).
- T019 avant T020 (le module doit être public pour les bindings).
- T020 avant T021 (l'enveloppe Python appelle les bindings).
- T023–T025 après T021.
- Spec `003` (preuve de winrate) fournit les entrées réelles ; T021 fonctionne avec des entrées de test en attendant.

## Critère de fin

- [x] Les valeurs tabulées du doc §2 et §6 sont reproduites par des tests automatisés.
- [x] Le RoR est calculé en Rust, sans duplication Python.
- [x] Les règles move-up/down et les limites de session sont déterministes et testées.
- [x] Chaque évaluation est journalisable pour l'audit.
- [x] `cargo test`, `cargo clippy`, `pytest` et `ruff` verts.
- [x] `docs/rust-migration-ledger.md` marque « Bankroll et risque » comme migré.
