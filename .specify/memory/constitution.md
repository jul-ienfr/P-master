# Constitution Poker Master

**Version**: 1.0.0 | **Ratifiée**: 2026-11-17 | **Dernière modification**: 2026-11-17

Cette constitution est la loi du projet. Elle prime sur les habitudes, les plans
antérieurs et les raccourcis d'implémentation. Toute spécification, tout plan et
toute tâche doivent pouvoir démontrer leur conformité ; une dérogation exige une
justification écrite, un test de non-régression et une date de réexamen.

## Préambule

Poker Master est un système d'aide à la décision au poker Texas Hold'em, destiné
à un opérateur unique et exécuté localement. Le produit final doit couvrir la
vision, la stratégie de jeu, la gestion de bankroll, la gestion de table et
l'exécution sur des plateformes telles que PokerStars et Winamax, avec le maximum
de composants critiques portés en Rust.

L'objectif n'est pas de « battre » un adversaire donné : c'est de produire des
décisions **scientifiquement fondées, mesurables, reproductibles et sûres**, à
une latence compatible avec le jeu réel.

Le projet reconnaît deux sources de vérité qui doivent rester synchronisées :

1. **la théorie** : les études C01–C27 de `docs/etudes.md` et la littérature
   associée ;
2. **la mesure** : les benchmarks, tests, journaux de décisions et artefacts
   versionnés.

Une affirmation non étayée par l'une des deux est une hypothèse, pas une
fonctionnalité.

## Principes fondamentaux

### I. Vérité scientifique et traçabilité (NON NÉGOCIABLE)

Tout comportement stratégique (mise, couche, range, exploitation, ICM, rake)
doit être rattaché à une référence scientifique ou à une campagne de mesure
documentée. Chaque fonctionnalité de stratégie cite au minimum un identifiant
C01–C27, ou explique pourquoi elle en est indépendante.

- Aucune heuristique « qui marche » n'entre en production sans ablation
  comparative et sans borne d'exploitabilité.
- Les métriques de référence sont l'exploitabilité (ou le MES best-response
  gap), l'EV en bb/100 avec intervalle de confiance, et les courbes de
  convergence. Un winrate sur un échantillon non significatif ne vaut pas
  preuve.
- Un modèle approximatif (multiway HU, abstraction de mises, range resserrée)
  est autorisé **à condition** d'être explicitement étiqueté dans la réponse,
  tracé dans le journal de décision et couvert par un test qui borne son écart.
- Toute campagne de validation produit un artefact daté et reproductible
  (`research/results/*.json`) référencé par la spec concernée.

### II. Rust-first pour le cœur déterministe

Le cœur chaud et déterministe est écrit en Rust : solveur CFR/DCFR/MCCFR,
équité, abstraction d'arbre, évaluation de ranges, résolution d'état de table,
orchestration de politique, bankroll, journalisation structurée et adaptateurs
de plateforme critiques.

Python reste autorisé, et préféré, pour : la capture d'écran et les pilotes
graphiques, l'entraînement et l'inférence de modèles ML, les notebooks de
recherche, l'outillage de développement et l'interface opérateur.

Règles :

- Un composant Python qui tourne dans la boucle de décision à chaud doit avoir
  un budget de latence mesuré et une justification de non-portage.
- Les appels Python ↔ Rust passent par des contrats typés (structures
  sérialisées ou PyO3) et sont couverts par des tests de contrat.
- Le registre de migration Rust (`docs/rust-migration-ledger.md`) est la source
  unique de vérité sur ce qui est porté, en cours, ou volontairement laissé en
  Python.
- Aucun composant ne doit exister en double (une implémentation Python et une
  implémentation Rust du même calcul) sans test de parité et sans date de
  retrait de l'ancienne version.

### III. Budgets de latence et reproductibilité

La latence est une exigence fonctionnelle, pas une optimisation tardive.

Budgets cibles, mesurés de bout en bout sur le matériel de référence :

