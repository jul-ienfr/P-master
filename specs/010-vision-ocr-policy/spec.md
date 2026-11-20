# Feature Specification: Politique OCR par site et preuve de vision

**Feature Branch**: `010-vision-ocr-policy`

**Created**: 2026-11-20

**Status**: En cours

**Input**: Audit du 17/11/2026, constat F-08 (« Vision non prouvée par site ») et cible §3.1 : « un moteur OCR principal + un fallback maximum, un jeu de fixtures par site/theme, un score de confiance calibré, et un adaptateur de site comme contrat testé. »

## Contexte

Trois défauts mesurés avant d'écrire cette spec :

1. **Quatre moteurs OCR, aucune politique par site.** `src/vision/ocr.py:73` supporte `rapidocr`, `tesseract`, `surya`, `doctr` ; `config.json` en active un seul (`rapidocr`) mais rien n'empêche d'en charger quatre, et le choix n'est relié ni au site ni à une mesure. Chaque moteur ajoute des dépendances lourdes et ses propres modes de défaillance. La cible est **un principal + un fallback maximum**.
2. **Un « vert » qui ne prouve rien.** `poker/pokerstars-7-fr-6-max/stable/manifest.json` porte `validation.status = "green"` avec `evaluated_samples = 0`. La cause est en `poker/tools/room_manager.py:1343` : `golden_pass_rate = min(golden_scores) if golden_scores else 1.0` — **aucun échantillon évalué donne un taux de réussite de 1,0**. Un preset jamais mesuré est donc déclaré vert. Le runtime moderne (`src/`) ne lit même pas ce champ : le vert n'est ni vrai ni utilisé.
3. **Aucune fixture d'écran versionnée.** Il n'existe pas un seul `.png`/`.jpg` dans `tests/`, et `reference_samples: []` dans le manifeste. La précision réelle par site n'est donc pas mesurable et ne l'a jamais été.

Cette spec ne prétend pas produire des captures d'écran qu'elle n'a pas (les images sont des données d'exploitation, non committables ici). Elle produit ce qui manque et qui est testable hors ligne : **une politique OCR par site explicite**, la **correction du vert vide**, et un **harnais de mesure** qui produit un artefact daté dès que des captures sont fournies — et qui, sans capture, dit honnêtement « non mesuré » plutôt que « vert ».

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Un moteur principal et un fallback, par site (Priority: P1)

En tant qu'opérateur, je veux que le runtime charge au plus deux moteurs OCR (un principal, un fallback) choisis par la politique du site, afin de maîtriser le coût de maintenance et la latence.

**Why this priority**: c'est la cible explicite de F-08 ; quatre moteurs chargés en parallèle multiplient les dépendances et les pannes.

**Independent Test**: la politique d'un site retourne `(principal, fallback)` avec au plus deux noms, tous deux dans le catalogue supporté ; une politique déclarant un moteur inconnu est rejetée.

**Acceptance Scenarios**:

1. **Given** un site livré, **When** sa politique OCR est demandée, **Then** elle retourne un moteur principal et au plus un fallback, tous deux supportés.
2. **Given** un moteur principal indisponible sur la machine, **When** la politique est appliquée, **Then** le fallback prend la main, ou le mode dégradé est explicite (jamais un moteur inconnu chargé en silence).
3. **Given** une politique déclarant trois moteurs, **When** elle est validée, **Then** elle est rejetée (la cible est « 1 + 1 maximum »).

---

### User Story 2 - Un preset non mesuré n'est pas « vert » (Priority: P1)

En tant que mainteneur, je veux qu'un preset jamais évalué soit marqué « non mesuré » et non « vert », afin qu'un vert signifie réellement « testé et conforme ».

**Why this priority**: un vert vide est pire qu'un rouge : il donne confiance sans preuve, et masque l'absence de mesure.

**Independent Test**: une validation avec zéro échantillon évalué a le statut `unmeasured` ; dès qu'un échantillon est évalué et réussi, le statut devient `green`.

**Acceptance Scenarios**:

1. **Given** une validation sans échantillon évalué, **When** le statut est calculé, **Then** il vaut `unmeasured`, jamais `green`.
2. **Given** des échantillons évalués tous réussis, **When** le statut est calculé, **Then** il vaut `green`.
3. **Given** des échantillons évalués dont un échoue, **When** le statut est calculé, **Then** il vaut `red` ou `yellow` selon le seuil, jamais `green`.

---

### User Story 3 - Mesurer la précision par site, ou dire qu'elle ne l'est pas (Priority: P2)

En tant que mainteneur, je veux un harnais qui, à partir de captures étiquetées, produit la précision et la latence par site et par champ, afin de disposer d'une preuve mesurée — et qui, sans capture, produit un artefact « non mesuré » explicite.

**Why this priority**: la cible de F-08 exige une précision « mesurée sur un jeu de fixtures et documentée » ; le harnais est le moyen de la produire, mais il dépend de captures que je ne peux pas fournir ici.

**Independent Test**: le harnais, sans capture, retourne un rapport dont le statut est `unmeasured` et dont le taux de réussite est `None` (pas `1.0`).

**Acceptance Scenarios**:

