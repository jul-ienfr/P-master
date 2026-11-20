# Feature Specification: Observabilité — traces par étage, SLO et registre de versions

**Feature Branch**: `008-observability-slo`

**Created**: 2026-11-20

**Status**: En cours

**Input**: Audit du 17/11/2026 §3.8 (« Observabilité ») et constat F-10 (« Pas de traces/SLO complets », P1). Correctif attendu : « tracing `spot_id`, métriques par étage, SLO et alertes ». L'audit §3.4 ajoute : « le taux de fallback n'est pas un SLO bloquant ».

## Contexte

Trois manques mesurés avant d'écrire cette spec :

1. **Aucune mesure par étage.** `get_best_action` traverse une dizaine d'étages (profil villain, range héros, mise à jour bayésienne de range, RL, appel solveur, exploitation, gate, post-traitement), mais **seule la latence totale du solveur** est enregistrée (`gto_details["elapsed_ms"]`). Le journal de décision (`src/runtime/decision_log.py`) porte `decision.elapsed_ms` — un seul nombre. Quand une décision est lente, rien ne dit *quel étage* l'est : le seul recours est de lire le code et d'instrumenter à la main. Un `perf_counter` autour de chaque étage coûte moins d'une microseconde et répond définitivement à la question.

2. **Aucun SLO ni alerte.** Il existe des seuils d'admission au go-live (`DEFAULT_GO_LIVE_THRESHOLDS` : `max_block_rate`, `max_fallback_rate`, `max_rolling_latency_ms`) et un moniteur de santé par sous-système (`src/runtime/health.py`), mais **rien** n'évalue en continu un objectif de niveau de service sur les décisions réelles et ne déclenche d'alerte quand il est franchi. Un taux de fallback de 40 % en session ne lève aucun signal : il n'est visible qu'en relisant un snapshot. L'audit le dit explicitement.

3. **Aucun registre de versions par décision.** Une décision passée n'est pas reproductible parce qu'on ne sait pas *avec quoi* elle a été prise : version du schéma, du blueprint préflop (`BLUEPRINT_FORMAT_VERSION`), du modèle de range (`RangeModelVersion` des contrats V2), des tailles de mise du solveur (`solver_bet_sizes`/`solver_raise_sizes`). Ces versions **existent** dans le code mais ne sont attachées à aucun enregistrement. De plus, `validate_decision_record` rejette tout enregistrement dont `schema_version != SCHEMA_VERSION` : le jour où le schéma passe à 2, **tout le journal historique devient « invalide »** — un audit de log ancien échoue en bloc au lieu de le lire avec son schéma d'origine.

Cette spec ne prétend pas ajouter un backend de métriques externe (Prometheus/OTLP) : elle produit ce qui manque et qui est **testable hors ligne** — l'instrumentation par étage dans le chemin réel, une évaluation de SLO pure et testable, un registre de versions attaché à chaque décision, et une lecture du journal qui respecte le schéma d'origine de chaque enregistrement. L'export externe reste un chantier distinct.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Savoir quel étage coûte le temps (Priority: P1)

En tant qu'opérateur, je veux que chaque décision enregistre le temps passé par étage, afin d'attribuer une lenteur à un étage précis au lieu de deviner.

**Why this priority**: c'est le premier item du correctif de F-10, et la condition pour que les SLO aient un sens (un SLO sur la latence totale ne dit pas quoi corriger).

**Independent Test**: une décision produite par le chemin instrumenté porte un `stages_ms` non vide dont la somme des étages d'appel solveur approche la latence totale, et le résumé d'un journal calcule des percentiles par étage.

**Acceptance Scenarios**:

1. **Given** une décision passée par le chemin instrumenté, **When** l'enregistrement est construit, **Then** il porte un `stages_ms` avec au moins les étages traversés, chacun à une valeur ≥ 0.
2. **Given** un journal d'enregistrements portant `stages_ms`, **When** le résumé est calculé, **Then** il rapporte p50/p95/p99 par étage, pas seulement la latence totale.
3. **Given** un enregistrement sans `stages_ms` (schéma antérieur), **When** le résumé est calculé, **Then** il reste valide et le résumé n'invente pas d'étage absent.
4. **Given** les fixtures de rejeu golden, **When** une décision est rejouée, **Then** la comparaison au champ près reste inchangée : l'instrumentation n'ajoute pas de clé au payload de décision comparé.

---

### User Story 2 - Un SLO évalué en continu et des alertes (Priority: P1)

