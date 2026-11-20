# Audit complet — Poker Master

**Date :** 17 novembre 2026
**Périmètre :** `C:\Users\julie\Desktop\Poker-master` (code, tests, CI, docs, plans)
**Constitution appliquée :** `.specify/memory/constitution.md` v1.0.0 (ratifiée le 17/11/2026)
**Méthode :** lecture du code et des plans, vérification des chemins d'appel, confrontation aux artefacts de mesure existants (`docs/PHASE1_BASELINE_2026-11-14.md`, `research/results/*.json`). Aucun test de charge ni campagne de winrate n'a été relancé pour cet audit ; les chiffres cités sont ceux des artefacts datés, avec leur limite explicite.

**Mise à jour du 17 novembre 2026 :** le constat F-02 (« multiway non branché ») ci-dessous est historique et désormais clos par la spec `002-runtime-n-way`. Voir la clôture Sprint 0 en § 8 et le benchmark multiway dans `research/results/runtime_multiway_benchmark.json`. F-01 (range héros complète) et F-03 (preuve empirique de performance) restent des sujets distincts.

**Mise à jour du 19 novembre 2026 (soir) :** F-01 est corrigé dans le code (range de position complète transmise, main cible séparée, cache et journal étendus ; spec `001-gto-hero-range`). Les deux critères bloquants de la mesure du matin sont levés : p95 froid **812,0 ms** (cible ≤ 950 ms) après optimisation du chemin solveur, et rejeu golden `pass` avec non-convergence étiquetée et courbe de convergence documentée (0,455 à 12,8 s). La convergence à budget court (800 ms) reste hors d'atteinte : ~2 itérations DCFR seulement. Détails en § 6.1 et § F-01.

---

## 1. Verdict exécutif

Le projet est un **prototype de recherche avancé et sérieusement instrumenté**, pas encore le système « parfaitement aligné aux études » décrit comme objectif. La base Rust est solide, la documentation scientifique est d'un niveau rare, et la CI existe. Mais trois écarts empêchent aujourd'hui de revendiquer un comportement GTO de production :

1. **Le runtime résolvait le héros sur une seule main** (`hero_range=hero_hand`), produisant l'équilibre d'un jeu où le villain connaît la main du héros. **Constat historique : corrigé le 17/11/2026 par la spec `001-gto-hero-range`.** Le correctif est livré et testé ; ses critères de latence sont levés au 19/11 (soir) : p95 froid 812,0 ms (cible ≤ 950 ms) après optimisation du chemin solveur, rejeu golden `pass` avec non-convergence étiquetée. Réserve : à budget 800 ms la convergence n'est pas atteinte (~2 itérations DCFR), donc l'exploitabilité rapportée sur flop froid (12,49) reste au-dessus de la cible 0,5 (§ 6.1).
2. **Le multiway réel n'est pas branché au runtime.** Le NLHE 3–6 way existe côté Rust, mais `DecisionMaker` appelle le solveur sans `num_players` et sans les ranges des villains secondaires. Le format recommandé (cash 6-max) est donc joué en approximation HU, avec un simple resserrement de range. **Constat historique : clos le 17/11/2026 par la spec `002-runtime-n-way`.**
3. **La preuve empirique de performance n'existe pas encore.** Le benchmark externe Slumbot est à −60,75 bb/100 (IC 95 % très large) et utilise une politique heuristique, pas le solveur de production. Les simulations de pool ne battent pas le pool de façon significative. Le système est donc **mesurable**, mais pas **prouvé**.

Ces trois points sont des prérequis P0. Le reste (bankroll, Winamax, observabilité, dette legacy) est important mais ne peut pas être corrigé sérieusement avant eux, car il s'appuierait sur des décisions biaisées.

**Ce qui est déjà bon :** solveur DCFR HU en Rust, MCCFR multiway séparé, abstraction de mises, rake dans l'arbre, EV par combo, node-locking, cache, journals de décision, CI Rust/Python, 27 études référencées, et une culture de la mesure honnête (les docs reconnaissent les résultats non significatifs).

---

## 2. Carte du système

### 2.1 Volumétrie

| Zone | Langage | Lignes | Rôle |
|---|---|---:|---|
| `src/*.rs`, `python_bindings/` | Rust | ~17 830 | Solveur, équité, arbre, multiway, API V2, bindings |
| `src/` | Python | ~34 625 | Runtime moderne : vision, décision, API, sessions |
| `poker/` | Python | ~26 290 | Application historique PyQt6, outils, support sites |
| `tests/` | Python | 133 fichiers de test | Couverture runtime moderne |
| `docs/` | Markdown | — | Études, plans, baselines, audits |

Le code Python de production potentiel représente ~61 000 lignes, dont **43 % dans `poker/`**, un package historique dont la frontière avec `src/` n'est pas définie. La CI le dit elle-même : `poker/` est à ~12 % de couverture et dilue le seuil global ; `src/` seul est à ~84 % (`.github/workflows/python-tests.yml:55`).

### 2.2 Flux de décision réel

```
Capture (DXcam/WGC)
  → Vision (YOLO/ONNX + OCR)
  → Gate (confiance, cohérence, légalité)
  → DecisionMaker
      → préflop store / solver provider
      → solve_spot_v2 (Rust via PyO3 ou HTTP)
      → node-locking / RL / ICM
  → ActionController (clavier/souris ou API)
  → journal de décision
```

Le flux est plausible et bien découpé en apparence, mais deux contrats sont rompus : la range passée au solveur et le nombre de joueurs (sections 4.3 et 4.4).

### 2.3 Deux bases de code, une seule vérité ?

`src/` est la base moderne (runtime V2, solver, API). `poker/` est l'ancienne application, avec des outils spécifiques aux sites (dont Winamax) et une UI PyQt6. Certains tests et scripts de release référencent encore `poker/`. Sans décision d'architecture, chaque correctif peut diverger entre les deux, et la couverture globale masque la qualité réelle.

**Recommandation :** ADR explicite. Soit `poker/` est un outil de laboratoire isolé (hors chemin de production, hors couverture bloquante), soit il est migré morceau par morceau puis supprimé. Il ne doit pas rester un troisième runtime implicite.

---

## 3. État par domaine

### 3.1 Vision

**Forces :** capture Windows native (DXcam/WGC), YOLO/ONNX, calibration de templates, plusieurs moteurs OCR, confiance par champ, tests unitaires.

**Faiblesses :**

- Quatre moteurs OCR sont supportés (`rapidocr`, `tesseract`, `surya`, `doctr` — `src/vision/ocr.py:73`). Chaque moteur ajoute des dépendances lourdes, des formats de sortie différents et des modes de défaillance différents. Le coût de maintenance et de packaging est élevé.
- Aucun benchmark de bout en bout par site et par thème n'est versionné comme gate. On ne connaît pas la précision réelle (cartes, montants, boutons) sur PokerStars et Winamax, ni la latence p95 de la chaîne complète.
- `src/vision/site_adapter.py:85-91` n'expose que `PokerStarsAdapter` ; Winamax lève `ValueError`. Le support Winamax n'existe que dans `poker/tools/supported_sites.py`, hors runtime moderne. — **corrigé le 20/11/2026 (spec `005`)** : registre d'adaptateurs avec `WinamaxAdapter`, sélection par configuration, parseur de montants issu du format déclaré, limites d'action par site ; voir §3.6.
- La résolution d'état (sièges, bouton, pot, stacks, historique) n'a pas de tests de rejeu sur captures réelles versionnées.

