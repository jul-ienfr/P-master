# Ordre conseillé — quoi jouer et implémenter en premier

> Répond à "qu'est-ce qui est conseillé de jouer en premier comme variante / nombre de joueurs"
> et, indissociablement, quoi documenter et implémenter en premier.
> Sources : socle 27 études (C10 Pluribus, C15 Supremus, C20 rake, C21 sizing, C23-24 PKO/ICM) + modèle proba (`probabilites.md`).

---

## 1. Ordre pour le joueur — quelle variante et quel N en premier

| Rang | Variante + N | Pourquoi (WR/variance/bankroll/rake) | Bankroll requis | Rôle |
|------|--------------|--------------------------------------|-----------------|------|
| **1** | **Cash 6-max micro (NL2-NL10) 3..6** | WR méd ~7 bb/100 le plus élevé vs field, trafic maximal (75-95% du trafic micro), rake élevé mais compensé +1..+3 rake-aware, pardonne le tilt, 40bi suffisent | 40 buy-ins | Apprendre, financer la BR |
| 2 | Cash HU micro | WR plus élevé +8..+15 mais adversaire unique s'adapte → variance d'adaptation, tilt plus coûteux | 40bi (mais 60+ si tilt-prone) | Spécialisation |
| 3 | MTT micro (1-5€) | ROI 10-25% attractif mais σ 1.9-2.6 buy-ins, downswing 30-50 BI normal, P(profit) 65-75% seulement à 500 MTT | 100-200 buy-ins | Seulement avec BR 6-max |
| 4 | MTT mid / PKO | Bounty 25-33% early → 2-4× FT, ICM 15-25% tighter, besoin mode $EV séparé (C23-C24) | 150-200bi | V1.2-V2 |
| 5 | PLO / Spin hyperturbo | Hors scope socle, rake 10%+, variance extrême | 200+ bi | Pas en V1 |

**Logique** : 6-max micro maximise WR/σ et le nombre de mains/heure, minimise le risque de ruine (`RoR = exp(−2·edge·roll/var)`) à BR donnée. C'est l'ordre dans lequel le plan est phasé (V1 bloc 6-max 3..6) — pas un hasard, c'est la conclusion conjointe Pluribus/Supremus/Ganzfried/Rake-aware (C10/C15/C03/C20).

### Détail par rang

**Rang 1 — Cash 6-max micro : pourquoi en premier ?**
- Le field micro est le plus faible (WR solver +5..+10, méd ~7). Même un solver imparfait (avant V1 : +4..+8.5) est déjà gagnant à 78-93% à 50k mains.
- Volume : 6-max permet 500-800 mains/heure en multi-tabling, vs ~250 en HU (un seul adversaire) et ~60 MTT (structure lente).
- Rake élevé en micro (5%/$3-4) mais le solver rake-aware (C20) compense +1..+3 bb/100 — ignorer le rake = −1.5..−4.
- Bankroll 40bi suffit (RoR ~5% à WR +5, voir `probabilites.md` §6).
- Pédagogie : on apprend toutes les streets (préflop → river), tous les N (HU→6-way), et la gestion multiway — transférable à tout autre format.

**Rang 2 — HU : quand ?**
- Une fois la BR 6-max à 40-60bi et le jeu postflop maîtrisé. HU exige une adaptation constante à un seul adversaire (exploit puni si mal calibré, C07-C09).
- WR plus élevé en théorie (+8..+15) mais σ d'adaptation plus dur à modéliser.

**Rang 3 — MTT micro : quand ?**
- Seulement avec 100-200bi de BR MTT (séparée de la BR cash). Variance MTT : σ 1.9-2.6 buy-ins, P(profit) seulement 65-75% à 500 MTT même à ROI 15% (voir `probabilites.md` §3).
- Ne pas mélanger BR cash et MTT — la variance MTT peut raser une BR cash en quelques sessions.

