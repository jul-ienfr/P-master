# Stratégie par format — Matrice variantes × N × streets/sizing/rake/ICM

> Synthèse opérationnelle tirée du socle 27 études (voir `etudes.md` C01–C27).
> Chaque table donne la reco GTO, la déviation exploit, et le chantier qui l'implémente.

---

## 1. Par nombre de joueurs (N)

| N | Algo recommandé | Sizing | Cap raises | Iters (temps fixe) | WR attendu | Exploitabilité | Note |
|---|-----------------|--------|------------|--------------------|------------|----------------|------|
| **HU (2)** | **HS-PCFR(30)** `γ(t)=30−5t/1000` drop-in (C16), sinon DCFR `γ=3.0` (`solver.rs` actuel, C09) | `BetSize` générique `33/50/75/100 + /x/c/e/a` (`bet_size.rs`) | 3–4 | `base` (`time_budget_ms 1000`) | +8..+15 bb/100 vs field, +14.7 vs élite (Libratus C07) | DCFR <0.05 exploit (Cepheus C05 ref), HS 2–3 ordres mieux | `solver.rs` intact V1 |
| **3-way** | **MCCFR external sampling** (Pluribus C10, Lanctot 2009) | flop 33/50/100, turn 50/75/100, river 50/100/150 overbet | 2 | `base×3/n` clamp 1200..15000 | +1.2..+3 bb/100 contribution multiway (~28% mains 6-max sont 3-way) | Fallback HU strat en 3-way = −2 à −5 sur ces spots | `deviation_cap 0.6×` serré (N>2 pas de Nash unique, C01) |
| **6-max (3..6)** | Même MCCFR N-param (`[T;MAX]+n`, `FxHashMap` complet, `sampling deal →Result`) + `SizingConfig` + rake + `hero_position_to_index` | Idem 3-way | 2 postflop / 3 préflop | Idem `base×3/n` | +5..+10 micro méd ~7 (6-max complet, Annexe B) | Bench N=3 vs N=6 scalés écart <15% sinon scaling B | Kill-switch `config.multiway_max_players` |
| **9-max / MTT (7..9)** | **V1 : approx** `range tightening + equity bucket` si MCCFR 6-max exact >1000ms (cible acceptée AUDIT P3) → **V1.2** `MAX 6→9` + `DonkSizeOptions` → **V2** `GT-CFR unifié` (SoG C14) | Idem + donk 33-50% flop OOP en V1.2 | 1 si N≥7 désactivé (+12-18% seulement) → 2 | `base×3/n` | ROI 10-25% MTT micro avec bloc V1 | Collision 35% à 9-way sans shuffle pondéré | Shuffle `AliasTable` si 9×AA starve >50% |

**Règle d'or N>2** : pas de Nash unique → solver converge vers *un* équilibre exploitable si adversaires coordonnés ; calibrer `compute_mes_ev + deviation_cap` serré `0.6×` en 3-way, plus serré dès 4-way.

---

## 2. Par élément de jeu & par street

| Élément | Rue | Reco GTO (sizing / fréquence) | Déviation exploit | WR contrib. | Piège |
|---------|-----|-------------------------------|-------------------|-------------|-------|
| **Préflop** | — | RFI 15-25% (UTG 15, BTN 40-50 — tighten −2-5% avec rake C20) ; 3bet 7-12% ; BB defend −10-15% avec rake ; limp rare ; 2bb/3bb cap 3 | `deviation_cap` bayésien, serré si N>3 | ~30% du edge total | Overfit MCCFR sans abstraction → cap 3 + bench `success_rate>50%` |
| **Flop** | F | c-bet 40-65% selon texture ; sizing 33/50/100 ; donk 5-15% low/pairé 25-33% pot (C22) reporté V1.2 ; check-raise 10-15% | 0.6× en 3-way | +0.3..+0.7 | Figé half/pot = −1.5..−3 (Ganzfried C03) |
| **Turn** | T | 50/75/100 ; barrel 40-55% ; overbet rare | 0.6× | +0.2..+0.5 | Translation error si 33% omis |
| **River** | R | 50/100/150 overbet 15-25% polarisé (C21: 33%+75% perd 0.15% EV, +150% récupère 98%) ; bluff/value 1:1..2:1 ; block 25-33% | Exploit le plus rentable mais le plus puni si mal calibré (−2) | +0.2..+0.5 (150 seul) +0.9 (50/100→33/50/75/150) | Omettre 150 = −0.2-0.5 |
| **Rake** | * | Rake 5%/$3-4 cap : `share=(pot−rake)/winners` ; pot 100bb cap touché plus souvent multiway → même `rake_rate/cap` HU→MCCFR obligatoire (C20) | Pas d'exploit | +1..+3 micro si pris en compte, −1.5..−4 si omis | `rake=0` en micro = tueur |
| **ICM (MTT)** | * | ChipEV → `$EV=ChipEV+BountyEV` (PKO C23) / `ICM 15-25% tighter` + `FGS 2-3` (C24) ; early bounty 25-33%, FT 2-4× bounty, cover +10-20% wider | risk premium négatif si on cover → plus large que chipEV | +1..+3% ROI | Confondre chipEV et $EV |
| **Abstraction / translation** | * | Bucketing EMD −30% exploit (C25), geometric `bet=pot*((SPR+1)^(1/n)-1)` (C21) ; pseudo-harmonique hard>soft (C03) ; HS-PCFR(30) sans abstraction +2-3 ordres | — | −30-50% EV si mal choisie | 2 sizings perdent 35% EV river |
| **Variance / bench** | * | HS-PCFR(30) drop-in 5/5 (C16) ; AIVAT −85% / 44× mains (C11) ; MIVAT +40% sur AIVAT en 6-max (C27) ; ES-CFR −30-50% variance sampling (C18) | — | bench 10× moins de mains pour CI | Bench sans AIVAT = CI bruité |

