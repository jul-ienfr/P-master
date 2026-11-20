# Feature Specification: Schedules d'hyperparamètres CFR et mesure de convergence

**Feature Branch**: `012-cfr-hyperparameter-schedules`

**Created**: 2026-11-20

**Status**: Draft

**Input**: Audit du 17/11/2026, constat F-12 (« HS-PCFR/EMD/FGS/PKO absents », correctif attendu « expérimenter C16/C25/C23/C24 derrière des flags »), traçabilité C16 marquée « Absent » (`docs/etudes.md`, `docs/AUDIT_COMPLET_2026-11-17.md` §5). Feuille de route Sprint 3 : « Expérience HS-PCFR sur un sous-ensemble de spots. → reste à faire (C16). »

## Contexte

L'audit §5 marque **C16 « HS-PCFR(30) — Absent — expérimentation de convergence »** et la feuille de route Sprint 3 laisse C16 « à faire ». La fiche C16 de `docs/etudes.md` en fait un « **P0 optionnel** — swap DCFR → HS-PCFR+ drop-in (remplacer `DiscountParams::gamma_t`) », avec un apport annoncé de « **2–3 ordres de magnitude** vs DCFR ».

En préparant cette spec, quatre défauts ont été mesurés dans l'état actuel :

1. **Les deux identifiants arXiv de la fiche C16 sont faux.** La fiche cite « arXiv [2405.08234](https://arxiv.org/abs/2405.08234) + [2405.15794](https://arxiv.org/abs/2405.15794) ». Vérification à la source (API arXiv et page de l'article) : `2405.08234` est *« Nakajima's quiver varieties and triangular bases of bipartite cluster algebras »* (Li Li, math.RT) et `2405.15794` est *« Finite Groundings for ASP with Functions »* (Gerlach, Carral, Hecher, cs.AI). **Aucun des deux ne concerne le CFR ni le poker.** Le vrai article est **arXiv 2404.09097**, *Faster Game Solving via Hyperparameter Schedules* (Naifeng Zhang, Stephen McAleer, Tuomas Sandholm, AAAI 2026). Une référence scientifique fabriquée viole directement le principe I de la constitution (« la théorie » est l'une des deux sources de vérité).
2. **La formule citée est incomplète et la variante recommandée est la mauvaise pour ce projet.** La fiche écrit `γ(t) = 30 − 5t/1000` : c'est `HSγ30` évalué à `n = 1000` seulement. La formule réelle est `γ = 30 − 5·(t/n)`. Plus grave : la fiche attribue le gain au **HS-PCFR+**, alors que l'article **recommande HS-DCFR(30) pour les grands jeux de poker** et constate que HS-PCFR+ est *moins* efficace que DCFR sur les jeux de type poker (Leduc, Big Leduc, Liar's dice), PCFR+ n'étant meilleur que sur Kuhn — un jeu minuscule. Un swap vers « HS-PCFR+ » tel que décrit aurait donc appliqué la variante déconseillée au domaine cible.
3. **`solver.rs` implémente une variante DCFR propre au crate, non le DCFR canonique.** `DiscountParams::new` (`src/solver.rs:18-38`) utilise `α_t = t^1,5/(t^1,5+1)`, `β_t = 0,5` **constant** (le DCFR canonique recommande β = 0) et `γ_t = (t_γ/(t_γ+1))³` où `t_γ` est remis à zéro **à chaque puissance de 4** (`nearest_lower_power_of_4`), donc la stratégie cumulée est réinitialisée périodiquement. Le doc de `lib.rs` l'assume (« γ is set to 3.0 instead of the 2.0 recommended »). Le gain de C16 a été mesuré par ses auteurs sur *leur* implémentation : le transposer à une variante différente est une hypothèse, pas un fait — l'article lui-même avertit que « the relative advantage of HSs diminishes as the game size increases ».
4. **`config.json` porte une clé morte.** `"hs_pcf_30_enabled": false` (ligne 139) n'est lue par **aucun** code : `grep` sur tout le dépôt (`.py`, `.rs`, `.json`, `.md`, hors `.kilo/`) ne la trouve que dans `config.json`. Une clé de configuration qui n'a aucun effet est un mensonge par omission : elle suggère un réglage qui n'existe pas. Même famille de défaut que le `SessionManager` orphelin (spec `004`) et le `strategy_metrics` jamais fourni (spec `011`).

Cette spec livre ce qui est **testable hors ligne et reproductible** : un schedule de discount **sélectionnable**, à comportement par défaut **inchangé**, et un **harnais de mesure de convergence** sur les jeux de test déjà présents dans le dépôt (`tests/kuhn.rs`, `tests/leduc.rs`), qui ont une valeur de jeu de référence connue et vérifiée. Elle corrige la référence C16 et traite la clé de configuration morte.

**Hors périmètre, assumé et motivé :**
- **C23 (PKO bounty) et C24 (ICM/FGS)** : tournois uniquement. `config.json` porte `"tournament": {"enabled": false}` et l'audit écrit « pour le cash, ce n'est pas bloquant ; pour les tournois, oui ». Les implémenter serait une fonctionnalité sans usage dans le mode livré.
- **C25 (EMD clustering)** : abstraction de ranges. L'audit note que « l'abstraction de ranges reste heuristique » ; c'est un chantier de bucketing, pas un swap de schedule, et il n'a pas de vérité de référence hors ligne équivalente à Kuhn/Leduc. Reste ouvert, priorité inchangée.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Un schedule de discount sélectionnable, sans changement par défaut (Priority: P1)

En tant que mainteneur, je veux pouvoir choisir le schedule de discount du solveur (DCFR actuel, HS-DCFR(30), HS-DCFR(15)) par la requête, afin d'expérimenter la convergence sans toucher au comportement de production.

**Why this priority**: c'est le prérequis de toute mesure. Sans un schedule sélectionnable et un défaut strictement inchangé, on ne peut ni comparer ni revenir en arrière.

**Independent Test**: deux requêtes identiques, l'une sans schedule explicite, l'autre avec le schedule DCFR explicite, produisent une réponse identique champ pour champ ; une requête avec `hs_dcfr_30` produit un résultat fini et étiqueté.

**Acceptance Scenarios**:

1. **Given** une requête sans sélection de schedule, **When** le solveur résout, **Then** le comportement est celui d'avant cette spec (mêmes paramètres de discount, mêmes sorties).
2. **Given** une requête avec le schedule DCFR sélectionné explicitement, **When** le solveur résout, **Then** la réponse est identique à la requête sans sélection.
3. **Given** une requête avec `hs_dcfr_30`, **When** le solveur résout, **Then** la réponse est finie, non dégénérée, et le schedule utilisé est tracé dans les métadonnées.
4. **Given** un schedule inconnu, **When** la requête est construite, **Then** elle est rejetée explicitement, jamais silencieusement ramenée au défaut.

---

### User Story 2 - Mesurer la convergence hors ligne sur Kuhn et Leduc (Priority: P1)

En tant que mainteneur, je veux mesurer l'exploitabilité atteinte à nombre d'itérations fixé, pour chaque schedule, sur les jeux de test du dépôt, afin de savoir si le schedule change réellement la convergence **dans ce codebase** — pas dans celui de l'article.

**Why this priority**: le principe I de la constitution interdit de livrer une heuristique sans ablation comparative. Un swap de schedule sans mesure est une hypothèse.

**Independent Test**: exécuter la mesure sur Kuhn et Leduc, vérifier que chaque schedule atteint la **valeur de jeu de référence** (Kuhn −1/18, Leduc −0,0856, déjà vérifiée contre OpenSpiel dans `tests/leduc.rs`) et produire un artefact daté avec l'exploitabilité par palier d'itérations.

**Acceptance Scenarios**:

1. **Given** Kuhn ou Leduc et un schedule, **When** la mesure tourne à itérations fixées, **Then** la valeur de jeu obtenue égale la référence à la tolérance près — pour **tous** les schedules.
2. **Given** deux schedules, **When** la mesure tourne avec la même graine et les mêmes itérations, **Then** le protocole est identique et la comparaison est valide.
3. **Given** la mesure terminée, **When** le rapport est écrit, **Then** il porte la date, les itérations, la tolérance, la valeur de référence et l'exploitabilité par palier — et il **ne conclut pas** au-delà de ce qui a été mesuré.
4. **Given** un schedule qui ne bat pas DCFR dans ce codebase, **When** le rapport est écrit, **Then** il le dit explicitement ; aucun gain n'est inventé.

---

### User Story 3 - Une référence scientifique exacte et une configuration honnête (Priority: P2)

En tant que mainteneur, je veux que la fiche C16 cite la vraie publication et ses vrais chiffres, et qu'aucune clé de configuration ne soit inerte, afin que la documentation décrive l'état réel.

**Why this priority**: la constitution §IX exige que « la documentation décrive l'état réel ». Une référence fabriquée et une clé morte sont deux mensonges de nature différente mais de même effet.

**Independent Test**: la fiche C16 cite arXiv 2404.09097 avec ses auteurs et ses chiffres réels ; `config.json` ne contient plus de clé de schedule non lue, ou la clé est effectivement lue.

**Acceptance Scenarios**:

1. **Given** la fiche C16, **When** on suit son identifiant arXiv, **Then** on atteint *Faster Game Solving via Hyperparameter Schedules* (Zhang, McAleer, Sandholm).
2. **Given** la fiche C16, **When** on lit la recommandation, **Then** elle indique HS-DCFR(30) pour les grands jeux de poker, conformément à l'article.
3. **Given** `config.json`, **When** on cherche une clé de schedule, **Then** soit elle est lue par le code et le test le prouve, soit elle n'existe plus.

---

### Edge Cases

- **Première itération (`t = 0`).** Les schedules de l'article sont donnés pour `t ≥ 1` ; `HSβ : β = −1 − 2t/n` donne `β = −1` à `t = 0`, et `t^β` n'est pas défini en `t = 0`. Le code doit produire un paramètre fini et borné à `t = 0`, jamais `NaN` ni `∞`.
- **Budget mural.** En mode budget, le nombre total d'itérations n'est pas connu à l'avance : `n` est le **plafond** (`max_num_iterations`), pas le compte réel. La mesure hors ligne se fait donc à itérations fixées (pas de budget), où `n` est exact.
- **Reset périodique de la stratégie cumulée.** `DiscountParams::new` remet `t_γ` à zéro à chaque puissance de 4. Un schedule linéaire en `t` absolu doit décider comment il coexiste avec ce reset : la spec exige que le choix soit **explicite et testé**, pas implicite.
- **Chemin compressé et non compressé.** Les deux chemins lisent `params.alpha_t`/`beta_t`/`gamma_t` (`src/solver.rs:363-419`) : un schedule doit donner le même résultat dans les deux modes.
- **Schedule inconnu** dans une requête : rejet explicite, jamais de repli silencieux vers le défaut.
- **Mode strict (`epsilon_target`) et schedule non défaut.** Le mode strict promet que `converged` vaut exactement `exploitability <= epsilon_target`, sur une exploitabilité **mesurée**. Le schedule ne change pas cette promesse : il change la vitesse de décroissance des regrets, pas le critère de verdict. L'interaction est donc **définie comme neutre** — un schedule non défaut est appliqué dans la boucle stricte, le verdict reste mesure-driven, le schedule appliqué est tracé dans `metadata["discount_schedule"]`, et aucune combinaison n'est refusée. Un schedule ne peut pas rendre `converged` optimiste : le verdict ne lit que l'exploitabilité mesurée. Testé par `tests/v2_api.rs::strict_mode_accepts_a_non_default_schedule_with_an_honest_verdict` (FR-016).
- **Multiway.** `src/multiway.rs` (MCCFR) a son propre chemin ; hors périmètre de cette spec, mais le schedule ne doit pas le casser.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le comportement du solveur **sans sélection explicite de schedule** MUST rester identique à l'état d'avant cette spec (mêmes paramètres de discount, mêmes sorties pour une requête donnée).
- **FR-002**: Un schedule de discount MUST être sélectionnable par la requête, aux trois niveaux du contrat : `SolveRequestV2` (`src/v2_api.rs`), `gto_api::SolveRequest` (`src/gto_api.rs`) et le binding PyO3 (`python_bindings/src/lib.rs`).
- **FR-003**: Les schedules implémentés MUST être : le DCFR actuel du crate (défaut), `HS-DCFR(30)` et `HS-DCFR(15)`, selon les formules publiées (`HSα : α = 1 + 3t/n`, `HSβ : β = −1 − 2t/n`, `HSγ30 : γ = 30 − 5t/n`, `HSγ15 : γ = 15 − 5t/n`), où `n` est le nombre total d'itérations.
- **FR-004**: Un schedule inconnu MUST être rejeté explicitement par la construction de la requête, jamais ramené silencieusement au défaut.
- **FR-005**: Le schedule effectivement appliqué MUST être traçable dans les métadonnées de la réponse.
- **FR-006**: Le schedule MUST produire des paramètres finis et bornés pour toute itération, y compris `t = 0` ; aucun `NaN` ni `∞` ne doit atteindre la mise à jour des regrets ou de la stratégie.
- **FR-007**: Un schedule MUST donner le même résultat sur le chemin compressé et non compressé, à itérations et entrée identiques.
- **FR-008**: Un harnais de mesure MUST comparer les schedules à itérations fixées sur au moins Kuhn et Leduc, en rapportant l'exploitabilité à des paliers d'itérations.
- **FR-009**: Chaque schedule MUST atteindre la valeur de jeu de référence du jeu mesuré (Kuhn `−1/18`, Leduc `−0,0856`) à la tolérance déclarée — condition de correction de l'implémentation, indépendante de la vitesse.
- **FR-010**: La mesure MUST être déterministe (aucun service externe, aucune graine non fixée) et reproductible sur le matériel de référence.
- **FR-011**: Le rapport de mesure MUST être un artefact daté et versionné, portant les itérations, la tolérance, la valeur de référence, les paramètres d'abstraction et l'exploitabilité par palier.
- **FR-012**: Le rapport MUST NOT affirmer un gain qui n'a pas été mesuré ; si un schedule ne bat pas le défaut, il le déclare.
- **FR-013**: La fiche C16 de `docs/etudes.md` MUST citer la publication réelle (arXiv 2404.09097 ; Zhang, McAleer, Sandholm ; AAAI 2026) et ses chiffres réels, et MUST recommander HS-DCFR(30) pour les grands jeux de poker.
- **FR-014**: `config.json` MUST NOT contenir de clé de schedule sans effet ; la clé `solver.hs_pcf_30_enabled` est soit retirée, soit câblée et couverte par un test.
- **FR-015**: Aucune régression : `cargo test`, `cargo fmt --check`, la suite Python, `ruff` et le gate de performance F-09 restent verts.
- **FR-016**: Le mode strict (`epsilon_target`) MUST rester disponible et testé, et son interaction avec un schedule non défaut MUST être définie.

### Key Entities

- **DiscountSchedule** : énumération des schedules disponibles (`Dcfr` défaut, `HsDcfr30`, `HsDcfr15`), sérialisable et désérialisable, avec conversion depuis une chaîne de requête et rejet explicite de l'inconnu.
- **DiscountParams** : les trois facteurs multiplicatifs (`alpha_t`, `beta_t`, `gamma_t`) effectivement appliqués aux regrets et à la stratégie cumulée ; produits par un schedule pour une itération `t` et un total `n`.
- **ConvergenceSample** : un point de mesure — itérations écoulées, exploitabilité mesurée, valeur de jeu du joueur suivi.
- **ScheduleBenchmarkReport** : l'artefact daté — jeu, schedule, itérations, tolérance, valeur de référence, échantillons, verdict honnête.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `cargo test` est vert, y compris les tests de convergence Kuhn et Leduc sous chaque schedule, aux valeurs de référence près.
- **SC-002**: L'exploitabilité à itérations fixées est mesurée pour le défaut et pour HS-DCFR(30) sur Kuhn **et** Leduc, dans un artefact daté et versionné.
- **SC-003**: Le comportement de production est inchangé quand aucun schedule n'est sélectionné : vérifié par un test de non-régression sur un spot rejoué (mêmes sorties qu'avant la spec).
- **SC-004**: Aucune clé de configuration de schedule inerte ne subsiste : `config.json` est soit nettoyé, soit la clé est lue et un test le prouve.
- **SC-005**: La fiche C16 ne cite plus aucun identifiant arXiv invalide, et sa recommandation de variante correspond à celle de l'article.
- **SC-006**: La suite Python complète reste verte et `ruff` reste vert ; le gate de performance F-09 reste vert (aucun changement du chemin de production par défaut).

## Assumptions

- Le matériel de référence est stable (hypothèse de la constitution) ; les mesures Kuhn/Leduc sont petites et reproductibles sur toute machine.
- Kuhn et Leduc sont des jeux **tabulaire à information imparfaite** ; l'article valide ses schedules sur ce type de jeux, donc la mesure y est pertinente. La transposition au postflop HU à range complète n'est **pas** prouvée par cette spec.
- Le crate implémente une variante DCFR qui n'est pas le DCFR canonique de l'article (β = 0,5 constant, reset de la stratégie à chaque puissance de 4) : la comparaison mesure l'effet **dans ce codebase**, pas la reproduction de l'article.
- Aucune modification du comportement de production par défaut : le flag est désactivé par défaut et la clé de configuration livrée reste `false`.
- Les jeux de test Kuhn et Leduc restent dans `tests/` (tests d'intégration) et leur valeur de référence ne change pas.

## Dépendances

| Dépend de | Raison |
|---|---|
| — | Indépendante des specs `001`, `002`, `004`, `005`, `008`, `010`, `011` |
| `001-gto-hero-range` | Consommatrice : une convergence plus rapide attaque la réserve ouverte de F-01 (convergence hors budget 800 ms), sans la résoudre à elle seule |

**Note de dépendance.** Cette spec ne prétend pas résoudre la réserve de F-01 (« à budget 800 ms la convergence reste hors d'atteinte »). Elle livre l'outil de mesure qui permet de trancher si un schedule rapproche de cette cible ; la décision d'adopter un schedule en production appartient à une spec ultérieure, adossée à la mesure produite ici.
