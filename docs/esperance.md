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
| `ev_bb_per_100` | WR normalisé /100 mains | `ev_bb_per_100 = ev_bb * 100 / N_hands` | Tables P(profit) `probabilites.md` §2, bench exploitabilité (mbb/g = 10× bb/100) |
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
- `probabilites.md` **§1** décomposition a-f du WR (`ev_bb_per_100`), **§1bis** additivité a+b+d+e+f ; **§2** `P(profit)` cash/MTT/HU, **§3** MTT σ 1.9-2.6, **§6** `RoR`.
- `strategie-par-format.md` **§4** matrice variantes×N (sizing/algo) — même découpage N que §4 ci-dessus.
