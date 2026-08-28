# Espérance (EV) — définitions, unités et formules du solver

> Unité de compte de tout le solver : `hero_ev` en chips est l'espérance brute, déclinée en bb, bb/100, $ et $EV. Rake et PKO inclus.
> Refs socle : `etudes.md` C11 (AIVAT Variance), C20 (rake-aware), C23 (PKO Bounty Power), C24 (ICM/FGS) ; `probabilites.md` §1 (décomposition a-f du edge) et §2–3 (P(profit)/RoR).

---

## 1. Définitions

- **hero_ev (chips)** : sortie brute du solver (`solver.rs` / `multiway.rs:payoffs`) — EV en jetons du point de vue de hero à stratégie fixée, pot et rake inclus. Unité pivot avant conversion.
- **EV(a)** : espérance d'une action `a` (bet/check/fold) au nœud courant : `EV(a) = Σ_z P(z|a)·u(z)` où `u(z)` est le payoff terminal (share net). Le solver choisit `a* = argmax EV(a)`.
- **equity** : `P(win) + 0.5·P(split)` à showdown, estimée par Monte-Carlo 120–4000 samples (`equity.rs`). Sans rake/PKO : `EV ≈ equity·pot − cost`.

## 2. Formules

```
EV brut (sans rake) :  EV = equity * pot - cost
  cost = mise à payer pour voir le payoff ; pot = pot total avant rake.

Rake share (C20) :    rake = min(pot * rake_rate, cap)   ; ex. 5%, cap $3
                      share = (pot - rake) / winners.len()
  → EV net = equity * (pot - rake) - cost   (à N>2, divise par winners)
  Code : multiway.rs:payoffs()  share = (pot - rake)/winners.len()  [C20]

PKO $EV (C23) :       $EV = ChipEV + BountyEV
  ChipEV  : hero_ev converti en part de prize pool (ICM/FGS si MTT, C24)
  BountyEV: Σ_bounties P(éliminer j)·bounty_j  ; early 25-33% BI, FT 2-4× [C23]
  Cover   : si hero couvre, EV élargit +10-20% wider (bounty power).

Variance-aware (C11) : AIVAT/MIVAT ne changent pas EV (estimateur sans biais) mais
  Var(EV_est) −68 à −85% → 44× moins de mains pour même CI [C11].
```

## 3. Table correspondance unités

| Unité (clé code) | Définition | Conversion | Quand l'utiliser |
|------------------|------------|------------|------------------|
| `ev_chips` | hero_ev brut en jetons | — (sortie solver) | Calcul interne, payoffs, AIVAT |
| `ev_bb` | hero_ev en big blinds | `ev_bb = ev_chips / bb` | **Pivot comparables** (WR, edge a-f) ; contient `ev_bb` |
| `ev_bb_per_100` | WR normalisé /100 mains | `ev_bb_per_100 = ev_bb * 100` (spot instantané ; WR agrégé `Σev_bb/N_hands*100`) | Tables P(profit) `probabilites.md` §2, bench exploitabilité (mbb/g = 10× bb/100) |
| `ev_dollars` | Cash direct | `ev_dollars = ev_bb * $/bb` | Bankroll cash, rake $ cap |
| `$ev` | ICM / bounty-adjusted (MTT/PKO) | `$EV = ChipEV($) + BountyEV($)` (FGS 2-3, C24) | MTT 7..9, PKO — **≠ chipEV** |
| `equity` | Proba showdown [0,1] | `EV = equity*pot - cost` (avant rake) | Input de EV, bucketing EMD |

> Règle : comparer en `ev_bb`/`ev_bb_per_100` entre limites, en `$ev` entre tournois (ICM), jamais en `ev_chips` brut inter-limites.

## 4. Matrice compacte EV par variante × N (rake et PKO inclus)

`ev_chips → ev_bb → ev_bb_per_100 → $EV` ; rake 5%/$3-4 cap (C20), PKO early 25-33% → FT 2-4× (C23), ICM 15-25% tighter FGS2-3 (C24).

