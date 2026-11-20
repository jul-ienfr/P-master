# Feature Specification: Moteur de bankroll et de risque

**Feature Branch**: `004-bankroll-risk`

**Created**: 2026-11-20

**Status**: Livrée (20/11/2026) — moteur Rust `src/bankroll.rs` (16 tests contre les formes fermées des docs), 9 fonctions exposées par PyO3, enveloppe `src/bot/bankroll.py` avec journal d'audit JSONL, `session_manager.py` branché sur le moteur. Constat F-07 clos ; preuves dans `tasks.md` et `docs/AUDIT_COMPLET_2026-11-17.md` §3.5/§8.

**Input**: Audit du 17/11/2026, constat F-07 et cible §3.5 : « un moteur de bankroll en Rust, déterministe, avec RoR et probabilité de profit par limite, règles move-up/down explicites, limites dures par session, par jour et par format, journal d'audit de chaque changement de limite, tests contre des formules fermées. »

## Contexte

`src/bot/session_manager.py:15-17` ne définit que trois constantes :

- `max_session_hours = 4.0`
- `stop_loss_buyins = 3.0`
- `stop_win_buyins = 10.0`

Il n'existe **aucun** plan de bankroll : pas de risque de ruine, pas de move-up/move-down, pas de séparation cash/tournoi, pas de limites par format, pas de journal d'audit. Les documents `docs/probabilites.md` §6 et `docs/esperance.md` contiennent pourtant les formules (RoR, P(profit)) et les seuils recommandés (40 BI cash, 100–200 BI MTT, `docs/ordre-conseille.md`), mais rien n'est codé.

Deux pièges sont documentés et doivent être évités :

1. **Unités incohérentes.** Une version antérieure du §6 mélangeait bb et buy-ins et donnait des RoR absurdes. La règle est explicite dans le doc : `edge` et `roll` en buy-ins, `variance` en BI² par 100 mains (cash) ou BI² par tournoi (MTT).
2. **Formules non testées.** Une formule non confrontée à sa forme fermée dérive silencieusement. Chaque fonction doit être testée contre les valeurs tabulées du doc.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connaître son risque de ruine par limite (Priority: P1)

En tant qu'opérateur, je veux connaître le risque de ruine de ma bankroll à une limite donnée, afin de choisir ma limite sur une base chiffrée et non sur une intuition.

**Why this priority**: c'est la question de départ de toute gestion de bankroll, et le doc fournit déjà les valeurs de référence pour vérifier le calcul.

**Independent Test**: calculer le RoR 6-max WR 7 bb/100, σ 90, 40 BI et vérifier 0,10 % (valeur tabulée §6.2).

**Acceptance Scenarios**:

1. **Given** un winrate, un écart-type et une bankroll en buy-ins, **When** le RoR est calculé, **Then** il vaut `exp(−2·edge·roll/variance)` avec les unités du §6.
2. **Given** un RoR calculé, **When** il est comparé aux seuils documentés, **Then** une bande de risque qualitative est retournée (Safe / Acceptable / Elevated / Excessive).
3. **Given** un RoR cible (1 %), **When** on demande la bankroll minimale, **Then** la fonction inverse de `exp` retourne le nombre de buy-ins correspondant.

---

### User Story 2 - Savoir quand monter ou descendre de limite (Priority: P1)

En tant qu'opérateur, je veux une règle déterministe de move-up/move-down, afin d'augmenter ma limite quand la bankroll le permet et de redescendre avant la ruine.

**Why this priority**: sans règle explicite, la décision se prend à chaud et se termine en ruine ou en sur-conservatisme.

**Independent Test**: avec une règle up = 50 BI / down = 30 BI, vérifier `MoveUp` à 60 BI, `MoveDown` à 25 BI et `Stay` à 40 BI (zone morte).

**Acceptance Scenarios**:

