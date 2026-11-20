# Feature Specification: Contrat de plateforme multi-site (PokerStars, Winamax)

**Feature Branch**: `005-vision-multi-site`

**Created**: 2026-11-20

**Status**: En cours

**Input**: Audit du 17/11/2026, constat F-06 (« Winamax absent du runtime moderne ») et cible §3.6 : « un contrat `PlatformAdapter` (capture, calibration, décodage d'état, encodage d'action, limites) avec une implémentation PokerStars et une implémentation Winamax, testées sur des fixtures. » Registre de migration §7, ligne `005` : « Encodage/validation d'actions plateforme ».

## Contexte

`src/vision/site_adapter.py:85-91` n'expose que `PokerStarsAdapter` ; toute autre clé de site lève `ValueError`. Le support Winamax n'existe que dans `poker/tools/supported_sites.py` (laboratoire historique, hors runtime moderne, cf. ADR-001).

Trois défauts de fond ont été mesurés avant d'écrire cette spec :

1. **Le site est codé en dur.** `src/runtime/table_manager.py:141` et `src/runtime/frame_pipeline.py:83` appellent littéralement `get_active_adapter("pokerstars")`, sans lecture de configuration. Changer de site exige d'éditer le code.
2. **`FormatProfile` est orphelin.** Le format des montants (séparateurs de milliers et décimaux) est déclaré dans l'adaptateur mais **jamais consommé** : `src/vision/numeric_reader.py:37` construit `NumericParser()` avec ses valeurs par défaut, et l'OCR est configuré depuis `config.json` (`ocr.amount_format`), pas depuis l'adaptateur. Deux sources de vérité pour la même information, dont une morte.
3. **Aucune fixture de site.** Il n'existe pas un seul échantillon versionné de montant ou d'état de table par site : la conformité de l'adaptateur n'est donc pas testable et le restera pas.

Le contrat §3.6 couvre cinq responsabilités (capture, calibration, décodage d'état, encodage d'action, limites). Le décodage d'état (manifeste, géométrie) existe déjà et fonctionne pour PokerStars ; **capture** et **calibration** relèvent des pilotes OS et de l'UI opérateur, déjà outillés ailleurs. Cette spec se concentre donc sur ce qui manque et qui est testable hors ligne : **la sélection du site, le format des montants, les limites d'action et les fixtures de conformité**.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Jouer sur les deux sites sans toucher au code (Priority: P1)

En tant qu'opérateur, je veux choisir mon site par configuration et que le runtime adapte seul ses manifestes, son format de montants et ses limites d'action, afin de passer de PokerStars à Winamax sans réécrire de code.

**Why this priority**: c'est le cœur du constat F-06 ; sans cela, Winamax reste un site théorique et chaque adaptation devient un patch.

**Independent Test**: `get_active_adapter("winamax")` retourne un adaptateur dont `site_key == "winamax"`, `display_name == "Winamax"` et dont le format de montants est européen ; `get_active_adapter("partypoker")` lève une erreur explicite.

**Acceptance Scenarios**:

1. **Given** une clé de site valide, **When** l'adaptateur est demandé, **Then** il expose `site_key`, `display_name`, un thème, un format de montants, un profil de fenêtre et des limites d'action cohérents avec ce site.
2. **Given** une clé de site inconnue, **When** l'adaptateur est demandé, **Then** une erreur explicite est levée (jamais un adaptateur par défaut silencieux qui ferait jouer sur le mauvais site).
3. **Given** une configuration `bot.active_site`, **When** le runtime démarre, **Then** les sessions de table et la résolution de géométrie utilisent cet adaptateur, sans littéral `"pokerstars"` dans le chemin.
4. **Given** un titre de fenêtre de table, **When** le site est résolu, **Then** le site correspondant est identifié par les motifs déclarés (titre, classe, process), sans dépendre de l'ordre du dictionnaire.

---

### User Story 2 - Lire les montants au format du site (Priority: P1)

En tant qu'opérateur, je veux que les montants affichés soient interprétés selon les conventions du site (séparateur de milliers, séparateur décimal, décimales autorisées), afin de ne pas confondre « 1 234 » avec « 1,234 ».

**Why this priority**: une erreur de séparateur change la taille d'une mise d'un facteur 1000. C'est un risque financier direct, et le format déclaré est aujourd'hui mort.

**Independent Test**: un parseur construit depuis l'adaptateur Winamax interprète `"1 234,50"` comme `1234.5` et `"12,5"` comme `12.5` ; le même parseur construit depuis l'adaptateur PokerStars play money rejette les décimales et lit `"1 234"` comme `1234`.

