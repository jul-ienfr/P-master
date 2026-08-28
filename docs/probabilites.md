# Probabilités de gain — Modèle complet (cash / MTT / HU)

> Décomposition du edge, tables P(profit), pièges et risque de ruine.
> Sources : socle 27 études (C04–C11, C16, C20–C21) + modèle proba agent a88bdc7f §2–§5.
> Formule corrigée : `P = Φ(WR·√(N/100) / σ)` — la littérale `Φ(WR·√N/90)` saturait à >99.9% dès 10k pour WR>2.

---

## 1. Décomposition du edge (bb/100) — solver complet vs field

| Source | Cash 6-max (bb/100) | MTT (ROI%) | HU (bb/100) | Clé |
|--------|---------------------|------------|-------------|-----|
| (a) Proba pure (équité/combos) | +1.0 – +2.5 | +1 – +2% | +1.5 – +3.0 | MC 120-4000 samples ; −1 bb/100 si >2% equity err |
| (b) GTO baseline (inexploit) | +1.5 – +3.5 | +1.5 – +3% | +3.0 – +7.0 | Pluribus +3.2 vs élite 6-max ; Libratus +14.7 HU |
| (c) Exploit calibré (bayésien) | +2.0 – +6.0 micro / +0.5 – +2.5 mid / 0 – +1 high | +2 – +8% micro | +2 – +8 micro | `compute_mes_ev + deviation_cap` ; mal calibré → −2 — tueur #1 |
| (d) Rake-aware | +1.0 – +3.0 micro / +0.5 – +1.5 mid | +0.3 – +1% | +0.5 – +1.5 | `rake_rate/cap` ; rake=0 → −1.5 à −4 bb/100 en micro |
| (e) Sizing moderne 33/50/75/100/**150** | +0.8 – +2.0 | +0.5 – +1.5% | +0.8 – +2.5 | 50/100 → 33/50/75/150 = +0.9 ; 150 seul +0.2-0.5 |
| (f) Multiway 3..6 correct | +0.7 – +2.0 (3-way) / +1.2 – +3.0 (3..6) | +1 – +3% | 0 | ~28% mains 3-way en 6-max ; HU strat en 3-way = −2 à −5 sur ces spots |

**Total solver complet (V1 bloc 5.5j) — borne P50 ±1σ** : micro/faible +5 à +10 (méd. ~7), mid +1.5 à +5.5 (méd. ~3.2), high −0.5 à +2.5 (méd. ~0.8) net post-rake 6-max.
Vs GTO ~0. Avant V1 bloc (actuel : HU+3-way half/pot sans rake, 150 manquant, 4-6 fallback) : micro +4.0 à +8.5 (40-60% de (f) en 4-6 perdu, −0.2-0.5 sur (e)).

**Additivité** : a+b+d+e+f quasi-additifs ; (c) multiplicatif sur (b) mais non-additif avec (f) en N>2 (2 adversaires peuvent contre-exploiter — `deviation_cap` serré 0.6× en 3-way).

Références : Pluribus +32 mbb/g vs elite (Science 2019), Libratus +14.7 bb/100 HU, Supremus ~7-10 bb/100 6-max.

---

## 1bis. Espérance de gain par spot & par session

### 1bis.1 Définitions — EV du solver (unités chips)

**hero_ev (chips)** — champ `hero_ev` retourné par le solveur (`solver.rs`, `v2_api.rs`, `etudes.md` C11).

> `hero_ev_chips = E[payoff_chips | hero_strategy, opp_strategies] − starting_pot/2`

Convention : le pot initial (`starting_pot`, typiquement 1.5 bb = SB+BB) est soustrait à demi car partagé statistiquement à l'entrée du spot. Un `hero_ev = 0` signifie jeu à l'équilibre sur ce spot (on récupère sa part du pot mort) ; `>0` est le gain net au-delà.

**Action EV** — pour chaque action `a` dans l'arbre :

> `E[payoff | a] = Σ_h P(h)·payoff(h, a)` (espérance conditionnelle sachant qu'on joue `a`, adversaires suivent leur range C11 AIVAT)

Le solveur choisit `argmax_a E[payoff|a]` ; toute déviation bayésienne (`compute_mes_ev + deviation_cap`) n'est rentable que si elle augmente cette espérance estimée au-delà de l'erreur d'estimation (C11, C16).

**Pot-équité EV (approximation rapide sans arbre complet)** :

> `EV_chips ≈ equity × pot − cost_to_call`

où `equity` est la part d'équité réalisée (MC 120–4000 samples, C04), `pot` le pot courant, `cost_to_call` le montant à payer. Erreur >2% sur l'équité → −1 bb/100 (cf. §1 ligne a).

**Rake-aware share** (C20) — le payoff réel n'est pas `pot/winners` mais :

> `share = (pot − min(pot × rake_rate, cap)) / winners.len()`

`rake_rate` typique 5%, `cap` $3–4 (≈ 3–4 bb selon limite). Omettre ce terme = −1.5 à −4 bb/100 en micro. Le même `rake_rate/cap` s'applique de HU (`solver.rs` DCFR) à MCCFR N-way 3..6 (`multiway.rs:payoffs()`).

### 1bis.2 PKO / ICM — $EV (C23, C24)

**ChipEV vs $EV** — en MTT/PKO, l'EV en chips ne vaut pas l'EV en dollars :

> `$EV = ChipEV + BountyEV` (C23 PKO Bounty Power)

- **PKO** : early stage bounty ≈ 25–33% d'un buy-in, table finale 2–4× un buy-in ; couvrir l'adversaire (cover) élargit la range de +10–20% (on paye plus large quand on peut éliminer).
- **ICM** : payout non-linéaire → stratégie **15–25% tighter** que chipEV (C24 ICMIZER/HRC) ; l'approximation **FGS 2–3 steps** (Future Game Simulation) corrige le chipEV myope. Confondre chipEV et $EV = −1 à −3% ROI.

En pratique V1 : le solveur cash optimise `hero_ev` en chips (ChipEV) ; le module MTT/PKO (V1.2–V2) convertit via BountyEV + ICM FGS avant de choisir l'action.

### 1bis.3 Table des unités — lire et convertir l'EV

| Unité | Notation | Définition | Conversion | Usage |
|-------|----------|------------|------------|-------|
| **ev_chips** | `ev_chips` / `hero_ev` | Chips nets au-delà de `starting_pot/2` sur le spot | `ev_chips / 100 = ev_bb` si 1 bb = 1 chip | Sortie brute du solveur |
| **ev_bb** | `ev_bb` | Big blinds gagnées sur le spot | `ev_bb × 100 = ev_bb_per_100` sur 100 mains | Comparaison inter-limites |
| **ev_bb_per_100** | `ev_bb/100` / `WR` | Winrate standard cash | `ev_bb/100 × bb_value = ev_dollars/100` | Benchmark Pluribus/Libratus |
| **ev_dollars** | `ev_$` | Dollars nets (après rake) | `ev_bb × bb_$` | BR et RoR cash |
| **$ev** | `$EV` | Dollars tournoi (ICM/bounty inclus, C23–C24) | Non-convertible linéairement en chips | Décision MTT/PKO |
| **equity** | `equity` | Part du pot à l'abattage (0–1) | `equity × pot − cost = EV_chips` (approx) | Approximation rapide |

Exemple : pot 10 bb, hero equity 55%, cost 3 bb → `EV ≈ 0.55×10 − 3 = 2.5 bb` brut ; moins rake `min(10×5%, 4)=0.5` → `share 9.5/winners` → EV net ~2.2 bb.

### 1bis.4 Pont vers le winrate de session — P(profit) et risque de ruine

Ces EV par spot s'agrègent en **WR** (bb/100 en cash, ROI en MTT) qui détermine la probabilité d'être gagnant sur une session de `N` mains/tournois et le risque de ruine. Formules détaillées aux §2–§3 et §6 :

- **P(profit)** : `P = Φ(WR·√(N/100) / σ)` (cash, §2–§3) — `Φ` = CDF N(0,1), `σ` par variante (HU ~70, 6-max ~90, MTT 1.9–2.6 BI).
- **RoR** : `RoR = exp(−2·edge·roll / variance)` (§6) — `edge` = WR (ou ROI), `roll` = bankroll en buy-ins, `variance` = σ².

Un edge de +7 bb/100 (§1 total micro) ne signifie pas "gagnant chaque session" : à 10k mains P≈78%, à 50k P≈96% — voir tables §2–§3. Les fiches EV ci-dessus sont sourcées C03 (sizing/translation), C11 (AIVAT/EV sans biais), C20 (rake), C23 (bounty), C24 (ICM FGS).

---

## 2. P(profit) après N mains — cash par variante × N

`P = Φ(WR·√(N/100) / σ)` avec Φ = CDF N(0,1), WR en bb/100, σ = écart-type en bb/100 mains, N = mains, `√(N/100)` = √(nb blocks de 100 mains).

### 2.1 Cash HU — N=2, σ≈70 bb/100

_Réf. variance HU : Libratus/DeepStack HU σ ~70 (C07) — plus faible qu'en 6-max (moins de multiway) mais WR plus dur à maintenir face à un adversaire unique qui s'adapte._

| Variante | N | WR (bb/100) | σ | 10k mains | 50k mains | 100k mains |
|----------|---|-------------|---|-----------|-----------|------------|
| **HU** | **2** | +2 | 70 | 61% | 74% | 82% |
| **HU** | **2** | **+5** | 70 | **76%** | **94%** | **99%** |
| **HU** | **2** | +8 | 70 | 87% | 99% | ~100% |
| **HU** | **2** | +12 | 70 | 96% | ~100% | 100% |
| **HU** | **2** | +10 (méd. micro) | 70 | 92% | 99.8% | ~100% |

Lecture HU : à WR +5 (réaliste post-adaptation), 10k mains ne donnent que 76% de chance d'être positif — l'adaptation adversarial annule l'avantage de variance plus faible. À WR +8–10 (micro vs field faible), 50k suffisent pour >99% P(profit), mais ce WR est difficile à maintenir contre un régulier.

### 2.2 Cash 6-max — N=3..6, σ≈90 bb/100

_Réf. variance 6-max : Pluribus/Supremus 6-max σ ~90 (C10, C15) — plus élevée (multiway, rake, variance de distribution). Chaque ligne N=3,4,5,6 partage le même σ≈90 en première approximation (la variance inter-N est dominée par le rake/sizing, pas par N lui-même) ; le WR attendu varie avec N via la contribution multiway (f) du §1. Formule `P=Φ(WR·√(N/100)/σ)` (§7)._

| Variante | N | WR (bb/100) | σ | 10k mains | 48k (4h×5j) | 50k mains | 86k (6h×6j reco) | 100k mains | 173k (12h×6j) | Note WR |
|----------|---|-------------|---|-----------|-------------|-----------|------------------|------------|---------------|---------|
| **6-max** | **3** | +2 | 90 | 59% | 69% | 69% | 74% | 76% | 82% | Borne basse (solver incomplet) |
| **6-max** | **3** | +5 | 90 | 71% | 89% | 89% | 95% | 96% | 99% | Micro avant V1 (partiel 3-way) |
| **6-max** | **3** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **96%** | **99%** | **99%** | **~100%** | **V1 bloc 3-way correct** |
| **6-max** | **3** | +8 | 90 | 81% | 97% | 98% | ~100% | ~100% | ~100% | Micro haut V1 |
| **6-max** | **4** | +5 | 90 | 71% | 89% | 89% | 95% | 96% | 99% | 4-way avant V1 (fallback HU = −2..−5 sur ces spots) |
| **6-max** | **4** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **96%** | **99%** | **99%** | **~100%** | **V1 bloc 3..6 (SizingConfig+rake)** |
| **6-max** | **4** | +8 | 90 | 81% | 97% | 98% | ~100% | ~100% | ~100% | Micro haut |
| **6-max** | **5** | +5 | 90 | 71% | 89% | 89% | 95% | 96% | 99% | 5-way avant V1 : 40–60% de (f) perdu |
| **6-max** | **5** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **96%** | **99%** | **99%** | **~100%** | **V1 bloc complet** |
| **6-max** | **5** | +3.2 (méd. mid) | 90 | 64% | 78% | 79% | 85% | 87% | 93% | Mid-stakes micro→mid transition |
| **6-max** | **6** | +5 | 90 | 71% | 89% | 89% | 95% | 96% | 99% | 6-way max (rare ~2% des mains) |
| **6-max** | **6** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **96%** | **99%** | **99%** | **~100%** | **V1 bloc MAX 6** |
| **6-max** | **6** | +0.8 (méd. high) | 90 | 54% | 58% | 58% | 60% | 61% | 64% | High-stakes : field écrase l'edge |
| **6-max** | **6** | +3.2 (méd. mid) | 90 | 64% | 78% | 79% | 85% | 87% | 93% | Mid P50 |

Lecture 6-max : V1 bloc à +7 bb/100 (médiane micro, tous N=3..6) ⇒ ~78% à 10k, **96% à 50k**, 99% à 100k d'être positif. Même solver à +3.2 bb/100 en mid (médiane) ⇒ 79% à 50k, 87% à 100k — le field écrase la proba plus que le solver. En high (méd. 0.8) ⇒ 60% à 50k — quasi pile ou face même à 50k. En micro, fourchette +5..+10 ⇒ 50k : **89–99.9%** (méd. 96%).

> **Lecture régimes** — `48k = 4h×5j`, `86k = 6h×6j reco` (86 400 à 600/h, arrondi 860 blocs — 864→605€ à 1k près), `173k = 12h×6j` à 600 mains/h (cf. `esperance.md` §7) :
> - **WR 7 médian micro** : P passe **96% à 48k → 99% à 86k → ~100% à 173k** (95.6% / 98.9% / 99.9% bruts, `Φ(WR·√(N/100)/90)` §7). Le seuil « significatif » 95%+ est franchi dès 4h×5j ; 6h×6j sécurise 99%.
> - **WR 5 bas micro** : **89% à 48k → 95% à 86k → 99% à 173k** (88.8% / 94.8% / 99.0%). Il faut 86k pour dépasser 95% et 173k pour frôler 99% — le bas de fourchette micro reste sensible au volume.
> - **WR 3.2 mid** : **78% à 48k → 85% à 86k → 93% à 173k** (≈ 79% à 50k, 87% à 100k). Même à 173k, ~1 session sur 14 reste perdante — le field mid écrase l'edge.
> - **WR 0.8 high** : **58% à 48k → 60% à 86k → 64% à 173k** — quasi pile ou face même à 173k (z≈0.37). En high, le volume ne compense pas l'absence d'edge.

> **Au-delà de 8h/j** : WR dégrade **7 → 5 par tilt (−30% §5 piège #1)** → P redescend (à 173k : ~100% → 99%) et **€/h chute** (4.18 → 3.00 €/h à NL10), voir `esperance.md` §7 et `ordre-conseille.md` §1. Le régime 12h×6j est théorique — en pratique le tilt annule la moitié du gain de volume.

### 2.2bis Régimes de volume — P(profit) à 48k / 86k / 173k mains

> Même formule `P = Φ(WR·√(N/100)/σ)` (σ=90) appliquée aux 3 régimes canoniques de `esperance.md` §7 / `ordre-conseille.md` §1 : **48k = 4h×5j (80h)**, **86k = 6h×6j (144h, recommandé — 86 400 à 600/h, arrondi 860 blocs / 864→605€ à 1k près)**, **173k = 12h×6j (288h, théorique)**. Débit médian 600 mains/h 6-max 4-6 tables.

| N | WR (bb/100) | 10k | 50k | 100k | **48k (4h×5j)** | **86k (6h×6j)** | **173k (12h×6j) th.** | Note |
|---|-------------|-----|-----|------|-----------------|-----------------|----------------------|------|
| **3..6** | **+7 méd. micro V1** | 78% | 96% | 99% | **95.6%** | **98.9%** | **99.9% th.** | Médiane V1 bloc |
| 3..6 | +5 bas micro | 71% | 89% | 96% | 88.8% | 94.8% | 99.0% | Avant V1 / tilt WR 7→5 |
| 3..6 | +8 haut micro | 81% | 98% | ~100% | 97.4% | 99.5% | ~100% | Field très faible |
| 3..6 | +3.2 méd. mid | 64% | 79% | 87% | 78.2% | 85.1% | 93.0% | NL25-NL50 |
| 3..6 | +0.8 méd. high | 54% | 60% | 63% | 57.7% | 60.3% | 64.4% | NL100+ quasi pile/face |

> **Lecture régimes** :
> - **Micro WR 7 (méd.)** : P passe **95.6% à 48k → 98.9% à 86k → 99.9% th. à 173k** — le palier 50k (~17j à 6h×5j) suffit déjà à 96%.
> - **Micro WR 5 (bas / tilt)** : 88.8% → 94.8% → 99.0% — même en bas de fourchette, 86k franchit 95%.
> - **Mid WR 3.2** : 78% → 85% → 93% — il faut 173k pour dépasser 90%.
> - **High WR 0.8** : 58% → 60% → 64% — quasi pile ou face même à 173k (`RoR >4%` §6).
>
> **Au-delà de 8h/j, WR 7→5 par tilt −30% (§5 piège #1) → P redescend** : à 173k th. 99.9% mais réel 99.0% si tilt, et **€/h 4.20→3.00 (−28%)** (`esperance.md` §7). D'où la reco **6h×6j** (`ordre-conseille.md` §1).

---

## 3. MTT — variance structure ICM/payout par variante × N (7..9)

Distribution log-normale/skew, pas comparable au cash. ROI 10–25% en micro MTT avec V1 bloc ⇒ P(profit) après 500 MTT ~75–94% selon σ. Modéliser en `ROI·√N / σROI` séparé, avec σROI en buy-ins (σ≈1.9–2.6 BI = 190–300% ROI).

`P = Φ(ROI·√N / σROI)` avec ROI en buy-ins/tournoi (ex. 15% = 0.15), σROI en BI, N = nombre de MTT.

| Variante | N | ROI attendu | σ (BI) | 200 MTT | 500 MTT | 1000 MTT |
|----------|---|-------------|--------|---------|---------|----------|
| **MTT** | **7** | 8% | 1.9 | 72% | 83% | 91% |
| **MTT** | **7** | **15%** | **1.9** | **87%** | **96%** | **99%** |
| **MTT** | **7** | 25% | 1.9 | 97% | 99.8% | ~100% |
| **MTT** | **7** | 15% | 2.2 | 83% | 94% | 98% |
| **MTT** | **7** | 15% | 2.6 | 79% | 90% | 97% |
| **MTT** | **8** | 8% | 2.2 | 70% | 79% | 87% |
| **MTT** | **8** | **15%** | **2.2** | **83%** | **94%** | **98%** |
| **MTT** | **8** | 25% | 2.2 | 95% | 99.4% | ~100% |
| **MTT** | **8** | 8% | 1.9 | 72% | 83% | 91% |
| **MTT** | **8** | 15% | 2.6 | 79% | 90% | 97% |
| **MTT** | **9** | 8% | 2.6 | 67% | 75% | 83% |
| **MTT** | **9** | **15%** | **2.6** | **79%** | **90%** | **97%** |
| **MTT** | **9** | 25% | 2.6 | 91% | 98% | 99.9% |
| **MTT** | **9** | 15% | 1.9 | 87% | 96% | 99% |
| **MTT** | **9** | 8% | 2.2 | 70% | 79% | 87% |

> **Comment lire** : chaque ligne Variante×N correspond à un palier de table finale / structure. σ=1.9 (tight, deepstack, faible payout skew) → 2.2 (field moyen) → 2.6 (turbo/hyper, payout très skew, ICM fort). À ROI 15% et N=500, P(profit) varie de 96% (σ 1.9) à 90% (σ 2.6) — le format (turbo vs deep) compte autant que le ROI.

Exemple détaillé : ROI 15%, σ 2.0 BI, N=500 → z = 0.15·√500/2.0 ≈ 1.68 → Φ(1.68) ~95% — mais seul vrai si pas de tilt de structure. En pratique micro MTT : viser **500+ tournois** pour 90%+ P(profit) à ROI 15% (σ 2.2), **1000+** si turbo (σ 2.6).

_Réf. σ MTT 1.9–2.6 : ordre de grandeur des trackers MTT (ICMIZER C24, SharkScope) — σ croît avec la vitesse (turbo > deep) et la profondeur de field._

---

## 4. Avant V1 vs V1 bloc — delta P(profit) (cash 6-max micro, 50k mains)

|  | WR micro | P(profit) 50k |
|--|----------|---------------|
| **Avant V1** (HU+3-way half/pot sans rake, 150 manquant, 4-6 fallback) | +4.0 à +8.5 | 78-93% |
| **V1 bloc** (+5 à +10, méd. 7, multiway 3..6 + rake + 150 + SizingConfig) | +5 à +10 (méd. 7) | **88-100%** (méd. 96-98%) |
| **Delta** | +1.0 à +1.5 | **+10-18 pts** |

En high (avant V1 −0.5..+1.8 → ~58-65%, V1 −0.5..+2.5 méd. 0.8 → +2 haut ⇒ 69-76%) : gain existe mais ne supprime pas la variance — le field high est trop fort pour que le solver seul suffise.

---

## 5. Cinq pièges qui cassent la proba (même avec solver parfait)

1. **Tilt / bankroll <40 buy-ins** — WR +8 mais 20% sessions en tilt −30% EV ⇒ WR réel +5. Le tilt est le tueur #1 en micro, pas la stratégie.
2. **N>2 : pas de Nash unique** — solver converge vers *un* équilibre, pas *le* ; exploitable si adversaires coordonnés (c vs f non-additif, `deviation_cap 0.6×` serré en 3-way).
3. **Rake mal calibré** — 1 bb/100 d'erreur si cap ignoré ; en micro rake=0 → −1.5..−4 bb/100. Toujours `rake_rate/cap` identique HU→MCCFR.
4. **Sizing figée** — rester half/pot = −1.5..−3 bb/100 (Ganzfried C03) ; vision `table_id` probe 10-15% mains mal attribuées (audit P0-P5 `oracle_randomized + spot_id`).
5. **Préflop overfit** — MCCFR préflop sans abstraction = variance ; besoin cap 3 raises + 2 tailles (2bb/3bb) + bench + `success_rate>50%` dealing.

---

## 6. Risque de ruine (RoR) par variante × N

`RoR = exp(−2·edge·roll / variance)` (Kelly / formule gambler's ruin) — **unités cohérentes obligatoires** : `edge` et `roll` en **buy-ins**, `variance` en **BI² par 100 mains** (cash) ou **BI² par tournoi** (MTT).

- Cash : `edge_BI = WR/100` (ex. WR 7 bb/100 → 0.07 BI/100 mains, 1 BI = 100 bb), `var_BI = (σ/100)²` (ex. σ 90 bb/100 → var 0.81 BI²/100 mains), `roll` en BI. Alors `RoR = exp(−2·(WR/100)·roll / (σ/100)²)`. La version antérieure utilisait `WR` en bb/100 et `σ²` en bb² avec `roll` en BI sans conversion (dimensionnellement fausse → RoR ~93% au lieu de ~0.1%).
- MTT : `edge` = ROI en BI/tournoi (ex. 15% = 0.15), `roll` en BI, `variance` = σ² en BI² (déjà cohérent).
- `RoR` = proba de ruine (perte totale du roll) ; `1−RoR` = proba de survie. Viser RoR <1% (MTT) à <5% (cash).
- **Lecture** : la formule suppose marche aléatoire infinie sans tilt/biais ; en pratique le tilt et les downswings réels aggravent le RoR d'un facteur 2–5× si BR < seuil. **Errata** : les tables cash antérieures affichaient ~93% à 40 BI pour WR 7 par erreur d'unités ; valeur corrigée ~0.1% (voir ci-dessous).

### 6.1 Cash HU — N=2, σ≈70 → σ_BI 0.70, var_BI 0.49

| Variante | N | WR (bb/100) | σ | Roll 20 BI | Roll 40 BI | Roll 100 BI |
|----------|---|-------------|---|------------|------------|-------------|
| **HU** | **2** | +5 (réaliste) | 70 | RoR 1.69% · survie 98.3% | 0.029% · survie ~100% | ~0% · ~100% |
| **HU** | **2** | **+10 (méd. micro)** | 70 | **0.029% · ~100%** | **~0% · ~100%** | **~0% · ~100%** |
| **HU** | **2** | +12 (élite) | 70 | 0.0056% · ~100% | ~0% · ~100% | ~0% · ~100% |
| **HU** | **2** | +8 | 70 | 0.15% · 99.85% | ~0% · ~100% | ~0% · ~100% |

> HU : à WR ≥5 et 40 BI, le RoR théorique pur est <0.1% — l'unité BI compte. Le seuil **40 BI reste recommandé** car la variance d'adaptation (adversaire unique, `deviation_cap`) et le tilt (§5 piège #1) dominent le risque réel, non la formule idéale.

### 6.2 Cash 6-max — N=3..6, σ≈90 → σ_BI 0.90, var_BI 0.81

| Variante | N | WR (bb/100) | σ | Roll 20 BI | Roll 40 BI | Roll 100 BI |
|----------|---|-------------|---|------------|------------|-------------|
| **6-max** | **3** | **+7 (méd. micro V1)** | 90 | **3.16% · 96.8%** | **0.10% · 99.90%** | **~0% · ~100%** |
| **6-max** | **3** | +5 | 90 | 8.49% · 91.5% | 0.72% · 99.28% | ~0% · ~100% |
| **6-max** | **4** | **+7 (méd. micro V1)** | 90 | **3.16% · 96.8%** | **0.10% · 99.90%** | **~0% · ~100%** |
| **6-max** | **4** | +3.2 (méd. mid) | 90 | 20.6% · 79.4% | 4.24% · 95.8% | 0.037% · 99.96% |
| **6-max** | **5** | **+7 (méd. micro V1)** | 90 | **3.16% · 96.8%** | **0.10% · 99.90%** | **~0% · ~100%** |
| **6-max** | **5** | +5 | 90 | 8.49% · 91.5% | 0.72% · 99.28% | ~0% · ~100% |
| **6-max** | **6** | **+7 (méd. micro V1)** | 90 | **3.16% · 96.8%** | **0.10% · 99.90%** | **~0% · ~100%** |
| **6-max** | **6** | +3.2 (méd. mid) | 90 | 20.6% · 79.4% | 4.24% · 95.8% | 0.037% · 99.96% |
| **6-max** | **6** | +0.8 (méd. high) | 90 | 67.4% · 32.6% | 45.4% · 54.6% | 13.9% · 86.1% |

> 6-max : même lecture pour tous les N=3..6 (σ_BI 0.90 commun). En micro V1 à WR 7, **40 BI → RoR ~0.1%** (survie 99.90%) — d'où la règle **40 BI minimum cash** (60 BI si tilt-prone) validée empiriquement Pluribus/Supremus + downswing réel (§5 piège #1). En mid WR 3.2, 40 BI → 4.2% (encore >1%) — monter à 60-80 BI recommandé. En high WR 0.8, même 100 BI → 13.9% — le field écrase l'edge, le volume ne compense pas.

### 6.3 MTT — N=7..9, σ 1.9–2.6 BI (var=3.6–6.8)

| Variante | N | ROI | σ (BI) | Roll 50 BI | Roll 100 BI | Roll 200 BI |
|----------|---|-----|--------|------------|-------------|-------------|
| **MTT** | **7** | 15% | **1.9** | 1.57% · survie 98.4% | 0.02% · 99.98% | ~0% · ~100% |
| **MTT** | **7** | 8% | 1.9 | 10.9% · 89.1% | 1.19% · 98.8% | 0.01% · 99.99% |
| **MTT** | **7** | 25% | 1.9 | 0.10% · 99.90% | ~0% · ~100% | ~0% · ~100% |
| **MTT** | **8** | **15%** | **2.2** | **4.51% · 95.5%** | **0.20% · 99.80%** | **~0% · ~100%** |
| **MTT** | **8** | 8% | 2.2 | 19.1% · 80.9% | 3.67% · 96.3% | 0.13% · 99.87% |
| **MTT** | **8** | 25% | 2.2 | 0.57% · 99.43% | ~0% · ~100% | ~0% · ~100% |
| **MTT** | **9** | **15%** | **2.6** | **10.9% · 89.1%** | **1.18% · 98.8%** | **0.01% · 99.99%** |
| **MTT** | **9** | 8% | 2.6 | 30.6% · 69.4% | 9.38% · 90.6% | 0.88% · 99.12% |
| **MTT** | **9** | 25% | 2.6 | 2.48% · 97.5% | 0.06% · 99.94% | ~0% · ~100% |

> MTT : RoR directement interprétable (edge et roll en même unité BI). À ROI 15% et σ 2.2 (field moyen N=8), **100 BI → RoR 0.20%** (survie 99.80%) — mais la formule sous-estime le RoR réel (skew log-normale, bubbling). D'où la règle **100–200 BI en MTT** (et 200 BI+ en turbo N=9, σ 2.6).

**Règle pratique** : 40 BI cash 6-max (60 BI+ si tilt-prone), 100–200 BI MTT. En dessous, même WR>0 n'empêche pas la ruine par variance — et les tables ci-dessus montrent que chaque variante×N a son seuil (HU plus exigeant en WR, MTT turbo N=9 plus exigeant en roll).

---

## 7. Formule — pourquoi la correction

La forme naïve `P = Φ(WR·√N / 90)` avec N=mains donne Φ(WR·√N/90) qui sature à >99.9% dès 10k pour WR>2 — absurde (tout le monde serait gagnant à 10k). La forme correcte normalise par blocks de 100 mains : `P = Φ(WR·√(N/100) / 90) = Φ(WR·√N / 900)`. Vérification : WR +5, N=50k → √(500)=22.36, z=5·22.36/90=1.24 → Φ(1.24)=89% — cohérent avec les données empiriques Pluribus/Supremus.
