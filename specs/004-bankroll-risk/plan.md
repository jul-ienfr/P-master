# Implementation Plan: Moteur de bankroll et de risque

**Branch**: `004-bankroll-risk` | **Date**: 2026-11-20 | **Spec**: `specs/004-bankroll-risk/spec.md`

## Summary

Migrer la gestion de bankroll du Python (`src/bot/session_manager.py`, trois constantes) vers un moteur Rust pur, déterministe et testé contre les formes fermées de `docs/probabilites.md` §2 et §6. Le module `src/bankroll.rs` fournit le calcul (RoR, P(profit), Kelly, bankroll cible, move-up/down, limites de session) ; les bindings PyO3 l'exposent au runtime, qui conserve la seule responsabilité de l'alimentation en données et de la journalisation.

## Technical Context

**Language/Version**: Rust stable (édition du crate), Python 3.11
**Primary Dependencies**: aucune nouvelle — `f64::exp`/`ln`/`sqrt` de la std ; PyO3 pour l'exposition
**Storage**: aucun — fonctions pures ; la persistance du journal reste au runtime
**Testing**: `cargo test --lib bankroll`, `pytest tests/test_bankroll.py`
**Target Platform**: Windows, runtime local
**Project Type**: crate natif + runtime Python
**Performance Goals**: coût négligeable (arithmétique scalaire) ; contrainte réelle = déterminisme
**Constraints**: unités buy-ins obligatoires ; `f32` pour les valeurs, `f64` pour `Φ` ; aucune panique sur entrée invalide
**Scale/Scope**: quelques dizaines d'appels par session ; un enregistrement d'audit par changement de limite

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | Chaque formule est testée contre la valeur tabulée du doc ; l'erreur de `Φ` est bornée et documentée |
| II. Rust-first | Le calcul migre du Python vers `src/bankroll.rs` ; le Python ne garde que l'I/O |
| III. Latence | Arithmétique scalaire, aucun impact sur le budget de décision |
| IV. Fail-closed | Entrée invalide → `None` ; jamais de RoR inventé ; règle invalide → `Stay` |
| VI. Tests | 16 tests unitaires Rust + tests de parité Python ; valeurs de référence des docs |
| IX. Source unique | Une seule implémentation du RoR, en Rust ; le Python n'en duplique aucune |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Moteur Rust (`src/bankroll.rs`)

Module pur, sans état, sans dépendance CFR :

- `risk_of_ruin(edge_bi, variance_bi2, roll_bi) -> Option<f32>` — forme canonique.
- `risk_of_ruin_cash(wr_bb, sigma_bb, roll_bi)` / `risk_of_ruin_mtt(roi, sigma_bi, roll_bi)` — conversions d'unités faites ici, pour que l'appelant reste en unités naturelles.
- `bankroll_for_target_ror(edge, variance, target)` — inverse, sert à justifier le seuil de 40 BI.
- `norm_cdf` via `erf` (Abramowitz & Stegun 7.1.26, erreur ≤ 1,5·10⁻⁷), exposé avec sa constante d'erreur.
- `probability_of_profit_cash` / `_mtt`.
- `kelly_fraction`.
- `MoveRule` + `decide_move` — hystérésis, bornes d'échelle.
- `SessionLimits` + `session_verdict` — ordre de priorité déterministe.
- `risk_band`, `assess`, `assess_cash` — agrégat journalisable.

Choix de conception : les fonctions retournent `Option` plutôt que de paniquer. Un RoR indéfini est une information, pas une erreur de programme ; l'appelant décide (afficher « indéfini » ou refuser de conseiller).

### 2. Bindings PyO3 (`python_bindings/src/lib.rs`)

Exposer `risk_of_ruin_cash`, `risk_of_ruin_mtt`, `bankroll_for_target_ror`, `probability_of_profit_cash`, `probability_of_profit_mtt`, `kelly_fraction`, `session_verdict` et un `assess_cash` renvoyant un dict. Les enums deviennent des chaînes (`"safe"`, `"move_up"`, `"max_duration"`) pour rester lisibles dans le journal.

### 3. Intégration runtime

- `src/bot/session_manager.py` conserve la boucle et l'état de session ; ses seuils sont lus depuis `SessionLimits` (défauts identiques : 4 h, −3 BI, +10 BI) au lieu d'être redéclarés.
- Un nouveau `src/bot/bankroll.py` enveloppe les bindings : il alimente winrate/σ depuis les mesures, appelle `assess_cash`, et écrit une ligne d'audit par changement de limite.
- Aucun changement de comportement par défaut : mêmes seuils de session qu'aujourd'hui, plus les informations nouvelles (RoR, bande, cible).

### 4. Journal d'audit

Une ligne JSONL par évaluation : `{ts, format, roll_bi, edge, variance, ror, band, kelly, decision, stop_reason}`. Le schéma est stable et testé (un test vérifie que tous les champs sont présents et sérialisables).

### 5. Tests

1. `Φ` : points connus, symétrie, queues.
2. RoR : tables du doc (§6.1 HU, §6.2 6-max ×2, §6.3 MTT).
3. Entrées dégénérées et edge nul/négatif.
4. Monotonie (bankroll, edge, mains).
5. Inverse du RoR (aller-retour 10⁻⁵) + seuil 40 BI < 1 %.
6. P(profit) : tables §2.1/§2.2, croissance avec N.
7. Kelly : valeur, bornes, cas invalides.
8. Move-up/down : zone morte, bornes, règle invalide.
9. Session : chaque motif, priorité.
10. Parité Python ↔ Rust sur un jeu de valeurs.

## Structure des fichiers

```text
src/bankroll.rs                    # moteur (livré)
src/lib.rs                         # enregistrement du module + réexports (livré)
python_bindings/src/lib.rs         # exposition PyO3
src/bot/bankroll.py                # enveloppe runtime + journal d'audit
src/bot/session_manager.py         # seuils lus depuis SessionLimits
tests/test_bankroll.py             # parité et contrat Python
docs/probabilites.md               # référence (inchangé ; source de vérité)
docs/rust-migration-ledger.md      # statut Python → Rust
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Erreur d'unités (bb ↔ BI) | Conversion centralisée dans `risk_of_ruin_cash`/`_mtt`, testée contre les tables du doc |
| Approximation de `Φ` trop grossière | Erreur bornée à 1,5·10⁻⁷, testée ; suffisant pour des probabilités affichées à 1 % |
| Régression de comportement de session | Défauts identiques à `session_manager.py`, test de non-régression dédié |
| Winrate d'entrée irréaliste | Le moteur ne juge pas la qualité de l'entrée ; la spec `003` la produit, le doc la borne |
| Dérive des formules vs doc | Chaque valeur tabulée du doc est un test ; un écart fait échouer la CI |

## Portes de qualité

- `cargo test --lib bankroll` — 16 tests.
- `cargo clippy -- -D warnings` sur le module.
- `uv run pytest tests/test_bankroll.py`.
- `uv run ruff check src/bot/bankroll.py`.
- Parité Python ↔ Rust vérifiée sur les valeurs de référence.

## Complexity Tracking

Aucune complexité ajoutée : le module est une collection de fonctions pures. La seule structure non triviale (`BankrollAssessment`) est justifiée par la journalisation d'audit, qui exige un enregistrement unique et complet plutôt que cinq appels séparés.
