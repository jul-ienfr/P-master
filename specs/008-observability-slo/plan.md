# Implementation Plan: Observabilité — traces par étage, SLO et registre de versions

**Branch**: `008-observability-slo` | **Date**: 2026-11-20 | **Spec**: `specs/008-observability-slo/spec.md`

## Summary

Rendre une décision **attribuable** et une dégradation **signalée pendant la session** : mesurer le temps par étage dans le chemin réel (sans toucher au payload comparé par les rejeux golden), évaluer des SLO purs sur les métriques réelles avec alertes structurées, et attacher à chaque enregistrement les versions qui l'ont produit — en acceptant de **lire** un journal écrit sous un schéma antérieur au lieu de le rejeter en bloc.

## Technical Context

**Language/Version**: Python 3.11 (venv du projet) ; aucun changement Rust
**Primary Dependencies**: aucune nouvelle — `time.perf_counter`, `statistics`, `dataclasses`
**Storage**: aucun artefact nouveau ; les SLO sont configurables via `config.json` (`bot.slo`) et par défaut dans un seul module
**Testing**: `pytest tests/test_stage_timing.py tests/test_slo_evaluation.py tests/test_decision_versions.py`
**Target Platform**: Windows, runtime local
**Project Type**: instrumentation runtime (`src/bot/`, `src/runtime/`) + un module pur de politique (`src/runtime/slo.py`)
**Performance Goals**: `< 1 µs` par étage mesuré (`time.perf_counter`), mesuré et non supposé ; aucun budget de décision modifié
**Constraints**: FR-002 — l'instrumentation n'ajoute aucune clé au payload de décision comparé par `tests/test_runtime_decision_replays.py` (qui exclut `metadata`) ; le verdict du gate go-live reste inchangé
**Scale/Scope**: six étages du chemin HU (`profile`, `ranges`, `rl`, `solver`, `exploit`, `assemble`) ; SLO génériques (nom, métrique, opérateur, cible, sévérité)

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | Une latence totale ne dit pas quoi corriger : la spec rend chaque étage mesuré et chaque version attachée à la décision. Aucun chiffre inventé : un étage absent n'apparaît pas, une version indisponible vaut `None` |
| II. Rust-first | Aucun calcul chaud ajouté (le coût est un `perf_counter` par étage, mesuré < 1 µs). L'évaluation de SLO tourne dans le snapshot opérateur, hors boucle de décision. Le registre §7 n'a pas de ligne à ouvrir : rien de déterministe n'est dupliqué |
| III. Latence et reproductibilité | La reproductibilité est l'objet de US3 : schéma, blueprint, modèle de range et tailles de mise sont attachés à chaque décision. Le budget de latence n'est pas modifié |
| IV. Fail-closed | Un SLO sans effectif suffisant est `insufficient_data`, jamais `ok` ; un schéma inconnu est signalé, jamais accepté silencieusement ; une cible absente est ignorée avec une raison, jamais un `breached` implicite |
| V. Modularité | `stage_timing.py` ne connaît ni le solveur ni le gate ; `slo.py` ne connaît ni le journal ni le bridge (métriques + cibles → statuts + alertes) ; le registre de versions est composé dans `decision_log.py`, seul endroit qui sait ce qu'est un enregistrement |
| VI. Tests | 3 fichiers de tests nouveaux ; la non-régression des rejeux golden et du gate go-live est explicitement vérifiée |
| IX. Source unique | Les seuils de SLO sont déclarés une seule fois (`DEFAULT_SLO_OBJECTIVES`) et surchargeables en un point ; `SCHEMA_VERSION` reste la version courante, `KNOWN_SCHEMA_VERSIONS` la source unique des schémas lisibles |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Mesure par étage (`src/runtime/stage_timing.py`, nouveau)

`StageTimer` : accumulateur ordonné d'étages. `with timer.stage("solver"):` mesure une section avec `time.perf_counter` ; les étages imbriqués sont autorisés et la somme est rapportée **telle quelle** (jamais recadrée à la latence totale). `as_dict()` retourne `{nom: ms}` arrondi, `total_ms` la durée totale du timer.

`summarize_stage_timings(records)` : p50/p95/p99 par étage sur des enregistrements portant `stages_ms`, plus `stage_counts`. Un étage absent d'un enregistrement n'est pas inventé : il est compté sur les seuls enregistrements qui le portent.

`percentile(sorted_values, ratio)` : `0.0` sur liste vide, jamais une exception (même primitive que `decision_log`, importée plutôt que dupliquée).

### 2. Instrumentation du chemin réel (`src/bot/decision_maker.py`, modifié)

`get_best_action` ouvre un `StageTimer` et mesure les six étages traversés (`profile`, `ranges`, `rl`, `solver`, `exploit`, `assemble`). Le résultat est posé dans `metadata["stages_ms"]` et `metadata["stages_total_ms"]` — **dans `metadata`, jamais à la racine de la décision** : `tests/test_runtime_decision_replays.py` compare la décision au champ près en excluant `metadata`, donc FR-002 est satisfait par construction, pas par convention.

Les retours anticipés (circuit breaker, multiway non supporté, aucune action légale) gardent leur payload actuel sans `stages_ms` : un étage non traversé n'apparaît pas.

### 3. Journal : `stages_ms` et résumé par étage (`src/runtime/decision_log.py`, modifié)

`stages_ms` entre dans `DECISION_FIELDS` et dans `record_from_runtime_trace` (depuis `metadata["stages_ms"]`). `summarize_decision_records` gagne `stages_ms` : percentiles par étage, sur les seuls enregistrements qui le portent. Un journal sans `stages_ms` reste valide et son résumé n'invente aucun étage.