| Étage | Cible p95 | Plafond p99 |
|---|---|---|
| Préflop (cache/fast path) | ≤ 20 ms | ≤ 50 ms |
| Tour/rivière (solve chaud) | ≤ 150 ms | ≤ 400 ms |
| Flop à froid (budget 800 ms) | ≤ 950 ms | ≤ 1 500 ms |
| Vision : capture + OCR + résolution d'état | ≤ 300 ms | ≤ 600 ms |
| Décision complète (vision → action) | ≤ 1 500 ms | ≤ 2 500 ms |

- Un budget déclaré (`time_budget_ms`) est une **borne murale**, finalisation et
  conversion incluses.
- Les benchmarks de référence sont exécutés en CI et versionnés ; une
  régression de plus de 10 % sur le p95 ou sur l'exploitabilité bloque la merge.
- Les résultats doivent être reproductibles : graine fixée, version du solveur,
  version des ranges, paramètres d'abstraction et empreinte du matériel sont
  enregistrés avec chaque mesure.
- Le mode strict (zéro approximation) est un chemin de vérification, pas le
  mode par défaut ; il doit rester disponible et testé.

### IV. Fail-closed, explicabilité et contrôle opérateur

Une décision doit toujours être explicable et sûre en cas d'incertitude.

- Toute réponse de décision contient : action choisie, EV par action, stratégie
  agrégée, exploitabilité ou gap, budget consommé, backend utilisé, avertissements
  et raison de repli éventuelle.
- En cas de doute sur l'état (confiance de vision basse, range incohérente,
  solveur indisponible), l'action par défaut est l'action légale la moins
  engageante (CHECK si possible, sinon FOLD), jamais une mise agressive.
- Aucun repli silencieux : chaque repli incrémente une métrique et écrit une
  entrée de journal avec un identifiant de spot.
- Un coupe-circuit opérateur (kill switch) doit pouvoir arrêter les décisions,
  les mises et l'automatisation sans arrêter la journalisation.
- Le système ne mise jamais plus que la bankroll ou la limite de table
  configurée, même si le solveur le recommande.

### V. Modularité par domaine et contrats typés

Le système est découpé en domaines à frontières explicites :

- **Vision** : capture, détection de table, reconnaissance de cartes, OCR des
  montants, suivi des sièges et de l'historique.
- **État & règles** : résolution d'un état canonique, légalité des actions,
  positions, rues, pots, stacks effectifs.
- **Stratégie** : préflop, postflop, multiway, abstraction, node-locking,
  exploitation, ICM/PKO.
- **Bankroll & risque** : plan de bankroll, risque de ruine, move-up/down,
  stop-loss/stop-win, limites par format.
- **Plateforme** : adaptateurs PokerStars/Winamax, entrées/sorties, conformité.
- **Orchestration** : boucle de session, gate de décision, exécution, reprise
  après erreur.
- **Observabilité** : journaux, métriques, traces, artefacts de validation.

Chaque domaine expose un contrat stable et testable. Un domaine ne lit pas les
structures internes d'un autre : il consomme son contrat. Les dépendances
pointent vers le cœur (Rust) et jamais l'inverse.

### VI. Test-first, parité et validation empirique

- Toute correction de bug commence par un test qui échoue.
- Toute fonctionnalité stratégique possède : tests unitaires, test de contrat
  Python↔Rust, test d'intégration sur un état réel rejoué, et test de
  non-régression de performance.
- Les rejeux (« golden replays ») d'états de table, de décisions et de réponses
  solveur sont versionnés et rejouables hors ligne.
- Les propriétés critiques (conservation des probabilités, EV cohérente,
  monotonie des ranges, légalité des actions) sont testées par propriétés.
- La couverture Python globale ne doit pas baisser ; la couverture du code de
  production (`src/`) est suivie séparément de celle du code historique.
- Aucun test ne dépend d'un service externe, d'un site de poker ou d'un modèle
  non déterministe sans double de test.

### VII. Sécurité, conformité et jeu responsable

- Aucun secret, jeton ou identifiant ne doit être versionné. Les secrets sont
  fournis par l'environnement ou un coffre local, jamais par un fichier suivi.
- L'automatisation sur une plateforme doit respecter ses conditions
  d'utilisation et les lois applicables. Le système doit permettre un mode
  supervisé par l'opérateur et ne doit pas intégrer de mécanisme d'évasion de
  détection ou de contournement de sécurité.
