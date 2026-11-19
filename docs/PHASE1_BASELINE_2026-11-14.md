# Baseline Phase 1 — 14 novembre 2026

> Mis à jour le 19 novembre 2026 après les optimisations du chemin solveur sur
> range héros complète (section 5.6 : p95 froid ~811 ms médian, 774–878 ms selon
> le run, rejeu golden `pass`),
> puis le 16 novembre 2026 après le correctif d'équité Monte-Carlo, le
> benchmark externe Slumbot, les mesures MES natives, les correctifs préflop
> heads-up (sections 2.2 et 3.2.2), la modélisation des spots « face à une
> mise » (section 3.2.1), l'activation du store préflop (section 3.2.3), le
> fallback de tapis nul face à un all-in (section 3.2.4) et la tenue du budget
> mural sur flop froid (section 5.4).

Ce document consigne les mesures reproductibles disponibles après la Phase 0.
**Aucune session live n'a été jouée** : les résultats internes sont des
simulations PokerKit. Les benchmarks externes Slumbot (heuristique en 3.1,
runtime de production en 3.2) et les mesures MES (section 5.1) complètent le
tableau, mais il manque toujours une session play-money réelle avec le pipeline
vision complet.

## 1. Session simulée 100 mains par archétype

Commande :

```bash
python -m research.monte_carlo_sim --hands 100 --seed 20261114 \
  --output research/results/phase1_100_hands_sim.json
```

Politique : `hero_heuristic` (Chen préflop, équité Monte-Carlo postflop).
Adversaires : nit, tag, lag, station, whale. Tapis 100 bb, HU, 500 mains au
total (100 par adversaire).

| Adversaire | Winrate bb/100 | IC 95 % | Verdict |
|---|---:|---|---|
| nit | +14,0 | [−16,4 ; +44,4] | non significatif |
| tag | +22,0 | [−16,3 ; +60,3] | non significatif |
| lag | +22,0 | [−28,3 ; +72,3] | non significatif |
| station | −16,0 | [−34,9 ; +2,9] | non significatif |
| whale | +40,0 | [+2,5 ; +77,5] | significatif |
| **Agrégat** | **+16,4** | — | `beats_pool=false` |

**Lecture honnête :** l'agrégat est positif et le whale sort significativement
positif, mais quatre intervalles sur cinq contiennent zéro et la politique ne
bat pas le pool. Un échantillon de 100 mains par adversaire reste trop petit
pour conclure.

## 2. Session simulée 1 000 mains par archétype

Artefact existant `research/results/monte_carlo_sim.json` (seed 20260826,
5 000 mains) :

| Adversaire | Winrate bb/100 | IC 95 % |
|---|---:|---|
| nit | +17,6 | [4,5 ; 30,7] |
| tag | +5,8 | [−5,1 ; 16,7] |
| lag | −1,0 | [−24,3 ; 22,3] |
| station | +7,3 | [−4,6 ; 19,2] |
| whale | +0,6 | [−23,0 ; 24,2] |
| **Agrégat** | **+6,06** | `beats_pool=false` |

Même à 5 000 mains, le résultat n'est pas une preuve d'avantage : seul le nit
sort significativement positif et les IC restent larges. La simulation suppose
aussi des adversaires synthétiques, pas des joueurs réels.

### 2.2 Politique préflop heads-up corrigée (16 novembre)

`make_heuristic_hero_policy` appliquait les seuils 6-max à toutes les positions :
Chen ≥ 12 pour relancer, ≥ 9 pour payer. En heads-up, le bouton abandonnait donc
ATo, KQo et la BB se couchait face à une ouverture. La politique dépend
désormais de `View.is_button` :

| Spot | Action |
|---|---|
| Bouton, pas de relance | relance 2,5 bb si Chen ≥ 4, sinon limp |
| Bouton face à une relance | 3-bet si Chen ≥ 11, call si ≥ 5,5 |
| BB, SB limpe | relance 3 bb si Chen ≥ 7, sinon check |
| BB face à une relance | 3-bet si Chen ≥ 12, défense si ≥ 1,5 |

`research.slumbot_benchmark.choose_increment` transmet maintenant la position
réelle (`client_pos == 1` est le SB/bouton dans le protocole Slumbot) au lieu de
`is_button=False`.

Évaluation interne (500 mains par archétype, seed 20260826,
`phase1_500_hands_sim_v3.json`) : **+3,92 bb/100**, `beats_pool=false`. Les cinq
IC 95 % contiennent zéro (de −19,4 à +26,7). Le résultat est statistiquement
indistinguable de celui de la section 1 ; il n'est pas une régression prouvée,
mais pas une amélioration prouvée non plus sur ce pool synthétique.

### 2.1 Correctif d'équité Monte-Carlo (15 novembre)

`make_heuristic_hero_policy` passait `view.board_cards` sous forme de chaîne
(`"9h8c2cKc"`) à `monte_carlo_equity`, qui faisait `known.update(board)`. Chaque
caractère était donc traité comme une carte : les cartes du board restaient dans
le deck, les runouts contenaient des doublons et les mains à sept cartes
pouvaient être invalides. `pokerkit` se bloquait parfois sur ces combinaisons et
les équités étaient biaisées.

Le correctif normalise le board en cartes de deux caractères et utilise
`phevaluator` en chemin rapide (repli `pokerkit`). Le test de régression
`test_monte_carlo_equity_accepts_board_string_and_list_equivalently` verrouille
l'équivalence chaîne/liste.

Les chiffres des sections 1 et 2 remplacent ceux du 14 novembre
(+7,8 agrégat sur 100 mains, +5,34 sur 5 000 mains), qui sont invalides.

## 3. Oracle de showdown

`phevaluator==0.6.0` est ajouté aux dépendances de développement. La suite
`research/run_validation_suite.py` compare les évaluateurs sur 500 mains
aléatoires :

