# Feature Specification: Multiway réel 3–6 joueurs

**Feature Branch**: `002-runtime-n-way`

**Created**: 2026-11-17

**Status**: Clôturée (19/11/2026) — implémentation livrée, tests verts, benchmark multiway 3–6 exécuté (40 mesures, 0 fallback, 40/40 `sampled=true`). Clôture du constat F-02 de l'audit ; preuves dans `tasks.md` et `docs/AUDIT_COMPLET_2026-11-17.md` §8.

**Input**: Audit du 17/11/2026, constat F-02 : le runtime appelle le solveur sans `num_players` ni ranges secondaires et approxime le multiway en HU.

## Contexte

Le solveur Rust possède un chemin MCCFR multiway pour 3 à 6 joueurs (`src/multiway.rs:13`, `MAX_PLAYERS = 6`). L'API V2 peut l'utiliser (`src/v2_api.rs:985-990`). Mais le runtime de production ne l'appelle jamais :

- `src/bot/gate_flow.py:352` calcule `active_villain_count` ;
- `src/bot/decision_maker.py:1683-1702` l'utilise pour resserrer la range et émettre un warning « approximation HU » ;
- `src/bot/decision_maker.py:1791-1804` n'envoie ni `num_players` ni les ranges des autres villains ;
- `SolveRequestV2.num_players` vaut 2 par défaut (`src/v2_api.rs:401`).

Le format recommandé par les docs est le cash 6-max. C'est donc le cas d'usage principal qui est approximé.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Résoudre un spot 3-way (Priority: P1)

En tant qu'opérateur, je veux qu'un pot 3-way soit résolu avec trois joueurs et trois ranges, afin que la stratégie tienne compte des deux adversaires.

**Why this priority**: le 3-way est la première marche au-delà du HU et il est déjà supporté par le moteur.

**Independent Test**: rejouer un spot 3-way avec trois ranges distinctes et vérifier que la requête contient `num_players=3` et que le backend est multiway.

**Acceptance Scenarios**:

1. **Given** un état 3-way valide, **When** le runtime demande une décision, **Then** la requête contient `num_players=3` et trois ranges ordonnées.
2. **Given** la même main, **When** on compare HU et 3-way, **Then** les stratégies ou les EV diffèrent et le journal indique le mode multiway.
3. **Given** un joueur assis-out, **When** l'état est résolu, **Then** il n'est pas compté comme actif.

---

### User Story 2 - Résoudre un spot 6-max (Priority: P1)

En tant qu'opérateur, je veux qu'un spot 6-max soit résolu avec six joueurs ou, si le moteur ne peut pas, avec un fallback explicite, afin de ne plus jouer du 6-max comme du HU.

**Why this priority**: c'est le format cible et le cas où l'approximation actuelle est la plus éloignée de la réalité.

**Independent Test**: rejouer un spot 6-max avec cinq villains actifs et vérifier `num_players=6`, cinq ranges, et un warning de convergence.

**Acceptance Scenarios**:

1. **Given** un état 6-max valide, **When** le runtime demande une décision, **Then** la requête contient `num_players=6` et cinq ranges.
2. **Given** un état 6-max avec un joueur assis-out, **When** l'état est résolu, **Then** `num_players` vaut 5 et quatre ranges sont envoyées.
3. **Given** un nombre de joueurs supérieur à la limite du kill switch, **When** la décision est demandée, **Then** le fallback est explicite et journalisé, jamais une approximation HU silencieuse.

---

### User Story 3 - Tracer et borner l'approximation (Priority: P2)

En tant qu'opérateur, je veux savoir quand une réponse est échantillonnée, non convergée ou approximée, afin de ne pas la confondre avec un équilibre exact.

**Why this priority**: le MCCFR multiway est un échantillonnage ; il ne certifie pas une exploitabilité exacte.