---

## 3. Par variante

| Variante | N recommandé | Algo / mode | Sizing | Particularité | WR / difficulté | Quand |
|----------|--------------|-------------|--------|---------------|-----------------|-------|
| **Cash 6-max 100bb** (Pluribus C10 / Supremus C15) | 3..6 (tables 6 = 75-95% trafic micro → 15-25% à 200NL+) | MCCFR N-param + SizingConfig + rake | 33/50/100(F) 50/75/100(T) 50/100/150(R) | **Référence** | +5..+10 micro méd ~7 ; la plus pardonnable | **En premier** |
| **Cash HU 100bb** (Libratus C07) | 2 | HS-PCFR(30) ou DCFR γ=3.0 (`solver.rs` intact) | Générique 33/50/75/100 + /x/c/e/a geometric | Adversaire unique s'adapte → exploit puni | +8..+15 micro mais variance d'adaptation élevée | Après 6-max (BR 40bi) |
| **MTT / ICM** | 6..9 (payout-dépendant) | V1 approx tightening+bucket ; V1.2-V2 GT-CFR / ICM FGS2-3 / PKO ChipEV+BountyEV | Idem + ICM tighter 15-25% / PKO early 25-33% FT 2-4× | Skew log-normale, ROI≠bb/100 | ROI 10-25% micro ; σ 1.9-2.6 buy-ins | Après 6-max si BR 100-200 buy-ins |
| **Spin / HU hyperturbo** | 2-3, 25bb | Idem HU + push/fold Nash | Shove/fold | Rake très élevé | Très variance | Dernier |
| **PLO** | — | **Hors scope** (pas d'étude dans le socle 27) | — | Equité ~60/40 max → autre arbre | — | Pas en V1 |

---

## 4. Matrice décisionnelle compacte (variantes × N)

| Variante \ N | 2 (HU) | 3 | 3..6 (6-max) | 7..9 |
|--------------|--------|---|--------------|------|
| **Cash** | HS-PCFR(30)/DCFR · 33/50/75/100+/x/c/e/a · méd WR ~10 · σ~70 · **difficile** (adaptation) | MCCFR 33/50/100(F) · WR +1.2..+3 · **moyen** | **MCCFR N-param + SizingConfig + rake · 33/50/100 / 50/75/100 / 50/100/150 · méd ~7 · σ~90 · moyen — EN PREMIER** | approx tightening+bucket en V1, MAX 6→9 V1.2 |
| **MTT/ICM** | Push/fold Nash | Rare | V1 approx → V1.2 GT-CFR + ICM FGS2-3 | ICM 15-25% tighter, PKO ChipEV+BountyEV 25-33%→2-4× — après cash |

---

## 5. Implémentation — mapping vers le code

| Dimension | Fichier | Symbole |
|-----------|---------|---------|
| N-param 3..6 | `src/multiway.rs` | `MAX_PLAYERS=6`, `GameState { n, committed[6], ... }`, `Solver { n, rake_rate/cap }` |
| Sizing 33/50/75/100/150 | `src/multiway.rs` + `src/bet_size.rs` | `SizingConfig { flop_bet, turn_bet, river_bet, preflop_raise }`, `BetSize::PotRelative` |
| Rake | `src/multiway.rs:payoffs()` | `share = (pot − rake) / winners.len()` depuis `TreeConfig` / `config.json` |
| Préflop board 0 | `src/multiway.rs` + `src/v2_api.rs` | `is_valid_board_len: 0\|3..5`, `to_deal=3`, `starting_pot 1.5bb` |
| Bridge 3..6 | `src/v2_api.rs` | `can_solve_multiway 3..6`, `build_ordered_ranges`, `hero_position_to_index`, `scaled_max_iterations` |
| Bench | `research/` + `tests/` | AIVAT/MIVAT, `multiway_exploitability` bench, 19 tests |
