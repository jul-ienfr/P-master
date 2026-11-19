# Feature Specification: Programme Poker Master v1

**Feature Branch**: `000-programme-v1`

**Created**: 2026-11-17

**Status**: Draft

**Input**: User description: "Reprendre tous les plans du projet avec SpecKit, auditer l'état actuel, puis construire un système aligné aux études scientifiques, rapide, fiable, maintenable, modulaire, couvrant vision, stratégie, bankroll et gestion du jeu, fonctionnant sur PokerStars et Winamax, avec un maximum de composants en Rust."

## Contexte

Le programme transforme le prototype actuel en système de production scientifique. Il ne remplace pas les plans existants : il les ordonne, les rend testables et les rattache à la constitution `.specify/memory/constitution.md` v1.0.0.

Le programme est découpé en specs indépendantes. Chaque spec livre une tranche de valeur et peut être testée seule. L'ordre ci-dessous est l'ordre de dépendance, pas seulement l'ordre de priorité.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Décision GTO correcte (Priority: P1)

L'opérateur veut que chaque décision soit calculée sur la range complète du héros et, en multiway, sur le nombre réel de joueurs. Une décision doit être reproductible et explicable.

**Why this priority**: sans cette correction, toutes les autres fonctions (bankroll, vision, plateformes) s'appuient sur des décisions biaisées. C'est le prérequis scientifique.

**Independent Test**: rejouer un spot 6-max de référence et vérifier que la requête solveur contient une range héros multi-combos, `num_players` égal au nombre de joueurs actifs, et une range par villain.

**Acceptance Scenarios**:

1. **Given** un spot postflop avec une range héros de plusieurs combos, **When** le runtime demande une décision, **Then** la requête contient la range complète et la main cible séparément.
2. **Given** une table 6-max avec cinq villains actifs, **When** le runtime demande une décision, **Then** le solveur reçoit `num_players=6` et cinq ranges ordonnées.
3. **Given** un état ambigu ou un nombre de joueurs non supporté, **When** le solveur ne peut pas répondre, **Then** la réponse est un fallback explicite, journalisé, et jamais une approximation HU silencieuse.

---

### User Story 2 - Preuve scientifique et gate de validation (Priority: P1)

L'opérateur veut savoir si le système bat réellement un pool de référence, avec une incertitude quantifiée, avant de l'utiliser en argent réel.

**Why this priority**: le projet sait mesurer, mais les résultats actuels ne sont pas significatifs. Une décision go/no-go exige un protocole.

**Independent Test**: exécuter le benchmark de production sur un pool synthétique avec une taille d'échantillon prédéfinie et produire un rapport avec IC 95 %, exploitabilité et taux de fallback.

**Acceptance Scenarios**:

1. **Given** un pool de référence et une graine fixée, **When** le benchmark tourne, **Then** il produit un artefact versionné et reproductible.
2. **Given** un résultat non significatif, **When** le gate est évalué, **Then** le rapport le déclare explicitement et le gate refuse le go-live.
3. **Given** une amélioration du solveur, **When** le benchmark est rejoué, **Then** la comparaison avant/après utilise le même protocole et les mêmes seeds.

---

### User Story 3 - Vision fiable sur PokerStars et Winamax (Priority: P2)

L'opérateur veut que la capture, la reconnaissance des cartes et l'OCR des montants fonctionnent sur les deux plateformes, avec une précision et une latence mesurées.

**Why this priority**: sans vision fiable, la meilleure stratégie est inutilisable.

**Independent Test**: rejouer un jeu de captures versionnées par site et par thème, et vérifier la précision des cartes, montants, boutons et sièges, ainsi que la latence p95.

**Acceptance Scenarios**:

1. **Given** une capture PokerStars, **When** la vision la traite, **Then** l'état canonique est produit avec un score de confiance par champ.
2. **Given** une capture Winamax, **When** la vision la traite, **Then** le même contrat d'état est produit par l'adaptateur Winamax.
3. **Given** une confiance basse, **When** le gate évalue l'état, **Then** la décision est bloquée ou remplacée par l'action la moins engageante.

---

### User Story 4 - Bankroll et risque (Priority: P2)

L'opérateur veut un plan de bankroll explicite : limite courante, risque de ruine, règles de move-up/down, limites de session et arrêt automatique.

**Why this priority**: la stratégie ne suffit pas ; une bankroll mal gérée détruit l'espérance même avec un bon winrate.

**Independent Test**: simuler une séquence de résultats et vérifier que les règles de bankroll produisent les changements de limite et les arrêts attendus, avec un journal d'audit.

**Acceptance Scenarios**:

1. **Given** une bankroll et un format, **When** la session démarre, **Then** la limite, les mises maximales et les seuils d'arrêt sont calculés et journalisés.
2. **Given** une perte atteignant le stop-loss, **When** la session continue, **Then** elle s'arrête et aucune nouvelle main n'est jouée.
3. **Given** une bankroll suffisante pour monter de limite, **When** les conditions de move-up sont remplies, **Then** le système propose la nouvelle limite sans l'appliquer automatiquement sans confirmation.

---

### User Story 5 - Cœur Rust et maintenabilité (Priority: P2)

L'opérateur veut que les composants chauds et déterministes soient en Rust, sans double implémentation active, et que la base Python historique soit clairement séparée.

**Why this priority**: c'est la condition de la vitesse, de la fiabilité et de la maintenabilité à long terme.

**Independent Test**: vérifier que chaque composant du registre de migration a un propriétaire, un état et un test de parité ; vérifier qu'aucun composant n'a deux implémentations de production.

**Acceptance Scenarios**:

