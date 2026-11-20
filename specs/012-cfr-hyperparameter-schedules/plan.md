# Implementation Plan: Schedules d'hyperparamètres CFR et mesure de convergence

**Branch**: `012-cfr-hyperparameter-schedules` | **Date**: 2026-11-20 | **Spec**: `specs/012-cfr-hyperparameter-schedules/spec.md`

## Summary

Rendre le schedule de discount du solveur **sélectionnable** (défaut strictement inchangé), implémenter `HS-DCFR(30)` et `HS-DCFR(15)` selon les formules publiées, et livrer un **harnais de mesure de convergence** sur les jeux de test Kuhn et Leduc déjà présents. Corriger au passage la référence C16 (deux identifiants arXiv faux, variante recommandée erronée) et retirer la clé de configuration inerte.

## Technical Context

**Language/Version**: Rust (edition 2021, toolchain stable en CI) + Python 3.11
**Primary Dependencies**: aucune nouvelle — le schedule est une énumération et quatre expressions arithmétiques ; le harnais réutilise `solve_with_deadline`/`compute_exploitability`
**Storage**: `research/results/cfr_schedule_benchmark.json` (artefact daté, versionnable)
**Testing**: `cargo test` (tests de convergence existants + nouveaux tests de schedule), `pytest` (non-régression), gate F-09
**Target Platform**: Windows en exécution, Linux en CI
**Project Type**: crate natif + runtime Python
**Performance Goals**: **aucun surcoût mesurable** — le schedule est un calcul de trois `f32` par itération, à côté d'un parcours d'arbre complet. La mesure Kuhn/Leduc doit tenir en secondes.
**Constraints**: défaut bit-à-bit inchangé ; `cargo fmt --check` et `clippy` verts sur le code modifié ; aucune dépendance nouvelle
**Scale/Scope**: 3 schedules, 2 jeux de mesure, 1 artefact

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | La fiche C16 est corrigée : identifiants réels, chiffres réels, variante recommandée par l'article. La mesure est produite, pas supposée ; un schedule qui ne gagne pas est déclaré tel quel (FR-012) |
| II. Rust-first | Tout le calcul du schedule est en Rust, dans le chemin chaud ; aucun calcul déplacé en Python |
| III. Latence | Le défaut est inchangé (FR-001) ; le surcoût du schedule est trois `f32` par itération, négligeable devant un parcours d'arbre — mesuré, pas supposé |
| IV. Fail-closed | Un schedule inconnu est **rejeté** (FR-004), jamais ramené au défaut ; un paramètre non fini est impossible (FR-006) |
| V. Modularité | Le schedule est une énumération à côté de `DiscountParams` ; `DiscountParams` reste la seule structure lue par la boucle de mise à jour |
| VI. Test-first | Tests de non-régression du défaut **avant** l'ajout des schedules ; tests de convergence Kuhn/Leduc sous chaque schedule ; valeurs de référence déjà vérifiées contre OpenSpiel |
| IX. Source unique | `DiscountSchedule` est la seule source du choix ; la clé `config.json` inerte est supprimée (une clé qui n'a pas d'effet est une seconde source de vérité qui ment) |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Schedule sélectionnable (`src/solver.rs`)

