# Implementation Plan: Contrat de plateforme multi-site

**Branch**: `005-vision-multi-site` | **Date**: 2026-11-20 | **Spec**: `specs/005-vision-multi-site/spec.md`

## Summary

Étendre `src/vision/site_adapter.py` d'un adaptateur unique (PokerStars) vers un **registre** d'adaptateurs (PokerStars, Winamax) porteurs d'un contrat complet : identité, thème, format de montants, profil de fenêtre, limites d'action. Supprimer les deux défauts mesurés — le site codé en dur dans le runtime et le `FormatProfile` orphelin — en câblant la sélection par configuration et en construisant le parseur de montants depuis l'adaptateur. Ajouter des fixtures de montants par site et un test de conformité falsifiable.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: aucune nouvelle — `dataclasses`, `re`, `pathlib` ; le parseur existant `src/vision/numeric_parser.py` est réutilisé tel quel
**Storage**: `config.json` (clé non sensible `bot.active_site`), fixtures JSON sous `tests/fixtures/`
**Testing**: `pytest tests/test_site_adapter_contract.py`, nouveau `tests/test_site_adapter_registry.py`
**Target Platform**: Windows, runtime local
**Project Type**: runtime Python + crate natif
**Performance Goals**: négligeable (résolution et construction une fois par session)
**Constraints**: aucune régression du comportement PokerStars par défaut ; aucune valeur de site inventée (classe/process Winamax restent `None`)
**Scale/Scope**: deux sites livrés, registre conçu pour en accueillir d'autres sans modification du code d'appel

## Constitution Check

| Principe | Vérification |
|---|---|
| I. Vérité scientifique | Les conventions de montants par site sont documentées et testées par fixtures ; aucune règle de mise inventée sans source |
| II. Rust-first | Le décodage d'état et les limites d'action sont des candidats Rust (registre §7, ligne `005`) ; le décodage de chaîne courte reste en Python dans la boucle froide (une fois par session), pas dans la boucle chaude |
| III. Latence | Résolution d'adaptateur hors boucle de décision ; aucun impact mesurable |
| IV. Fail-closed | Clé de site inconnue → erreur explicite, jamais de repli silencieux ; montant illégal → refus motivé |
| VI. Tests | Fixtures par site, test de conformité, test de falsification |
| IX. Source unique | Le format de montants n'est déclaré qu'une fois (adaptateur) et consommé par le parseur ; plus de duplication config/adaptateur |

**Verdict :** conforme. Aucune dérogation nécessaire.

## Approche

### 1. Contrat d'adaptateur (`src/vision/site_adapter.py`)

Le contrat existant (`SiteAdapterProtocol`) est étendu de trois champs :

- `window_profile: WindowProfile` — motifs de reconnaissance (titre, classe, process), blinde par défaut, motif de limite. Remplace la lecture ad hoc de `config.json` dans `action_controller.py`.
- `action_limits: ActionLimits` — mise minimale (bb), incrément minimal de relance, décimales, tapis supporté.
- `amount_parser() -> NumericParser` — construit depuis `amount_format`, **source unique** du format.

Deux implémentations : `PokerStarsAdapter` (conservée, complétée) et `WinamaxAdapter` (nouvelle). Le registre `SITE_ADAPTERS` associe une clé à une fabrique ; `get_active_adapter` le consulte.

### 2. Résolution de site

- `resolve_site_from_title(title, adapters=None) -> str | None` : parcourt le registre dans un ordre **déterministe** (clé triée), applique `title_regex` puis les alias de titre ; retourne la clé ou `None`. Aucune dépendance à l'ordre d'insertion du dictionnaire (défaut actuel de `action_controller.py`).
- `get_active_adapter` accepte une clé vide comme valeur par défaut ; une clé inconnue lève.

### 3. Câblage runtime