1. **Given** une bankroll au-dessus du seuil haut, **When** la décision est évaluée, **Then** `MoveUp` est retourné.
2. **Given** une bankroll sous le seuil bas, **When** la décision est évaluée, **Then** `MoveDown` est retourné.
3. **Given** une bankroll dans la zone morte (entre down et up), **When** la décision est évaluée, **Then** `Stay` est retourné — aucune oscillation sur un seuil unique.
4. **Given** la limite la plus haute ou la plus basse de l'échelle, **When** la décision est évaluée, **Then** on ne sort pas de l'échelle.

---

### User Story 3 - Appliquer des limites dures de session (Priority: P1)

En tant qu'opérateur, je veux que la session s'arrête automatiquement sur durée, stop-loss, stop-win ou plafond de mains, afin de protéger la bankroll contre le tilt et la fatigue.

**Why this priority**: c'est le seul mécanisme de protection déjà présent en Python ; il doit être conservé, testé et étendu, pas perdu à la migration.

**Independent Test**: vérifier que chaque limite déclenche l'arrêt avec son motif, et que la durée prime sur le stop-loss.

**Acceptance Scenarios**:

1. **Given** une session dépassant `max_hours`, **When** l'état est évalué, **Then** l'arrêt est déclenché avec le motif `MaxDuration`.
2. **Given** une perte atteignant le stop-loss, **When** l'état est évalué, **Then** l'arrêt est déclenché avec le motif `StopLoss`.
3. **Given** un gain atteignant le stop-win, **When** l'état est évalué, **Then** l'arrêt est déclenché avec le motif `StopWin`.
4. **Given** un plafond de mains par jour atteint, **When** l'état est évalué, **Then** l'arrêt est déclenché avec le motif `DailyHands`.
5. **Given** plusieurs limites franchies simultanément, **When** l'état est évalué, **Then** le motif est déterministe (ordre : durée → plafond journalier → stop-loss → stop-win).

---

### User Story 4 - Vérifier la viabilité d'un plan (Priority: P2)

En tant qu'opérateur, je veux connaître ma probabilité d'être profitable après N mains, afin de juger si un winrate est exploitable ou si le volume requis est hors de portée.

**Why this priority**: utile pour décider de rester ou non à une limite, mais secondaire par rapport au risque de ruine.

**Independent Test**: P(profit) 6-max WR 7, σ 90, 50 000 mains → 96 % (§2.2).

**Acceptance Scenarios**:

1. **Given** un winrate, un écart-type et un nombre de mains, **When** P(profit) est calculé, **Then** il vaut `Φ(WR·√(N/100)/σ)`.
2. **Given** un plus grand nombre de mains, **When** P(profit) est recalculé, **Then** il augmente.

### Edge Cases

