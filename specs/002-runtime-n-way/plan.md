# Implementation Plan: Multiway réel 3–6 joueurs

**Branch**: `002-runtime-n-way` | **Date**: 2026-11-17 | **Spec**: `specs/002-runtime-n-way/spec.md`

## Summary

Brancher le chemin multiway déjà présent dans `src/multiway.rs` et `src/v2_api.rs` au runtime de production. Le changement consiste à construire un contexte multiway (joueurs actifs, positions, ranges) dans le gate, à le transmettre au `DecisionMaker`, puis au provider. Aucune réécriture du solveur n'est nécessaire.

## Technical Context

**Language/Version**: Python 3.11, Rust stable (multiway existant)
**Primary Dependencies**: `CanonicalTableState`, `TableTracker.PlayerState`, `PreflopManager`, `BayesianRangeUpdater`, `SolverProvider`
**Storage**: cache LRU, journal JSONL
**Testing**: `pytest`, tests de contrat `SolveRequestV2`, benchmark par nombre de joueurs
**Target Platform**: Windows, runtime local
**Project Type**: application desktop + solveur natif
**Performance Goals**: budget de décision respecté pour 3–6 joueurs ; dégradation contrôlée au-delà
**Constraints**: MCCFR échantillonné, pas de convergence exacte ; kill switch 3–6
**Scale/Scope**: 3 à 6 joueurs, cash game en priorité

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | Le multiway est étiqueté échantillonné/non convergé |
| II. Rust-first | Le calcul reste dans `multiway.rs` |
| III. Latence | Budget adapté au nombre de joueurs, benchmark obligatoire |
| IV. Fail-closed | Nombre invalide → fallback explicite, pas d'approximation HU |
| VI. Tests | Tests 3/4/5/6-way, assis-out, mode strict |
| IX. Source unique | Un seul chemin multiway, pas de duplication |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Contexte multiway

Ajouter une structure explicite, par exemple dans `src/bot/runtime_types.py` :

```python
@dataclass(frozen=True)
class MultiwayContext:
    num_players: int
    hero_player_index: int
    active_positions: tuple[str, ...]
    villain_ranges: tuple[str, ...]
```

Le gate construit ce contexte depuis `canonical_state.players` et le tracker (`PlayerState.position`). Il exclut le héros, les joueurs couchés et les assis-out.

### 2. Transmission

Ajouter à `DecisionMaker.get_best_action` :

- `num_players: int | None`
- `villain_ranges: list[str] | None`
- `hero_player_index: int | None`

Puis à `_call_solver_backend` et à l'appel `solve_spot_v2` :

```python
num_players=num_players,
villain_ranges=villain_ranges,
hero_position=hero_position,
```

Le chemin HU reste utilisé quand `num_players <= 2`.

### 3. Règles de décision

- `num_players == 2` → HU, comportement actuel.
- `3 <= num_players <= 6` et ranges valides → chemin multiway V2.
- `num_players > 6` ou état invalide → fallback explicite `multiway_not_supported`.
- `strict_mode` → refus explicite, jamais d'approximation.
- Si le moteur multiway échoue → fallback tracé, pas de HU silencieux.

### 4. Cache et journal

- Inclure `num_players` et les ranges ordonnées dans la clé de cache.
- Journaliser `num_players`, `active_positions`, `multiway_mode`, `converged`, `warnings`.
- Ajouter un compteur de fallback par raison.

### 5. Tests

1. Test unitaire du comptage des joueurs actifs (assis-out, couché).
2. Test de contrat : `SolveRequestV2` avec 6 joueurs et 5 ranges.
3. Test d'intégration : spot 3-way, vérifier `backend=multiway`.
4. Test d'intégration : spot 6-way, vérifier les warnings et la convergence.
5. Test de non-régression : HU inchangé.
6. Test de mode strict : refus explicite.
7. Benchmark : latence et mémoire par N.

## Structure des fichiers

```text
src/bot/runtime_types.py           # MultiwayContext
src/bot/gate_flow.py               # construction du contexte
src/bot/decision_maker.py          # transmission des paramètres
src/solver/provider.py             # passthrough (déjà **payload)
src/v2_api.rs                      # chemin multiway (existant, à vérifier)
src/multiway.rs                    # moteur (existant)
src/solver/spot_key.py             # clé avec num_players/ranges
src/runtime/decision_log.py        # champs de trace
tests/test_decision_maker.py
tests/test_gate_flow.py
tests/v2_api.rs
tests/multiway.rs
scripts/bench_production_runtime.py
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Explosion du temps de solve | Budget par N, itérations scalées, dégradation contrôlée |
| Variance MCCFR | Étiqueter non convergé, augmenter les itérations si budget |
| Ordre des ranges incorrect | Tester l'ordre des positions, un test par N |
| Régression HU | Test HU dédié, chemin séparé |
| Mémoire | Cap de joueurs, kill switch, mesure |
| Ranges dupliquées | Ordre par position, pas par nom |

## Portes de qualité

- `pytest` sur les tests de décision, gate et provider.
- `cargo test` sur `v2_api` et `multiway`.
- Benchmark 3/4/5/6-way : p95 et mémoire.
- Vérification qu'aucun log de production ne contient `multiway_approximation` sans `num_players`.

## Complexity Tracking

La structure `MultiwayContext` est justifiée par la multiplicité des sources (canonical state, tracker, ranges). Elle évite de propager quatre paramètres non typés.