| Indicateur | Valeur |
|---|---|
| Cas évalués | 500 |
| Échecs | 0 |
| Mismatches | 0 |
| Taux de succès phevaluator | 1,0 |
| Backends disponibles | phevaluator, pokersolver, poker_evaluator, skpokereval |

Artefact : `research/results/validation_suite.json`.

## 3.1 Benchmark externe Slumbot (15 novembre)

`research/slumbot_benchmark.py` joue la politique `hero_heuristic` contre
l'API HTTP publique de Slumbot (aveugles 50/100, tapis 200 bb, HU). La chaîne
d'actions renvoyée par le serveur est rejouée pour reconstruire le pot, le
montant à payer et la fenêtre de relance légale. Chaque main est journalisée en
JSONL avec ses incréments et sa latence.

Protocole : 1 000 mains, seed 20261115 pour le runner, pause de 0,2 s entre les
mains, reprise sur erreurs réseau, aucune erreur métier. Slumbot distribue les
cartes : la seed ne rend pas le deck reproductible.

| Indicateur | Valeur |
|---|---:|
| Mains | 1 000 |
| Total | −992,0 bb |
| Winrate | **−99,2 bb/100** |
| IC 95 % | ±101,709 → [−200,909 ; +2,509] |
| Écart-type | 16,4097 bb/main |
| Victoires / défaites / égalités | 148 / 852 / 0 |
| Décisions | 1 352 (1,35/main) |
| Latence décision p50 / p95 | 0,028 ms / 2,786 ms |
| Débit | 77,81 mains/min |
| Erreurs | 0 |

Artefacts : `research/results/slumbot_1000.jsonl` et
`slumbot_1000.summary.json`. Les essais antérieurs sont archivés dans
`research/results/archive/` et ne doivent pas être cités.

### 3.1.1 Bug d'unités du benchmark

Le premier essai comparait `to_call` en **jetons** Slumbot (50–100) au
`BIG_BLIND` de la simulation (2 bb). La branche « appel bon marché » était donc
morte et la politique abandonnait 266 mains sur 300 pour un résultat de
−65,667 bb/100. Ce chiffre ne mesurait pas la politique, mais ce bug.

`choose_increment` convertit désormais la vue en gros blindes avant d'appeler
la politique, puis reconvertit le montant de relance en jetons. Le test
`test_choose_increment_feeds_policy_view_in_big_blinds` verrouille le cas
`Ad7d` face à une relance à 2 bb, qui doit payer et non se coucher.

**Lecture honnête :** le point d'estimation est très négatif (−99 bb/100), mais
l'IC 95 % frôle zéro par le haut (+2,5) : l'échantillon de 1 000 mains ne permet
pas de rejeter formellement l'absence d'effet. Un essai pilote de 300 mains
après correctif donnait +36,7 bb/100 avec un IC de ±163,5 : la variance est
énorme. Le benchmark prouve que la chaîne externe fonctionne (HTTP, parsing,
incréments légaux, journalisation, latence) ; il ne prouve pas que le solveur
Rust de production est faible. La cause principale observée était un préflop
beaucoup trop serré : 807 mains sur 1 000 abandonnées au premier tour.

### 3.1.2 Préflop HU corrigé, second benchmark (16 novembre)

Après le correctif de la section 2.2, la même chaîne rejoue 1 000 mains
(nouvelles donnes : Slumbot mélange, la seed ne fixe pas le deck ;
`slumbot_1000_policy_v3.jsonl`, pause 0,05–0,1 s).

| Indicateur | Ancienne politique | Politique corrigée |
|---|---:|---:|
| Mains | 1 000 | 1 000 |
| Winrate | −99,2 bb/100 | **−60,75 bb/100** |
| IC 95 % | ±101,7 | ±143,4 |
| Écart-type | 16,41 bb/main | 23,13 bb/main |
| Premiers abandons | 807 (81 %) | 99 (10,5 %) |
| Premières relances | — | 208 (22 %) |
| Décisions / main | 1,35 | 2,96 |
| Latence p50 / p95 | 0,028 / 2,786 ms | 60,9 / 80,2 ms |
| Erreurs | 0 | 0 |

Artefacts : `research/results/slumbot_1000_policy_v3.jsonl` et
`.summary.json`. Les essais à 400 mains sont conservés mais ne doivent pas être
cités seuls : `slumbot_400_policy_v2.*` (position Slumbot inversée) et
`slumbot_400_policy_v3.*` (sous-échantillon du run final).