En tant qu'opérateur, je veux évaluer des objectifs de niveau de service sur les métriques réelles et recevoir une alerte quand ils sont franchis, afin qu'une dégradation soit signalée pendant la session et pas découverte après coup.

**Why this priority**: l'audit note que le taux de fallback n'est pas un SLO ; sans évaluation continue, aucune dégradation n'est signalée.

**Independent Test**: des métriques avec un taux de fallback de 0,4 et un p95 de 900 ms contre un SLO (fallback ≤ 0,1, p95 ≤ 500 ms) produisent deux violations et deux alertes ; des métriques dans les cibles ne produisent rien.

**Acceptance Scenarios**:

1. **Given** des métriques et une cible de SLO, **When** le SLO est évalué, **Then** chaque objectif est marqué `ok` ou `breached`, avec la valeur mesurée et la cible.
2. **Given** un objectif franchi, **When** le SLO est évalué, **Then** une alerte nommée porte l'objectif, la valeur, la cible et la sévérité.
3. **Given** des métriques sans effectif suffisant, **When** le SLO est évalué, **Then** l'objectif est `insufficient_data`, jamais un succès par défaut sur un échantillon vide.
4. **Given** aucun SLO configuré, **When** l'évaluation est demandée, **Then** elle retourne un ensemble vide, jamais une fausse alerte.

---

### User Story 3 - Reproductibilité : versions attachées à chaque décision (Priority: P2)

En tant qu'auditeur, je veux que chaque décision enregistre les versions qui l'ont produite, afin de pouvoir rejouer ou interpréter une décision passée sans deviner l'état du code.

**Why this priority**: l'audit liste « un registre des versions (code, ranges, modèle, solveur) attaché à chaque décision » ; c'est ce qui rend un journal exploitable dans le temps.

**Independent Test**: un enregistrement construit porte un bloc `versions` non vide avec au moins la version de schéma et la version du modèle de range ; deux décisions prises avec des tailles de mise de solveur différentes portent des versions différentes.

**Acceptance Scenarios**:

1. **Given** une décision enregistrée, **When** l'enregistrement est construit, **Then** il porte un bloc `versions` avec la version de schéma et les versions disponibles (blueprint, modèle de range, tailles de mise).
2. **Given** une version indisponible, **When** le bloc est construit, **Then** le champ vaut `None`, jamais une valeur inventée.
3. **Given** un journal écrit sous un schéma antérieur, **When** il est validé, **Then** il est accepté comme un schéma connu et signalé avec sa version, au lieu d'être rejeté en bloc.

---

### User Story 4 - Le gate go-live et les alertes ne se contredisent pas (Priority: P2)

En tant qu'opérateur, je veux que les seuils d'admission (gate) et les SLO de fonctionnement soient des notions distinctes et cohérentes, afin de ne pas confondre « apte à démarrer » et « en bonne santé maintenant ».

**Independent Test**: un SLO franchi ne modifie pas le verdict du gate, et le gate n'invente pas d'alerte.

**Acceptance Scenarios**:

1. **Given** un SLO franchi et un gate par ailleurs vert, **When** les deux sont évalués, **Then** le gate reste `go` et le SLO rapporte une alerte — les deux verdicts sont indépendants et nommés.
2. **Given** une évaluation de SLO, **When** elle retourne un résultat, **Then** elle n'écrit dans aucun état global et ne modifie aucun seuil du gate.

### Edge Cases

- `stages_ms` dont la somme dépasse la latence totale (mesures imbriquées) : la somme des étages est rapportée telle quelle, jamais recadrée à la latence totale.
- Objectif de SLO dont la cible est absente ou non numérique : objectif ignoré avec une raison, jamais un `breached` implicite.
- Effectif nul : `insufficient_data`, jamais `ok`.
- Percentile demandé sur une liste vide : `0.0`, jamais une exception.
- Version de schéma inconnue (ni la courante ni une connue) : signalée comme `unknown`, jamais acceptée silencieusement comme valide.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le chemin de décision MUST mesurer le temps passé par étage et l'exposer dans la trace de décision sous `stages_ms`.
- **FR-002**: L'instrumentation MUST NOT ajouter de clé au payload de décision comparé par les rejeux golden.
- **FR-003**: Le résumé d'un journal MUST calculer p50/p95/p99 **par étage** quand `stages_ms` est présent, sans inventer d'étage absent.
- **FR-004**: Le système MUST fournir une évaluation de SLO pure (métriques + cibles → statut par objectif + alertes), sans effet de bord.
- **FR-005**: Un objectif sans effectif suffisant MUST être `insufficient_data`, jamais `ok`.
- **FR-006**: Chaque alerte MUST porter l'objectif, la valeur mesurée, la cible et une sévérité.
- **FR-007**: Chaque enregistrement de décision MUST porter un bloc `versions` (schéma, blueprint, modèle de range, tailles de mise du solveur), les versions indisponibles valant `None`.
- **FR-008**: La validation d'un enregistrement MUST accepter tout schéma connu et signaler sa version, au lieu de rejeter en bloc un schéma antérieur.
- **FR-009**: L'évaluation de SLO MUST être indépendante du gate go-live : ni l'une ni l'autre ne modifie le verdict de l'autre.
- **FR-010**: Les seuils de SLO MUST être configurables et les valeurs par défaut déclarées en un seul endroit.