**Acceptance Scenarios**:

1. **Given** un adaptateur de site, **When** un parseur de montants est demandé, **Then** il est configuré depuis le `FormatProfile` de l'adaptateur, et non depuis des valeurs par défaut indépendantes.
2. **Given** un montant de fixture du site, **When** il est parsé, **Then** la valeur obtenue est celle attendue par la fixture.
3. **Given** un site sans décimales (play money), **When** un montant décimal est présenté, **Then** il est traité selon la convention déclarée (pas de décimale silencieuse).

---

### User Story 3 - Ne pas proposer une mise illégale (Priority: P2)

En tant qu'opérateur, je veux que la taille de mise proposée respecte les limites du site (mise minimale, incrément minimal de relance, décimales), afin d'éviter un rejet par le client de poker ou une mise non voulue.

**Why this priority**: le runtime applique aujourd'hui une correction locale (« si < 1 BB alors 3 BB ») sans modèle de limite par site ; c'est un correctif, pas une règle.

**Independent Test**: `validate_bet_amount` refuse une mise sous le minimum, accepte exactement le minimum, accepte un tapis, et arrondit selon les décimales autorisées.

**Acceptance Scenarios**:

1. **Given** une mise sous la limite minimale du site, **When** elle est validée, **Then** elle est refusée avec un motif explicite.
2. **Given** une mise valide, **When** elle est validée, **Then** elle est acceptée sans modification.
3. **Given** un tapis demandé et un site qui le supporte, **When** il est validé, **Then** il est accepté comme cas particulier du minimum.

---

### User Story 4 - Prouver la conformité par des fixtures (Priority: P2)

En tant que mainteneur, je veux un jeu de fixtures par site et un test de conformité, afin qu'une régression d'adaptateur soit détectée en CI plutôt qu'en session réelle.

**Why this priority**: sans fixtures, la conformité reste une affirmation ; le constat F-08 (vision non prouvée par site) en dépend directement.

**Independent Test**: le test de conformité parcourt tous les adaptateurs enregistrés et vérifie les champs du contrat, plus le parsing des montants de fixture.

**Acceptance Scenarios**:

1. **Given** l'ensemble des adaptateurs enregistrés, **When** le test de conformité s'exécute, **Then** chaque adaptateur expose des champs non vides et correctement typés.
2. **Given** une fixture de montants par site, **When** le test s'exécute, **Then** chaque montant produit la valeur attendue.
3. **Given** un adaptateur dont le format déclaré ne correspond pas à ses fixtures, **When** le test s'exécute, **Then** il échoue (falsification vérifiée).

### Edge Cases