**Interprétation :** la politique joue désormais un préflop heads-up lisible
(10,5 % d'abandons au premier tour au lieu de 81 %), et le point d'estimation
s'améliore de ~38 bb/100. Les deux IC se recouvrent largement : le gain n'est
pas démontré statistiquement. La latence par décision passe de 0,03 ms à ~60 ms
parce que la politique joue réellement des coups postflop (équité Monte-Carlo) ;
elle reste très en dessous du budget runtime. Le reste de l'écart au bot
correspond à la qualité postflop de l'heuristique, pas au harnais.

### 3.2 Benchmark externe du runtime de production (16 novembre)

`research/slumbot_runtime_benchmark.py` joue 100 mains contre Slumbot avec
`DecisionMaker.get_best_action` (store préflop, solveur Rust, cache, sélecteur
exploit, fallbacks) au lieu de `hero_heuristic`. Même protocole que la section
3.1 (aveugles 50/100, tapis 200 bb, HU), arbre 50 % / relances 2.5x.

Deux passes ont été réalisées le 16 novembre : avant puis après le correctif
« face à une mise » (section 3.2.1). Les deux sont conservées car elles montrent
l'effet du correctif sur la distribution des actions.

| Indicateur | Avant correctif | Après correctif |
|---|---:|---:|
| Mains | 100 | 100 |
| Total | +4,0 bb | −71,0 bb |
| Winrate | **+4,0 bb/100** | **−71,0 bb/100** |
| IC 95 % | ±125,646 → [−121,646 ; +129,646] | ±110,473 → [−181,473 ; +39,473] |
| Écart-type | 6,41 bb/main | 5,64 bb/main |
| Victoires / défaites / égalités | 34 / 66 / 0 | 26 / 73 / 1 |
| Décisions | 221 (2,21/main) | 220 (2,20/main) |
| Sources | `GTO_RUST` 130, `GTO_PREFLOP_FAST` 91 | `GTO_RUST` 124, `GTO_PREFLOP_FAST` 96 |
| Fallbacks | 0 | 1 (`effective_stack` nul sur une river) |
| Latence décision p50 / p95 | 1,27 ms / 1 344,6 ms | 1,14 ms / 1 316,5 ms |
| Latence solveur p50 / p95 | 282,0 ms / 1 382,0 ms | 269,0 ms / 1 333,0 ms |
| Exploitabilité > 1 | 84/130 (max 25,99) | 84/124 (max 26,27) |
| Relances postflop | **0** | **5** (29 actions agressives au total) |
| Erreurs | 0 | 0 |

Artefacts : `research/results/slumbot_runtime_100.jsonl` et
`slumbot_runtime_100.summary.json` (avant), puis
`slumbot_runtime_100_facing.jsonl` et `slumbot_runtime_100_facing.summary.json`
(après). Pilotes de 20 mains : `slumbot_runtime_pilot*`, non citables seuls.

**Lecture honnête :** les deux IC contiennent largement zéro ; 100 mains ne
prouvent rien sur le winrate, et la baisse du point d'estimation n'est pas
interprétable séparément. Le résultat solide est la distribution des actions :
après le correctif, le runtime relance enfin au flop/turn (4 relances flop,
1 relance turn) et mise quand il est checked to (15 mises flop, 6 turn,
3 river). Avant, il ne faisait que check/call/fold face aux mises. La passe
« après » révèle aussi un problème préflop distinct : **3 relances seulement sur
96 décisions préflop**, soit une politique très passive (40 calls, 53 folds)
qui mérite son propre audit.

### 3.2.1 Correctif : les spots « face à une mise » sont désormais modélisés

**Cause racine.** `build_game` (`src/gto_api.rs`) construisait toujours un arbre
de rue neuf depuis `starting_pot` / `effective_stack`. Le champ
`action_history` de la requête était transporté par l'API mais jamais appliqué :
le nœud racine restait « OOP peut checker ou miser ». Les décisions face à une
mise étaient donc résolues sur un autre spot, d'où zéro relance postflop.

**Correctif (Rust).** `SolveRequest` et `NormalizedSolveRequest` portent
`action_history`; `solve_cache_key` l'inclut. Après résolution de la rue
complète, `apply_action_history` (`src/gto_api.rs`) avance l'arbre token par
token : cartes aux nœuds de chance, sinon `best_history_action` choisit l'action
de l'arbre la plus proche (même classe d'abord, all-in en repli) et `play`
conditionne les ranges. Les montants d'un token sont des **contributions
totales de rue** en bb (`bets 300`, `raises to 900`) ; un historique
incompatible (taille absente, joueur inattendu, nœud terminal) remet l'arbre à
la racine et renvoie la réponse racine, sans casser le runtime. `v2_api.rs`
transmet le champ, `python_bindings/src/lib.rs` l'expose, et le module natif
`postflop_solver_py` a été reconstruit (`maturin build --release`) puis
réinstallé — sans ce rebuild, le runtime Python continuait d'utiliser l'ancien
binaire.

**Correctif (Python).** `_format_solver_action_history`
(`src/bot/decision_maker.py`) reconstruit l'historique de la rue courante :
filtrage par `street`, acteur via `actor` ou `player`/`villain_name`, insertion
des checks manquants (le tracker ne consigne que les actions qui font baisser un
stack) dans l'ordre OOP → IP. Le bug `CALL` → `allin` (la sous-chaîne « ALL »
est présente dans « CALL ») a été corrigé : il transformait chaque call en jam,
ce qui faisait échouer l'historique et retombait silencieusement sur la racine.

**Validation.** 6 tests Rust (`tests/gto_api.rs`, dont « check puis mise » et
« OOP mise »), 37 tests Python ciblés et 75 tests de la zone décision/solver
passent ; Ruff et Clippy sont propres. Le benchmark externe de 100 mains montre
5 relances postflop et 29 actions agressives, contre 0 relance avant.

**Restes.** (a) La politique préflop ne relance presque jamais (3/96) — corrigé
en section 3.2.2. (b) Un fallback sur `effective_stack = 0` (river, main 23) —
corrigé en section 3.2.4. (c) Latence solveur froide p95 ≈ 1,33 s, encore
au-dessus de la cible < 1 s.

### 3.2.2 Correctif : le préflop heads-up ouvre et défend (16 novembre, soir)

**Symptôme.** Dans la passe précédente, le bouton/SB abandonnait **50 fois sur
53 décisions** préflop, et le BB ne relançait que 3 fois sur 46. Le produit
jouait un préflop HU quasi conforme au « fold tout » alors que la section 2.2
avait déjà corrigé les seuils de Chen.

**Trois causes, toutes dans le chemin charts.**

1. **Position.** Les ranges HU de `PreflopManager` sont indexées `SB`/`BB`
   (le bouton est la petite blind), mais l'appelant annonce `BTN`. `BTN`
   n'existant pas dans les tables HU, le bouton retombait sur les charts 6-max
   (`BTN` RFI 45 %, ou `TT+, AQs+, AKo` face à une relance). `hu_position()`
   alias désormais `BTN → SB` en heads-up uniquement.