### Key Entities

- **StageTimings** : `stages_ms` (nom d'étage → millisecondes), `total_ms`.
- **SloObjective** : `name`, `metric`, `operator`, `target`, `severity`.
- **SloEvaluation** : `objectives` (statut par objectif), `alerts`, `evaluated_at`.
- **DecisionVersions** : `schema_version`, `blueprint_version`, `range_model_version`, `solver_bet_sizes`, `solver_raise_sizes`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Une décision du chemin instrumenté porte `stages_ms` avec les étages traversés — vérifié par test.
- **SC-002**: Le résumé d'un journal rapporte les percentiles par étage, et reste valide sans `stages_ms` — vérifié par test.
- **SC-003**: L'instrumentation ne change pas le payload comparé par les rejeux golden — vérifié par test de non-régression.
- **SC-004**: Un SLO franchi produit une alerte nommée ; des métriques dans les cibles n'en produisent aucune — vérifié par test.
- **SC-005**: Un effectif insuffisant donne `insufficient_data`, jamais `ok` — vérifié par test.
- **SC-006**: Un enregistrement porte `versions` ; un schéma antérieur connu est accepté et signalé — vérifié par test.
- **SC-007**: Le gate go-live reste inchangé (tests existants verts) ; `pytest` et `ruff` restent verts.

## Assumptions

- Aucun backend de métriques externe (Prometheus/OTLP/OpenTelemetry) n'est ajouté : le système produit des structures évaluables et exportables, l'export reste un chantier distinct. C'est le périmètre honnête de F-10 côté code.
- Les SLO portent sur des métriques déjà disponibles (latences, taux de fallback, taux de blocage, taux multiway échantillonné) ; aucune nouvelle source de données n'est requise.
- Les étages instrumentés sont ceux du chemin HU actuel (`profile`, `ranges`, `rl`, `solver`, `exploit`, `gate`) ; un étage absent d'une décision n'apparaît pas dans `stages_ms`.
- Le surcoût de l'instrumentation (`time.perf_counter` par étage, < 1 µs) est négligeable devant les budgets de décision (centaines de ms) ; il est mesuré, pas supposé.
- L'acceptation d'un schéma antérieur ne dispense pas de migrer : elle permet de **lire** un journal ancien, pas de le traiter comme courant.

## Plan de test

1. Test d'instrumentation : `stages_ms` présent, étages non négatifs, pas de clé ajoutée au payload de décision.
2. Test de résumé : percentiles par étage ; enregistrement sans `stages_ms` toujours valide.
3. Test de SLO : objectif tenu, objectif franchi, effectif insuffisant, SLO vide.
4. Test de versions : bloc `versions` présent, versions indisponibles à `None`, tailles de mise distinguées.
5. Test de schéma : schéma courant accepté, schéma antérieur connu accepté et signalé, schéma inconnu signalé.
6. Test d'indépendance : un SLO franchi ne change pas le verdict du gate (non-régression).

## Hors périmètre

- L'export vers un backend de métriques (Prometheus, OTLP) et les tableaux de bord : chantier d'industrialisation distinct.
- Le tracing distribué (span parent/enfant, OpenTelemetry) : la corrélation `spot_id` existe déjà dans le journal ; l'ajout d'un format de trace externe est hors périmètre.
- L'alerting hors processus (Slack, e-mail, PagerDuty) : le système produit des alertes structurées ; leur acheminement est un chantier distinct.
- La modification des seuils du gate go-live : la spec 011 a déjà étendu ses checks ; ici le gate n'est pas touché.