**Rangs 4-5 — PKO / PLO / Spin :**
- PKO : nécessite un module $EV = ChipEV + BountyEV (C23), bounty 25-33% early → 2-4× FT, cover +10-20% wider. Hors V1 bloc, prévu V1.2-V2.
- PLO : hors scope socle 27 (pas d'étude), équité max ~60/40 → autre arbre, autre solver.
- Spin hyperturbo : rake 7-10%+, variance extrême, push/fold Nash — dernier.

---

## 2. Ordre pour le repo — quoi documenter & implémenter en premier

| Rang | Livrable | Études qui le justifient | Effort | Statut |
|------|----------|--------------------------|--------|--------|
| **1** | **`docs/etudes.md`** — 27 fiches détaillées (C01-C27, DOI/arXiv + apport chiffré + limite + chantier) | Toutes C01-C27 | 0.3j | ✅ fait |
| 2 | **`docs/strategie-par-format.md`** — matrice variantes × N × streets/sizing/rake/ICM (C.2-C.4) | C03 C10 C15-C16 C20-C24 | 0.2j | ✅ fait |
| 3 | **`docs/probabilites.md`** — décomposition a-f, tables P(profit) corrigées cash/MTT/HU, 5 pièges, RoR, additivité (Annexe B) | C04 C05-C08 C11 C16 + modèle proba | 0.1j | ✅ fait |
| 4 | **`docs/ordre-conseille.md`** — ce document (ordre joueur 1..5 + matrice décisionnelle) | C10 C15 C23-C24 + modèle proba | 0.1j | ✅ fait |
| 5 | **Code V1 bloc 5.5j** — A1-A5 multiway N-param → S1-S4 SizingConfig+préflop → B bridge → C exports → D tests (19 tests, fuzz 1k) → E config.json + AUDIT §4 MAJ + README § solver | C03 C09-C10 C11 C16 C20-C21 C25 | 5.5j | à faire |
| 6 | MAJ `AUDIT §4` + `config.json` (multiway_max_players, sizing_preset, rake_rate/cap) + `README § solver` | C09-C10 C20 | inclus E 0.2j | à faire |
| 7 | V1.2 (1j) MAX 6→9 + shuffle + donk / V2 pistes GT-CFR/ReBeL/HS-PCFR+ | C13-C14 C22 C16 | 1j / V2 | conditionnel |

> Effort doc ~0.7j autonome (hors code) — prérequis au code 5.5j car fige les choix sizing/rake/N que le code implémente.

---

## 3. Matrice décisionnelle compacte — quoi implémenter/jouer en premier

| Variante \ N | 2 (HU) | 3 | 3..6 (6-max) | 7..9 |
|--------------|--------|---|--------------|------|
| **Cash** | HS-PCFR(30)/DCFR · 33/50/75/100+/x/c/e/a · méd WR ~10 · σ~70 · **difficile** (adaptation) | MCCFR 33/50/100(F) · WR +1.2..+3 · **moyen** | **MCCFR N-param + SizingConfig + rake · 33/50/100 / 50/75/100 / 50/100/150 · méd ~7 · σ~90 · moyen — EN PREMIER** | approx tightening+bucket en V1, MAX 6→9 V1.2 |
| **MTT/ICM** | Push/fold Nash | Rare | V1 approx → V1.2 GT-CFR + ICM FGS2-3 | ICM 15-25% tighter, PKO ChipEV+BountyEV 25-33%→2-4× — après cash |

---

## 4. Vérification doc

```bash
ls docs/etudes.md docs/strategie-par-format.md docs/probabilites.md docs/ordre-conseille.md
grep -c "^| C" docs/etudes.md        # ≥24 fiches
grep -c "DOI\|arXiv" docs/etudes.md  # chaque fiche sourcée
grep -c "SizingConfig\|rake" docs/strategie-par-format.md
```

Critère : les 4 docs existent, chaque fiche C01-C27 est sourcée (DOI/arXiv), les matrices variantes×N sont présentes.
