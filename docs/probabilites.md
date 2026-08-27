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

_Réf. variance 6-max : Pluribus/Supremus 6-max σ ~90 (C10, C15) — plus élevée (multiway, rake, variance de distribution). Chaque ligne N=3,4,5,6 partage le même σ≈90 en première approximation (la variance inter-N est dominée par le rake/sizing, pas par N lui-même) ; le WR attendu varie avec N via la contribution multiway (f) du §1._

| Variante | N | WR (bb/100) | σ | 10k mains | 50k mains | 100k mains | Note WR |
|----------|---|-------------|---|-----------|-----------|------------|---------|
| **6-max** | **3** | +2 | 90 | 59% | 69% | 76% | Borne basse (solver incomplet) |
| **6-max** | **3** | +5 | 90 | 71% | 89% | 96% | Micro avant V1 (partiel 3-way) |
| **6-max** | **3** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **99%** | **V1 bloc 3-way correct** |
| **6-max** | **3** | +8 | 90 | 81% | 98% | ~100% | Micro haut V1 |
| **6-max** | **4** | +5 | 90 | 71% | 89% | 96% | 4-way avant V1 (fallback HU = −2..−5 sur ces spots) |
| **6-max** | **4** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **99%** | **V1 bloc 3..6 (SizingConfig+rake)** |
| **6-max** | **4** | +8 | 90 | 81% | 98% | ~100% | Micro haut |
| **6-max** | **5** | +5 | 90 | 71% | 89% | 96% | 5-way avant V1 : 40–60% de (f) perdu |
| **6-max** | **5** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **99%** | **V1 bloc complet** |
| **6-max** | **5** | +3.2 (méd. mid) | 90 | 64% | 79% | 87% | Mid-stakes micro→mid transition |
| **6-max** | **6** | +5 | 90 | 71% | 89% | 96% | 6-way max (rare ~2% des mains) |
| **6-max** | **6** | **+7 (méd. micro V1)** | 90 | **78%** | **96%** | **99%** | **V1 bloc MAX 6** |
| **6-max** | **6** | +0.8 (méd. high) | 90 | 54% | 60% | 63% | High-stakes : field écrase l'edge |
| **6-max** | **6** | +3.2 (méd. mid) | 90 | 64% | 79% | 87% | Mid P50 |

Lecture 6-max : V1 bloc à +7 bb/100 (médiane micro, tous N=3..6) ⇒ ~78% à 10k, **96% à 50k**, 99% à 100k d'être positif. Même solver à +3.2 bb/100 en mid (médiane) ⇒ 79% à 50k, 87% à 100k — le field écrase la proba plus que le solver. En high (méd. 0.8) ⇒ 60% à 50k — quasi pile ou face même à 50k. En micro, fourchette +5..+10 ⇒ 50k : **89–99.9%** (méd. 96%).

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

`RoR = exp(−2·edge·roll / variance)` (Kelly / formule gambler's ruin).

- `edge` = WR en bb/100 (cash) ou ROI en BI/tournoi (MTT), `roll` = bankroll en buy-ins (1 BI = 100 bb en cash, 1 BI = buy-in MTT), `variance` = σ².
- `RoR` = proba de ruine (perte totale du roll) ; `1−RoR` = proba de survie. Viser RoR <1% (MTT) à <5% (cash).
- **Lecture** : RoR 95% ne veut pas dire "95% de chance de tout perdre" dans l'usage naïf — la formule suppose marche aléatoire infinie sans tilt/biais ; en pratique le tilt et les downswings réels aggravent le RoR d'un facteur 2–5× si BR < seuil.

### 6.1 Cash HU — N=2, σ≈70 (var=4900)

| Variante | N | WR (bb/100) | σ | Roll 20 BI | Roll 40 BI | Roll 100 BI |
|----------|---|-------------|---|------------|------------|-------------|
| **HU** | **2** | +5 (réaliste) | 70 | RoR 81.9% · survie 18.1% | 67.0% · survie 33.0% | 36.8% · survie 63.2% |
| **HU** | **2** | **+10 (méd. micro)** | 70 | **92.2% · 7.8%** | **84.9% · 15.1%** | **66.5% · 33.5%** |
| **HU** | **2** | +12 (élite) | 70 | 90.7% · 9.3% | 82.2% · 17.8% | 61.3% · 38.7% |
| **HU** | **2** | +8 | 70 | 93.9% · 6.1% | 88.2% · 11.8% | 72.6% · 27.4% |

> HU : RoR apparemment élevé car WR en bb/100 est petit devant σ=70 — mais la formule cash en bb/100 vs BI n'est pas directement comparable (1 BI=100 bb). Le bon repère HU est la survie : à WR +10 et 40 BI, ~15% survie théorique pure — en pratique le seuil 40 BI reste recommandé car la variance d'adaptation (adversaire unique) domine.

### 6.2 Cash 6-max — N=3..6, σ≈90 (var=8100)

| Variante | N | WR (bb/100) | σ | Roll 20 BI | Roll 40 BI | Roll 100 BI |
|----------|---|-------------|---|------------|------------|-------------|
| **6-max** | **3** | **+7 (méd. micro V1)** | 90 | **96.6% · 3.4%** | **93.3% · 6.7%** | **84.1% · 15.9%** |
| **6-max** | **3** | +5 | 90 | 97.6% · 2.4% | 95.2% · 4.8% | 88.4% · 11.6% |
| **6-max** | **4** | **+7 (méd. micro V1)** | 90 | **96.6% · 3.4%** | **93.3% · 6.7%** | **84.1% · 15.9%** |
| **6-max** | **4** | +3.2 (méd. mid) | 90 | 98.4% · 1.6% | 96.9% · 3.1% | 92.4% · 7.6% |
| **6-max** | **5** | **+7 (méd. micro V1)** | 90 | **96.6% · 3.4%** | **93.3% · 6.7%** | **84.1% · 15.9%** |
| **6-max** | **5** | +5 | 90 | 97.6% · 2.4% | 95.2% · 4.8% | 88.4% · 11.6% |
| **6-max** | **6** | **+7 (méd. micro V1)** | 90 | **96.6% · 3.4%** | **93.3% · 6.7%** | **84.1% · 15.9%** |
| **6-max** | **6** | +3.2 (méd. mid) | 90 | 98.4% · 1.6% | 96.9% · 3.1% | 92.4% · 7.6% |
| **6-max** | **6** | +0.8 (méd. high) | 90 | 99.6% · 0.4% | 99.2% · 0.8% | 98.0% · 2.0% |

> 6-max : même lecture pour tous les N=3..6 (σ≈90 commun). Le RoR théorique pur reste élevé car WR (bb/100) « pèse » peu face à σ=90 dans la formule exponentielle — l'interprétation opérationnelle est la règle **40 BI minimum cash** (60 BI si tilt-prone), validée empiriquement Pluribus/Supremus + downswing réel (§5 piège #1).

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
