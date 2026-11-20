# Implementation Plan: Politique OCR par site et preuve de vision

**Branch**: `010-vision-ocr-policy` | **Date**: 2026-11-20 | **Spec**: `specs/010-vision-ocr-policy/spec.md`

## Summary

Ramener le runtime de quatre moteurs OCR sans politique à **un principal + un fallback** choisis par site, corriger le « vert vide » des manifestes livrés (`status = "green"` avec `evaluated_samples = 0`) en un statut `unmeasured` honnête, et livrer le harnais de mesure qui produit la précision par site dès que l'opérateur fournit des captures — en disant « non mesuré » sinon.

## Technical Context

**Language/Version**: Python 3.11 (venv du projet) ; aucun changement Rust
**Primary Dependencies**: aucune nouvelle — `dataclasses`, `statistics`, `json` ; l'OCR existant (`src/vision/ocr.py`) est réutilisé
**Storage**: `research/results/vision_benchmark_<site>.json` (artefact daté, versionnable) ; manifestes de preset (`poker/*/stable/manifest.json`)
**Testing**: `pytest tests/test_ocr_policy.py tests/test_ocr_policy_runtime.py tests/test_preset_validation.py tests/test_vision_benchmark.py`
**Target Platform**: Windows, runtime local
**Project Type**: runtime Python + crate natif (inchangé ici)
**Performance Goals**: aucun impact dans la boucle chaude — la politique est appliquée une fois au boot, avant le chargement des moteurs
**Constraints**: aucune régression du comportement PokerStars par défaut ; le normaliseur bas niveau `_normalize_engines` garde son contrat (moteur inconnu écarté, jamais levé) car il est utilisé hors runtime (sonde, tests)
**Scale/Scope**: deux sites livrés, politique conçue pour en accueillir d'autres sans toucher au code d'appel

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | Un preset non mesuré n'est plus déclaré vert : les taux valent `None`, jamais un chiffre inventé. Le harnais mesure sur captures étiquetées, avec effectif exact |
| II. Rust-first | Aucun nouveau calcul chaud. Les moteurs OCR restent en Python (registre §7 : « Moteurs OCR — dépendances lourdes, interfaces Python ») ; la règle de politique est une table, pas un calcul |
| III. Latence | Politique appliquée une fois au boot ; `MAX_ENGINES = 2` réduit même le chargement au démarrage |
| IV. Fail-closed | Politique invalide (moteur inconnu, > 2 moteurs déclarés) → rejet ou réduction tracée, jamais un chargement silencieux ; capture illisible → échec compté, jamais exclu |
| VI. Tests | 39 tests nouveaux (politique, statut, harnais, câblage), dont non-régression sur les manifestes livrés |
| IX. Source unique | `ValidationOutcome` de `src/vision/preset_validation.py` est le seul type de validation ; le laboratoire l'aliasait avec un second type homonyme (supprimé) |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Politique OCR par site (`src/vision/ocr_policy.py`, nouveau)

`OCREnginePolicy(site_key, primary, fallback)` : un principal, au plus un fallback, tous deux du catalogue. Une politique invalide lève à la construction. `SITE_OCR_POLICIES` déclare la politique des sites livrés ; un site absent retombe sur le défaut (`rapidocr` + `tesseract`).

`clamp_to_policy(engines, policy)` restreint une sélection large aux moteurs de la politique, dans son ordre.

### 2. Câblage runtime (`src/vision/ocr.py`, `src/main.py`)

`PokerOCR.__init__` accepte `site_key`. Quand il est fourni, `_apply_ocr_policy` applique la politique **avant** le chargement :

- plus de deux moteurs déclarés → ramenés à la politique du site, la réduction est tracée dans `policy_notes` ;
- un ou deux moteurs valides → surcharge explicite honorée ;
- sans `site_key` (sonde, tests), le contrat du normaliseur est inchangé.