`DiscountSchedule` — énumération `Dcfr` (défaut), `HsDcfr30`, `HsDcfr15` — avec `from_str` explicite (rejet de l'inconnu) et `Display` pour la traçabilité.

`DiscountParams::new(t)` reste **inchangé** : c'est le comportement du défaut, et il ne doit pas bouger. Une fonction nouvelle `DiscountParams::for_schedule(schedule, t, n)` produit les paramètres :

- `Dcfr` → délègue à `new(t)` (aucune duplication de la formule existante) ;
- `HsDcfr30` / `HsDcfr15` → `α = 1 + 3·t/n`, `β = −1 − 2·t/n`, `γ = (30|15) − 5·t/n`.

**Point d'attention sur `t = 0`.** À `t = 0`, `β = −1`, et la mise à jour des regrets multiplie les regrets négatifs par `t^β` : `0^(−1)` n'est pas défini. Le code doit traiter `t = 0` comme une itération sans discount (première itération : rien à discount, la stratégie cumulée est vide), exactement comme le fait déjà `DiscountParams::new(0)` où `t_alpha = 0` donne `α = 0` et `γ = 0`. Choix explicite, testé (FR-006).

**Reset périodique.** Le DCFR du crate remet `t_γ` à zéro à chaque puissance de 4. Pour les schedules HS, `t` est l'itération **absolue** (c'est ce que dit l'article : `t` est l'itération courante, `n` le total). Le reset de la stratégie cumulée reste un comportement du chemin DCFR : un test vérifie que les deux chemins (compressé/non compressé) donnent le même résultat (FR-007), et le choix est documenté en commentaire.

Le paramètre `n` est passé à la boucle depuis `max_num_iterations`. En mode budget, `n` est le plafond (voir Edge Cases de la spec) — le schedule est alors une heuristique de décroissance sur le plafond, ce qui est cohérent avec son usage en mode itérations fixées.

### 2. Propagation du contrat

- `gto_api::SolveRequest` (`src/gto_api.rs`) : champ `discount_schedule: Option<String>` avec `#[serde(default)]`, `None` → `Dcfr`.
- `SolveRequestV2` (`src/v2_api.rs`) : même champ, transmis à `to_legacy_solve_request`.
- `python_bindings/src/lib.rs` : paramètre `discount_schedule: Option<String>` dans `solve_spot_v2`, ajouté à la signature PyO3 et à la construction de la requête.
- `src/solver/provider.py` : `discount_schedule` ajouté à `_NATIVE_SOLVE_KEYS`, sinon le champ est **silencieusement supprimé** avant l'appel natif (c'est le défaut que la spec `005` a trouvé pour le `FormatProfile` orphelin).
- `src/bot/decision_maker.py` : transmission depuis la configuration, défaut `None` (comportement inchangé).
- **Mode strict (FR-016).** `epsilon_target` sélectionne un plafond d'itérations strict (`strict_max_iterations`) et pose `target_exploitability = epsilon` ; le schedule est passé à la même boucle `solve_with_schedule` sans branche dédiée. Interaction **définie comme neutre** : le schedule change la vitesse, jamais le critère de verdict (`converged = exploitability <= epsilon_target`), et le mode strict n'est pas refusé du fait d'un schedule. Testé par `tests/v2_api.rs::strict_mode_accepts_a_non_default_schedule_with_an_honest_verdict`.

### 3. Traçabilité

Le schedule appliqué est posé dans `SolveResponseV2.metadata["discount_schedule"]`, aux côtés des champs de solver existants (`src/v2_api.rs:805` en pose déjà). Le journal de décision le reprend par le bloc `metadata` (spec `008`) — aucune modification de schéma.

### 4. Harnais de mesure (`tests/cfr_schedule_convergence.rs`)

Un test d'intégration Rust qui, pour chaque schedule et pour Kuhn puis Leduc :

1. construit le jeu (`KuhnGame`/`LeducGame` déjà présents dans `tests/`) ;
2. itère par paliers (p. ex. 10, 100, 1 000, 10 000) en appelant `solve_step` avec le schedule ;
3. mesure `compute_exploitability` à chaque palier ;
4. vérifie que la valeur de jeu de la racine atteint la référence (Kuhn `−1/18`, Leduc `−0,0856`) à la tolérance du test existant.

Les jeux de test sont **déjà** dans `tests/kuhn.rs` et `tests/leduc.rs`, avec leur valeur vérifiée contre OpenSpiel : le harnais réutilise cette infrastructure au lieu d'en inventer une. Un binaire `examples/cfr_schedule_benchmark.rs` écrit l'artefact daté pour l'opérateur (même schéma que `examples/phase_profile.rs`).

