# Feature Specification: Preuve statistique de performance et réduction de variance

**Feature Branch**: `011-scientific-validity`

**Created**: 2026-11-20

**Status**: En cours

**Input**: Audit du 17/11/2026, constat F-03 (« aucune preuve statistique de performance »), constat P0, et traçabilité C11 (AIVAT) / C27 (MIVAT) marquées « Absent ». Correctif attendu par l'audit : « un benchmark reproductible du solveur de production (pas de l'heuristique) contre un pool synthétique et, si possible, un bot de référence ; AIVAT/MIVAT pour réduire la variance (C11/C27) ; un nombre de mains et une puissance statistique définis à l'avance ; un artefact versionné et un gate CI. » Sprint 3 : « Gate de validation dans `go_live_gate` ».

## Contexte

Quatre défauts mesurés avant d'écrire cette spec :

1. **Les chiffres publiés mesurent l'heuristique, pas le produit.** `research/monte_carlo_sim.py` et `research/slumbot_benchmark.py` évaluent `hero_heuristic` (Chen + équité Monte-Carlo). Le runtime, lui, décide par `DecisionMaker.get_best_action` (store préflop, solveur Rust, cache, repli). Le seul benchmark du runtime est `research/slumbot_runtime_benchmark.py`, en 100 mains contre un service externe : son IC 95 % vaut ±125 bb/100 — il ne prouve rien. Rien n'empêche par ailleurs un artefact d'heuristique d'être lu comme une mesure du solveur : le champ `policy` existe, mais aucune règle ne l'utilise.
2. **Aucune puissance statistique déclarée.** La formule d'IC existe (`1.96·σ/√n`, `monte_carlo_sim.py:420`, `slumbot_benchmark.py` `summarize`), mais rien ne calcule **combien de mains il faut** pour atteindre une largeur d'IC visée *avant* de lancer la campagne. On mesure, puis on constate que l'intervalle est trop large (les IC publiés vont de ±100 à ±143 bb/100). L'audit l'exige explicitement : « un nombre de mains et une puissance statistique définis à l'avance ».
3. **Aucune réduction de variance (C11/C27).** Aucune occurrence d'AIVAT ni de MIVAT dans le dépôt. Les estimateurs sont des moyennes brutes : la variance du résultat par main en NLHE est énorme (σ ≈ 90 bb/100 en 6-max), donc il faut un volume irréaliste pour un IC étroit. AIVAT (C11) réduit la variance de 68–85 % sans biais ; MIVAT (C27) fait mieux en multiway. C'est le levier documenté par les études et il est absent.
4. **Le gate go-live a un trou mort.** `evaluate_go_live_gate` accepte `strategy_metrics` (`winrate_bb100`, `best_response_gap`) et neutralise les checks quand il est absent. Or **aucun appelant ne le fournit** : `operator_snapshot.py` appelle le gate sans cet argument. Les deux checks stratégiques sont donc toujours neutralisés — même schéma que le `SessionManager` orphelin trouvé en spec `004`. De plus, la seule condition est `winrate_bb100 >= 0` : un winrate de +0,1 bb/100 avec un IC [−50 ; +50] passerait, c'est-à-dire un résultat non significatif présenté comme une preuve.

Cette spec ne prétend pas produire un résultat significatif : le solveur coûte ~800 ms par flop à froid, une campagne de plusieurs milliers de mains n'est pas exécutable dans un tour de développement. Elle produit ce qui manque et qui est **testable hors ligne** : les **estimateurs à variance réduite** (vérifiés sans biais et réducteurs sur des jeux synthétiques à vérité connue), le **calcul de puissance statistique** à l'avance, un **harnais de benchmark du chemin de production** qui ne peut pas se faire passer pour l'heuristique, et le **câblage du gate** avec un artefact honnête. Le résultat réel s'obtient quand l'opérateur lance la campagne ; sans artefact, le gate reste honnêtement neutralisé.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Un estimateur de winrate sans biais et à variance réduite (Priority: P1)