**Independent Test**: vérifier que chaque réponse multiway contient `backend`, `num_players`, `converged=false` (ou l'équivalent) et un warning.

**Acceptance Scenarios**:

1. **Given** une réponse multiway, **When** elle est journalisée, **Then** le mode, le nombre de joueurs et l'état de convergence sont enregistrés.
2. **Given** le mode strict, **When** un spot multiway est demandé, **Then** la requête est refusée explicitement (`multiway_strict_refused`), pas approximée.
3. **Given** un budget insuffisant, **When** le solveur rend la main, **Then** la réponse est étiquetée non convergée et le fallback est explicite.

### Edge Cases

- Un seul villain actif : doit rester HU, pas multiway.
- Deux villains avec la même range : les ranges doivent rester distinctes dans l'ordre des positions.
- Position du héros absente ou invalide : fallback explicite.
- Board incomplet pour la rue : fallback ou erreur contrôlée.
- Plus de six joueurs : refus explicite, pas de troncature silencieuse.
- Mémoire insuffisante : dégradation contrôlée, jamais de crash.
- Rake et PKO : le rake doit rester transmis au chemin multiway ; le PKO est hors périmètre.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le runtime MUST calculer le nombre de joueurs actifs à partir de l'état canonique, pas d'une constante.
- **FR-002**: Le runtime MUST transmettre `num_players` au solveur.
- **FR-003**: Le runtime MUST transmettre une range par villain actif, ordonnée par position.
- **FR-004**: Le runtime MUST utiliser le chemin multiway V2 pour 3 à 6 joueurs.
- **FR-005**: Le runtime MUST conserver le chemin HU pour deux joueurs.
- **FR-006**: Toute réponse multiway MUST être étiquetée comme échantillonnée et non convergée.
- **FR-007**: Le mode strict MUST refuser le multiway au lieu de l'approximer.
- **FR-008**: Le budget MUST être adapté au nombre de joueurs et au budget global de décision.
- **FR-009**: Le fallback MUST être explicite, journalisé et compté dans les métriques.
- **FR-010**: Le cache MUST inclure `num_players` et l'ensemble des ranges.
- **FR-011**: Le journal MUST contenir le nombre de joueurs, les positions et le mode de résolution.
- **FR-012**: Le système MUST rester compatible avec le rake et l'historique d'actions.

### Key Entities

- **TableState** : joueurs actifs, positions, stacks, bouton, rues, pot.
- **MultiwayRequest** : ranges ordonnées, board, pot, stack, héros, itérations, rake.
- **MultiwayResponse** : action, EV, convergence, warnings, backend.
- **ActivePlayerSet** : ensemble ordonné des joueurs actifs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % des spots 3–6 way utilisent le chemin multiway ou un fallback explicitement étiqueté.
- **SC-002**: Zéro approximation HU silencieuse dans les journaux de production.
- **SC-003**: Le benchmark 6-max montre `backend=multiway` et `num_players=6` sur les spots prévus.
- **SC-004**: La latence p95 d'un spot 6-way reste dans le budget de décision ou déclenche une dégradation contrôlée documentée.
- **SC-005**: Le cache distingue deux configurations de joueurs différentes.
- **SC-006**: Les tests 3-way, 4-way, 5-way et 6-way passent, y compris avec un joueur assis-out.
- **SC-007**: Le mode strict refuse le multiway avec un motif identifiable.

## Assumptions

- Le solveur multiway est déjà fonctionnel pour 3 à 6 joueurs et n'a pas besoin d'être réécrit.
- Le MCCFR multiway est un échantillonnage : il ne fournit pas une exploitabilité exacte.
- Le runtime peut obtenir les ranges par position via `PreflopManager` et `BayesianRangeUpdater`.
- Le budget de décision reste piloté par le tier Jev et le nombre de joueurs.
- Le PKO et l'ICM multiway sont hors périmètre de cette spec.

## Plan de test

1. Test unitaire : comptage des joueurs actifs avec assis-out.
2. Test de contrat : `SolveRequestV2` avec `num_players=6` et cinq ranges.
3. Test d'intégration : rejeu d'un spot 6-max, vérification du backend et des warnings.
4. Test de non-régression : HU inchangé.
5. Test de cache : deux ensembles de joueurs produisent deux clés.
6. Test de mode strict : refus explicite.
7. Benchmark : latence et mémoire par nombre de joueurs.

## Hors périmètre

- La correction de la range héros (spec `001`), qui doit être livrée avant.
- La preuve de winrate (spec `003`).
- Le support des tournois PKO/ICM multiway.
- L'optimisation Rust du MCCFR au-delà des besoins du budget.