`src/main.py` construit les trois instances OCR avec le site actif de la configuration (`bot.active_site`), comme les manifestes et les limites d'action (spec `005`). La politique et les moteurs indisponibles apparaissent dans les métadonnées (FR-011).

### 3. Statut de validation honnête (`src/vision/preset_validation.py`, `poker/tools/room_manager.py`)

`compute_validation_status` retourne `unmeasured` avec des taux `None` quand aucun échantillon n'a été évalué. Le laboratoire consomme cette source unique : son second type `ValidationResult` (qui arrondissait `None` et levait) est remplacé par un alias de `ValidationOutcome`. Les deux manifestes livrés passent de `green`/`1.0`/`0` à `unmeasured`/`null`/`0`.

### 4. Harnais de mesure (`src/vision/vision_benchmark.py`, `scripts/vision_benchmark.py`)

`run_vision_benchmark(samples, reader)` mesure par champ : effectif évalué, corrects, illisibles, non évaluables, précision, latence médiane. Distingue deux échecs jamais exclus : `unevaluable` (étiquette absente) et `unreadable` (lecteur muet, compté dans le dénominateur). Sans échantillon évaluable : `unmeasured`, taux `None`.

`scripts/vision_benchmark.py` est le point d'entrée opérateur : il lit un dossier de captures étiquetées (`labels.json`), appelle l'OCR du site, et écrit l'artefact daté dans `research/results/`.

## Structure des fichiers

```text
src/vision/ocr_policy.py            # politique OCR par site (nouveau)
src/vision/preset_validation.py     # source unique du statut (nouveau)
src/vision/vision_benchmark.py      # harnais de mesure (nouveau)
src/vision/ocr.py                   # câblage de la politique (modifié)
src/main.py                         # site actif transmis à l'OCR (modifié)
poker/tools/room_manager.py         # consomme la source unique de statut (modifié)
scripts/vision_benchmark.py         # point d'entrée opérateur (nouveau)
tests/test_ocr_policy.py            # politique (nouveau)
tests/test_ocr_policy_runtime.py    # câblage runtime (nouveau)
tests/test_preset_validation.py     # statut + non-régression manifestes (nouveau)
tests/test_vision_benchmark.py      # harnais (nouveau)
poker/*/stable/manifest.json        # vert vide corrigé (modifié)
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Régression du comportement PokerStars par défaut | Le site par défaut reste `pokerstars` ; la politique livrée est `rapidocr` + `tesseract`, exactement ce que `config.json` active déjà |
| Contrat du normaliseur cassé pour les appelants hors runtime | `_apply_ocr_policy` ne s'exécute que si `site_key` est fourni ; test dédié |
| Statut `unmeasured` cassant un consommateur qui attend un nombre | `live_pass_rate` peut valoir `None` ; le seul consommateur numérique (`list_versions`) le sérialise tel quel, et `DriftResult.score` accepte `None` |
| Capture manquante faisant échouer tout le run | L'échantillon devient non évaluable, le reste est mesuré ; testé |
| Mesure confondue avec une preuve | Le rapport distingue `measured`/`unmeasured` et le script imprime explicitement « non mesuré, aucun taux inventé » |

## Portes de qualité

- `uv run pytest tests/test_ocr_policy.py tests/test_ocr_policy_runtime.py tests/test_preset_validation.py tests/test_vision_benchmark.py`.
- `uv run ruff check src tests scripts poker/tools`.
- Suite Python complète verte (non-régression) et `poker/tests/test_room_manager.py`.
- `cargo test --lib` et `cargo fmt --check` inchangés (aucun code Rust touché).

## Complexity Tracking

Aucune complexité algorithmique ajoutée. Les trois structures nouvelles (`OCREnginePolicy`, `ValidationOutcome`, `VisionBenchmarkReport`) remplacent des règles implicites et non testées ; sans elles, le choix des moteurs reste sans politique, le statut reste un vert vide, et la précision par site reste non mesurable.