En tant que mainteneur, je veux un estimateur de winrate qui utilise une variable de contrôle corrélée au résultat, afin d'obtenir un intervalle de confiance étroit avec beaucoup moins de mains qu'une moyenne brute — sans introduire de biais.

**Why this priority**: c'est le cœur de C11/C27 et la condition pour qu'un benchmark parle ; sans réduction de variance, aucun volume réaliste ne donne un IC exploitable.

**Independent Test**: sur un jeu synthétique à vérité connue, l'espérance de l'estimateur égale celle de la moyenne brute (sans biais) et sa variance est strictement inférieure.

**Acceptance Scenarios**:

1. **Given** des résultats et une variable de contrôle de moyenne connue, **When** l'estimateur est calculé, **Then** son espérance égale celle du résultat brut (aucun biais introduit).
2. **Given** une variable de contrôle corrélée au résultat, **When** l'estimateur est calculé, **Then** sa variance est strictement inférieure à celle de la moyenne brute.
3. **Given** une variable de contrôle constante, **When** l'estimateur est calculé, **Then** il est identique à la moyenne brute (aucune réduction inventée).
4. **Given** une variable de contrôle égale au résultat, **When** l'estimateur est calculé, **Then** sa variance est nulle.
5. **Given** plusieurs joueurs, **When** MIVAT est appliqué, **Then** chaque joueur reçoit son propre estimateur, sans biais, à partir de sa propre variable de contrôle.

---

### User Story 2 - Déclarer la puissance statistique avant de mesurer (Priority: P1)

En tant que mainteneur, je veux calculer à l'avance le nombre de mains nécessaire pour un intervalle de confiance visé, afin de ne pas découvrir après la campagne que le résultat est ininterprétable.

**Why this priority**: l'audit exige une taille d'échantillon justifiée à l'avance ; c'est ce qui distingue un protocole d'une mesure opportuniste.

**Independent Test**: pour σ = 90 bb/100 et une demi-largeur visée de 10 bb/100, le nombre de mains requis est 3 112 (=(1,96·90/10)²), et il croît quand la largeur visée décroît.

**Acceptance Scenarios**:

1. **Given** un écart-type et une demi-largeur d'IC visée, **When** le nombre de mains requis est calculé, **Then** il vaut `⌈(z·σ/demi-largeur)²⌉`.
2. **Given** une demi-largeur visée plus petite, **When** le nombre requis est recalculé, **Then** il est strictement plus grand (monotonie).
3. **Given** un écart-type nul, **When** le nombre requis est calculé, **Then** il vaut zéro (aucune main nécessaire pour un résultat certain).
4. **Given** un résultat mesuré et le nombre requis, **When** le verdict est calculé, **Then** il vaut `significant_positive`, `significant_negative`, `not_significant` ou `underpowered`, et le protocole est déclaré complet seulement si l'effectif atteint le requis et que l'IC est fourni.

---

### User Story 3 - Mesurer le chemin de production, jamais l'heuristique (Priority: P1)

En tant que mainteneur, je veux un harnais qui mesure une politique fournie (le chemin de production) sur un pool synthétique, enregistre honnêtement quelle politique a été mesurée, et refuse de présenter une mesure d'heuristique comme une mesure du solveur.

**Why this priority**: c'est le reproche central de F-03 — les chiffres publiés mesurent la chaîne heuristique, pas le produit. Un artefact doit porter cette distinction.

**Independent Test**: un rapport construit sur une politique étiquetée non-production porte `hero_policy_is_production = false` et ne satisfait pas le protocole du gate ; un rapport sans main évaluable est `unmeasured` avec des taux `None`.

**Acceptance Scenarios**:

1. **Given** une politique et un pool, **When** le harnais s'exécute, **Then** il produit winrate, IC 95 %, effectif évalué et le nombre de mains requis, dans un artefact JSON daté.
2. **Given** une politique étiquetée non-production, **When** l'artefact est écrit, **Then** `hero_policy_is_production` vaut faux et le protocole n'est pas complet.
3. **Given** aucune main évaluable, **When** le harnais s'exécute, **Then** le rapport est `unmeasured` avec des taux `None`, jamais un chiffre inventé.
4. **Given** une variable de contrôle fournie, **When** le harnais s'exécute, **Then** l'artefact porte l'estimation réduite et le taux de réduction mesuré, jamais un taux de réduction supposé.