2. **Détection de relance.** `facing_raise` était déduit de
   `CALL ∈ legal ∧ CHECK ∉ legal`. Or le SB doit toujours 0,5 bb pour compléter
   sa blind : ce spot était donc lu comme « face à une relance », et le bouton
   jouait la range de défense avant de se coucher. La détection s'appuie
   maintenant sur l'historique agressif préflop (`_is_facing_preflop_raise`) ;
   l'ancienne heuristique ne sert que si `action_history is None` (appelants
   legacy).
3. **Option du BB après un limp.** Une fois (2) corrigé, le BB relançait 85 %
   de sa range quand le SB limpe. Le fast-path checke désormais par défaut dans
   ce spot et ne relance que `TT+, AQs+, AKo`.

**Bug du harnais.** `action_history_from_log` ne produisait un historique que
pour les rues 1–3 : la rue 0 n'avait pas de libellé et renvoyait `[]`. La
détection par historique voyait donc un préflop vide dans le benchmark. Le
libellé `PREFLOP` est ajouté ; une passe intermédiaire (BB relançait 55/55) est
archivée dans `research/results/archive/` et n'est pas citable.

**Mesure externe (100 mains, `.venv` Python 3.11, mêmes réglages).** Slumbot
mélange : les donnes diffèrent de la passe précédente, seuls la politique et
les distributions sont comparables.

| Indicateur | Après « face à une mise » | Après préflop |
|---|---:|---:|
| Winrate | −71,0 bb/100 | **−108,0 bb/100** |
| IC 95 % | [−181,5 ; +39,5] | [−442,1 ; +226,1] |
| Écart-type | 5,64 bb/main | 17,05 bb/main |
| Victoires / défaites / égalités | 26 / 73 / 1 | 38 / 62 / 0 |
| Décisions | 220 | 351 (3,51/main) |
| Sources | `GTO_RUST` 124, fast 96 | `GTO_RUST` 242, fast 109 |
| Fallbacks | 1 | **0** |
| Latence décision p50 / p95 | 1,14 / 1 316,5 ms | 7,99 / 1 270,9 ms |
| Latence solveur p50 / p95 | 269,0 / 1 333,0 ms | 254,5 / 1 279,0 ms |
| Relances postflop | 5 | 0 |
| Cache hits | 96 | 109 |

Distribution préflop :

| Spot | Après « face à une mise » | Après préflop |
|---|---|---|
| Bouton/SB premier | 50 folds / 53 | **41 relances, 18 folds, 4 calls / 63** |
| BB face à une relance | 40 calls, 3 folds, 3 relances / 46 | **39 calls, 2 folds, 5 relances / 46** |

**Lecture honnête.** Le bouton ouvre désormais 65 % de ses décisions (41/63) et
le BB continue face à une relance dans 96 % des cas (44/46 : 39 calls,
5 relances), au lieu de se coucher. Le volume de décisions passe de 220 à 351 : le bot joue réellement des
coups, ce qui augmente mécaniquement la variance (écart-type 5,64 → 17,05
bb/main) et rend le winrate de 100 mains encore moins interprétable (IC
[−442 ; +226]). Le résultat solide reste la distribution des actions. Aucune
relance postflop sur cette passe, contre 5 sur la précédente : les donnes sont
différentes, l'échantillon est minuscule, et le correctif « face à une mise »
reste verrouillé par les tests Rust.

**Défaut connu, corrigé en section 3.2.3 : les clés du store préflop.**
`enumerate_combos` (`src/bot/preflop_solutions.py`) générait les combos en rangs
**croissants** (`23o`, `KAs`) alors que `hero_combo_notation` produit la notation
standard en rangs **décroissants** (`32o`, `AKs`). Le store ne matchait donc que
les paires (13 combos sur 169) : 6 décisions `preflop_precomputed` sur 109 dans
cette passe. Les seuils synthétiques étaient en plus indépendants de la position
et, à 100 bb, la bande de call était vide (`call_threshold ≥ aggression`).

Artefacts : `research/results/slumbot_runtime_100_preflop.jsonl` et son
`.summary.json`.

**Validation.** 48 tests préflop/benchmark (dont 9 nouveaux : alias HU,
détection de relance, option du BB, historique préflop) et la suite complète
`1 197 passed, 5 skipped`. Ruff (`check`) propre ; aucun fichier Rust modifié.

### 3.2.3 Correctif : le store préflop est activé (16 novembre, nuit)

**Trois causes.**

1. **Clés non canoniques.** `enumerate_combos` générait les rangs en ordre
   croissant (`23o`, `KAs`) ; `hero_combo_notation` produit l'ordre standard
   décroissant (`32o`, `AKs`). Seules les 13 paires matchaient.
2. **Seuils position-agnostiques.** `build_spot_solution` choisissait l'action à
   partir d'une équité Monte-Carlo contre une main aléatoire et de seuils
   identiques pour toutes les positions. À 100 bb, `call_threshold` valait
   0,47 / 0,52 / 0,57 contre une agressivité de 0,46 / 0,52 / 0,58 : la bande de
   call était vide ou quasi vide, donc le BB ne payait jamais.
3. **Équité Monte-Carlo biaisée.** Le runout était pris **en tête de paquet**
   (`pool[k] for k in range(5)`), donc identique à chaque échantillon. Sur le
   board fixe `2c2h2s3c3d`, 72o affichait 93 % d'équité et AA 69 % — l'EV
   stockée était fausse, et le mode `live` en héritait.