| Variante × N | `ev_chips` → `ev_bb` | `ev_bb_per_100` (méd. micro) | `$EV` | Rake / PKO |
|--------------|----------------------|-------------------------------|-------|------------|
| **HU 2** (HS-PCFR/DCFR) | `ev_bb = ev_chips/bb` direct, pas de split | **+8..+15** (méd ~10, σ~70) | `$EV≈ev_dollars` (pas d'ICM) | rake 5% cap $3 : `share=(pot-rake)/1` ; PKO rare |
| **3-way** (MCCFR) | `/bb`, split `/winners` si chop | **+1.2..+3** contrib. multiway (~28% mains 6-max) ; σ~90 | `$EV≈ev_dollars` cash | rake cap touché plus souvent 3-way → même `rake_rate/cap` que HU (C20) |
| **6-max 3..6** (MCCFR N-param, **référence V1**) | `/bb`, `share=(pot-rake)/winners` | **+5..+10** complet (méd ~7, σ~90) → **96-98% P(profit) à 50k** (`probabilites.md` §2) | cash `$EV=ev_dollars` | rake-aware **+1..+3** si inclus, **−1.5..−4** si omis (C20) |
| **MTT 7..9** (ICM/PKO) | `ev_chips` legs → `ev_bb` | ROI **10-25%** micro ↔ ~+1.5..+5 bb/100 equiv. ; σ 1.9-2.6 BI | **`$EV=ChipEV+BountyEV`** ; bounty early 0.25-0.33 BI → FT 2-4× [C23] ; ICM 15-25% tighter FGS2-3 [C24] | rake = fee tournoi ; PKO `BountyEV = Σ P(elim)·bounty` ; cover +10-20% wider |

Lecture : `ev_chips` est l'unique sortie solver ; `ev_bb` compare les limites ; `ev_bb_per_100` alimente `P(profit)=Φ(WR·√(N/100)/σ)` et `RoR=exp(−2·edge·roll/var)` (`probabilites.md` §2-3, §6) ; `$EV` seul décide en MTT/PKO.

## 5. Exemples chiffrés

**Ex.1 — EV de base (équité·pot − cost)** : pot 100bb, equity 0.55, cost 50bb (call) → `EV = 0.55*100 − 50 = 55 − 50 = +5bb` → `ev_bb=+5`, `ev_chips=+5·bb`. C'est le cas `equity*pot-cost` nominal ; le solver compare ce `EV(call)` à `EV(fold)=0` et `EV(raise)`.

**Ex.2 — Rake 5% cap $3 (C20)** : pot $100, `rake = min(100*0.05, 3) = $3` → net $97. HU winner : `share=97` → `EV = equity*97 − cost` (−3 vs brut). 3-way winner unique idem ; pot $30 → rake $1.5 → net $28.5. Omettre le rake surestime `ev_bb` de **1.5 à 4 bb/100 en micro** (C20, `probabilites.md` §1d). Code `share=(pot−rake)/winners.len()`.

**Ex.3 — PKO bounty 0.3 BI (C23)** : MTT PKO, bounty 0.3 buy-in (=30bb à 100bb BI), `P(elim)=0.2` sur ce coup → `BountyEV=0.2*0.3=0.06 BI (=6bb)`. Si `ChipEV=+4bb`, alors `$EV = 4 + 6 = +10bb` en équivalent chips bounty-inclus, soit ~+0.10 BI de $EV. Early stage bounty vaut 25-33% BI, FT 2-4× ; couvrir élargit +10-20% (bounty power). Sans ce terme, `ChipEV` seul sous-évalue de 60% le spot.

## 6. Références croisées

- `etudes.md` **C11** AIVAT : variance −68..−85% sans biais sur `hero_ev` ; **C20** rake 5%/$3-4 cap RFI −2-5% ; **C23** PKO `$EV=ChipEV+BountyEV` 25-33%→2-4× ; **C24** ICM 15-25% tighter, FGS 2-3, 1-KLSS multiway.
- `probabilites.md` **§1** décomposition a-f du WR (`ev_bb_per_100`), **§1bis** additivité a+b+d+e+f ; **§2–2.2bis** `P(profit)` cash/MTT/HU et par régime 48k/86k/173k, **§3** MTT σ 1.9-2.6, **§6** `RoR`.
- `strategie-par-format.md` **§1–2** sizing `SizingConfig::default()` F33/50/100 T50/75/100 R50/100/150 + préflop 2bb/3bb cap3, **§4** matrice variantes×N (sizing/algo) — même découpage N que §4 ci-dessus.

---

## 7. Gain mensuel par limite et régime de volume

> Convertit le WR du solver (`ev_bb_per_100`, `probabilites.md` §1 total V1 bloc) en revenu mensuel cash, sans dupliquer les tables `P(profit)` (voir `probabilites.md` §2.2 pour `P(profit)` à ces volumes).

### 7.1 Rappel formule et hypothèses

**Formule** — gain mensuel cash (post-rake, hors rakeback/bonus) :

```
gain mensuel  =  WR  ×  (mains / 100)  ×  $/bb
$/h           =  gain mensuel / heures jouées
```

où `WR = ev_bb_per_100` en bb/100 (médianes `probabilites.md` §1 total V1 bloc), `$/bb` = valeur d'une grosse blinde à la limite, `mains` = volume mensuel. Source code : `src/ev.rs:ev_summary()` — `ev_bb = ev_chips / bb` puis `ev_bb_per_100 = ev_bb × 100` (helper per-spot ; WR agrégé multi-mains `Σev_bb/N_hands×100`, voir `probabilites.md` §2), `ev_dollars = ev_bb × $/bb` [C20 rake-aware partagé HU→MCCFR ; C21 sizing `SizingConfig::default()` flop F33/50/100 turn T50/75/100 river R50/100/150 + préflop 2bb/3bb cap3 incluse dans le WR].

**Hypothèse volume** — médiane **600 mains/h** en 6-max 4–6 tables (`ordre-conseille.md` §1, rang 1 — 500–800 mains/h en multi-tabling 6-max vs ~250 HU / ~60 MTT). Trois régimes canoniques (même hypothèse 600/h) :

| Régime | Rythme | Heures/mois | Mains/mois | Blocs de 100 | Statut |
|--------|--------|-------------|------------|--------------|--------|
| **A — loisir soutenu** | 4 h × 5 j/sem | **80 h** | **48 k** | 480 | atteignable |
| **B — reco (sweet spot)** | 6 h × 6 j/sem | **144 h** | **~86 k** (86 400 à 600/h, arrondi 860 blocs) | 860 | **recommandé** |
| **C — théorique** | 12 h × 6 j/sem | **288 h** | **~173 k** (172 800, arrondi 1 730 blocs) | 1 730 | illustratif — WR dégrade **7 → 5** bb/100 en micro si tilt (`probabilites.md` §5 piège #1 : tilt −30% EV, 20% sessions en tilt) |

> Régime C : on retient `WR=5` (au lieu de 7) pour les limites micro (NL2–NL10) afin d'illustrer la dégradation tilt/fatigue. En mid/high la même décote s'applique pro-rata si tilt (`probabilites.md` §5) — voir encadré 7.4.

**WR médians utilisés** — `probabilites.md` §1 total V1 bloc 5.5j, borne P50 ±1σ net post-rake 6-max :

- **Micro (NL2–NL10)** : **7 bb/100** (fourchette **5 → 10**, `etudes.md` C20/C21/C10-C15)
- **Mid (NL25–NL50)** : **3.2 bb/100** (fourchette **1.5 → 5.5**)
- **High (NL100+)** : **0.8 bb/100** (fourchette **−0.5 → 2.5**, `probabilites.md` §2.2 — à 0.8, P(profit) ~60% à 50k même en V1 bloc)

`$/bb` par limite : NL2 $0.02, NL5 $0.05, NL10 $0.10, NL25 $0.25, NL50 $0.50, NL100 $1.00, NL200 $2.00.

### 7.2 Table synthétique — gain mensuel médian + fourchette et $/h

Gains arrondis à l'euro. Fourchette = gain à WR bas → WR haut du palier (micro 5→10, mid 1.5→5.5, high −0.5→2.5). `$/h` = gain médian / heures du régime.

| Limite | $/bb | WR médian (bb/100) | Gain 48k (80 h) médian [fourchette] — $/h | **Gain 86k reco (144 h) médian [fourchette] — $/h** | Gain 173k théorique (288 h) médian dégradé — $/h |
|--------|------|--------------------|--------------------------------------------|------------------------------------------------------|---------------------------------------------------|
| **NL2** | 0.02 | **7** [5→10] | 67 € [48→96] — 0.84 €/h | **120 € [86→172] — 0.84 €/h** | 173 € à WR 5 [173→346 à 5→10 non dégradé, 173=5×1730×0.02] — 0.60 €/h dégradé |
| **NL5** | 0.05 | **7** [5→10] | 168 € [120→240] — 2.10 €/h | **301 € [215→430] — 2.09 €/h** | 433 € à WR 5 [433→865 à 5→10 non dégradé] — 1.50 €/h dégradé |
| **NL10** | 0.10 | **7** [5→10] | 336 € [240→480] — 4.20 €/h | **602 € [430→860] — 4.18 €/h** | 865 € à WR 5 [865→1 730 à 5→10 non dégradé] — 3.00 €/h dégradé |
| **NL25** | 0.25 | **3.2** [1.5→5.5] | 384 € [180→660] — 4.80 €/h | **688 € [323→1 183] — 4.78 €/h** | 1 384 € à WR 3.2 [649→2 379] — 4.81 €/h (dégrade à 2.2 si tilt → 968 € — 3.36 €/h) |
| **NL50** | 0.50 | **3.2** [1.5→5.5] | 768 € [360→1 320] — 9.60 €/h | **1 376 € [645→2 365] — 9.56 €/h** | 2 768 € à WR 3.2 [1 298→4 758] — 9.61 €/h (tilt 2.2 → 1 935 € — 6.72 €/h) |
| **NL100** | 1.00 | **0.8** [−0.5→2.5] | 384 € [−240→1 200] — 4.80 €/h | **688 € [−430→2 150] — 4.78 €/h** | 1 384 € à WR 0.8 [−865→4 325] — 4.81 €/h (tilt 0.56 → 969 € — 3.36 €/h) |
| **NL200** | 2.00 | **0.8** [−0.5→2.5] | 768 € [−480→2 400] — 9.60 €/h | **1 376 € [−860→4 300] — 9.56 €/h** | 2 768 € à WR 0.8 [−1 730→8 650] — 9.61 €/h (tilt 0.56 → 1 937 € — 6.73 €/h) |

> Lecture : NL10 reco `7 × 860 × 0.10 = 602 €` ; NL50 reco `3.2 × 860 × 0.50 = 1 376 €`. La fourchette mid/high montre qu'en high le bas de fourchette est **négatif** même à 86k — cohérent avec `probabilites.md` §2.2bis (P(profit) 60% à 86k pour WR 0.8, σ~90 ; détail par régime §2.2bis, synthèse §2.2). Voir `probabilites.md` §2.2bis pour `P(profit)` à 48k/86k/173k et §6 pour `RoR` (40 BI cash, 100–200 BI MTT ; volumes exacts `86 400` à 600/h — `860×602€` arrondi `864×605€` à 1k mains près). Rake-aware (C20) et sizing `SizingConfig::default()` flop F33/50/100 turn T50/75/100 river R50/100/150 + préflop 2bb/3bb cap3 (`src/multiway.rs:29`, `strategie-par-format.md` §1–2) déjà inclus dans les WR médians ; hors V1 bloc (avant : HU+3-way half/pot sans rake) retirer ~1.0–1.5 bb/100 (`probabilites.md` §4).

### 7.3 Exemple détaillé — NL10

```
Reco  6h×6j (144 h, 86k mains) :  7  × 860 × 0.10 = 602 €  →  602/144 = 4.18 €/h
Loisir 4h×5j (80 h, 48k mains) :  7  × 480 × 0.10 = 336 €  →  336/80  = 4.20 €/h
Théo 12h×6j (288 h, 173k mains) :  5* × 1 730 × 0.10 = 865 €  →  865/288 = 3.00 €/h
                                          * WR dégradé 7→5 si tilt (probabilites.md §5 piège #1)
```

À volume horaire constant (600 mains/h), doubler les heures double presque le gain brut (336 € → 602 € de 80 h à 144 h, `$/h` stable ~4.20 €/h), mais pousser à 288 h **dégrade le $/h de 4.20 → 3.00 €/h** malgré 865 € bruts — le WR tilté annule ~30% du gain attendu (7×1 730×0.10 = 1 211 € sans tilt vs 865 € avec). En mid/high, même mécanisme : NL50 reco 9.56 €/h → 6.72 €/h si tilt −30%.

> Pour la probabilité d'être gagnant à ces volumes, voir `probabilites.md` §2.2bis : à WR 7, P(profit) ~89–98% à 48k–86k (σ~90) ; à WR 3.2, ~79% à 86k ; à WR 0.8, ~61% à 86k. Tables détaillées `probabilites.md` §2.2bis — non dupliquées ici (synthèse §2.2).

### 7.4 Encadré — Pourquoi 6h×6j est le sweet spot EV / tilt / €/h

> **6h×6j (144 h, ~86k mains) maximise le ratio EV/tilt/€/h.**
>
> - **EV** : à 86k mains, un WR micro de 7 bb/100 atteint déjà **96–98% P(profit)** (`probabilites.md` §2.2bis — synthèse §2.2) — au-delà, chaque bloc de 100 mains ajoute peu de certitude mais beaucoup de fatigue. En mid (3.2) on est à ~79% à 86k, encore loin du plateau ; en high (0.8) on reste ~61% — pousser le volume ne compense pas un WR trop faible.
> - **Tilt** : `probabilites.md` §5 piège #1 — WR +8 mais 20% sessions en tilt −30% EV ⇒ WR réel +5. À 12h×6j, la part de sessions en tilt explose (fatigue, `deviation_cap` relâché, exploit mal calibré puni −2 bb/100 en N>2 car pas de Nash unique — `probabilites.md` §5 piège #2, `deviation_cap 0.6×` serré en 3-way, `etudes.md` C01/C10). Le WR médian micro chute 7→5, soit −28% de €/h (4.20→3.00 €/h à NL10).
> - **€/h** : 4h×5j et 6h×6j ont le même €/h (~4.20 €/h à NL10, ~9.56 €/h à NL50) car WR constant ; 12h×6j fait chuter le €/h de ~30% malgré un brut supérieur. Le sweet spot est donc le plus gros volume **à WR constant** — soit 6h×6j. Au-delà, on échange du €/h contre du brut tilté.
> - **Règle pratique** : viser 144 h/mois (6h×6j, 4–6 tables, 600 mains/h) en 6-max micro (`ordre-conseille.md` rang 1) pour financer la BR (40 BI, `probabilites.md` §6) avant de monter de limite. Monter à NL25+ ne s'envisage qu'à WR mid stabilisé (≥3 bb/100 sur ≥100k mains) — sinon le gain/h high à 0.8 bb/100 reste inférieur au NL10 micro à 7 bb/100.
>
> Refs : `probabilites.md` §1 (WR totaux V1 bloc), §2.2bis (P(profit) 6-max σ~90 ; synthèse §2.2), §5 pièges #1 (tilt −30%) et #2 (`deviation_cap 0.6×` N>2), §6 (RoR 40 BI) ; `ordre-conseille.md` §1 rang 1 (600 mains/h, 6-max micro en premier) ; `etudes.md` C20 (rake-aware) C21 (`SizingConfig::default()` F33/50/100 T50/75/100 R50/100/150 + préflop 2bb/3bb cap3, `src/multiway.rs:29`) C23 (PKO) C24 (ICM/FGS) — le WR médian intègre déjà (d)+(e)+(f).