---

### User Story 4 - Le gate go-live consomme l'artefact (Priority: P2)

En tant qu'opérateur, je veux que le gate de mise en production lise l'artefact d'évaluation stratégique, afin qu'un winrate significativement négatif ou un protocole incomplet bloque le déploiement — et qu'un résultat honnêtement non significatif soit accepté.

**Why this priority**: l'audit liste « gate de validation dans `go_live_gate` » ; le câblage existe mais est mort, et sa condition actuelle accepte un résultat non significatif.

**Independent Test**: un artefact avec IC [−50 ; +50] et effectif insuffisant ne rend pas le protocole complet ; un artefact avec IC [−80 ; −5] bloque le go-live ; un artefact avec IC [+2 ; +12] et effectif suffisant passe.

**Acceptance Scenarios**:

1. **Given** un artefact stratégique daté avec effectif ≥ requis et IC fourni, **When** le gate est évalué, **Then** le protocole est complet.
2. **Given** un IC dont la borne haute est négative, **When** le gate est évalué, **Then** le go-live est bloqué (winrate significativement négatif).
3. **Given** un IC contenant zéro, **When** le gate est évalué, **Then** le résultat est non significatif et **n'est pas** présenté comme une preuve (le protocole reste incomplet si l'effectif n'atteint pas le requis).
4. **Given** aucun artefact stratégique, **When** le gate est évalué, **Then** les checks stratégiques sont neutralisés, jamais bloquants (comportement historique préservé).

### Edge Cases

- Variable de contrôle dont la moyenne est estimée sur l'échantillon mesuré : l'estimateur est signalé comme non garanti sans biais (l'estimation doit venir d'un échantillon de calibration distinct ou d'une moyenne connue par construction).
- Écart-type nul ou demi-largeur nulle dans le calcul de puissance : entrée dégénérée, jamais une division par zéro.
- Effectif nul : `unmeasured`, jamais `0.0` bb/100.
- Artefact illisible ou absent : neutralisation, jamais un winrate de zéro inventé.
- Réduction de variance négative mesurée (contrôle anti-corrélé) : rapportée telle quelle, jamais forcée à zéro par le calcul.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le système MUST fournir un estimateur de winrate à variable de contrôle, sans biais pour toute variable de contrôle et toute moyenne connue.
- **FR-002**: L'estimateur MUST réduire la variance quand la variable de contrôle est corrélée au résultat, et MUST être identique à la moyenne brute quand elle est constante.
- **FR-003**: L'estimateur MUST rapporter sa variance et le taux de réduction de variance effectivement mesuré, jamais un taux supposé.
- **FR-004**: Le système MUST fournir une variante multi-joueurs (MIVAT) donnant un estimateur par joueur.
- **FR-005**: Le système MUST calculer le nombre de mains requis pour une demi-largeur d'IC visée, avant toute mesure.
- **FR-006**: Le système MUST classer un résultat mesuré en `significant_positive`, `significant_negative`, `not_significant` ou `underpowered`, et déclarer un protocole complet seulement si l'effectif atteint le requis et que l'IC est fourni.
- **FR-007**: Le harnais de benchmark MUST mesurer une politique fournie (le chemin de production) sur un pool synthétique et produire winrate, IC 95 %, effectif et nombre requis.
- **FR-008**: L'artefact MUST enregistrer la politique mesurée et un indicateur `hero_policy_is_production` ; une mesure d'heuristique MUST NOT être présentée comme une mesure du solveur.
- **FR-009**: Sans main évaluable, le harnais MUST produire un rapport `unmeasured` avec des taux `None`, jamais un chiffre inventé.
- **FR-010**: L'artefact MUST être JSON, daté et versionnable (`research/results/production_winrate_<site>.json`).
- **FR-011**: Le gate go-live MUST lire l'artefact stratégique et bloquer sur un winrate significativement négatif (borne haute de l'IC < 0).
- **FR-012**: Le gate MUST déclarer le protocole incomplet quand l'effectif est sous le requis ou que l'IC est absent, et MUST neutraliser les checks stratégiques quand aucun artefact n'est fourni.
- **FR-013**: Un artefact produit sur l'heuristique MUST NOT satisfaire le protocole du gate.
- **FR-014**: Le système MUST exposer un point d'entrée opérateur lançant la campagne et écrivant l'artefact, avec un message honnête quand rien n'est mesuré.