**Correctif.** Les combos sont générés en rangs décroissants. Les tables sont
désormais dérivées des **charts par position** (`PreflopManager`) : RFI, 3-bet
`TT+, AQs+, AKo`, bande de call de défense BB et défenses heads-up. L'équité MC
ne sert plus qu'à l'EV indicative, avec un runout réellement tiré. Des tables
heads-up dédiées (`hu_rfi`, `hu_vs_raise` × `SB`/`BB`) évitent que le bouton HU
retombe sur les charts 6-max ; `BTN` est aliasé `SB` en HU. Le loader lit les
clés avec `rsplit("_", 2)` pour accepter les contextes `hu_*`.

**Mesure externe (100 mains, mode `precomputed` par défaut).** Slumbot mélange :
les donnes diffèrent encore, seules la politique et les distributions sont
comparables.

| Indicateur | Après préflop (charts) | Après store préflop |
|---|---:|---:|
| Winrate | −108,0 bb/100 | **−24,5 bb/100** |
| IC 95 % | [−442,1 ; +226,1] | [−238,2 ; +189,2] |
| Écart-type | 17,05 bb/main | 10,90 bb/main |
| Victoires / défaites / égalités | 38 / 62 / 0 | 48 / 51 / 1 |
| Décisions | 351 | 343 |
| Décisions préflop | 109 | 107 |
| dont store pré-calculé | 6 | **101** |
| dont fast-path charts | 103 | 6 |
| Fallbacks | 0 | **0** |
| Latence décision p50 / p95 | 7,99 / 1 270,9 ms | 5,41 / 1 314,1 ms |
| Latence solveur p50 / p95 | 254,5 / 1 279,0 ms | 209,0 / 1 339,0 ms |
| Actions agressives postflop | 39 `BET` | 36 `BET` |

Distribution préflop (première décision) :

| Spot | Charts | Store |
|---|---|---|
| SB / bouton (to_call 0,5) | 41 relances, 9 folds | **44 relances, 6 folds** |
| BB face à une relance (to_call 1,0) | 39 calls, 2 folds | **42 calls, 1 fold** |
| Face à un 3-bet (to_call 4,0) | 9 folds, 4 calls | 10 folds, 3 calls, 1 relance |

**Lecture honnête.** Le store remplace le fast-path sur 101 des 107 décisions
préflop, sans fallback et sans changer la distribution : le bouton ouvre 44 fois
sur 50, le BB défend 42 fois sur 43. Le winrate remonte de −108 à −24,5 bb/100
mais l'IC 95 % reste [−238 ; +189] : aucune conclusion sur l'avantage, seulement
sur le fait que la chaîne pré-calculée est branchée et cohérente avec les
charts. La latence solveur p95 reste au-dessus de la cible < 1 s.

**Validation.** 39 tests préflop et 16 tests de benchmark passent, dont 7
nouveaux (clés canoniques, tables par position, bande de call, tables HU,
chargement `hu_*`, BU→SB, équité MC non biaisée). Suite complète :
`1 204 passed, 5 skipped`. Ruff propre.

Artefacts : `research/results/slumbot_runtime_100_precomputed.jsonl` et son
`.summary.json`.

### 3.2.4 Correctif : plus de fallback sur tapis nul face à un all-in

**Symptôme.** La passe « face à une mise » comptait un fallback (main 23,
river) : `ActionTree: Effective stack must be positive: 0`, action `FOLD`.

**Cause.** `ParsedState.effective_stack` du harnais valait
`min(hero_stack, bot_stack)`. Quand l'adversaire est all-in, `bot_stack` vaut 0
et le tapis effectif devenait nul, ce que l'arbre du solveur refuse. Or le héros
avait encore 157 bb derrière et 157 bb à payer : le tapis réellement en jeu est
l'appel.

**Correctif.** `effective_stack = max(min(hero_stack, bot_stack),
min(hero_stack, to_call))`. Un tapis terminal (`to_call = 0`, les deux joueurs
à 0) reste à 0. Le spot exact de la main 23 (Kh3s sur QhJc6h5d3d, pot 243,
157 à payer) est rejoué par le runtime : `CALL`, backend `native_solver`,
exploitabilité 0,47, 1 ms, **aucun fallback**.

**Validation.** Un test dédié (all-in avec tapis positif, tapis terminal) et
28 tests Slumbot. Suite complète : `1 205 passed, 5 skipped`. Ruff propre.

## 4. Journal de décision

Nouveau module `src/runtime/decision_log.py` :

- schéma `schema_version=1` ;
- `spot_hash` SHA-256 stable (même normalisation que le cache solveur) ;
- validation des champs requis et des bornes ;
- conversion d'une trace runtime (`chosen_action`, `hero_cards`, `latency_ms`)
  vers le format canonique ;
- résumé p50/p95/p99, taux de fallback, actions, backends.

CLI :

```bash
python scripts/decision_log_audit.py log/decisions.jsonl
python scripts/decision_log_audit.py log/decisions.jsonl --json
```

La trace live `_record_decision_trace` inclut désormais `schema_version` et
`spot_hash`, sans retirer les champs existants. Les 6 tests dédiés passent.

## 5. Laboratoire RL

`python research/run_rl_lab.py` s'exécute et écrit
`research/results/rl_lab_summary.json`. État :

- challengers prêts : `pokerkit`, `rlcard` ;
- indisponibles : `pypokerengine`, `pokerrl`, `neuron_poker`, `poker_ai` ;
- best-response : `solver_evaluated_records=0`, backend
  `alternatives_fallback`, `average_gap=0,0178`, `lbr_gap=0,16`.

Le laboratoire n'est donc pas cassé, mais son best-response agrégé n'est pas
encore évalué par le solveur. C'est une limite à corriger avant d'en tirer une
conclusion sur les politiques RL.

### 5.1 Best-response natif (MES)

