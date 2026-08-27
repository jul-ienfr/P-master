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

## 2. P(profit) après N mains — cash 6-max (σ≈90 bb/100 mains)

`P = Φ(WR·√(N/100) / 90)` avec Φ = CDF N(0,1), WR en bb/100, σ≈90, N = mains, √(N/100) = √(nb blocks).

| WR (bb/100) | 10k mains | 50k mains | 100k mains | 200k mains |
|-------------|-----------|-----------|------------|------------|
| +2 | 59% | 69% | 76% | 84% |
| +5 | 71% | 88-89% | 96% | 99% |
| +8 | 81% | 96-98% | ~100% | ~100% |
| +12 | 91% | ~100% | 100% | 100% |

Lecture : V1 bloc à +7 bb/100 (médiane micro) ⇒ ~78% à 10k, **96-98% à 50k** d'être positif ; même solver à +3 bb/100 en high (médiane 0.8 mais borne haute 2.5 ⇒ +2 réaliste) ⇒ ~69% à 50k, 76% à 100k — le field écrase la proba plus que le solver. En micro, ton +5..+10 ⇒ 50k : fourchette **88-100%** (méd. 96-98%).

### HU (σ ~70 bb/100 mais WR plus dur à maintenir)

À σ=70, WR +5 → 89-100% à 50k ; WR +8 → 98-100% déjà à 10k — l'adaptation adversarial annule l'avantage variance.

| WR (bb/100) HU | 10k | 50k | 100k |
|----------------|-----|-----|------|
| +5 | 76% | 94% | 99% |
| +8 | 87% | 99% | ~100% |
| +12 | 96% | ~100% | 100% |

---

## 3. MTT — variance structure ICM/payout (σ≈1.9-2.6 buy-ins = 190-300% ROI)

Distribution log-normale/skew, pas comparable au cash. ROI 10-25% en micro MTT avec V1 bloc ⇒ P(profit) après 500 MTT ~65-75% seulement (variance payout). Modéliser en `ROI·√N / σROI` séparé.

| WR ROI (MTT micro) | 200 MTT | 500 MTT | 1000 MTT |
|---------------------|---------|---------|----------|
| +8%  | ~58% | ~65% | ~71% |
| +15% | ~64% | ~75% | ~85% |
| +25% | ~71% | ~85% | ~93% |

Exemple : ROI 15%, σ 2 buy-ins = 200%, N=500 → z = 0.15·√500/2 ≈ 1.68 → ~95% — mais seul vrai si pas de tilt de structure. En pratique micro MTT : viser 500+ tournois pour 75%+ P(profit) à ROI 15%.

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

## 6. Risque de ruine (RoR)

`RoR = exp(−2·edge·roll / variance)` (Kelly / formule gambler's ruin).

- edge = WR en bb/100, roll = bankroll en buy-ins (1 buy-in = 100bb), variance = σ² (σ≈90 cash, ~70 HU, 190-300 MTT).
- Exemple cash 6-max : WR +5, roll 40bi, σ=90 → RoR = exp(−2·5·40 / 90²) = exp(−400/8100) ≈ 95% survie — mais avec tilt/downswing réel, viser 40bi minimum.
- MTT : σ 2 buy-ins, ROI 15% (0.15 buy-in/tournoi), roll 100bi → RoR ≈ exp(−2·0.15·100 / 4) = exp(−7.5) ≈ 0.06% — mais skew log-normale rend la formule optimiste ; viser 100-200bi en MTT.

**Règle pratique** : 40bi cash 6-max, 60bi+ si tilt-prone, 100-200bi MTT. En dessous, même WR>0 n'empêche pas la ruine par variance.

---

## 7. Formule — pourquoi la correction

La forme naïve `P = Φ(WR·√N / 90)` avec N=mains donne Φ(WR·√N/90) qui sature à >99.9% dès 10k pour WR>2 — absurde (tout le monde serait gagnant à 10k). La forme correcte normalise par blocks de 100 mains : `P = Φ(WR·√(N/100) / 90) = Φ(WR·√N / 900)`. Vérification : WR +5, N=50k → √(500)=22.36, z=5·22.36/90=1.24 → Φ(1.24)=89% — cohérent avec les données empiriques Pluribus/Supremus.