### Key Entities

- **EstimatorResult** : `n`, estimation réduite, estimation brute, demi-largeur d'IC réduite et brute, taux de réduction de variance, coefficient β, moyenne de la variable de contrôle, indicateur « entrées sans biais ».
- **WinrateVerdict** : `verdict`, `significant`, `protocol_complete`, `reasons`.
- **ProductionBenchmarkReport** : politique, indicateur de production, adversaires, mains, mains requises, winrate, IC, verdict, statut, réduction de variance, date.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: L'estimateur est sans biais sur un jeu synthétique à vérité connue (l'IC de l'estimation couvre la vérité au taux nominal) — vérifié par test.
- **SC-002**: L'estimateur réduit la variance sur un contrôle corrélé et est identique à la moyenne brute sur un contrôle constant — vérifié par test.
- **SC-003**: Le nombre de mains requis vaut `⌈(1,96·σ/demi-largeur)²⌉` et croît quand la largeur visée décroît — vérifié par test.
- **SC-004**: Le verdict distingue significatif positif, significatif négatif, non significatif et sous-dimensionné — vérifié par test.
- **SC-005**: Un artefact d'heuristique n'est pas accepté comme mesure de production par le gate — vérifié par test.
- **SC-006**: Le gate bloque sur un IC entièrement négatif et neutralise ses checks quand aucun artefact n'est fourni (non-régression) — vérifié par test.
- **SC-007**: `pytest`, `ruff` restent verts ; le comportement du gate sans artefact est inchangé.

## Assumptions

- Aucun nouveau solveur ni modèle n'est ajouté : les estimateurs consomment des résultats et des variables de contrôle fournis ; la variable de contrôle d'équité préflop réutilise `monte_carlo_equity` existant.
- La campagne réelle sur le pool synthétique n'est pas exécutée dans un tour de développement (coût solveur ~800 ms par flop à froid) : le harnais est testé sur des politiques déterministes, et la mesure réelle s'exécute quand l'opérateur lance le script.
- L'estimateur vit dans `research/` (outillage d'évaluation), conformément au principe II : Python est préféré pour les notebooks et l'outillage de recherche ; le calcul chaud (équité, solveur) reste en Rust et n'est pas dupliqué.
- Les adversaires sont les archétypes synthétiques existants (`nit`, `tag`, `lag`, `station`, `whale`) ; un bot de référence externe reste hors périmètre (dépendance réseau, déjà outillé par `slumbot_runtime_benchmark.py`).

## Plan de test

1. Test d'estimation : sans biais sur jeu synthétique, réduction de variance, contrôle constant, contrôle parfait, β optimal.
2. Test MIVAT : un estimateur par joueur, sans biais, sur un jeu synthétique à N joueurs.
3. Test de puissance : formule du nombre requis, monotonie, cas dégénérés.
4. Test de verdict : les quatre verdicts et la complétude du protocole.
5. Test de harnais : effectif exact, artefact daté, politique non-production signalée, `unmeasured` sans main.
6. Test de gate : protocole complet, blocage sur IC négatif, non-régression sans artefact.

## Hors périmètre

- HS-PCFR(30) (C16), EMD (C25), PKO/ICM tournois (C23/C24) : chantiers distincts listés par l'audit §5.
- L'entraînement d'un réseau de valeur appris (C06/C12) : AIVAT ici utilise une variable de contrôle analytique (équité), pas un modèle appris.
- Le portage Rust des estimateurs : ils tournent hors boucle de décision, dans `research/` (principe II).
- Le remplacement du benchmark Slumbot externe : il reste le seul point de comparaison contre un bot réel.