`research/mes_spot.py` mesure un preset avec le MES du solveur Rust. Les ranges
des presets se chevauchant, elles sont rendues disjointes en préservant la plus
petite ; les combos retirés sont conservés dans `removed_overlap` et les ranges
effectivement résolues dans `normalized_oop_range` / `normalized_ip_range`. Le contrôle
`ranges_overlap` échoue désormais avant l'appel au solveur, ce qui évite une
allocation de 13–15 Go observée sur des ranges non disjointes.

| Preset | Itérations | Exploitabilité | EV check | EV MES | Gap | Backend |
|---|---:|---:|---:|---:|---:|---|
| `4bp_hu_100bb` | 50 | 1,1471 | 25,4898 | 42,7416 | 17,2518 | `native_mes` |
| `river_jam_low_spr` | 20 | 0,1585 | 36,7184 | 36,7184 | 0,0 | `native_mes` |

Artefacts : `research/results/mes_4bp_hu_100bb.json` et
`mes_river_jam_low_spr.json`.

Sur le spot river, le solveur converge sous la cible d'exploitabilité 0,5 et
`check` est effectivement optimal (gap nul). Sur le flop de 4-bet, le spot n'est
pas complètement convergé (exploitabilité 1,15 > 0,5) : le gap de 17,25 indique
que `check` est nettement sous-optimal, mais reste indicatif.

La correspondance des noms d'actions existe dans
`research.best_response.map_policy_action_to_solver` : `bet_50` est converti en
mise cible (50 % du pot) puis rapproché de l'action solveur la plus proche
(`bet_9`), `jam`/`all_in` de `allin_N`. Deux tests la verrouillent (taille
proche et all-in).

### 5.2 Laboratoire RL branché sur le solveur (16 novembre)

`python research/run_rl_lab.py --solver --max-iterations 20` résout chaque spot
du corpus au lieu d'utiliser les EV inventées. L'arbre est construit **à la
taille de l'action de la politique** (`bet_33` → `33%`) pour éviter l'explosion
mémoire d'un arbre multi-tailles (13,7 Go observés, allocation refusée), puis
l'action est rapprochée de l'unique mise de l'arbre
(`mapping=single_tree_size`).

| Indicateur | Valeur |
|---|---:|
| Spots | 9 |
| Spots évalués | 8 |
| Gap moyen | 5,02 |
| Gap max | 20,79 |
| Exploitabilité max | 5,80 |
| Backend | `native_mes` |

Artefact : `research/results/rl_lab_solver_summary.json`. Les gaps sont
**indicatifs et non convergés** : 20 itérations laissent une exploitabilité de
0,5 à 5,8. Le seul spot non évalué est le replay mocké dont l'action `bet` n'a
pas de taille de pot exploitable. Le branchement est réel ; la qualité de
politique qu'il mesure encore ne l'est pas.

### 5.3 Benchmark du runtime de production (16 novembre)

`scripts/bench_production_runtime.py` appelle `DecisionMaker.get_best_action`
(gate, préflop store, solveur Rust, cache, fallbacks) sur 6 spots fixes :
2 préflop, 2 flops, 1 turn, 1 river. Arbre réduit
(`POKER_SOLVER_BET_SIZES=50%`), tapis 60–100 bb, HU. Chaque spot est joué deux
fois (froid puis chaud).

| Indicateur | Valeur |
|---|---:|
| Exécutions | 12 (6 spots × 2) |
| Latence froide p50 / p95 | 125,6 ms / **1 245,8 ms** |
| Latence chaude p50 / p95 | 0,6 ms / 8,4 ms |
| Fallbacks | 0 |
| Exploitabilité max | 7,64 |

Détail : le préflop précalculé répond en **236 ms** au premier appel (chargement
du store) puis 0,1 ms ; les deux flops coûtent **1,05 s et 1,25 s** à froid ; le
turn et la river répondent en 10–15 ms mais avec une exploitabilité élevée
(5,5 sur la river), donc peu convergés.

**Lecture honnête :** le cache rend les répétitions quasi gratuites, mais un
flop froid reste au-dessus de la cible p95 < 1 s, même avec l'arbre réduit.
L'exploitabilité max de 7,64 montre que le budget de 1 000 ms ne suffit pas à
converger sur ces spots. C'est cohérent avec la section 7 : il faut un arbre par
défaut plus petit ou un blueprint pour tenir le budget. Artefact :
`research/results/runtime_benchmark.json`.

### 5.4 Correctif : la finalisation tient dans le budget (16 novembre, nuit)

Le CFR respectait déjà l'échéance, mais `finalize()` (stockage des EV de l'arbre)
et la conversion de la réponse s'exécutaient **après** elle. Sur un flop froid
50 %/2.5x, la finalisation seule coûtait 85–110 ms, d'où un dépassement du budget
mural de 800 ms.

`src/solver.rs` réserve désormais cette durée dans l'échéance : la durée du
premier calcul d'exploitabilité (un parcours d'arbre comparable) est mesurée et
retranchée du temps laissé au CFR. La réserve est auto-calibrée par arbre, sans
constante arbitraire, et ne s'applique qu'aux appels avec budget.

| Indicateur | Avant | Après |
|---|---:|---:|
| Latence froide p50 / p95 | 125,6 ms / 1 245,8 ms | **95,6 ms / 835,8 ms** |
| Latence chaude p50 / p95 | 0,6 ms / 8,4 ms | 0,5 ms / 0,6 ms |
| Fallbacks | 0 | 0 |
| Exploitabilité max | 7,64 | 6,66 |

Détail froid : préflop 186 ms, flops 836 ms et 832 ms, turn 5 ms, river 4 ms.
Une seconde passe donne 890 ms de p95, soit 836–891 ms selon la charge machine.
L'exploitabilité des deux flops (6,66 et 6,12) est identique à la mesure sans
réserve : la cible p95 < 1 s est atteinte **sans** sacrifier d'itérations. Une
réserve proportionnelle plus agressive (25 %) avait été testée puis écartée :
elle descendait le p95 à 757 ms mais faisait monter l'exploitabilité du flop
`AhKh` de 6,66 à 12,96, preuve que les itérations restent utiles sur ce spot.