1. **Given** un composant marqué « migré », **When** le runtime l'appelle, **Then** il n'existe qu'un chemin actif et il est couvert par un test de contrat.
2. **Given** `poker/` et `src/`, **When** la CI mesure la couverture, **Then** les deux périmètres sont rapportés séparément.
3. **Given** une régression de performance, **When** la CI s'exécute, **Then** la merge est bloquée.

---

### User Story 6 - Observabilité et release (Priority: P3)

L'opérateur veut pouvoir expliquer chaque décision et installer le système de façon reproductible.

**Independent Test**: à partir d'un `spot_id`, retrouver la capture, l'état, la requête solveur, la réponse, l'action et la latence de chaque étage.

**Acceptance Scenarios**:

1. **Given** une décision, **When** l'opérateur ouvre le journal, **Then** il voit les versions de code, de ranges et de modèle.
2. **Given** une release, **When** elle est publiée, **Then** la licence, les dépendances et les artefacts sont documentés.

### Edge Cases

- Spot avec une seule main possible (river, range dégénérée) : doit rester valide et traçable.
- Spot multiway avec un joueur assis-out ou un stack court : le nombre de joueurs actifs doit être correct.
- Solveur indisponible ou timeout : fallback explicite, pas de mise agressive.
- Capture partielle ou OCR en échec : état incomplet, décision bloquée.
- Bankroll inconnue : limites par défaut conservatrices, pas d'argent réel.
- Site non supporté : refus explicite, pas de tentative silencieuse.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le runtime MUST transmettre au solveur une range héros complète et une main cible distincte.
- **FR-002**: Le runtime MUST transmettre le nombre réel de joueurs actifs et une range par villain en multiway.
- **FR-003**: Toute approximation MUST être étiquetée dans la réponse et journalisée.
- **FR-004**: Toute décision MUST contenir action, EV par action, stratégie, exploitabilité ou gap, budget, backend et avertissements.
- **FR-005**: Le système MUST produire un benchmark reproductible du solveur de production avec IC 95 %.
- **FR-006**: Le système MUST implémenter une méthode de réduction de variance (AIVAT ou MIVAT) pour l'évaluation.
- **FR-007**: La vision MUST produire un état canonique avec confiance par champ pour PokerStars et Winamax.
- **FR-008**: La bankroll MUST calculer la limite, le risque de ruine et les seuils d'arrêt, et journaliser chaque changement.
- **FR-009**: Les composants chauds MUST être en Rust ou justifiés dans le registre de migration.
- **FR-010**: La CI MUST bloquer une régression de latence ou d'exploitabilité au-delà du seuil convenu.
- **FR-011**: Les secrets MUST être absents du dépôt.
- **FR-012**: Le système MUST fonctionner en mode supervisé et respecter les conditions d'utilisation des plateformes.

### Key Entities

- **Range** : ensemble pondéré de combos, avec version et source.
- **CanonicalState** : état de table validé (joueurs, positions, stacks, pot, rue, actions).
- **SolveRequest** : range héros, ranges villains, `num_players`, board, historique, budget, abstraction.
- **DecisionRecord** : action, EV, stratégie, confiance, versions, latence, fallback.
- **BankrollPlan** : limite, bankroll, RoR, règles de move-up/down, limites de session.
- **PlatformAdapter** : capture, calibration, décodage, encodage d'action, limites.
- **BenchmarkArtifact** : protocole, seeds, résultats, IC, versions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % des appels solveur de production contiennent une range héros de plus d'un combo, sauf spot dégénéré explicitement justifié.
- **SC-002**: 100 % des spots 3–6 way utilisent le chemin multiway ou un fallback explicitement étiqueté ; zéro approximation HU silencieuse.
- **SC-003**: Le benchmark de production produit un IC 95 % et une conclusion go/no-go reproductible.
- **SC-004**: La latence p95 d'une décision complète reste sous 1 500 ms sur le matériel de référence, avec un p99 sous 2 500 ms.
- **SC-005**: La précision de vision par site est mesurée sur un jeu de fixtures et documentée ; aucune régression de plus de 2 points n'est acceptée.
- **SC-006**: 100 % des changements de limite et des arrêts de bankroll sont journalisés et rejouables.
- **SC-007**: Aucun secret n'est présent dans les fichiers suivis par git.
- **SC-008**: La couverture `src/` est rapportée séparément et ne baisse pas.

## Assumptions

- L'opérateur travaille en local, sur Windows, avec un matériel de référence stable.
- Les sites cibles peuvent changer leur interface ; les adaptateurs doivent être versionnés.
- Le mode argent réel est désactivé par défaut et nécessite une configuration explicite.
- Les benchmarks synthétiques ne remplacent pas une validation sur des populations réelles ; ils bornent le risque.
- La licence AGPL-3.0-only est acceptée pour le projet et ses dépendances.

## Dépendances entre specs

| Spec | Dépend de | Livre |
|---|---|---|
| `001-gto-hero-range` | — | Correction de la range héros |
| `002-runtime-n-way` | 001 | Multiway réel 3–6 |
| `003-scientific-validity` | 001, 002 | Benchmark et AIVAT/MIVAT |
| `004-bankroll-risk` | — | Bankroll et risque |
| `005-vision-multi-site` | — | PokerStars + Winamax |
| `006-legacy-boundary` | — | Frontière `src/` / `poker/` |
| `007-rust-core-migration` | 001, 002, 006 | Migration des domaines chauds |
| `008-observability-slo` | 001, 002 | Traces et SLO |
| `009-packaging-compliance` | 005, 006 | Release et conformité |