**Ce que le harnais ne fait pas** : il ne rejoue pas le postflop HU à range complète (coût ~800 ms/spot, hors d'un tour de développement) et ne prétend donc rien sur le chemin de production. Il tranche la question « le schedule change-t-il la convergence dans ce codebase », qui est la question préalable.

### 5. Documentation et configuration

- `docs/etudes.md` fiche C16 : identifiants arXiv corrigés, chiffres réels, recommandation HS-DCFR(30) pour les grands jeux de poker, état daté.
- `config.json` : `"hs_pcf_30_enabled": false` est **retiré** — une clé sans effet n'est pas un réglage. Le schedule se sélectionne par requête ; si l'opérateur veut un jour un défaut configurable, la clé sera ajoutée avec son câblage et son test dans le même changement.
- `docs/AUDIT_COMPLET_2026-11-17.md` : ligne F-12 mise à jour (C16 traité, C23/C24/C25 hors périmètre motivé) et table de traçabilité §5.

## Structure des fichiers

```text
src/solver.rs                          # DiscountSchedule + for_schedule (modifié)
src/gto_api.rs                         # champ discount_schedule (modifié)
src/v2_api.rs                          # champ + propagation + metadata (modifié)
python_bindings/src/lib.rs             # paramètre PyO3 (modifié)
src/solver/provider.py                 # allowlist native (modifié)
src/bot/decision_maker.py              # transmission depuis la config (modifié)
tests/cfr_schedule_convergence.rs      # harnais de convergence (nouveau)
examples/cfr_schedule_benchmark.rs     # point d'entrée opérateur (nouveau)
tests/kuhn.rs, tests/leduc.rs          # jeux réutilisés (inchangés)
docs/etudes.md                         # fiche C16 corrigée (modifié)
docs/AUDIT_COMPLET_2026-11-17.md       # F-12, §5 (modifié)
config.json                            # clé inerte retirée (modifié)
research/results/cfr_schedule_benchmark.json  # artefact daté (nouveau)
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Le défaut change et casse la production | `DiscountParams::new` n'est **pas** touché ; `Dcfr` délègue à `new` ; test de non-régression sur un spot rejoué (SC-003) |
| Un schedule produit `NaN`/`∞` à `t = 0` | `t = 0` traité explicitement ; test de finitude sur toute itération (FR-006) |
| Chemin compressé et non compressé divergent | Les deux lisent les mêmes `params` ; test de parité (FR-007) |
| Le gain de l'article ne se transpose pas à ce crate | C'est un **résultat possible et acceptable** : le rapport déclare le résultat réel (FR-012). La variante du crate n'est pas le DCFR canonique — c'est documenté en assumption |
| Le schedule est lu par le natif mais supprimé par le provider Python | `discount_schedule` ajouté à `_NATIVE_SOLVE_KEYS` ; test Python que la clé traverse |
| Coût du harnais en CI | Kuhn et Leduc sont minuscules ; paliers bornés ; le harnais n'est pas dans le chemin de production |
| Référence C16 corrigée mais un autre identifiant faux ailleurs | Correction limitée à C16 (le constat F-12) ; les autres fiches ne sont pas auditées ici |

## Portes de qualité

- `cargo test` (lib + intégration, dont Kuhn/Leduc sous chaque schedule) et `cargo fmt --check`.
- `cargo clippy` vert sur le code modifié.
- `uv run pytest` complet vert (non-régression) ; `uv run ruff check src tests scripts poker/tools`.
- Gate de performance F-09 vert (défaut inchangé).
- Artefact `research/results/cfr_schedule_benchmark.json` produit et lisible.

## Complexity Tracking

La complexité ajoutée est une énumération à trois variantes et quatre expressions arithmétiques. Elle remplace un paramètre figé et non mesuré par un paramètre sélectionnable et **mesuré** : sans elle, C16 reste « Absent », la référence scientifique de la fiche C16 reste fausse, et la clé de configuration reste un mensonge. Aucun chemin de production n'est modifié par défaut.