1. **Given** un jeu de captures étiquetées, **When** le harnais s'exécute, **Then** il produit la précision par champ, la latence et un IC, dans un artefact JSON daté.
2. **Given** aucune capture, **When** le harnais s'exécute, **Then** il produit un rapport `unmeasured` avec des taux `None`, jamais des taux inventés.
3. **Given** des captures dont un montant est illisible, **When** le harnais s'exécute, **Then** le champ est compté comme échec, pas exclu silencieusement.

### Edge Cases

- Politique de site absente : la politique par défaut (principal `rapidocr`, fallback `tesseract`) s'applique, jamais un chargement de tous les moteurs.
- Moteur principal présent mais échouant à l'exécution : le fallback est utilisé ; si lui aussi échoue, la valeur retournée est invalide (jamais `0.0`).
- Capture présente mais étiquette absente : la capture est comptée comme non évaluable, et le rapport le dit.
- Validation avec des échantillons mais aucun réussi : `red`, jamais `unmeasured`.
- Seuil de précision non atteint sur un champ critique (montant) : le rapport le signale comme régression, sans masquer les autres champs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le système MUST exposer une politique OCR par site : un moteur principal et au plus un fallback, tous deux du catalogue supporté.
- **FR-002**: La politique MUST être validable : plus de deux moteurs, ou un moteur inconnu, MUST être rejeté.
- **FR-003**: Le système MUST fournir une politique par défaut (principal `rapidocr`, fallback `tesseract`) quand aucune politique de site n'est déclarée.
- **FR-004**: Le calcul du statut de validation d'un preset MUST retourner `unmeasured` quand aucun échantillon n'a été évalué.
- **FR-005**: Le statut `green` MUST exiger au moins un échantillon évalué et réussi.
- **FR-006**: Le système MUST fournir un harnais de mesure produisant, par site et par champ, précision, latence et effectif évalué.
- **FR-007**: Le harnais MUST produire un artefact JSON daté et versionnable (`research/results/vision_benchmark_<site>.json`).
- **FR-008**: Le harnais MUST, sans capture, produire un rapport `unmeasured` avec des taux `None` — jamais un taux inventé.
- **FR-009**: Un champ illisible MUST être compté comme échec de mesure, pas exclu.
- **FR-010**: Le runtime MUST charger au plus deux moteurs OCR issus de la politique active, jamais le catalogue entier.
- **FR-011**: Les moteurs indisponibles MUST être signalés dans les métadonnées, sans lever.

### Key Entities

- **OCREnginePolicy** : `site_key`, `primary`, `fallback`, `mode` (priority/fallback).
- **ValidationStatus** : `unmeasured` | `green` | `yellow` | `red`.
- **VisionBenchmarkReport** : site, champ, effectif évalué, taux de réussite, latence médiane, IC, statut, date.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: La politique par défaut charge au plus deux moteurs — vérifié par test.
- **SC-002**: Une politique à trois moteurs ou à moteur inconnu est rejetée — vérifié par test.
- **SC-003**: Une validation sans échantillon évalué n'est jamais `green` — vérifié par test, y compris sur le manifeste PokerStars existant.
- **SC-004**: Le harnais sans capture produit un rapport `unmeasured` avec taux `None` — vérifié par test.
- **SC-005**: Le harnais avec captures étiquetées (jeu synthétique de test) produit une précision correcte et un effectif exact — vérifié par test.
- **SC-006**: `pytest` et `ruff` restent verts ; le comportement OCR par défaut est inchangé pour le site PokerStars.

## Assumptions

- Les captures d'écran réelles ne sont pas committables dans ce dépôt (données d'exploitation) : le harnais est testé sur des captures **synthétiques** générées en test, et la mesure réelle s'exécute quand l'opérateur fournit ses captures.
- La précision cible par champ est celle de la cible §3.1 (aucune régression de plus de 2 points, SC-005 de la spec programme) ; elle n'est pas réinventée ici.
- Le catalogue de moteurs reste `rapidocr`, `tesseract`, `surya`, `doctr` ; cette spec n'ajoute ni n'en retire aucun. — *Rectifié le 20/11/2026 : `surya` est retiré du catalogue (F-18, audit §P2 — moteur inerte, fenêtre d'API 0.15–0.17.1 incompatible avec F-17) ; le catalogue est désormais `rapidocr`, `tesseract`, `doctr`.*
- La correction du statut de validation touche `poker/tools/room_manager.py` (laboratoire) : c'est le seul endroit qui produit ce champ ; le runtime moderne le consommera via le registre de presets.

## Plan de test

1. Test de politique : défaut à deux moteurs ; site livré ; rejet à trois moteurs ; rejet moteur inconnu.
2. Test de chargement : le runtime ne charge que les moteurs de la politique.
3. Test de statut : zéro échantillon → `unmeasured` ; tous réussis → `green` ; un échec → `red`/`yellow`.
4. Test de non-régression : le manifeste PokerStars actuel n'est plus `green` sans échantillon.
5. Test de harnais : sans capture → `unmeasured`/`None` ; avec captures synthétiques → précision et effectif exacts.
6. Test de comptage : un champ illisible est un échec, pas une exclusion.

## Hors périmètre

- La fourniture de captures d'écran réelles (données d'exploitation de l'opérateur).
- La calibration de score de confiance par apprentissage (relève d'un travail de données, non engagé).
- L'entraînement ou le réglage des modèles OCR.
- La reconnaissance de cartes (relève du template matching existant, non de l'OCR).
- Les traces `spot_id` et SLO (constat F-10, spec `008`).