Artefact : `research/results/runtime_benchmark.json` (récapitulatif 12 mesures).

### 5.5 Runtime multiway 3–6 (17 novembre)

`scripts/bench_production_runtime.py --mode multiway --repeat 5` appelle le
runtime de production sur un spot par nombre de joueurs (3, 4, 5, 6), en froid
puis en chaud, avec cinq répétitions. Les quatre spots utilisent le backend
`multiway_mccfr`, cinq ranges villain distinctes au maximum, et sont étiquetés
`sampled=true`, `converged=false`, warning `multiway_approximation`.

| Joueurs | Exécutions | Latence froide p50 / p95 | Latence chaude p50 / p95 | RSS max | Fallbacks | Sampled |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 10 | 0,3 ms / **601,5 ms** | 0,3 ms / 0,7 ms | 191,5 Mo | 0 | 10 |
| 4 | 10 | 0,3 ms / **200,1 ms** | 0,3 ms / 0,6 ms | 191,5 Mo | 0 | 10 |
| 5 | 10 | 0,3 ms / **143,9 ms** | 0,3 ms / 0,5 ms | 191,5 Mo | 0 | 10 |
| 6 | 10 | 0,3 ms / **80,8 ms** | 0,3 ms / 0,5 ms | 191,5 Mo | 0 | 10 |

**Lecture honnête :** le p95 froid du premier passage est 601,5 ms en 3-way,
donc sous la cible de 1 s du spec 001, mais il dépend de la charge machine. Les
répétitions suivantes sont servies par le cache ; le p50 froid agrégé (0,3 ms)
ne doit donc pas être lu comme un temps de résolution MCCFR. Le multiway est
échantillonné et non convergé : ces mesures prouvent le branchement et le budget,
pas un gain de winrate. Artefact :
`research/results/runtime_multiway_benchmark.json` (40 mesures).

### 5.6 Range héros complète : latence et convergence (19 novembre, 2e mesure)

Le correctif F-01 (`specs/001-gto-hero-range`) envoie au solveur la range de
position complète (570 combos, source `position_rfi`) au lieu de la main seule.
Effet mesuré sur le flop `AhKh` (`Jc 7s 2d`, pot 6, tapis 97) :

| Configuration | Budget | Temps mural | Exploitabilité |
|---|---:|---:|---:|
| Singleton `AhKh` | 800 ms | 487 ms | 0,039 |
| Range complète | 100 ms | 454 ms | 12,70 |
| Range complète | 800 ms | 677 ms | 12,70 |
| Range complète | 1 600 ms | 1 403 ms | 12,70 |
| Range complète | 3 200 ms | 2 800 ms | 5,14 |
| Range complète | 6 400 ms | 6 351 ms | 2,19 |
| Range complète | 12 800 ms | 9 719 ms | **0,455** (convergé) |

Mesures du 19/11 (nuit), rejeu `scripts/golden_hero_range_replay.py` ; les
valeurs varient de quelques pour cent d'un run à l'autre. L'exploitabilité
n'est recalculée que tous les 10 tours, d'où le plateau à 12,70 sur les trois
premiers budgets : c'est la mesure *d'avant* la boucle, la stratégie renvoyée
étant meilleure que ce qu'elle annonce.

**Ce qui a changé depuis la première mesure.** Trois optimisations du chemin
Rust ont supprimé l'essentiel du coût hors itérations :