- Les mises réelles sont désactivées par défaut ; leur activation exige une
  configuration explicite, des limites dures et une confirmation opérateur.
- Le jeu responsable fait partie du produit : limites de session, de perte et
  de temps, rappels, et arrêt automatique configurables.
- Les données personnelles éventuellement capturées sont minimisées, stockées
  localement et purgées selon une politique documentée.

### VIII. Observabilité et mesure continue

- Chaque décision produit une trace structurée corrélée par `spot_id`, avec les
  versions de code, de ranges et de modèle.
- Les métriques minimales sont : latence par étage (p50/p95/p99), taux de repli
  par raison, exploitabilité/gap, taux de cache, confiance de vision, actions
  par type, et erreurs par domaine.
- Les tableaux de bord et artefacts de benchmark sont générés par du code
  versionné, pas à la main.
- Un SLO non tenu déclenche une action documentée : alerte, dégradation
  contrôlée ou retour à la version précédente.

### IX. Source unique de vérité et dette maîtrisée

- Il existe une seule implémentation de production par fonction. Le code
  historique non utilisé est soit migré, soit isolé derrière une frontière
  explicite, soit supprimé selon un plan daté.
- Les plans, specs, tâches et décisions d'architecture vivent dans le dépôt et
  sont versionnés avec le code.
- Toute dette technique acceptée est enregistrée avec un propriétaire, un
  impact et une échéance.
- La documentation décrit l'état réel, pas l'état souhaité ; les fonctionnalités
  non implémentées sont marquées comme telles.

## Contraintes techniques

- **Python** : 3.11 (version CI et releases).
- **Rust** : toolchain nightly épinglée par la CI ; `clippy` et `fmt` sont
  bloquants sur le code modifié.
- **Licence** : AGPL-3.0-only pour le cœur Rust et le projet Python. Toute
  dépendance incompatible est interdite ; les obligations de redistribution
  sont documentées.
- **Plateformes cibles** : Windows en priorité pour l'exécution, Linux pour la
  CI et les benchmarks.
- **Données** : stockage local par défaut ; PostgreSQL/Redis sont optionnels et
  ne doivent jamais être requis pour une décision.
- **Déterminisme** : les chemins de décision critiques ne dépendent pas de
  l'ordre d'itération d'un `dict` non trié, d'une horloge non injectée ou d'un
  générateur aléatoire non semé.
- **Compatibilité** : tout changement de contrat public (API, format de
  requête/réponse, schéma de configuration) est versionné et migré.

## Workflow SpecKit et portes de qualité

Le développement suit le cycle SpecKit :

1. **Constitution** : ce document.
2. **Specify** : une spec par fonctionnalité, centrée sur la valeur et les
   scénarios testables.
3. **Clarify** : suppression des ambiguïtés avant tout plan.
4. **Plan** : architecture, contrats, stratégie de test, budgets.
5. **Tasks** : découpage en tâches atomiques et ordonnées.
6. **Implement** : code + tests + benchmarks.
7. **Analyze / Checklist** : vérification de conformité à la constitution.

Portes obligatoires avant merge :

- `cargo test`, `cargo clippy`, `cargo fmt --check` sur le code modifié ;
- `pytest` avec le seuil de couverture global et le seuil `src/` ;
- benchmark de latence et d'exploitabilité comparé à la référence ;
- revue de sécurité des secrets et des dépendances (`pip-audit`, `cargo audit`
  si disponible) ;
- mise à jour de la spec, du registre de migration et du journal de décision
  si le comportement change.

Une fonctionnalité sans spec ni critère de succès mesurable n'est pas prête à
être implémentée.

## Gouvernance

- La constitution est versionnée en SemVer. Toute modification passe par une
  pull request séparée, avec justification, impact et plan de migration.
- Les specs et plans doivent citer la version de la constitution appliquée.
- Un désaccord entre une spec et la constitution se résout en faveur de la
  constitution ; la spec est corrigée avant implémentation.
- Les revues vérifient explicitement les principes I, III, IV et VI ; les
  autres principes sont vérifiés au niveau du plan.
- Une dérogation est enregistrée dans `docs/architecture-decisions/` avec un
  identifiant ADR, une date d'expiration et un critère de sortie.