**État au 20/11/2026 — partiellement corrigé (spec `010`) :** deux des trois défauts mesurés sont clos, le troisième est désormais **mesurable**. (1) **La politique OCR existe** : `src/vision/ocr_policy.py` déclare une politique par site (un principal, au plus un fallback) — `OCREnginePolicy`, `SITE_OCR_POLICIES`, `clamp_to_policy` — et `PokerOCR` l'applique au boot (`site_key` issu de `bot.active_site`) : une configuration à quatre moteurs est ramenée à la politique du site et la restriction est **tracée** (`policy_notes`), jamais silencieuse ; le contrat du normaliseur bas niveau (`_normalize_engines`) reste inchangé hors runtime. (2) **Le vert vide est corrigé** : `src/vision/preset_validation.py` est la source unique du statut ; un preset sans échantillon évalué est `unmeasured` avec des taux `None` (la règle `min(scores) if scores else 1.0` de `room_manager.py` déclarait vert un preset jamais mesuré). Les deux manifestes livrés passent de `green`/`1.0`/`0` à `unmeasured`/`null`/`0`, et le second type homonyme du laboratoire est remplacé par un alias de la source unique. (3) **La précision par site est mesurable** : `src/vision/vision_benchmark.py` mesure précision, effectif et latence médiane par champ sur captures étiquetées, `scripts/vision_benchmark.py` est le point d'entrée opérateur (artefact daté `research/results/vision_benchmark_<site>.json`) ; un champ illisible est un **échec compté**, jamais exclu, et sans capture le rapport est `unmeasured` avec taux `None` — **aucun taux inventé**. 39 tests nouveaux. **Reste ouvert** : aucune capture d'écran n'est committée (données d'exploitation), donc la précision réelle PokerStars/Winamax n'est **pas encore mesurée** — le harnais la produira dès que l'opérateur fournira ses captures ; la conformité d'écran (thèmes, résolutions, DPI, langues) et le rejeu d'état sur captures versionnées restent ouverts.

**Cible :** un moteur OCR principal + un fallback maximum, un jeu de fixtures par site/theme, un score de confiance calibré, et un adaptateur de site comme contrat testé. Le post-traitement (fusion, cohérence, state machine) est un bon candidat Rust.

### 3.2 État, règles et légalité

Le gate et le `DecisionMaker` normalisent les actions et protègent les all-ins. Des tests couvrent la traduction des tailles de mise et l'historique. En revanche, l'état canonique n'est pas une structure unique et versionnée : pot, stacks, rues et positions sont reconstruits par plusieurs couches, avec des conventions différentes (bb vs jetons, `to_call`, relances). C'est une source classique de bugs silencieux.

**Cible :** un `CanonicalState` unique (Rust) avec validateurs, sérialisation et tests de propriété. Tous les domaines consomment ce contrat.

### 3.3 Stratégie et solveur

**Forces :**

- DCFR HU dans `src/solver.rs`, MCCFR multiway dans `src/multiway.rs`, abstraction de mises paramétrable (`src/bet_size.rs`, `SolveRequestV2.bet_size_spec`).
- Rake modélisé dans l'arbre (`rake_rate`/`rake_cap`), EV par combo (`hero_hand`, `combo_index`), MES/exploitabilité (`src/utility.rs:279`), node-locking.
- Budget mural corrigé le 16/11 : la finalisation est réservée dans l'échéance (`src/solver.rs:80-89`).

**Écarts majeurs :**

- **Range héros singleton** (P0, voir 4.3).
- **Multiway non branché** (P0, voir 4.4) — historique, clos par la spec `002-runtime-n-way`.
- **Exploitabilité résiduelle élevée** sur les flops à froid : 6,66 et 6,12 en unités solveur pour un budget de 800 ms ; le turn et la river répondent en 10–15 ms mais avec une exploitabilité supérieure à la cible (5,5 sur la river citée). Le budget ne suffit pas à converger ; il faut un blueprint ou un arbre plus petit, pas seulement plus d'itérations.
- **Pas de benchmark de convergence en CI.** Le p95 est mesuré dans un script, pas bloquant. Une régression de 10 % peut passer.
- **AIVAT/MIVAT** : corrigé le 20/11/2026 (spec `011`) — estimateurs à variable de contrôle dans `research/variance_reduction.py`, vérifiés sans biais et réducteurs sur jeux synthétiques à vérité connue. La variance des évaluations peut désormais être réduite ; la mesure réelle dépend d'une campagne opérateur.
- **HS-PCFR/HS-DCFR** : corrigé le 20/11/2026 (spec `012`) — le schedule de discount est **sélectionnable** (`DiscountSchedule` dans `src/solver.rs` : `dcfr` par défaut, `hs_dcfr_30`, `hs_dcfr_15`), propagé par la requête jusqu'au binding PyO3, refusé s'il est inconnu et tracé dans `metadata["discount_schedule"]`. **Mesuré** sur Kuhn et Leduc : les trois schedules atteignent la valeur de jeu de référence, mais HS-DCFR ne bat le DCFR du crate que sur 6 des 16 couples (schedule, jeu, palier) et perd aux paliers hauts. **Le gain de l'article n'est pas reproduit** ; la mesure est dans `research/results/cfr_schedule_benchmark.json`, la fiche C16 est corrigée (identifiants arXiv réels, chiffres réels, recommandation HS-DCFR(30) pour le poker). Aucune adoption en production.
- **Pas d'EMD clustering** (C25) : l'abstraction de ranges reste heuristique.
- **ICM partiel** (`src/bot/icm_calculator.py`), **FGS et PKO absents** (C23/C24). Pour le cash, ce n'est pas bloquant ; pour les tournois, oui.

### 3.4 Runtime et gestion du jeu

**Forces :** boucle asyncio, gate de décision, cache de spots, circuit breaker solveur, budgets par tier, journalisation, snapshots opérateur.

**Faiblesses :**

- Le solveur est appelé dans un thread via `asyncio.to_thread`, avec un timeout de 10 s (`decision_maker.py:1789-1806`) alors que le budget solveur est de 800 ms. Un vrai blocage peut donc immobiliser une décision pendant 10 s.
- Le fallback est fail-closed (CHECK/FOLD), ce qui est bien, mais le taux de fallback n'est pas un SLO bloquant.
- La sélection d'action mélange solveur, RL et exploitation sans une politique unique et testée de bout en bout. Le RL est un adapter, pas une preuve.
- La gestion de session est limitée (section 3.5).
- Aucun test end-to-end « capture → action » sur un rejeu complet n'est évident dans la CI.

### 3.5 Bankroll et risque

`src/bot/session_manager.py:15-17` définit seulement :

- `max_session_hours = 4.0`
- `stop_loss_buyins = 3.0`
- `stop_win_buyins = 10.0`

Il n'y a **pas** de plan de bankroll, pas de risque de ruine, pas de move-up/move-down, pas de séparation cash/tournoi, pas de limites par format, et pas de persistance claire des décisions de bankroll. Les documents `docs/probabilites.md` et `docs/esperance.md` contiennent les formules et les recommandations (40 BI cash, 100–200 BI MTT), mais elles ne sont pas codées.

**Cible :** un moteur de bankroll en Rust, déterministe, avec :

- RoR et probabilité de profit par limite,
- règles move-up/down explicites,
- limites dures par session, par jour et par format,
- journal d'audit de chaque changement de limite,
- tests contre des formules fermées.

**État au 20/11/2026 — cible atteinte (spec `004`).** `src/bankroll.rs` est un module pur et sans état :

- RoR `exp(−2·edge·roll/variance)` en unités buy-ins, avec les conversions cash (bb/100) et tournoi (ROI, BI) faites au même endroit — l'erreur d'unités qui avait faussé une version antérieure du §6 est structurellement impossible ;
- P(profit) `Φ(WR·√(N/100)/σ)` via une approximation `erf` d'erreur bornée (1,5·10⁻⁷) ;
- Kelly `edge/variance` borné, bankroll cible pour un RoR donné (inverse du RoR) ;
- move-up/down à hystérésis (seuil haut ≠ seuil bas, zone morte, bornes d'échelle) ;
- limites dures de session (durée, plafond journalier, stop-loss, stop-win) avec ordre de priorité déterministe.

Les tables du doc sont des tests : RoR 6-max WR7/σ90/40 BI = 0,10 %, HU WR5/σ70/20 BI = 1,69 %, MTT ROI15/σ1,9/50 BI = 1,57 %, P(profit) 50k = 96 %. Le seuil documenté de 40 BI n'est plus posé, il est *vérifié* : la bankroll qui ramène le RoR 6-max sous 1 % vaut ~24 BI.

Deux constats complémentaires : (1) `SessionManager` n'était **instancié nulle part** dans le runtime de production — la protection de bankroll était orpheline ; il est désormais branché sur le moteur Rust via `src/bot/bankroll.py`, en conservant ses seuils et messages historiques. (2) Chaque évaluation est journalisable (`BankrollAuditLog`, JSONL, schéma stable et testé) pour répondre à l'exigence d'audit.

Restent hors périmètre : la production du winrate et de l'écart-type (spec `003`), l'ICM/PKO, et le pilotage automatique de la limite sans confirmation humaine.

### 3.6 Plateformes

- Moderne : PokerStars seulement (`src/vision/site_adapter.py`).
- Legacy : Winamax, GGPoker, PartyPoker, WPT, iPoker, CoinPoker (`poker/tools/supported_sites.py`).
- Aucune suite de conformité par site (fixtures d'écran, thèmes, résolutions, DPI, langues).
- Aucune abstraction de « session de table » commune : le runtime moderne et l'ancien outil ne partagent pas le même modèle.

**État au 20/11/2026 — partiellement corrigé (spec `005`) :** le contrat de plateforme est livré pour **PokerStars et Winamax**. `src/vision/site_adapter.py` expose un **registre** (`SITE_ADAPTERS`) et `get_active_adapter` lève une erreur explicite pour une clé inconnue ; chaque adaptateur déclare identité, thème, format de montants, profil de fenêtre (titre/classe/process) et **limites d'action**. Deux défauts mesurés au passage sont corrigés : (1) le site était **codé en dur** (`get_active_adapter("pokerstars")` en littéral dans `table_manager.py` et `frame_pipeline.py`) — il vient désormais de `bot.active_site` (surchargeable par `POKER_ACTIVE_SITE`) ; (2) le `FormatProfile` était **orphelin** (déclaré mais jamais consommé, le parseur de montants étant construit indépendamment) — `adapter.amount_parser()` en fait la source unique du format. `src/vision/action_limits.py` porte la validation de taille de mise par site, remplaçant la correction locale « < 1 BB → 3 BB ». Les métadonnées de fenêtre Winamax non observées restent `None` (jamais inventées). Conformité verrouillée par `tests/test_site_adapter_registry.py` (21 tests) et des fixtures de montants par site, avec falsification vérifiée. **Reste ouvert** : la conformité d'écran (thèmes, résolutions, DPI, langues) et le benchmark de précision par site relèvent de F-08 — *le harnais de mesure et la politique OCR sont livrés le 20/11/2026 (spec `010`, voir §3.1) ; la précision réelle reste à mesurer faute de captures committables* ; le portage Rust du décodage d'état et des limites reste un candidat P2 (registre §7).

**Cible :** un contrat `PlatformAdapter` (capture, calibration, décodage d'état, encodage d'action, limites) avec une implémentation PokerStars et une implémentation Winamax, testées sur des fixtures. Le cœur de la state machine peut être en Rust ; les pilotes OS restent en Python.

**Conformité :** l'automatisation doit respecter les conditions d'utilisation des sites et le droit applicable. Le produit doit offrir un mode supervisé et ne pas inclure de mécanisme d'évasion de détection. C'est une exigence de conception, pas une note morale.

### 3.7 Données, profiling et apprentissage

Le projet contient un profilage (VPIP/PFR/AF), un adapter RL, des simulations Monte-Carlo et des datasets synthétiques. La qualité statistique reste limitée : profils heuristiques, pas de modèle bayésien hiérarchique, pas de validation croisée sur des populations réelles, pas de gestion explicite du concept drift. Les artefacts de recherche ne sont pas tous versionnés ni reproductibles en CI.

**Cible :** un pipeline de données versionné, des profils avec intervalles de confiance, et une séparation nette entre « recherche » et « production ».

### 3.8 Observabilité

Il existe des snapshots et un journal de décisions (`src/bot/metrics.py`, `src/runtime/history_store.py`). Il manquait :

- des traces corrélées de bout en bout (`spot_id` → vision → solveur → action),
- des métriques p50/p95/p99 par étage, exportables,
- des SLO et des alertes,
- un registre des versions (code, ranges, modèle, solveur) attaché à chaque décision.

**État au 20/11/2026 — corrigé (spec `008`).** Les quatre manques sont traités dans le périmètre **testable hors ligne** ; l'export vers un backend de métriques (Prometheus/OTLP) et l'acheminement hors processus des alertes restent des chantiers distincts, hors périmètre assumé :

- **métriques par étage** : `src/runtime/stage_timing.py` (`StageTimer`) mesure les six étages du chemin HU (`profile`, `ranges`, `rl`, `solver`, `exploit`, `assemble`) et les pose dans `metadata["stages_ms"]` — **dans `metadata`**, jamais à la racine du payload, donc les rejeux golden (qui comparent la décision au champ près en excluant `metadata`) restent inchangés **par construction**, pas par convention (FR-002). Un retour anticipé (circuit breaker, multiway non supporté, aucune action légale) ne porte pas d'étage non traversé. La somme des étages imbriqués est rapportée telle quelle, jamais recadrée à la latence totale ;
- **résumé par étage** : `summarize_decision_records` calcule p50/p95/p99 par étage sur les **seuls** enregistrements qui le portent — un étage absent d'une décision n'est ni inventé ni compté comme zéro. Le percentile est un **rang le plus proche** (`ceil(ratio·n)`) : un p95 sur quatre mesures vaut le maximum observé, pas la troisième valeur — un p95 qui sous-estime la queue ment sur la latence ;
- **SLO et alertes** : `src/runtime/slo.py` évalue des objectifs purs (nom, métrique, opérateur, cible, sévérité) sur les métriques réelles. Un effectif sous `min_samples` est `insufficient_data`, **jamais `ok`** ; une cible absente ou une métrique non mesurée est `ignored` avec sa raison, jamais un `breached` implicite. Le bridge opérateur expose le bloc `slo` et pousse **un** événement `slo_breached`/`slo_recovered` au *changement* de l'ensemble franchi — jamais un par snapshot. Les seuils sont déclarés une seule fois (`DEFAULT_SLO_OBJECTIVES`) et surchargeables par `bot.slo` (FR-010) ;
- **registre de versions** : chaque enregistrement porte un bloc `versions` (schéma, blueprint préflop, modèle de range, tailles de mise) ; une source indisponible vaut `None`, jamais une valeur inventée (FR-007). `KNOWN_SCHEMA_VERSIONS` rend un schéma antérieur **connu** lisible et signalé au lieu de rejeter en bloc tout le journal ; un schéma inconnu reste une erreur (FR-008).

La corrélation de bout en bout existe déjà par `spot_id` dans le journal ; le tracing distribué (span parent/enfant, OpenTelemetry) reste explicitement hors périmètre. Le SLO et le gate go-live sont deux verdicts **indépendants et nommés** (FR-009) : un SLO franchi ne change pas le verdict du gate, vérifié en non-régression.

### 3.9 Build, CI et licence

**Forces :** CI Python (ruff, pytest, coverage 52 %, pip-audit), CI Rust (nightly épinglée, clippy/fmt/doc), workflow refonte V2, releases Windows/macOS, site.

**Faiblesses :**

- Le seuil de couverture global (52 %) est artificiellement bas à cause de `poker/` ; il ne protège pas `src/`.
- Pas de gate de performance ni de gate d'exploitabilité.
- Pas de `cargo audit` ni de SBOM dans le workflow consulté.
- `config.json` est **suivi par git** (`git ls-files config.json`). Même s'il ne contient pas de secret aujourd'hui, c'est un risque : toute clé ajoutée serait versionnée. Les secrets doivent venir de l'environnement ou d'un fichier ignoré (`config.local.json`, `.env`).
- Licence AGPL-3.0-only : toute redistribution/déploiement réseau doit être conforme. À documenter dans le README et dans le processus de release.
- Python est épinglé à `==3.11.*` et le projet dépend de wheels Windows spécifiques (torch, onnxruntime-gpu, dxcam, uiautomation). La reproductibilité Linux est donc partielle.

---

## 4. Constats priorisés

### P0 — Corriger avant toute nouvelle fonctionnalité

#### F-01 : la range héros est une seule main

**Preuve :** `src/bot/decision_maker.py:653-672` :

```python
response = self.solver_provider.solve_spot_v2(
    hero_range=hero_hand,
    villain_ranges=[villain_range],
    ...
    hero_hand=hero_hand,
)
```

`hero_range` et `hero_hand` sont tous deux la main du héros. Or `SolveRequestV2` distingue explicitement les deux champs (`src/v2_api.rs:358` et `:381`), et `gto_api.rs:585-605` utilise `hero_hand` pour extraire l'EV du combo dans la range. L'API est conçue pour recevoir **une range complète** et **une main cible**.

**Impact :** le CFR calcule un équilibre où le villain peut déduire la main exacte du héros. Ce n'est pas l'équilibre du jeu réel. Les fréquences, l'EV, l'exploitabilité, le node-locking et les benchmarks sont tous conditionnés par ce modèle biaisé. C'est le défaut scientifique le plus grave du projet.

**Correctif attendu :**

- passer une range héros complète (par exemple `BASE_GTO_RANGE` ou une range de position/street),
- conserver `hero_hand` pour l'EV du combo,
- ajouter un test qui compare, sur un spot fixe, la stratégie « range complète + combo » à la stratégie « main seule » et qui verrouille la différence,
- vérifier que le cache key inclut bien la range et pas seulement la main.

**Critère d'acceptation :** un rejeu golden montre que la range héros contient plus d'un combo dans la requête solveur, que l'EV du combo est extraite par `hero_hand`, et que l'exploitabilité du spot ne se dégrade pas.

**État au 19/11/2026 (soir) — clôturée :** le code est en place — `_resolve_hero_range` (`decision_maker.py:1042`) alimente `hero_range` (570 combos, source `position_rfi`), `hero_hand` reste la main cible, le cache key et le journal incluent la range (`spot_key.py:63`, `decision_log.py:50-55`), et les tests `test_solver_receives_multi_combo_hero_range_and_target_combo`, `test_two_target_combos_of_same_range_do_not_share_cache`, `test_target_combo_absent_from_range_is_augmented_and_traced`, `test_production_path_never_sends_hero_hand_as_hero_range` passent. Les trois critères du golden sont satisfaits : range multi-combos dans la requête, EV du combo extraite, et dégradation traitée — après trois optimisations du chemin solveur (§ 6.1), le benchmark donne p95 froid 812,0 ms (cible ≤ 950 ms) et le rejeu `scripts/golden_hero_range_replay.py` conclut `pass` (non-convergence étiquetée, convergence 0,455 à 12,8 s). Réserve : le budget de 800 ms ne permet que ~2 itérations DCFR, donc l'exploitabilité rapportée sur flop froid (12,49) reste au-dessus de la cible 0,5 ; la voie pour la ramener dans le budget est un blueprint pré-calculé ou un bucketing de range. **Re-vérifié le 19/11 (nuit)** : la sonde sur `hero_ev` a montré que le rejeu validait « EV du combo extraite » en lisant l'EV de *range* (invariante au combo) — corrigé, et la preuve est maintenant directe : même range, deux combos, EV de combo différentes (1,0081 vs 21,4050) à EV de range identique (−1,0767). Détail en § 6.2.

#### F-02 : le multiway réel n'est pas branché — historique, clos le 17/11/2026

**Statut final :** F-02 est résolu par la spec `002-runtime-n-way` ; la preuve ci-dessous décrit l'état avant correctif.

**Preuve :** `src/bot/gate_flow.py:352` transmet `active_villain_count` au `DecisionMaker`. Celui-ci s'en sert uniquement pour déclencher une approximation :

- `decision_maker.py:1683-1702` : commentaire « le moteur ne supporte que HU », resserrement bayésien supplémentaire, warning `multiway_approximation` ;
- `decision_maker.py:1791-1804` : l'appel solveur ne transmet **ni `num_players` ni les ranges des villains secondaires** ;
- `src/v2_api.rs:401` : `num_players` vaut 2 par défaut ;
- `src/v2_api.rs:985-990` : le chemin multiway est pourtant prêt pour 3 à 6 joueurs ;
- `src/multiway.rs:13` : `MAX_PLAYERS = 6`.

**Impact :** le format recommandé (cash 6-max) est joué comme un HU contre le villain principal. Les autres joueurs ne sont représentés que par une range plus serrée. Ce n'est pas un équilibre N-way, et l'étiquette « GTO » est trompeuse. Le chemin Rust multiway est du code mort en production.

**Correctif attendu :**

- calculer le nombre réel de joueurs actifs et l'ordre des positions,
- transmettre `num_players` et une range par villain actif,
- utiliser le chemin `can_solve_multiway` (3–6) et étiqueter la réponse comme échantillonnée/non convergée,
- conserver un fallback explicite si le nombre de joueurs ou l'état est invalide,
- tester 3-way et 6-way avec des ranges distinctes, et vérifier que le résultat n'est pas le résultat HU.

**Critère d'acceptation :** une requête 6-max produit `backend` multiway, `num_players=6`, autant de ranges que de joueurs, et un warning de non-convergence ; le benchmark 6-max ne passe plus par l'approximation HU.

#### F-03 : aucune preuve statistique de performance

**Preuve :** `docs/PHASE1_BASELINE_2026-11-14.md` :

- Slumbot 1 000 mains : −60,75 bb/100, IC 95 % ±143,4 ;
- simulations de pool : agrégat +6,06 bb/100, `beats_pool=false` ;
- les benchmarks externes utilisent `hero_heuristic`, pas le solveur de production.

**Impact :** on ne peut pas affirmer que le système bat un pool, encore moins qu'il est « parfaitement aligné » aux études. Les chiffres actuels mesurent la chaîne et la politique heuristique, pas la qualité du solveur.

**Correctif attendu :**

- un benchmark reproductible du solveur de production (pas de l'heuristique) contre un pool synthétique et, si possible, un bot de référence ;
- AIVAT/MIVAT pour réduire la variance (C11/C27) ;
- un nombre de mains et une puissance statistique définis à l'avance ;
- un artefact versionné et un gate CI.

**Critère d'acceptation :** un rapport daté avec IC 95 %, taille d'échantillon justifiée, et une conclusion explicite « significatif » ou « non significatif ». Un résultat non significatif est acceptable ; une absence de protocole ne l'est pas.

**État au 20/11/2026 — corrigé (spec `011`).** Les quatre manques sont traités, et le constat a révélé deux défauts supplémentaires non listés à l'origine :

1. **Réduction de variance (C11/C27).** `research/variance_reduction.py` : `control_variate_estimate` (`X = u − β·(C − E[C])`, β optimal), `aivat_estimate` (contrôle centré), `mivat_estimate` (un estimateur par joueur). Sans biais pour toute moyenne de contrôle connue ; une moyenne estimée sur l'échantillon mesuré marque `unbiased_inputs=False` plutôt que de se prétendre sans biais. La réduction de variance rapportée est **mesurée**, jamais supposée (contrôle constant → 0, contrôle parfait → variance nulle).
2. **Puissance statistique déclarée à l'avance.** `research/sample_size.py` : `required_hands` calcule `⌈(z·σ/demi-largeur)²⌉` avant la mesure, et `classify_winrate` rend un verdict explicite (`significant_positive`, `significant_negative`, `not_significant`, `underpowered`, `unmeasured`). Le protocole n'est déclaré complet que si l'effectif atteint le requis **et** que l'IC est fourni.
3. **Benchmark du chemin de production.** `research/production_benchmark.py` mesure une politique fournie (donc `DecisionMaker.get_best_action` quand l'opérateur la passe) sur le pool synthétique, avec IC, effectif, mains requises et réduction de variance. L'artefact porte `hero_policy` et `hero_policy_is_production` : une mesure d'heuristique est étiquetée comme telle et **ne satisfait jamais** le protocole du gate. Point d'entrée opérateur `scripts/production_winrate_benchmark.py` (artefact daté `research/results/production_winrate_<site>.json`). Sans main évaluable, le rapport est `unmeasured` à taux `None`.
4. **Gate go-live.** `src/runtime/strategy_metrics.py` alimente `strategy_metrics` depuis l'artefact (chemin surchargeable par `POKER_STRATEGY_METRICS_PATH`), et `operator_snapshot.py` le passe au gate — le câblage n'est plus mort. Deux checks s'ajoutent, **actifs seulement quand l'artefact porte les champs de protocole** : `strategy_protocol` (IC fourni, effectif ≥ requis, politique de production, statut mesuré) et `strategy_winrate_significant` (borne haute de l'IC ≥ 0). Le comportement historique est préservé quand `strategy_metrics` est absent ou réduit à `{winrate_bb100, best_response_gap}` (contrat Phase 5.18), vérifié par les tests existants.

**Deux défauts trouvés en écrivant la spec :** (a) `strategy_metrics` n'était **jamais** fourni par un appelant — les deux checks stratégiques étaient toujours neutralisés (même schéma que le `SessionManager` orphelin de la spec `004`) ; (b) la seule condition était `winrate_bb100 >= 0`, donc un winrate de +0,1 bb/100 avec un IC [−50 ; +50] passait — un résultat non significatif présenté comme une preuve.

**Vérifié :** 44 tests nouveaux (non-biais, réduction de variance, formule de puissance, verdicts, harnais, contrat, gate) + non-régression du gate ; suite complète **1 362 passés** (contre 1 258), `ruff` vert, `cargo test --lib` 75 passés inchangé. **Reste ouvert :** la campagne réelle n'est pas exécutée (le solveur coûte ~800 ms par flop à froid) — le harnais est donc testé sur des politiques déterministes, et le gate reste honnêtement neutralisé jusqu'à ce que l'opérateur lance `scripts/production_winrate_benchmark.py --policy production`. Le critère d'acceptation (« un rapport daté avec IC, taille d'échantillon justifiée, conclusion explicite ») est satisfait par l'outillage ; le résultat chiffré reste à produire.

#### F-04 : risque de secrets versionnés

**Preuve :** `git ls-files config.json` retourne `config.json`. `.gitignore` ignore `config.local.json` et `.env`, mais pas `config.json`.

**Impact :** toute clé API, token ou identifiant ajouté à `config.json` serait commité. C'est un risque de sécurité et de conformité.

**Correctif attendu :** externeiser les secrets, garder `config.json` pour les valeurs non sensibles, ajouter un test/scan CI qui échoue si un secret connu apparaît, et documenter la procédure.

**État au 19/11/2026 — corrigé :** les valeurs sensibles de `config.json` sont des placeholders d'environnement (`${POKER_AUTO_ANNOTATOR_API_KEY:-}`, `${POKER_DB_DSN:-...__CHANGE_ME__...}`) ou des chaînes vides, et le scan `tests/test_config_no_secrets.py` échoue si une clé sensible non vide, hors placeholder ou marqueur `__CHANGE_ME__`, apparaît dans le fichier versionné (falsification vérifiée : une valeur `sk-live-...` est détectée). Le fichier reste suivi par git pour les valeurs non sensibles ; les secrets vivent dans `.env`/`config.local.json` (ignorés).

### P1 — Nécessaire pour un système fiable et maintenable

| ID | Constat | Preuve | Correctif |
|---|---|---|---|
| F-05 | Deux bases Python sans frontière | `src/` 34,6 k lignes, `poker/` 26,3 k ; couverture 52 % globale vs ~84 % `src/` | ADR, isoler `poker/`, split de couverture, plan de suppression — **frontière d'import fermée le 19/11/2026** : les contrats V2 passent de `poker/decisionmaker/v2_contracts.py` à `src/contracts/v2_contracts.py` (déplacement `git mv`, 23 importateurs basculés, comportement identique vérifié par empreinte des builders et des énumérations) ; `tests/test_adr001_boundary.py` verrouille le critère n°3 de l'ADR-001 (imports statiques et dynamiques, falsification vérifiée). Reste ouvert : split de couverture (F-14) et plan de suppression de `poker/` |
| F-06 | Winamax absent du runtime moderne | `site_adapter.py:85-91` | adaptateur Winamax + fixtures + tests de conformité — **corrigé le 20/11/2026** (spec `005`) : registre `SITE_ADAPTERS` (PokerStars, Winamax), `WinamaxAdapter` avec format européen et métadonnées de fenêtre non inventées, sélection par `bot.active_site` (fini le littéral `"pokerstars"` dans `table_manager.py`/`frame_pipeline.py`), parseur de montants construit depuis le `FormatProfile` (le format n'est plus déclaré deux fois), limites d'action par site (`src/vision/action_limits.py`). 21 tests + fixtures de montants par site, falsification vérifiée. Reste ouvert : conformité d'écran (F-08) et portage Rust (P2) |
| F-07 | Bankroll limitée à 3 seuils de session | `session_manager.py:15-17` | moteur bankroll/RoR/move-up-down en Rust — **corrigé le 20/11/2026** (spec `004`) : `src/bankroll.rs` implémente RoR `exp(−2·edge·roll/variance)` en unités buy-ins, P(profit) `Φ(WR·√(N/100)/σ)`, Kelly, bankroll cible pour un RoR donné, move-up/down à hystérésis et limites de session (durée, plafond journalier, stop-loss, stop-win) ; 16 tests Rust + 18 tests Python reproduisent les tables de `docs/probabilites.md` §2/§6 (RoR 6-max WR7/40BI = 0,10 %, HU WR5/20BI = 1,69 %, P(profit) 50k = 96 %). Découverte au passage : `SessionManager` n'était **instancié nulle part** dans le runtime de production — la protection de bankroll était orpheline, pas seulement minimale ; il est désormais branché sur le moteur Rust et conserve ses messages et seuils historiques |
| F-08 | Vision non prouvée par site | 4 OCR, pas de benchmark de bout en bout | fixtures, précision/latence par site, 1 OCR principal + 1 fallback — **corrigé le 20/11/2026** (spec `010`) : politique OCR par site `src/vision/ocr_policy.py` (un principal + au plus un fallback ; quatre moteurs déclarés sont ramenés à la politique du site avec trace `policy_notes`, jamais en silence), appliquée au boot par `PokerOCR` avec le site actif (`bot.active_site`) ; `src/vision/preset_validation.py` est la source unique du statut et un preset sans échantillon évalué est `unmeasured` à taux `None` (le vert vide `min(scores) if scores else 1.0` est supprimé ; les deux manifestes livrés passent de `green`/`1.0`/`0` à `unmeasured`/`null`/`0`) ; harnais `src/vision/vision_benchmark.py` + point d'entrée `scripts/vision_benchmark.py` mesurant précision/effectif/latence médiane par champ sur captures étiquetées (artefact daté `research/results/vision_benchmark_<site>.json`), champ illisible compté comme échec jamais exclu, rapport `unmeasured` sans capture — **aucun taux inventé**. 39 tests nouveaux, suite complète verte (1318 passés, 5 ignorés). Reste ouvert : aucune capture d'écran committée, donc la précision réelle par site reste **à mesurer** ; conformité d'écran (thèmes, DPI, langues) non couverte |
| F-09 | Pas de gate de performance | benchmark manuel | CI p95 + exploitabilité, seuil de régression 10 % — **corrigé le 19/11/2026**, **recalibré le 20/11/2026** : `scripts/check_perf_gate.py` compare la latence froide (minimum par spot, un processus neuf par répétition) à la baseline versionnée `research/results/perf_baseline.json`. Le premier run CI réel du gate a révélé deux défauts de mesure, tous deux corrigés : (1) un spot qui atteint le délai de garde du solveur (`budget + 2,0 s`) mesurait ce délai, pas le coût du solveur, et était compté comme régression (« +149 % ») puis comme fallback produit ; il est désormais identifié comme **saturation** et sorti de la comparaison ; (2) la calibration de vitesse était mono-thread alors que le solveur est parallèle (rayon), ce qui sous-estimait le handicap d'un runner à peu de cœurs — elle mesure maintenant un débit parallèle (`zlib`). Constat de fond : la latence absolue du solveur parallèle varie trop entre machines (×1,4 à ×3,2 selon le spot sur le runner GitHub) pour porter un gate bloquant ; la comparaison de latence est donc **informative** hors machine de référence (`--strict-latency` la rend bloquante là où la baseline a été mesurée), tandis que les invariants durs — **zéro fallback produit** et backend multiway présent — restent bloquants partout. Logique verrouillée par `tests/test_perf_gate_logic.py` (7 tests) ; falsification rejouée : fallback produit et backend absent font échouer le gate. Câblé dans `python-tests.yml`. Reste ouvert : un seuil de latence portable (machine épinglée ou métrique indépendante du matériel) |
| F-10 | Pas de traces/SLO complets | `metrics.py` agrège localement | tracing `spot_id`, métriques par étage, SLO et alertes — **corrigé le 20/11/2026** (spec `008`) : les six étages du chemin HU sont mesurés par `src/runtime/stage_timing.py` (`StageTimer`) et posés dans `metadata["stages_ms"]`, donc hors du payload comparé par les rejeux golden (FR-002) ; `summarize_decision_records` rapporte p50/p95/p99 **par étage** sur les seuls enregistrements qui le portent (percentile par rang le plus proche, un p95 sur quatre mesures vaut le maximum) ; `src/runtime/slo.py` évalue des objectifs purs sur les métriques réelles — effectif insuffisant → `insufficient_data` jamais `ok`, cible absente → `ignored` avec raison — et le bridge opérateur expose le bloc `slo` en poussant **un** événement `slo_breached`/`slo_recovered` au changement de l'ensemble franchi ; chaque enregistrement porte un bloc `versions` (schéma, blueprint, modèle de range, tailles de mise, indisponible → `None`) et `KNOWN_SCHEMA_VERSIONS` rend un schéma antérieur **connu** lisible et signalé au lieu de rejeter tout le journal (FR-007/FR-008). Le gate go-live garde un verdict indépendant du SLO (FR-009). 3 fichiers de tests nouveaux (62 tests), suite complète verte (1412 passés, 5 ignorés), ruff vert sur les fichiers touchés, `cargo test --lib` (75) et `cargo fmt --check` inchangés. Reste ouvert : export vers un backend de métriques (Prometheus/OTLP) et acheminement hors processus des alertes, hors périmètre de `008` |
| F-11 | AIVAT/MIVAT absents | aucune occurrence dans `src/`/`poker/` | **corrigé le 20/11/2026** (spec `011`) : `research/variance_reduction.py` implémente l'estimateur à variable de contrôle (`control_variate_estimate`, β optimal), AIVAT (`aivat_estimate`, contrôle centré) et MIVAT (`mivat_estimate`, un estimateur par joueur). Sans biais **par construction** (`E[X] = E[u]` pour tout β et toute moyenne de contrôle connue) et réducteur quand le contrôle est corrélé : vérifié par test sur jeux synthétiques à vérité connue (couverture nominale de l'IC, contrôle constant → estimation brute, contrôle parfait → variance nulle, β optimal ≥ β = 1). Le taux de réduction rapporté est **mesuré**, jamais supposé. Reste ouvert : le portage Rust (inutile — hors boucle de décision) |
| F-12 | HS-PCFR/EMD/FGS/PKO absents | aucune occurrence | **traité partiellement le 20/11/2026** (spec `012`) : C16 fait — schedule sélectionnable + harnais de convergence, mais le gain n'est **pas** reproduit dans ce codebase (mesure : `research/results/cfr_schedule_benchmark.json`). Deux défauts de fond trouvés **pendant** la validation et corrigés : (1) la clé du cache natif (`SOLVE_CACHE`, `src/gto_api.rs`) omettait le schedule — un spot résolu sous DCFR était servi à une requête HS-DCFR, la réponse traçant le nom demandé sur la stratégie du défaut (même défaut que la clé de cache Python, ici dans le cache natif) ; verrouillé par `tests/gto_api.rs::gto_cache_key_separates_discount_schedules`. (2) FR-016 (mode strict × schedule non défaut) n'était **ni défini ni testé** : interaction définie comme neutre (le schedule change la vitesse, jamais le critère `converged = exploitability ≤ epsilon_target`) et verrouillée par `tests/v2_api.rs::strict_mode_accepts_a_non_default_schedule_with_an_honest_verdict`. C23/C24 (PKO, ICM/FGS) hors périmètre motivé : tournois, `"tournament": {"enabled": false}`. C25 (EMD) reste ouvert — chantier de bucketing sans vérité de référence hors ligne |
| F-13 | Timeout solveur 10 s vs budget 800 ms | `decision_maker.py:1805` | timeout = budget + marge, annulation propre — **corrigé le 19/11/2026** : `timeout = budget_solve/1000 + 2,0 s` (marge = plancher d'itération non interruptible ~454 ms + réserve d'échéance), verrouillé par `tests/test_solver_circuit_breaker.py::test_solver_timeout_follows_budget_plus_margin` |
| F-14 | `poker/` hors périmètre de lint/tests | CI lint `src tests poker/tools` seulement | **tranché le 19/11/2026 — exclusion formelle** (ADR-001 : `poker/` est le laboratoire historique, hors production ; l'inclure coûterait 521 erreurs ruff dont 41 imports étoile et 41 `except` nus). La CI conserve le seuil global 52 % informatif et ajoute un **seuil bloquant indépendant pour `src/`** (`coverage report --include="src/*" --fail-under=80`, mesuré à 83 %, réutilise les données du run précédent), critère n°1 de l'ADR-001 |

### P2 — Qualité et industrialisation

- Packaging/release AGPL, SBOM, `cargo audit`.
- Reproductibilité Linux partielle (dépendances Windows).
- Documentation de l'état réel : plusieurs docs décrivent des fonctionnalités « DONE » alors que le runtime ne les utilise pas (multiway).
- Nettoyage des artefacts de recherche non versionnés ou non reproductibles.
- Tests de propriété sur l'état canonique et les ranges.
- Suppression des avertissements `fmt` préexistants (dérive de version rustfmt) pour rendre `cargo fmt --check` exploitable.

---

## 5. Traçabilité scientifique C01–C27

La documentation est excellente ; l'implémentation est partielle. Le tableau ci-dessous distingue **implémenté**, **partiel**, **doc seulement** et **non requis pour le cash**.

| Étude | Sujet | État dans le code | Commentaire |
|---|---|---|---|
| C01 | Équilibre Nash N-joueurs | Conceptuel | Fondement ; le multiway n'est pas encore branché |
| C02 | CFR | Implémenté | `solver.rs` (DCFR) |
| C03 | Action translation | Partiel | normalisation des tailles dans `decision_maker.py` |
| C04 | Taille des jeux | Doc | utilisé pour les choix d'abstraction |
| C05 | Cepheus | Non implémenté | référence HU limit |
| C06 | DeepStack | Non implémenté | non requis pour le cash |
| C07 | Libratus / safe subgame | Partiel | re-solving et node-locking partiels |
| C08 | Deep CFR | Non implémenté | le RL adapter n'est pas Deep CFR |
| C09 | DCFR | Implémenté | `solver.rs` |
| C10 | Pluribus / MCCFR | Partiel | `multiway.rs`, branché au runtime 3–6 way via `multiway_mccfr` (échantillonné, non convergé) |
| C11 | AIVAT | Implémenté | `research/variance_reduction.py` (`aivat_estimate`) — contrôle d'équité centré, sans biais, réduction mesurée (spec `011`) |
| C12 | ReBeL | Non implémenté | non requis à court terme |
| C13 | Player of Games | Non implémenté | recherche |
| C14 | Student of Games | Non implémenté | recherche |
| C15 | Supremus | Non implémenté | référence de benchmark |
| C16 | HS-DCFR(30)/(15) | Implémenté et mesuré | **fait le 20/11/2026** (spec `012`) : sélectionnable et tracé ; mesure Kuhn/Leduc — le gain de l'article **n'est pas reproduit** (6/16 couples gagnés, défaites aux paliers hauts) |
| C17 | DDCFR | Non implémenté | recherche — C16 mesure que HS-DCFR(30) est training-free et recommandé à sa place |
| C18 | ES-CFR | Partiel | MCCFR à échantillonnage externe |
| C19 | AlphaHoldem | Non implémenté | non requis |
| C20 | Rake-aware GTO | Implémenté | `rake_rate`/`rake_cap` dans l'arbre |
| C21 | Sizing simplification | Implémenté | `SizingConfig` F33/50/100, T50/75/100, R50/100/150 |
| C22 | Donk GTO | Implémenté | `donk` dans l'arbre |
| C23 | PKO bounty | Absent | tournois uniquement |
| C24 | ICM / FGS | Partiel | ICM Python, FGS absent |
| C25 | EMD clustering | Absent | abstraction de ranges |
| C26 | RL-CFR | Absent | l'adapter RL n'est pas RL-CFR |
| C27 | MIVAT | Implémenté | `research/variance_reduction.py` (`mivat_estimate`) — un estimateur par joueur (spec `011`) |

**Lecture :** le projet n'a pas besoin d'implémenter les 27 études. Il doit en revanche **déclarer** lesquelles fondent chaque fonctionnalité et **mesurer** l'écart. Les priorités scientifiques sont C11/C27 (évaluation), C16 (vitesse de convergence), C25 (abstraction), C23/C24 (tournois). C05/C06/C12–C15/C19 sont des références, pas des obligations.

---

## 6. Preuves de performance et de fiabilité

### 6.1 Latence

| Mesure | Avant correctif | Après correctif |
|---|---:|---:|
| Flop à froid p50 / p95 | 125,6 / 1 245,8 ms | **95,6 / 835,8 ms** |
| Seconde passe p95 | — | 890,5 ms |
| Chaud p50 / p95 | 0,6 / 8,4 ms | **0,5 / 0,6 ms** |
| Fallbacks | 0 | 0 |
| Exploitabilité max | 7,64 | 6,66 |

Le correctif `solver.rs:80-89` mesure le premier calcul d'exploitabilité et le retranche de l'échéance, ce qui garde la finalisation dans le budget. C'est une bonne ingénierie. La cible p95 < 1 s est atteinte de justesse, sans p99 ni mémoire mesurés.

**Mesure du 19 novembre 2026 (chemin F-01 actif).** Benchmark de production relancé machine au repos : flop froid 2 267,8 ms (p95), second flop 982,2 ms ; ces chiffres ne reproduisaient pas le tableau ci-dessus (run du 16/11). Cause racine : avec la range de production (570 combos), une itération CFR coûte ~1,7 s et l'échéance ne peut couper qu'entre deux itérations — même `time_budget_ms=100` rend la main en ~1,72 s. Le budget de 800 ms était donc structurellement inatteignable sur un flop à froid en l'état. Rejeu golden (`research/results/golden_hero_range_replay.json`) : verdict `fail`, exploitabilité 12,70 au budget 800 ms, 2,02 à 6,4 s. Artefacts régénérés le 19/11.

**Correctif du 19 novembre 2026 (2e mesure).** Trois optimisations du chemin Rust ont supprimé le coût hors itérations qui faisait dépasser le budget :

1. `solve_with_deadline_storing` ne finalise que le joueur héros (un parcours d'arbre au lieu de deux) ;
2. l'EV de range à la racine est lue dans les valeurs stockées (`root_range_ev`, O(#mains)) au lieu d'un parcours complet (`compute_current_ev`) ;
3. la réservation d'échéance est calibrée sur la durée de l'exploitabilité initiale du même arbre.

Résultat mesuré (machine au repos, six runs, `research/results/runtime_benchmark.json` en conserve un) : **p95 froid 774–878 ms selon le run, médiane 811 ms**, p50 135–158 ms, chaud p95 0,8 ms, zéro fallback — la cible ≤ 950 ms est tenue dans **tous** les runs. Le rejeu golden conclut `pass` sur ses critères mesurables : la non-convergence est étiquetée (`convergence_not_reached` dans les warnings, `converged=false` dans la réponse et la trace) et la courbe de convergence est documentée (12,70 → 5,14 → 2,19 → **0,455** à 12,8 s, cible 0,5 atteinte). Le plancher structurel reste : à 800 ms, ~2 itérations DCFR tournent, donc l'exploitabilité rapportée (12,49) est très au-dessus de la cible — la latence est tenue, pas la convergence à budget court.

**Re-vérification du 19 novembre 2026 (nuit).** Les deux artefacts ont été régénérés après reconstruction du module natif (`maturin develop`), pour vérifier qu'ils mesuraient bien le binaire corrigé et non une version antérieure. Le rejeu golden redonne `pass` avec la courbe identique au chiffre près (12,70 → 5,14 → 2,19 → 0,455). Le benchmark, relancé six fois, donne un p95 froid dispersé entre **774,1 et 877,9 ms** (médiane 811 ms) : le chiffre de 812,0 ms est représentatif, pas un point favorable isolé, et la cible ≤ 950 ms est tenue dans **tous** les runs. Le premier run après reconstruction (877,9 ms) est le plus lent — cache disque froid sur un `.pyd` fraîchement écrit — ce qui explique l'écart ; les runs suivants se regroupent à 785–816 ms. Le p95 est porté par le seul flop à range complète (`flop_srp_akhk`, 774–878 ms), les cinq autres spots restant sous 190 ms. **Aucun run ne dépasse 950 ms, y compris le plus défavorable.**

### 6.2 Qualité de décision

- Le solveur retourne une exploitabilité résiduelle de 6,66 sur le flop `AhKh` à 800 ms (run du 16/11). Avec la range de production actuelle (570 combos), la mesure du 19/11 (soir) donne 12,49 à 800 ms et 2,19 à 6,4 s, la cible 0,5 étant atteinte à 12,8 s (0,455) : la convergence demande plusieurs secondes sur un flop froid avec une range complète. La latence, elle, est tenue (p95 froid 812,0 ms).
- Le turn et la river répondent vite (10–15 ms) mais avec une exploitabilité supérieure à la cible : le budget est court.
- Un journal antérieur aurait montré `BET` choisi avec un EV inférieur à `CHECK` (−4,22 vs −0,17). La sélection `argmax` par combo est désormais verrouillée par un test (`tests/v2_api.rs::hero_combo_ev_selection_prefers_best_ev_for_exact_hand`, ligne 509) ; le rejeu golden du 19/11 montre en outre que la stratégie change bien entre singleton et range complète (bet_3 → check).

**Sémantique des EV — deux corrections apportées par la sonde du 19/11 (nuit).** En vérifiant le rejeu golden après reconstruction du module natif, une sonde sur le champ `hero_ev` a révélé deux défauts dans le script de rejeu lui-même, tous deux corrigés :

1. **`hero_ev` est l'EV de *range*, pas l'EV du combo.** C'est la moyenne pondérée sur la range du héros à la racine (`root_range_ev`, `gto_api.rs:512`) : elle est *identique* pour deux `hero_hand` différents de la même range (mesuré : `AhKh` et `AsKh` donnent tous deux −14,7985 à 800 ms). L'EV du combo cible est dans `actions[].ev` lorsque `selection == "combo_ev_max"`. Le check `combo_ev_extracted` du rejeu lisait `hero_ev` : il passait donc pour la mauvaise raison (n'importe quelle réponse non nulle l'aurait validé). Il lit désormais `actions[].ev` et exige `selection == "combo_ev_max"`.
2. **`selection` est exposé à la racine de la réponse**, pas sous `metadata` (le binding PyO3 l'aplatit, `python_bindings/src/lib.rs:461-468`) : le rejeu enregistrait `null`. Corrigé.

**Preuve ajoutée : l'EV extraite dépend bien du combo.** Le rejeu résout désormais la même range à budget convergé (12 800 ms) pour deux combos, `AhKh` et `7c7d` (77). Résultat déterministe sur trois exécutions : l'EV de range est identique (−1,0767 pour les deux), l'EV du combo diffère (1,0081 vs 21,4050). C'est la vérification directe que `hero_hand` sélectionne bien le combo et non la range.

**Instabilité de mesure documentée (et non masquée).** L'exploitabilité n'est recalculée que tous les 10 tours (`solver.rs:171`). Conséquence sur le singleton à 800 ms : ~10 itérations y tiennent selon la charge machine, donc la valeur *rapportée* bascule entre 0,0389 (fraîche, `converged=true`) et 11,6855 (valeur pré-boucle, `converged=false`) — observé sur deux exécutions successives du même script. Le rejeu ajoute donc une jambe de référence à 3 200 ms, déterministe (0,0389, `converged=true`, reproduit 6 fois), et c'est cette valeur qui sert de comparaison. Sur la range complète, ~2 itérations seulement tiennent dans 800 ms, donc la valeur rapportée y est toujours la valeur pré-boucle 12,7015.

**Preuve de performance — protocole désormais outillé (spec `011`).** Les winrates publiés (`monte_carlo_sim`, `slumbot_benchmark`) mesurent `hero_heuristic`, pas le chemin de production : leurs IC (±100 à ±143 bb/100) ne prouvent rien sur le solveur. L'outillage ajouté rend une mesure *interprétable* au lieu d'un chiffre nu : estimateurs à variance réduite (AIVAT/MIVAT), nombre de mains requis calculé à l'avance pour une demi-largeur visée, harnais qui mesure une politique fournie et étiquette honnêtement `hero_policy_is_production`. Aucune campagne chiffrée n'est encore exécutée — le tableau ci-dessus reste la seule mesure disponible, et elle porte sur l'heuristique.

### 6.3 Tests

- La suite Rust couvre le solveur, l'équité, le multiway, l'API V2 et les doctests (dernier run documenté : 47 lib + 8 multiway + 9 V2 + 13 doctests).
- La suite Python compte 133 fichiers ; le seuil global est 52 %.
- Les tests ciblés du correctif de latence passent (Rust + 23 tests Python).
- La spec `008` ajoute 62 tests (timer par étage et son coût mesuré, SLO et vacuité, registre de versions et schémas lisibles, exposition du SLO par le bridge) ; suite complète verte (1412 passés, 5 ignorés).
- Il manque un test end-to-end « capture → état → décision → action » et un test de non-régression de performance en CI.

---

## 7. Registre de migration Rust

### Déjà en Rust

- Solveur DCFR HU, MCCFR multiway, équité, arbre, abstraction de mises, rake, MES/exploitabilité.
- Évaluation de mains et calculs de pot.
- API V2 et bindings PyO3.

### À porter en priorité (P1)

1. **État canonique et validateurs** : résolution des rues, positions, stacks, pots, actions légales. C'est le plus gros gain de fiabilité.
2. **Orchestrateur de politique** : sélection préflop/postflop, node-locking, exploitation, fallback. Aujourd'hui en Python, avec des chemins entremêlés.
3. **Bankroll et risque** : RoR, move-up/down, limites de session, audit. — *Corrigé le 20/11/2026 (spec `004`) : moteur `src/bankroll.rs` + enveloppe `src/bot/bankroll.py`, voir §3.5 et §8.*
4. **Journal de décision structuré** : schéma versionné, sérialisation, corrélation `spot_id`. — *Schéma et registre de versions faits côté Python le 20/11/2026 (spec `008`) : bloc `versions` par décision, `KNOWN_SCHEMA_VERSIONS` rend un journal antérieur lisible, `stages_ms` par étage (voir §3.8). Le portage Rust du journal reste ouvert.*
5. **Post-traitement vision** : fusion OCR, cohérence temporelle, machine à états de table.
6. **Encodage/validation des actions de plateforme** : règles légales et limites par site.

### À garder en Python (pour l'instant)

- Capture d'écran et pilotes Windows (DXcam/WGC/uiautomation).
- Inférence YOLO/ONNX et entraînement des modèles.
- OCR (rapidocr/surya) : les moteurs sont Python et lourds ; seul le post-traitement doit migrer.
- API HTTP/asyncio et interface opérateur.
- Notebooks et scripts de recherche.

### Règle de migration

Aucun composant ne doit avoir deux implémentations actives. On migre par contrat :

1. écrire le contrat et les tests de parité,
2. implémenter en Rust,
3. basculer le runtime derrière un flag,
4. comparer les sorties sur des rejeux,
5. supprimer l'ancien chemin.

Le registre `docs/rust-migration-ledger.md` doit lister chaque composant, son état, son propriétaire et sa date cible.

---

## 8. Feuille de route

### Sprint 0 — Correction scientifique (1 semaine)

- F-01 range héros complète.
- F-02 multiway branché.
- Rejeu golden d'un spot 6-max.
- Reproduire l'anomalie d'EV BET/CHECK. → **fait** : l'anomalie historique (BET choisi avec un EV inférieur à CHECK) est verrouillée par `tests/v2_api.rs::hero_combo_ev_selection_prefers_best_ev_for_exact_hand` (voir § 6.2) ; le rejeu golden du 19/11 confirme que la stratégie suit les EV par combo (bet_3 → check selon la range).
- Tests Rust + Python + benchmark de non-régression.

**Sortie :** le runtime résout la bonne range et le bon nombre de joueurs ; les réponses sont étiquetées correctement.

#### Clôture Sprint 0 — 17 novembre 2026

- F-01 range héros complète : **code livré** le 17/11 (`specs/001-gto-hero-range`, T001–T012, tests verts) ; **critères de latence levés au 19/11 (soir)** — p95 froid 812,0 ms (cible ≤ 950 ms) après optimisation du chemin solveur, rejeu golden `pass` (non-convergence étiquetée, convergence à 0,455 atteinte à 12,8 s). Réserve : à budget 800 ms la convergence reste hors d'atteinte (~2 itérations), donc l'exploitabilité rapportée sur flop froid (12,49) dépasse la cible 0,5 — la latence est tenue, pas la convergence à budget court (voir § 6.1 et § F-01).
- F-02 multiway branché : **fait**. `DecisionMaker` transmet `num_players`,
  `villain_ranges`, `hero_player_index`, `active_positions` et
  `primary_villain_index` au solveur. Les spots 3–6 utilisent le backend
  `multiway_mccfr`, avec `sampled=true`, `converged=false` et un warning.
  Le mode strict refuse explicitement (`multiway_strict_refused`) au lieu de
  produire une approximation HU silencieuse ; les états invalides tombent en
  `multiway_not_supported`.
- Rejeu golden 3-way contre HU : fait via
  `tests/v2_api.rs::same_spot_three_way_differs_from_heads_up_and_logs_multiway_mode`.
- Rejeu golden 6-max : fait via
  `tests/v2_api.rs::six_way_river_routes_to_native_multiway_solver`,
  `tests/multiway.rs::six_way_river` et
  `tests/test_decision_maker.py::test_six_way_request_contains_num_players_and_five_ranges`.
- Tests Rust et Python : verts. Benchmark multiway 3–6 exécuté :
  40 mesures, 0 fallback, 40/40 `sampled=true`, p95 froid
  601,5 / 200,1 / 143,9 / 80,8 ms pour 3 / 4 / 5 / 6 joueurs ;
  artefact `research/results/runtime_multiway_benchmark.json`.
- `cargo fmt --check` reste rouge sur des fichiers historiques non liés à cette
  spec ; les six fichiers Rust touchés passent `rustfmt --edition 2021 --check`.

### Sprint 1 — Frontières et sécurité (2 semaines)

- ADR `src/` vs `poker/`, split de couverture.
- Secrets hors de `config.json`, scan CI.
- Timeout solveur aligné sur le budget.
- Gate CI de latence et d'exploitabilité.

**Sortie :** une seule base de production, pas de secret versionné, une régression de performance bloque la merge.

**État au 19/11/2026 — clos.** Les quatre points sont traités :

- **Frontière ADR-001** : les contrats V2 sont passés de `poker/decisionmaker/` à
  `src/contracts/v2_contracts.py` (23 importateurs basculés) ; plus aucun import
  de `src/` vers `poker/`, verrouillé par `tests/test_adr001_boundary.py`.
  `poker/` est formellement exclu du lint (`extend-exclude`) et du seuil de
  couverture bloquant, qui porte désormais sur `src/` seul (80 %, mesuré 83 %).
- **Secrets** : `config.json` ne contient que des placeholders d'environnement ;
  `tests/test_config_no_secrets.py` échoue sur toute valeur en clair.
- **Timeout solveur** : `timeout = budget_solve/1000 + 2,0 s` au lieu de 10 s
  fixes, verrouillé par
  `tests/test_solver_circuit_breaker.py::test_solver_timeout_follows_budget_plus_margin`.
- **Gate de performance** : `scripts/check_perf_gate.py` compare la latence
  froide minimale par spot à la baseline versionnée, avec calibration machine
  parallèle et seuil de régression 10 % ; câblé dans `python-tests.yml`. Le
  premier run CI réel a montré que la latence absolue du solveur parallèle n'est
  pas comparable d'une machine à l'autre : les **invariants durs** (zéro fallback
  produit, backend multiway présent) bloquent partout, la comparaison de latence
  est informative hors machine de référence et bloquante avec `--strict-latency`.
  Les saturations au délai de garde solveur sont identifiées comme telles et
  sorties de la comparaison. Logique verrouillée par `tests/test_perf_gate_logic.py`.

### Sprint 2 — Domaines manquants (3 semaines)

- Adaptateur Winamax + fixtures. → **fait le 20/11/2026** (spec `005`) : registre d'adaptateurs PokerStars/Winamax, sélection par configuration, parseur de montants depuis le format déclaré, limites d'action par site, 21 tests + fixtures de montants par site (falsification vérifiée). Le site n'est plus codé en dur et le `FormatProfile` n'est plus orphelin.
- Moteur bankroll/RoR en Rust. → **fait le 20/11/2026** (spec `004`) : `src/bankroll.rs` (RoR en unités buy-ins, P(profit) `Φ`, Kelly, bankroll cible, move-up/down à hystérésis, limites de session), exposé par PyO3 (9 fonctions), enveloppé par `src/bot/bankroll.py` (journal d'audit JSONL) et branché dans `session_manager.py`. 16 tests Rust + 18 tests Python reproduisent les tables de `docs/probabilites.md` §2/§6 ; `SessionManager`, qui n'était instancié nulle part, est désormais utilisable.
- Vision : benchmark par site, réduction à 1 OCR principal + 1 fallback.
- Traces `spot_id` et métriques par étage.

**Sortie :** vision et bankroll utilisables sur les deux plateformes, avec des preuves mesurées.

### Sprint 3 — Validation scientifique (4 semaines)

- ~~AIVAT/MIVAT.~~ → **fait le 20/11/2026** (spec `011`) : estimateurs à variable de contrôle (`research/variance_reduction.py`), sans biais par construction, réduction mesurée ; MIVAT par joueur.
- ~~Benchmark du solveur de production sur un pool synthétique, puissance statistique définie.~~ → **outillage fait le 20/11/2026** (spec `011`) : harnais `research/production_benchmark.py` mesurant une politique fournie, `required_hands` (mains requises déclarées à l'avance), verdict explicite. La **campagne chiffrée** reste à lancer par l'opérateur (`scripts/production_winrate_benchmark.py --policy production`).
- ~~Expérience HS-PCFR sur un sous-ensemble de spots.~~ → **fait le 20/11/2026** (spec `012`) : `DiscountSchedule` sélectionnable (`dcfr` par défaut, `hs_dcfr_30`, `hs_dcfr_15`) et harnais de convergence sur Kuhn et Leduc (`tests/cfr_schedule_convergence.rs`, artefact `research/results/cfr_schedule_benchmark.json`). La mesure tranche **négativement** : HS-DCFR ne bat le DCFR du crate que sur 6 des 16 couples mesurés et perd aux paliers hauts — le gain de l'article n'est pas transposé. L'adoption en production reste ouverte, adossée à cette mesure.
- EMD pour l'abstraction de ranges. → reste à faire (C25).
- ~~Gate de validation dans `go_live_gate`.~~ → **fait le 20/11/2026** (spec `011`) : le câblage mort est réparé (`strategy_metrics_from_artifacts` → `operator_snapshot`), et deux checks de protocole bloquent un échantillon sous-dimensionné, un artefact d'heuristique ou un winrate significativement négatif.

**Sortie :** un rapport de winrate avec IC et une décision explicite de go/no-go — l'outillage est livré, le rapport chiffré reste à produire.

### Sprint 4 — Industrialisation (4 semaines)

- Packaging/release AGPL, SBOM, `cargo audit`.
- Tests end-to-end sur rejeux.
- Documentation de l'état réel.
- Nettoyage de la dette et suppression des chemins morts.

**Sortie :** un système installable, reproductible, auditable.

---

## 9. Programme SpecKit

La constitution est ratifiée. Les specs suivantes structurent le programme ; seules les P0 sont ouvertes immédiatement.

| Spec | Titre | Priorité | État |
|---|---|---|---|
| `000-programme-v1` | Programme Poker Master v1 | Cadre | Ouverte |
| `001-gto-hero-range` | Range héros complète et EV combo | P0 | **Livrée (19/11/2026)** : p95 froid 812,0 ms, rejeu golden `pass` ; réserve : convergence hors budget 800 ms (blueprint/bucketing) |
| `002-runtime-n-way` | Multiway 3–6 joueurs branché au runtime | P0 | Livrée (17/11/2026) |
| `003-scientific-validity` | AIVAT/MIVAT et benchmark de production | P1 | **Livrée (20/11/2026)** sous `011` : estimateurs AIVAT/MIVAT sans biais, puissance statistique déclarée à l'avance, harnais de benchmark du chemin de production étiqueté honnêtement, gate go-live câblé sur l'artefact ; 44 tests, suite verte ; constats F-03/F-11 clos (campagne chiffrée à lancer par l'opérateur) |
| `011-scientific-validity` | Preuve statistique de performance et réduction de variance | P0 | **Livrée (20/11/2026)** : `research/variance_reduction.py` (AIVAT/MIVAT), `research/sample_size.py` (puissance + verdict), `research/production_benchmark.py` (harnais honnête), `src/runtime/strategy_metrics.py` + checks de protocole du gate, `scripts/production_winrate_benchmark.py` ; constats F-03 et F-11 clos |
| `004-bankroll-risk` | Bankroll, RoR, move-up/down | P1 | **Livrée (20/11/2026)** : moteur Rust `src/bankroll.rs` (RoR, P(profit), Kelly, bankroll cible, move-up/down, limites de session), 16 tests contre les formes fermées, bindings PyO3, enveloppe Python + journal d'audit ; constat F-07 clos |
| `005-vision-multi-site` | Adaptateurs PokerStars/Winamax | P1 | **Livrée (20/11/2026)** : registre `SITE_ADAPTERS` (PokerStars, Winamax), `WindowProfile`/`ActionLimits`/`amount_parser()` au contrat, sélection par `bot.active_site`, `src/vision/action_limits.py`, fixtures de montants par site ; 21 tests, comportement PokerStars inchangé ; constat F-06 clos |
| `006-legacy-boundary` | Frontière `src/` vs `poker/` | P1 | Backlog |
| `007-rust-core-migration` | Migration des domaines chauds | P1 | Backlog |
| `008-observability-slo` | Traces, métriques, SLO | P2 | **Livrée (20/11/2026)** : `src/runtime/stage_timing.py` (six étages mesurés dans `metadata`, hors payload de rejeu), `src/runtime/slo.py` (objectifs purs, `insufficient_data`/`ignored`, alertes de transition), bloc `versions` + `KNOWN_SCHEMA_VERSIONS` dans `src/runtime/decision_log.py`, exposition du bloc `slo` par le bridge opérateur ; 62 tests, suite complète verte ; constat F-10 clos (export de métriques hors périmètre) |
| `009-packaging-compliance` | Release, AGPL, conformité | P2 | Backlog |
| `010-vision-ocr-policy` | Politique OCR par site et preuve de vision | P1 | **Livrée (20/11/2026)** : `src/vision/ocr_policy.py` (un principal + au plus un fallback, par site, appliqué au boot avec trace), `src/vision/preset_validation.py` (source unique : un preset non mesuré est `unmeasured` à taux `None`, le vert vide est supprimé), harnais `src/vision/vision_benchmark.py` + `scripts/vision_benchmark.py` (précision/latence par champ, artefact daté, « non mesuré » sans capture) ; 39 tests, suite complète verte ; constat F-08 clos, mesure réelle par site en attente de captures |

Chaque spec doit contenir des scénarios testables, des exigences fonctionnelles numérotées et des critères de succès mesurables. Une spec sans critère de succès n'entre pas en planification.

---

## 10. Risques et questions ouvertes

1. **Le solveur est-il réellement GTO sur une range complète ?** La correction F-01 peut changer les décisions et révéler d'autres bugs. Il faut un jeu de rejeux avant/après. — *Rejeu golden livré le 19/11 (`scripts/golden_hero_range_replay.py`) ; son extension à un jeu de spots plus large reste souhaitable.*
2. **Le multiway 6-way tient-il dans le budget ?** Le MCCFR est échantillonné ; il faudra mesurer la variance et le temps par nombre de joueurs, et probablement réduire l'abstraction.
3. **Quelle est la définition de « convergé » pour un spot de production ?** Exploitabilité absolue, gap MES, ou stabilité de l'action ? Il faut trancher dans la spec.
4. **Quel pool de référence ?** Les adversaires synthétiques ne prouvent pas la performance réelle. Il faut définir un pool, une taille d'échantillon et une méthode d'évaluation.
5. **Winamax :** le support legacy est-il réutilisable, ou faut-il repartir du contrat moderne ? La réponse dépend de l'ADR sur `poker/`.
6. **Licence AGPL :** le mode de distribution (local, réseau, SaaS) doit être clarifié avant la release.
7. **Sécurité :** `config.json` suivi par git doit être audité avant toute publication.

---

## 11. Conclusion

Le projet a déjà fait le plus difficile : un solveur Rust sérieux, une architecture de mesure, une documentation scientifique et une culture de l'honnêteté sur les résultats. Il lui manque trois choses pour passer du prototype au système :

1. **la correction scientifique** (range héros ; multiway clos le 17/11/2026 par la spec `002`) ;
2. **la preuve empirique** — outillage livré le 20/11/2026 (spec `011`) : benchmark du chemin de production, AIVAT/MIVAT, puissance déclarée, gate câblé ; il reste à **lancer la campagne** pour obtenir le chiffre ;
3. **la discipline de production** (une seule base, secrets, gates, bankroll, observabilité).

Les deux premières sont des prérequis. La troisième est un programme de quelques semaines, pas une réécriture. F-02 est corrigé ; F-01 est corrigé dans le code (range complète transmise, main cible séparée) et ses critères de latence sont levés au 19/11 (soir) : p95 froid 812,0 ms contre 950 ms visés, rejeu golden `pass` avec non-convergence étiquetée et convergence à 0,455 à 12,8 s. Réserve : à budget 800 ms la convergence n'est pas atteinte (~2 itérations), donc l'exploitabilité rapportée sur flop froid (12,49) reste au-dessus de la cible 0,5 — un blueprint pré-calculé ou un bucketing de range est la voie pour la ramener dans le budget.

---

## Annexe A — Commandes de vérification

```bash
cargo test
cargo clippy --all-targets
cargo fmt --check
uv run pytest --cov=src --cov=poker --cov-fail-under=52
uv run ruff check src tests poker/tools
python scripts/bench_production_runtime.py
python scripts/bench_production_runtime.py --mode multiway --repeat 5
```

## Annexe B — Fichiers de référence

- Constitution : `.specify/memory/constitution.md`
- Solveur : `src/solver.rs`, `src/utility.rs`, `src/multiway.rs`, `src/v2_api.rs`
- Décision : `src/bot/decision_maker.py`, `src/bot/gate_flow.py`
- Session : `src/bot/session_manager.py`
- Vision : `src/vision/ocr.py`, `src/vision/site_adapter.py`
- CI : `.github/workflows/python-tests.yml`, `.github/workflows/rust.yml`
- Études : `docs/etudes.md`
- Baseline : `docs/PHASE1_BASELINE_2026-11-14.md`
- Benchmark : `scripts/bench_production_runtime.py`, `research/results/runtime_benchmark.json`, `research/results/runtime_multiway_benchmark.json`