1. `solve_with_deadline_storing` ne finalise que le joueur héros (la
   finalisation coûtait un parcours d'arbre complet par joueur) ;
2. l'EV de range à la racine est lue dans les valeurs stockées par la
   finalisation (`root_range_ev`, O(#mains)) au lieu d'un parcours complet
   (`compute_current_ev`) ;
3. la réservation d'échéance utilise la durée de l'exploitabilité initiale,
   mesurée sur le même arbre.

Le benchmark de production (`research/results/runtime_benchmark.json`, 19/11,
machine au repos) donne **p95 froid 812,0 ms** contre 2 267,8 ms avant : la
cible ≤ 950 ms du spec 001 est tenue. Le rejeu golden
(`scripts/golden_hero_range_replay.py`) conclut `pass` sur ses critères
mesurables : la non-convergence est étiquetée (`convergence_not_reached`) et le
balayage de budget montre la courbe 12,70 → 5,14 → 2,19 → 0,455.

**Dispersion (re-vérification du 19/11, nuit, après reconstruction du module
natif).** Six runs donnent un p95 froid entre **774,1 et 877,9 ms** (médiane
811 ms) ; la cible ≤ 950 ms est tenue dans tous les runs, le plus lent inclus.
Le p95 est porté par le seul flop à range complète (774–878 ms) ; les cinq
autres spots restent sous 190 ms. Le run le plus lent est le premier après
reconstruction du `.pyd` (cache disque froid) ; les suivants se regroupent à
785–816 ms. Le chiffre de 812,0 ms du tableau est donc une médiane
représentative, pas un point favorable isolé. L'artefact
`runtime_benchmark.json` ne conserve qu'un run : celui du 19/11 (nuit) affiche
774,1 ms.

**Plancher du budget.** Le balayage golden mesure le coût d'une itération DCFR
non interruptible sur ce flop : à `time_budget_ms=100`, le mur rend la main en
**454 ms** (première itération + exploitabilité initiale). En dessous de ce
plancher, le budget annoncé ne peut pas être respecté — mais la réponse reste
étiquetée non convergée (`converged=false`, `convergence_not_reached`), ce qui
satisfait l'AC3 du spec (« la réponse est étiquetée non convergée et le
fallback reste explicite »).

**Sémantique des EV et instabilité (sonde du 19/11, nuit).** `hero_ev` est l'EV
de *range* (moyenne pondérée à la racine, `root_range_ev`) : elle est identique
pour deux `hero_hand` de la même range. L'EV du *combo* cible est dans
`actions[].ev` quand `selection == "combo_ev_max"`. Vérification directe à
budget convergé (12 800 ms), même range, deux combos : EV de combo 1,0081
(`AhKh`) vs 21,4050 (`7c7d`), EV de range identique (−1,0767) — déterministe.
Par ailleurs, l'exploitabilité n'étant rafraîchie que tous les 10 tours, la
valeur *rapportée* du singleton à 800 ms bascule entre 0,0389 (`converged=true`)
et 11,6855 (valeur pré-boucle) selon la charge machine ; la référence
déterministe est le singleton à 3 200 ms (0,0389, `converged=true`). Sur la
range complète à 800 ms, ~2 itérations tiennent, donc la valeur rapportée y est
toujours la valeur pré-boucle 12,7015.

**Lecture honnête :** le budget de 800 ms ne fait tourner qu'environ deux
itérations DCFR sur ce flop ; l'exploitabilité rapportée à ce budget (12,70)
reste très au-dessus de la cible 0,5, qui demande ~12,8 s. Le chiffre de 12,70
est de plus la mesure *d'avant* la boucle (l'exploitabilité n'est recalculée
que tous les 10 tours) : la stratégie renvoyée est meilleure que ce qu'elle
annonce. La latence est tenue, pas la convergence à budget court. Voies
possibles : blueprint pré-calculé hors ligne (infrastructure existante,
`config/blueprint/blueprints.jsonl`), bucketing de range, ou révision explicite
du critère de convergence du spec.

## 6. Jev / Djev

Voir l'addendum de l'audit (section 14.3) et
`scripts/probe_ai_gate.py`. Mesures : 18/20 réponses parsées, p50 289 ms,
p90 1 156 ms, p95 2 281 ms, 2 HTTP 400. Le timeout Jev de 0,8 s est trop court
pour ce proxy en collecte de données.

## 7. Budget du solveur (correctif du 15 novembre)

`time_budget_ms` ne bornait pas le temps réel : 1 000 ms donnait 512
itérations. Un flop HU 94 bb, ranges de production, arbre par défaut, a été
tué après 120 s à la 125ᵉ itération (~0,96 s/itération). `solve_with_deadline`
vérifie désormais l'échéance entre deux itérations et le cache distingue les
budgets.

| Configuration | Temps mural | Itérations |
|---|---:|---:|
| Arbre par défaut, budget 1 000 ms | 10,8 s | 1 |
| Arbre réduit (`bet_sizes=50%`) | 2,3 s | 3 |

La cible p95 < 1 000 ms n'est pas atteinte : la construction du jeu et le
calcul d'exploitabilité coûtent ~9 s à eux seuls sur l'arbre par défaut. Il
faut un arbre plus petit ou un blueprint pour les spots fréquents.

## 8. Ce qui manque pour conclure

1. Une session play-money réelle de 100 mains avec le pipeline vision complet.
2. Un corpus de 100 décisions réelles à rejouer (le journal et le CLI sont
   prêts ; `log/runtime_history.jsonl` ne contient aucune décision).
3. ~~Un benchmark externe Slumbot/GTO Wizard avec protocole et IC.~~ Fait :
   1 000 mains, −99,2 bb/100, IC 95 % [−200,909 ; +2,509] (section 3.1).
4. ~~Un best-response RL évalué par le solveur.~~ Fait le 16 novembre : deux
   presets en MES natif (section 5.1) et le corpus du laboratoire évalué par le
   solveur (section 5.2, 8 spots, gap moyen 5,02, non convergé).
5. ~~Un benchmark externe du runtime complet (solveur Rust + gate + vision).~~
   Partiellement fait le 16 novembre : runtime headless mesuré (section 5.3 :
   froid p95 1,25 s, chaud < 10 ms, 0 fallback) puis runtime de production joué
   contre Slumbot (section 3.2 : deux passes de 100 mains, IC contenant zéro).
   Restent la vision et une session réelle.
6. ~~Une revue du préflop : 807 abandons sur 1 000 mains au premier tour.~~ Fait
   le 16 novembre (section 2.2 et 3.1.2) : 10,5 % d'abandons, −60,75 bb/100,
   gain non significatif mais chaîne et préflop désormais lisibles.
7. ~~Modéliser les spots « face à une mise » dans le solveur.~~ Fait le
   16 novembre (section 3.2.1) : `action_history` est appliqué après résolution,
   le module natif reconstruit, et le benchmark externe montre 5 relances
   postflop contre 0 auparavant.
8. ~~Auditer la passivité préflop (3 relances/96).~~ Fait le 16 novembre
   (section 3.2.2) : alias bouton/SB, détection de relance par historique et
   option du BB corrigés ; 46 relances préflop sur 109 décisions, 0 fallback.
9. ~~Corriger les clés du store préflop et l'activer.~~ Fait le 16 novembre
   (section 3.2.3) : combos canoniques, tables dérivées des charts par position,
   bande de call, tables heads-up, équité MC corrigée ; 101/107 décisions
   préflop servies par le store, 0 fallback.
10. ~~Traiter le fallback `effective_stack = 0` face à un all-in.~~ Fait le
    16 novembre (section 3.2.4) : tapis effectif = appel du héros, spot rejoué
    sans fallback.
11. ~~Tenir le budget mural sur un flop froid.~~ Fait le 16 novembre
    (section 5.4) : la finalisation est réservée dans l'échéance auto-calibrée ;
    p95 froide 835,8 ms, exploitabilité inchangée (6,66).
    Reste : winrate toujours non significatif.
