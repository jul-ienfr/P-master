# Feature Specification: Range héros complète et EV du combo

**Feature Branch**: `001-gto-hero-range`

**Created**: 2026-11-17

**Status**: Clôturée (19/11/2026, soir ; re-vérifiée le 19/11 nuit après reconstruction du module natif) — code livré le 17/11/2026 ; critères de latence levés le 19/11/2026 : p95 froid 812,0 ms (cible ≤ 950 ms), rejeu golden `pass` (non-convergence étiquetée, convergence à 0,455 atteinte à 12,8 s). Re-vérification : six runs de benchmark donnent 774,1–877,9 ms, cible tenue dans tous les runs. Réserve documentée : la convergence à budget 800 ms n'est pas atteinte (~2 itérations DCFR), l'exploitabilité rapportée sur flop froid reste au-dessus de la cible 0,5 ; SC-004 est annoté en conséquence.

**Input**: Audit du 17/11/2026, constat F-01 : le runtime passe `hero_range=hero_hand` et résout le héros sur une seule main, ce qui produit l'équilibre d'un jeu où le villain connaît la main du héros.

## Contexte

Le solveur V2 distingue deux entrées :

- `hero_range` : la range complète du héros, utilisée pour construire le jeu ;
- `hero_hand` : la main cible, utilisée pour extraire l'EV et la stratégie du combo.

Le runtime actuel passe la même valeur aux deux champs (`src/bot/decision_maker.py:653-672`). La range héros est donc réduite à un combo. Le CFR calcule alors un équilibre conditionné sur une information que le villain ne possède pas dans la vraie partie. Toutes les fréquences et tous les EV sont biaisés.