- Clé de site vide ou `None` : traitée comme la valeur par défaut (`pokerstars`), jamais comme une erreur.
- Clé de site inconnue : erreur explicite, jamais de repli silencieux.
- Adaptateur sans manifeste présent sur le disque (Winamax tant qu'aucun profil n'est calibré) : `preset_manifests()` retourne un tuple vide, sans lever.
- Titre de fenêtre ne correspondant à aucun site : résolution retourne `None` (l'appelant garde son défaut).
- Montant non numérique ou vide : le parseur retourne une valeur invalide, jamais `0.0`.
- Décimales demandées sur un site qui les interdit : arrondi à l'entier, motif tracé.
- Site dont la classe de fenêtre ou le nom de process n'est pas encore connu : champ `None` explicite, jamais une valeur inventée.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le système MUST exposer un registre d'adaptateurs de site contenant au minimum `pokerstars` et `winamax`.
- **FR-002**: Chaque adaptateur MUST déclarer `site_key`, `display_name`, un `ThemeProfile`, un `FormatProfile`, un profil de fenêtre et des limites d'action.
- **FR-003**: `get_active_adapter` MUST lever une erreur explicite pour une clé inconnue, et ne MUST jamais retourner un adaptateur par défaut pour une clé inconnue.
- **FR-004**: Le runtime MUST sélectionner l'adaptateur depuis la configuration (`bot.active_site`) et MUST ne plus coder le site en littéral dans le chemin d'exécution.
- **FR-005**: Le système MUST fournir une résolution de site depuis un titre de fenêtre, fondée sur les motifs déclarés par les adaptateurs.
- **FR-006**: Le système MUST construire le parseur de montants depuis le `FormatProfile` de l'adaptateur (séparateurs, décimales), sans duplication de configuration.
- **FR-007**: Chaque adaptateur MUST déclarer des limites d'action (mise minimale en bb, incrément minimal de relance, décimales autorisées, tapis supporté).
- **FR-008**: Le système MUST fournir une validation de taille de mise par site, retournant un verdict explicite (acceptée / refusée + motif / arrondie + valeur).
- **FR-009**: Le système MUST versionner des fixtures de montants par site et un test de conformité qui les vérifie.
- **FR-010**: Un adaptateur dont le manifeste est absent sur le disque MUST retourner une liste de manifestes vide sans lever.
- **FR-011**: Les valeurs non vérifiées (classe de fenêtre, nom de process d'un site non observé) MUST rester `None` et documentées comme telles, jamais inventées.
- **FR-012**: L'ajout d'un site MUST ne pas exiger de modifier le code d'appel, seulement le registre et sa configuration.

### Key Entities

- **PlatformAdapter** (contrat) : `site_key`, `display_name`, `theme`, `amount_format`, `window_profile`, `action_limits`, `preset_manifests()`, `amount_parser()`.
- **ThemeProfile** : identité visuelle du site (thème, réseau).
- **FormatProfile** : décimales autorisées, séparateurs de milliers et décimaux, symboles monétaires.
- **WindowProfile** : motifs de reconnaissance de fenêtre (titre, classe, process), blinde par défaut, motif de limite.
- **ActionLimits** : mise minimale en bb, incrément minimal de relance, décimales, tapis supporté.
- **BetAmountVerdict** : `accepted` | `rejected` (motif) | `adjusted` (valeur).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `get_active_adapter("winamax")` et `get_active_adapter("pokerstars")` réussissent ; une clé inconnue lève — vérifié par test.
- **SC-002**: 100 % des adaptateurs enregistrés passent le test de conformité (champs du contrat présents et typés).
- **SC-003**: 100 % des montants de fixture produisent la valeur attendue, pour les deux sites.
- **SC-004**: Aucune occurrence du littéral `"pokerstars"` dans le chemin d'exécution du runtime hors valeur par défaut de configuration.
- **SC-005**: Le test de conformité échoue si un format déclaré ne correspond pas à ses fixtures (falsification vérifiée).
- **SC-006**: `pytest` et `ruff` restent verts ; la suite existante n'est pas modifiée dans son comportement par défaut.

## Assumptions

- Les métadonnées de fenêtre de Winamax (classe, process) ne sont pas connues avec certitude ; elles restent configurables et `None` par défaut plutôt qu'inventées. Le titre (`Winamax`) suffit à la résolution initiale.
- Le manifeste de preset Winamax n'existe pas encore : `preset_manifests()` retourne vide jusqu'à la calibration d'un profil par l'opérateur. La conformité porte sur le contrat, pas sur des assets non fournis.
- Les montants de fixture sont des chaînes représentatives des conventions de chaque site, pas des captures d'écran ; la reconnaissance d'image est hors périmètre (elle relève de F-08).
- La configuration `bot.active_site` est un ajout non sensible à `config.json`, valeur par défaut `pokerstars`.

## Plan de test

1. Test de registre : PokerStars et Winamax résolus ; clé inconnue → erreur ; clé vide → défaut.
2. Test de conformité : parcours de tous les adaptateurs, champs du contrat présents et typés.
3. Test de format : parseur construit depuis l'adaptateur, montants de fixture → valeur attendue, par site.
4. Test de falsification : un adaptateur dont le format contredit ses fixtures fait échouer le test.
5. Test de limites : mise sous le minimum refusée, minimum accepté, tapis accepté, arrondi selon décimales.
6. Test de résolution de site : titres représentatifs → site attendu ; titre inconnu → `None`.
7. Test de manifestes : adaptateur sans manifeste présent → tuple vide, sans exception.
8. Test de non-régression : `PokerStarsAdapter` conserve son comportement (site_key, décimales play money, manifestes filtrés).

## Hors périmètre

- La reconnaissance d'image et le benchmark de vision par site (constat F-08, spec dédiée) : cette spec fournit les fixtures et le contrat, pas la mesure de précision OCR.
- Les traces `spot_id` et les SLO (constat F-10, spec `008-observability-slo`).
- La capture d'écran et la calibration de fenêtre (pilotes OS, UI opérateur existante).
- Les sites autres que PokerStars et Winamax (GGPoker, PartyPoker, WPT, iPoker, CoinPoker) : le registre est conçu pour les accueillir, ils ne sont pas livrés ici.
- Le portage Rust du décodage d'état et des limites d'action : candidat P2 (registre §7), non engagé ici.
- Tout mécanisme d'évasion de détection : exclu par conception (§3.6).