- `src/config.py` : ajouter `POKER_ACTIVE_SITE` en surcharge d'environnement, comme les autres surcharges (`POKER_WINDOW_KEYWORDS`).
- `src/runtime/table_manager.py:141` et `src/runtime/frame_pipeline.py:83` : remplacer le littéral par une lecture de configuration (`bot.active_site`), avec `pokerstars` en défaut. Le défaut de configuration est le seul endroit où le nom de site apparaît.

### 4. Limites d'action

`validate_bet_amount(amount_bb, limits, *, is_all_in=False) -> BetAmountVerdict` : module `src/vision/action_limits.py` (pur, testable). Il ne juge pas la stratégie — il borne la taille selon le site et arrondit selon les décimales. Le runtime peut l'appeler pour remplacer la correction locale « < 1 BB → 3 BB ».

### 5. Fixtures

`tests/fixtures/site_amounts/<site>.json` : liste de couples `{text, expected, note}` représentatifs des conventions du site. Le test de conformité parcourt tous les adaptateurs, charge la fixture du site, et vérifie le parsing via `adapter.amount_parser()`.

### 6. Tests

1. Registre : PokerStars et Winamax résolus ; clé inconnue lève ; clé vide → défaut.
2. Conformité : tous les adaptateurs exposent les champs du contrat, non vides, correctement typés.
3. Format : montants de fixture → valeur attendue, par site.
4. Falsification : un format contradictoire avec ses fixtures fait échouer le test.
5. Limites : refus sous minimum, acceptation du minimum, tapis, arrondi.
6. Résolution de site : titres représentatifs → site ; titre inconnu → `None`.
7. Manifestes : adaptateur sans manifeste présent → tuple vide, sans exception.
8. Non-régression : comportement `PokerStarsAdapter` inchangé.

## Structure des fichiers

```text
src/vision/site_adapter.py          # contrat étendu + registre + adaptateurs (modifié)
src/vision/action_limits.py         # validation de taille de mise par site (nouveau)
src/config.py                       # surcharge POKER_ACTIVE_SITE (modifié)
src/runtime/table_manager.py        # sélection par configuration (modifié)
src/runtime/frame_pipeline.py       # sélection par configuration (modifié)
tests/fixtures/site_amounts/*.json  # fixtures de montants par site (nouveau)
tests/test_site_adapter_contract.py # non-régression PokerStars (conservé)
tests/test_site_adapter_registry.py # registre, conformité, fixtures (nouveau)
config.json                         # bot.active_site (modifié)
```

## Risques et mitigations

| Risque | Mitigation |
|---|---|
| Régression du comportement PokerStars | Le défaut reste `pokerstars` ; les tests existants de `test_site_adapter_contract.py` sont conservés sans modification |
| Métadonnées Winamax inventées | Classe et process restent `None` et configurables ; seule la reconnaissance par titre est affirmée |
| Double source de vérité pour le format | Le parseur est construit depuis l'adaptateur ; `config.json` garde `ocr.amount_format` comme surcharge d'exécution documentée, l'adaptateur devient la valeur par défaut par site |
| Ordre de résolution non déterministe | Résolution sur clés triées, testée |
| Limites d'action divergentes du client réel | Les limites sont déclaratives et testées ; un écart observé en session se corrige dans le registre, sans toucher au code d'appel |

## Portes de qualité

- `uv run pytest tests/test_site_adapter_registry.py tests/test_site_adapter_contract.py tests/test_numeric_parser.py`.
- `uv run ruff check src/vision/site_adapter.py src/vision/action_limits.py`.
- Suite Python complète verte (non-régression).
- Aucune occurrence de `"pokerstars"` en littéral dans le chemin d'exécution hors défaut de configuration.

## Complexity Tracking

Aucune complexité algorithmique ajoutée. La seule structure nouvelle (`ActionLimits`, `WindowProfile`) est justifiée par la conformité par site : sans elles, les limites et les motifs de fenêtre restent dispersés dans `config.json` et `action_controller.py`, et aucun test de conformité n'est possible.
