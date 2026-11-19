# Implementation Plan: Range héros complète et EV du combo

**Branch**: `001-gto-hero-range` | **Date**: 2026-11-17 | **Spec**: `specs/001-gto-hero-range/spec.md`

## Summary

Corriger le chemin de décision pour envoyer au solveur la range complète du héros (`hero_range`) et la main cible séparément (`hero_hand`), puis extraire l'EV du combo. Le changement est localisé dans le runtime Python ; le solveur Rust sait déjà faire.

## Technical Context

**Language/Version**: Python 3.11, Rust stable (inchangé)
**Primary Dependencies**: `SolverProvider`, `PreflopManager`, `BayesianRangeUpdater`, `spot_cache_key`
**Storage**: cache LRU en mémoire, journal JSONL
**Testing**: `pytest`, tests de contrat provider, benchmark `scripts/bench_production_runtime.py`
**Target Platform**: Windows, runtime local
**Project Type**: application desktop + solveur natif
**Performance Goals**: p95 froid ≤ 950 ms, pas de dégradation > 5 % de l'exploitabilité
**Constraints**: budget solveur 800 ms, cache byte-identique pour les autres champs
**Scale/Scope**: un seul chemin de décision postflop, HU dans cette spec

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | La correction supprime un biais d'information ; elle est testée par rejeu |
| II. Rust-first | Le calcul reste dans le solveur Rust ; seul l'appel Python change |
| III. Latence | Budget inchangé ; benchmark obligatoire |
| IV. Fail-closed | Main absente de la range → fallback explicite |
| VI. Tests | Test rouge avant correctif, test de contrat, rejeu golden |
| IX. Source unique | Un seul chemin d'appel, pas de double implémentation |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Résolution de la range héros

Avant l'appel solveur, résoudre :

```python
hero_range = self.preflop_manager.get_hero_range(
    hero_position,
    facing_raise=self._is_facing_preflop_raise(legal_actions, action_history),
)
```

La range doit être multi-combos. Si elle est vide, utiliser `BASE_GTO_RANGE`. Si le combo cible n'y appartient pas, journaliser un warning et utiliser une range de secours contenant le combo ; si aucune range valide n'existe, marquer `degenerate_range=true` et documenter le fallback.

### 2. Transmission au provider

Ajouter `hero_range` à `_call_solver_backend` et passer :

- `hero_range=hero_range`
- `hero_hand=hero_hand`
- `villain_ranges=[villain_range]`

Ne jamais utiliser `hero_hand` comme `hero_range`.

### 3. Cache

`spot_cache_key` doit inclure `hero_range` (et sa version si disponible). Mettre à jour les trois appelants :

- `src/bot/decision_maker.py`
- `src/runtime/decision_log.py`
- `src/solver/blueprint_store.py`

Les clés existantes changent : prévoir une invalidation propre du cache et du blueprint store.

### 4. Traçabilité

Ajouter au journal :

- `hero_range`
- `hero_range_size`
- `hero_range_source` (`position`, `node_locking`, `fallback`)
- `hero_combo`
- `degenerate_range`

### 5. Tests

1. Test unitaire de `_call_solver_backend` : la requête contient une range multi-combos et `hero_hand`.
2. Test de contrat `solve_spot_v2` : l'EV retourné correspond au combo.
3. Test de cache : deux combos différents → deux clés.
4. Test d'erreur : combo absent, range vide, syntaxe invalide.
5. Rejeu golden d'un spot postflop avant/après.
6. Benchmark des six spots : p95 et exploitabilité.

## Structure des fichiers

```text
src/bot/decision_maker.py          # résolution et transmission de la range
src/bot/preflop_ranges.py          # get_hero_range (existant, à utiliser)
src/solver/spot_key.py             # ajout de hero_range dans la clé
src/solver/blueprint_store.py      # clé de blueprint
src/runtime/decision_log.py        # clé et champs de trace
tests/test_decision_maker.py       # tests du chemin de décision
tests/test_decision_maker_helpers.py
tests/test_blueprint_live_lookup.py
scripts/bench_production_runtime.py
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Arbre plus grand, latence en hausse | Benchmark, réduction de l'abstraction si nécessaire, jamais de réduction de range |
| Décisions différentes | Rejeu golden, documentation, pas de rollback silencieux |
| Cache invalidé | Versionner la clé, vider le cache au démarrage |
| Combo absent de la range | Fallback explicite + warning, pas d'EV arbitraire |
| Préflop fast path | Ne pas casser le chemin précalculé ; tester les deux |

## Portes de qualité

- `pytest` sur les tests de décision et de provider.
- `scripts/bench_production_runtime.py` : p95 ≤ 950 ms, exploitabilité ≤ baseline + 5 %.
- `ruff check` sur les fichiers modifiés.
- Journal de décision vérifié sur un rejeu.

## Complexity Tracking

Aucune violation de la constitution. Le changement est localisé et ne justifie pas de nouvelle abstraction.