- Variance nulle ou négative : pas de RoR défini → `None`, jamais une division par zéro silencieuse.
- Edge nul ou négatif : la ruine est certaine à horizon infini → 1,0 (pas `None`).
- Bankroll négative : entrée invalide → `None`.
- Valeurs non finies (NaN, inf) : entrée invalide → `None`.
- RoR cible hors de ]0, 1[ : entrée invalide → `None`.
- Règle move-up/down inversée (down ≥ up) : règle invalide → `Stay`.
- Kelly au-delà de 1 : borné à 1 (jamais plus que la bankroll entière).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le système MUST calculer le risque de ruine par `exp(−2·edge·roll/variance)` avec `edge` et `roll` en buy-ins et `variance` en BI² par 100 mains (cash) ou BI² par tournoi (MTT).
- **FR-002**: Le système MUST accepter les unités naturelles du cash (bb/100, bb/100) et faire la conversion vers les unités buy-ins en interne.
- **FR-003**: Le système MUST séparer les formats cash et tournoi.
- **FR-004**: Le système MUST calculer P(profit) par `Φ(WR·√(N/100)/σ)`, avec une approximation de `Φ` d'erreur absolue documentée.
- **FR-005**: Le système MUST fournir la bankroll minimale pour un RoR cible (inverse du RoR).
- **FR-006**: Le système MUST fournir des règles move-up/down à hystérésis (seuil haut ≠ seuil bas).
- **FR-007**: Le système MUST borner les décisions de limite aux extrémités de l'échelle.
- **FR-008**: Le système MUST évaluer les limites dures de session (durée, plafond journalier, stop-loss, stop-win) avec un ordre de priorité déterministe.
- **FR-009**: Le système MUST retourner une entrée invalide par `None` (Rust) / `None` (Python) plutôt que par une valeur inventée.
- **FR-010**: Le calcul MUST être déterministe et sans état — mêmes entrées, mêmes sorties.
- **FR-011**: Le système MUST être exposé au runtime Python via les bindings PyO3.
- **FR-012**: Chaque décision de bankroll MUST être journalisable pour l'audit.
- **FR-013**: Les valeurs de référence des docs MUST être des tests automatisés (formes fermées).

### Key Entities

- **BankrollAssessment** : format, bankroll en BI, RoR, bande de risque, fraction de Kelly, bankroll cible pour 1 % de RoR.
- **MoveRule** : seuils haut et bas en buy-ins.
- **MoveDecision** : `Stay` | `MoveUp` | `MoveDown`.
- **SessionLimits** : durée, stop-loss, stop-win, plafond journalier de mains.
- **SessionVerdict** : `Continue` | `Stop(StopReason)`.
- **RiskBand** : `Safe` | `Acceptable` | `Elevated` | `Excessive`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Les valeurs tabulées du doc §2 et §6 sont reproduites à la tolérance près (RoR 6-max WR7/40BI = 0,10 % ; RoR HU WR5/20BI = 1,69 % ; P(profit) 50k = 96 %).
- **SC-002**: 100 % des fonctions publiques ont au moins un test, y compris les cas d'entrée invalide.
- **SC-003**: L'inverse du RoR redonne la valeur d'entrée (aller-retour à 10⁻⁵).
- **SC-004**: Le seuil documenté de 40 BI ramène le RoR 6-max sous 1 % — vérifié par calcul, pas posé.
- **SC-005**: La monotonie est vérifiée : plus de bankroll réduit le RoR, plus d'edge réduit le RoR, plus de mains augmente P(profit).
- **SC-006**: Le runtime Python obtient les mêmes valeurs que le Rust.
- **SC-007**: `cargo test` et `pytest` restent verts.

## Assumptions

- Les formules du doc sont la source de vérité ; en cas de désaccord, le doc est relu avant le code.
- `f32` suffit pour les valeurs de bankroll (précision bien au-delà des seuils de décision) ; `f64` est utilisé pour `Φ`.
- Le winrate et l'écart-type proviennent de mesures existantes (spec `003`) ; cette spec ne les produit pas.
- L'échelle de limites (blindes) est fournie par l'appelant ; cette spec ne code pas de table de limites par site.
- Le journal d'audit réutilise l'infrastructure de journalisation existante.

## Plan de test

1. Test unitaire : `Φ` contre les points connus (0,5 / 0,8413 / 0,9750) et symétrie.
2. Test unitaire : RoR cash, HU, 6-max et MTT contre les tables du doc.
3. Test unitaire : entrées dégénérées → `None` ; edge nul/négatif → 1,0.
4. Test unitaire : monotonie en bankroll, edge et nombre de mains.
5. Test unitaire : inverse du RoR (aller-retour).
6. Test unitaire : règles move-up/down, zone morte, bornes, règle invalide.
7. Test unitaire : limites de session, priorité et chaque motif.
8. Test d'intégration : bindings Python == valeurs Rust.

## Hors périmètre

- La production du winrate et de l'écart-type (spec `003`).
- L'ICM/PKO et les structures de tournoi complexes (C23/C24).
- Le Kelly multi-limites / le portefeuille de limites.
- La table des limites par site (relève du contrat `PlatformAdapter`, §3.6).
- Le pilotage automatique du siège ou de la limite sans confirmation humaine.