Cette spec corrige uniquement ce défaut. Elle ne traite pas le multiway (spec `002`) ni la preuve de performance (spec `003`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Résoudre sur la range réelle (Priority: P1)

En tant qu'opérateur, je veux que le solveur reçoive la range complète du héros et la main cible séparément, afin que la stratégie calculée soit celle de la vraie partie.

**Why this priority**: c'est le prérequis de toute décision GTO. Sans cela, les EV, les fréquences et l'exploitabilité sont faux.

**Independent Test**: lancer un spot postflop de référence avec une range héros de plusieurs combos et vérifier, dans la requête et dans le journal, que `hero_range` contient plus d'un combo et que `hero_hand` identifie le combo cible.

**Acceptance Scenarios**:

1. **Given** une range héros de position contenant plusieurs combos et une main `AhKh`, **When** le runtime demande une décision, **Then** la requête contient la range complète dans `hero_range` et `AhKh` dans `hero_hand`.
2. **Given** la même range et deux mains cibles différentes, **When** les deux décisions sont calculées, **Then** chaque réponse retourne l'EV et la stratégie du combo demandé, et les deux requêtes ne se confondent pas dans le cache.
3. **Given** une main cible absente de la range, **When** le solveur reçoit la requête, **Then** la réponse est explicite (fallback ou erreur contrôlée), pas un EV arbitraire.
4. **Given** un spot où la range ne contient qu'un combo (river dégénérée), **When** la décision est calculée, **Then** le comportement reste valide et le journal indique que la range est dégénérée.

---

### User Story 2 - Tracer la range utilisée (Priority: P1)

En tant qu'opérateur, je veux voir dans le journal la taille de la range, sa source et le combo cible, afin de pouvoir expliquer et reproduire une décision.

**Why this priority**: une correction non traçable ne peut pas être auditée.

**Independent Test**: provoquer une décision et vérifier que `DecisionRecord` contient `hero_range_size`, `hero_range_source`, `hero_combo` et la version de la range.

**Acceptance Scenarios**:

1. **Given** une décision, **When** le journal est écrit, **Then** il contient la taille de la range et le combo cible.
2. **Given** une mise à jour de range par node-locking, **When** la décision est prise, **Then** la version et la source de la range mise à jour sont journalisées.

---

### User Story 3 - Ne pas dégrader les performances (Priority: P2)

En tant qu'opérateur, je veux que la correction ne fasse pas exploser la latence ni l'exploitabilité.

**Why this priority**: une range complète agrandit l'arbre ; le budget de 800 ms doit rester tenable.

**Independent Test**: exécuter le benchmark de production sur les six spots fixes et comparer p95 et exploitabilité à la baseline du 16/11.

**Acceptance Scenarios**:

1. **Given** le benchmark de production, **When** la correction est active, **Then** le p95 froid reste sous 950 ms.
2. **Given** les deux flops de référence, **When** la correction est active, **Then** l'exploitabilité ne se dégrade pas de plus de 5 % par rapport à la baseline.
3. **Given** un dépassement de budget, **When** le solveur s'arrête, **Then** la réponse est étiquetée non convergée et le fallback reste explicite.

### Edge Cases

- Range syntaxiquement invalide : erreur contrôlée, pas de crash.
- Main cible avec une couleur/forme différente de la notation de la range : normalisation avant comparaison.
- Range vide après node-locking : fallback vers la range de base, avec warning.
- Préflop fast path : la range préflop précalculée reste utilisée ; la correction concerne le chemin solveur postflop et le préflop live.
- Multiway : la correction doit rester compatible avec l'ordre des ranges de la spec `002`.
- Cache : deux combos différents de la même range ne doivent pas partager une réponse qui contient l'EV d'un autre combo.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le runtime MUST passer une range héros multi-combos à `hero_range`.
- **FR-002**: Le runtime MUST passer la main cible à `hero_hand`, distincte de `hero_range`.
- **FR-003**: La range héros MUST provenir d'une source identifiée : range de position, range d'ouverture/défense, ou range mise à jour par les actions observées.
- **FR-004**: Le solveur MUST extraire l'EV et la stratégie du combo via `hero_hand` lorsque fourni. *(Précision 19/11 : l'EV du combo est exposée dans `actions[].ev` avec `selection == "combo_ev_max"` ; `hero_ev` reste l'EV de range et n'est pas l'EV du combo. Preuve : même range, deux combos → 1,0081 vs 21,4050 à EV de range identique.)*
- **FR-005**: Le cache MUST inclure la range, la main cible, la version de range et les paramètres d'abstraction.
- **FR-006**: La réponse MUST contenir `hero_range_size`, `hero_combo` et un indicateur `degenerate_range` si la range ne contient qu'un combo.
- **FR-007**: Le journal de décision MUST enregistrer la source et la version de la range.
- **FR-008**: Le système MUST refuser ou étiqueter explicitement une requête dont la main cible n'appartient pas à la range.
- **FR-009**: Le comportement MUST rester compatible avec les appels HTTP et PyO3 du provider.
- **FR-010**: Aucun chemin de production ne MUST utiliser `hero_hand` comme `hero_range`.

### Key Entities

- **HeroRange** : range pondérée, source, version, liste de combos.
- **HeroCombo** : main cible normalisée, EV par action, stratégie.
- **RangeResolution** : résultat de la sélection de range (position, actions, node-locking).
- **DecisionRecord** : trace de la décision, incluant la range et le combo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % des appels solveur postflop de production ont `hero_range_size > 1`, hors spots dégénérés explicitement journalisés.
- **SC-002**: 100 % des réponses contiennent l'EV du combo cible lorsque `hero_hand` est fourni.
- **SC-003**: Le p95 froid du benchmark de production reste sous 950 ms. *(Vérifié sur six runs le 19/11/2026 : 774,1–877,9 ms, médiane 811 ms — cible tenue dans tous les runs.)*
- **SC-004**: L'exploitabilité des spots de référence ne se dégrade pas de plus de 5 %. *(Note de clôture 19/11 : critère inapplicable tel quel — range complète et singleton sont deux jeux différents, leurs exploitabilités ne se comparent pas. Invariants retenus : état de convergence explicite (US3-AC3) et courbe de budget décroissante, 0,455 à 12,8 s. Voir `tasks.md`, « Critère de fin ».)*
- **SC-005**: Un rejeu golden avant/après montre la différence de stratégie sur au moins un spot et documente laquelle est correcte.
- **SC-006**: Aucun test existant de décision, de cache ou de provider ne régresse.

## Assumptions

- La range de base par position existe déjà (`BASE_GTO_RANGE`, `PreflopManager`, `BayesianRangeUpdater`) et peut être réutilisée.
- Le solveur V2 sait déjà extraire l'EV d'un combo (`combo_index`, `expected_values_detail`).
- Le budget de 800 ms reste la référence pour le flop à froid.
- La correction peut modifier les décisions ; c'est attendu et doit être documenté, pas masqué.

## Plan de test

1. Test unitaire : `_call_solver_backend` transmet une range multi-combos et la main cible.
2. Test de contrat : `solve_spot_v2(hero_range=R, hero_hand=H)` retourne l'EV de `H`.
3. Test de cache : deux mains cibles différentes produisent deux clés différentes.
4. Test d'intégration : rejeu d'un spot postflop avec range de position.
5. Test de non-régression : benchmark des six spots, p95 et exploitabilité.
6. Test d'erreur : main cible absente de la range, range vide, syntaxe invalide.

## Hors périmètre

- Le multiway (spec `002`).
- La preuve statistique de winrate (spec `003`).
- La migration Rust de l'orchestrateur (spec `007`).
- Les changements d'interface utilisateur.