### 4. SLO purs et alertes (`src/runtime/slo.py`, nouveau)

`SloObjective(name, metric, operator, target, severity, min_samples)`, `DEFAULT_SLO_OBJECTIVES` (taux de fallback, taux de blocage, latence p95, latence p95 du solveur, échantillon minimal de décisions) — déclarés en un seul endroit.

`evaluate_slo(metrics, objectives=None)` : pur, sans effet de bord, retourne `SloEvaluation(objectives, alerts, evaluated_at)`. Chaque objectif est `ok`, `breached`, `insufficient_data` (effectif sous `min_samples`, **jamais `ok`**) ou `ignored` (cible absente ou non numérique, avec raison). Chaque alerte porte l'objectif, la valeur, la cible et la sévérité. Aucun objectif configuré → ensemble vide, jamais une fausse alerte.

`slo_metrics_from_history(local_metrics, decisions)` : compose les métriques depuis l'historique réel (taux de fallback, taux de blocage, latence p95 totale et p95 de l'étage `solver`) sans nouvelle source de données.

`breached_names(evaluation)` : utilitaire de transition pour l'alerte, utilisé par l'appelant — l'évaluation elle-même n'écrit dans rien.

### 5. Câblage opérateur (`src/bot/operator_snapshot.py`, modifié)

`_build_runtime_bridge_state` et `_get_runtime_status` exposent un bloc `slo` (objectifs, alertes, `evaluated_at`) et posent `last_slo_evaluation`. Un changement de l'ensemble des objectifs franchis pousse **un** événement runtime `slo_breached` / `slo_recovered` — l'alerte est signalée pendant la session, pas découverte après coup. Les seuils viennent de `bot.slo` (config) et retombent sur les défauts du module.

Le verdict du gate go-live n'est ni lu ni modifié ici : les deux notions restent indépendantes (FR-009).

### 6. Registre de versions et schémas lisibles (`src/runtime/decision_log.py`, modifié)

`build_decision_record` pose un bloc `versions` : `schema_version`, `blueprint_version` (`BLUEPRINT_FORMAT_VERSION`), `range_model_version` (`RangeModelVersion` des contrats V2), `solver_bet_sizes`, `solver_raise_sizes` — chaque champ valant `None` quand la source est indisponible (import gardé), jamais une valeur inventée.

`KNOWN_SCHEMA_VERSIONS = (SCHEMA_VERSION,)` est la source unique des schémas lisibles. `schema_status(record)` retourne `current`, `legacy` (connu mais antérieur) ou `unknown` ; `validate_decision_record` accepte tout schéma **connu** et signale sa version, au lieu de rejeter en bloc un journal antérieur — un schéma inconnu reste une erreur.

## Structure des fichiers

```text
src/runtime/stage_timing.py       # StageTimer + percentiles par étage (nouveau)
src/runtime/slo.py                # objectifs, évaluation pure, alertes (nouveau)
src/runtime/decision_log.py       # stages_ms, résumé par étage, bloc versions, schémas connus (modifié)
src/bot/decision_maker.py         # instrumentation des six étages (modifié)
src/bot/operator_snapshot.py      # exposition du SLO et alerte de transition (modifié)
tests/test_stage_timing.py        # timer, imbrication, percentiles (nouveau)
tests/test_slo_evaluation.py      # objectifs, effectif, alertes, indépendance du gate (nouveau)
tests/test_decision_versions.py   # bloc versions, schémas connus/inconnus, résumé par étage (nouveau)
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| L'instrumentation casse les rejeux golden | `stages_ms` vit dans `metadata`, exclu de la comparaison au champ près ; test de non-régression explicite sur les deux fixtures de décision |
| Un SLO vert sur un échantillon vide | `min_samples` par objectif → `insufficient_data` ; test dédié (effectif nul, objectif jamais `ok`) |
| Une cible absente produit un faux `breached` | `ignored` avec raison ; test dédié |
| Le SLO contamine le gate go-live | Aucun accès au gate dans `slo.py` ; test d'indépendance (SLO franchi, gate inchangé) |
| Un schéma inconnu passe pour valide | `schema_status` retourne `unknown` et `validate_decision_record` le signale en erreur ; test dédié |
| Surcoût d'instrumentation supposé négligeable | Mesuré par test (timer vide sur 10 000 itérations), jamais affirmé |
| Une alerte par snapshot (bruit) | L'événement n'est poussé qu'au **changement** de l'ensemble des objectifs franchis |

## Portes de qualité

- `uv run pytest tests/test_stage_timing.py tests/test_slo_evaluation.py tests/test_decision_versions.py`.
- `uv run pytest tests/test_runtime_decision_replays.py tests/test_decision_log.py tests/test_bot_metrics.py` (non-régression des rejeux et du résumé).
- `uv run pytest tests/test_main_decision_gate_replay.py tests/test_operator_snapshot_full.py` (non-régression du gate et du snapshot).
- `uv run ruff check src tests scripts research poker/tools`.
- Suite Python complète verte.
- `cargo test --lib` et `cargo fmt --check` inchangés (aucun code Rust touché).

## Complexity Tracking

Aucune complexité algorithmique ajoutée. Les trois structures nouvelles (`StageTimer`, `SloObjective`/`SloEvaluation`, `DecisionVersions`) remplacent des pratiques implicites : une latence totale sans attribution, un taux de fallback visible seulement en relisant un snapshot, et des versions qui existent dans le code mais ne sont attachées à aucune décision. Sans elles, une lenteur reste inexpliquée et un journal ancien devient illisible au premier changement de schéma.
