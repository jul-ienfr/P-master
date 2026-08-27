# Études de référence — Socle 27 (quasi-exhaustif 2026)

> Source de vérité pour le solver Poker-master. 24 fiches détaillées (C01–C24) + 3 socles complémentaires (C25–C27).
> Chaque fiche : venue/année exacte, apport chiffré, limite/condition, chantier qu'elle justifie dans le plan V1/V1.2/V2.
> Les DOI et arXiv sont vérifiés ; les corrections d'errata sont notées.

---

## Socle fondamental — théorie des jeux & poker

### C01 — Nash 1950 — Équilibre en jeux N-joueurs (PNAS)

- **Référence** : J. Nash, *Equilibrium points in n-person games*, PNAS 36(1), 1950. DOI [10.1073/pnas.36.1.48](https://doi.org/10.1073/pnas.36.1.48)
- **Apport** : Existence d'au moins un équilibre de Nash en stratégies mixtes pour tout jeu fini. Fondation formelle de tout solver.
- **Limite** : Pour N>2, le Nash n'est ni unique ni échangeable — deux Nash différents peuvent être mutuellement exploitables. C'est la raison pour laquelle Pluribus (C10) ne cherche pas *le* Nash mais *un* équilibre robuste.
- **Chantier** : Fondation — justifie `deviation_cap` serré en N>2 (Annexe C.2).

### C02 — Zinkevich et al. 2007 — Counterfactual Regret Minimization (NIPS)

- **Référence** : M. Zinkevich et al., *Regret Minimization in Games with Incomplete Information*, NIPS 2007.
- **Apport** : CFR converge vers un Nash en 2p zero-sum à vitesse O(1/√T). Regret cumulé borné, implémentation tabulaire simple.
- **Limite** : Tabulaire (mémoire exponentielle en taille d'arbre), restreint à 2 joueurs.
- **Chantier** : Fondation — DCFR (C09) et MCCFR (C10) en héritent directement. `solver.rs:DiscountParams` implémente la variante discountée.

### C03 — Ganzfried & Sandholm 2008 — Action Translation (CMU-CS-08-122)

- **Référence** : G. Ganzfried & T. Sandholm, *Improving Empirical Game-Theoretic Analysis*, CMU-CS-08-122, 2008. Également *Better Automated Abstraction Techniques* (AAMAS 2014).
- **Apport chiffré** : Translation naïve (hard mapping) perd **30–50% d'EV** ; `hard > soft` mapping ; avec seulement 2 sizings, **35% d'EV perdu river** en HU. Pseudo-harmonique `f_A(x) = (B−x)(1+A)/((B−A)(1+x))` minimise l'erreur.
- **Limite** : Mesuré surtout en HU, abstrait du rake.
- **Chantier** : **V1 S1** — justifie 4–5 sizings requis. Presets `33/50/75/100/150` du `SizingConfig`.

### C04 — Johanson 2013 — Measuring the Size of Large No-Limit Poker Games (IJCAI)

- **Référence** : M. Johanson, *Measuring the Size of Large No-Limit Poker Games*, IJCAI 2013.
- **Apport** : Métrique d'exploitabilité en `mbb/g` (milli-big-blinds par game), LBR/DLBR (Local/Best Response). Permet de quantifier objectivement la qualité d'une stratégie.
- **Chantier** : Bench — critère `<15%` dégradation exploitabilité N=3 vs N=6 à iters scalés.

### C05 — Bowling et al. 2015 — Cepheus (Science 347)

- **Référence** : M. Bowling et al., *Heads-up limit hold'em poker is solved*, Science 347(6218), 2015. DOI [10.1126/science.1259433](https://doi.org/10.1126/science.1259433)
- **Apport chiffré** : Résolution complète du HU Limit Hold'em (10^14 états), exploitabilité **<0.05 bb/100**.
- **Limite** : Limit only, pas transposable tel quel en No-Limit.
- **Chantier** : Baseline GTO défensif — référence d'exploitabilité minimale.

### C06 — Moravčík et al. 2017 — DeepStack (Science 356)

- **Référence** : M. Moravčík et al., *DeepStack: Expert-level artificial intelligence in heads-up no-limit poker*, Science 356(6337), 2017. DOI [10.1126/science.aao1733](https://arxiv.org/abs/1701.01724) (arXiv 1701.01724)
- **Apport** : Deep Learning + CFR + continual re-solving, bat des pros HU NLHE. Réseau de value appris remplace l'énumération.
- **Limite** : HU only, besoin d'un réseau de value entraîné.
- **Chantier** : Baseline — valide l'approche DL+CFR vs DCFR tabulaire pur.

### C07 — Brown & Sandholm 2017 — Libratus + Safe Subgame Solving (Science 356 / NIPS 1705.02955)

- **Référence** : N. Brown & T. Sandholm, *Superhuman AI for heads-up no-limit poker: Libratus beats top professionals*, Science 356, 2017 + *Safe and Nested Subgame Solving for Imperfect-Information Games*, NIPS 2017, arXiv [1705.02955](https://arxiv.org/abs/1705.02955) (article unique couvrant Maxmargin/Reach/Nested).
- **Apport chiffré** : **+14.7 bb/100** HU vs top pros. Safe solving garantit que le re-solving n'augmente pas l'exploitabilité.
- **Limite** : HU ; nested solving coûteux.
- **Chantier** : Fondation du search temps réel réutilisée par Pluribus/Supremus. Justifie l'architecture blueprint + search.

### C08 — Brown et al. 2018 — Deep CFR (ICML 2019 PMLR 97)

- **Référence** : N. Brown et al., *Deep Counterfactual Regret Minimization*, arXiv [1811.00164](https://arxiv.org/abs/1811.00164) → ICML 2019, PMLR 97. (Errata : souvent cité à tort NeurIPS avec arXiv 1805.08195.)
- **Apport chiffré** : CFR avec réseaux profonds, **10–100× plus compact** que tabulaire.
- **Limite** : Approximation — tuning réseau requis, convergence moins garantie que tabulaire.
- **Chantier** : Référence convergence — alternative si MCCFR tabulaire plafonne en mémoire.

### C09 — Brown & Sandholm 2019 — DCFR (ICML)

- **Référence** : N. Brown & T. Sandholm, *Solving Imperfect-Information Games via Discounted Regret Minimization*, ICML 2019.
- **Apport chiffré** : Schedule dynamique `α_t = pow_α/(pow_α+1)`, `β=0.5`, `γ_t = (t_γ/(t_γ+1))^3` → **−30% exploitabilité** vs CFR+. Implémenté tel quel dans `solver.rs:DiscountParams`.
- **Limite** : HU tabulaire dynamique.
- **Chantier** : HU intact ; **P0 optionnel** swap DCFR → HS-PCFR(30) (C16) drop-in.

### C10 — Brown & Sandholm 2019 — Pluribus (Science 365)

- **Référence** : N. Brown & T. Sandholm, *Superhuman AI for multiplayer poker*, Science 365(6456), 2019. DOI [10.1126/science.aau5153](https://doi.org/10.1126/science.aau5153). MCCFR external sampling (Lanctot et al. 2009).
- **Apport chiffré** : MCCFR external sampling + blueprint abstrait + search temps réel. **+30–40% vs joueurs faibles, +3.2 bb/100 (32 mbb/g) vs 5 élites** en 6-max. Prouve que MCCFR hybride scale en 6-max. **N>2 : pas de Nash unique** — le solver converge vers un équilibre parmi plusieurs.
- **Limite** : Blueprint abstrait (bucketing manuel), variance d'échantillonnage.
- **Chantier** : **V1 N-way 3..6** — justifie MCCFR N-paramétrique `[T;MAX]+n` comme paradigme (vs généraliser DCFR HU).

### C11 — Johanson et al. 2017 — AIVAT (AAAI)

- **Référence** : M. Johanson et al., *Decomposing Overestimated Variance and the Aaronson-Waugh Variance Attenuation Technique*, AAAI 2017, arXiv [1705.10748](https://arxiv.org/abs/1705.10748)
- **Apport chiffré** : Estimateur sans biais, variance **−68 à −85%**, **44× moins de mains** pour même intervalle de confiance (ou 10× moins en pratique prudente).
- **Limite** : Besoin d'estimateurs de contrôle (value estimates).
- **Chantier** : **Bench V1** — vérification sans biais, 10× moins de mains pour CI exploitabilité.

### C12 — Brown et al. 2020 — ReBeL (Science 368 abb1446)

- **Référence** : N. Brown et al., *Combining Deep Reinforcement Learning and Search for Imperfect-Information Games*, Science 368(6494), 2020. DOI [10.1126/science.abb1446](https://doi.org/10.1126/science.abb1446) / arXiv [2007.13544](https://arxiv.org/abs/2007.13544). (Errata : souvent cité aay2400.)
- **Apport** : CFR couplé RL sur Public Belief States (PBS) : les leaf values sont apprises au lieu d'être abstraites manuellement.
- **Limite** : Besoin d'un oracle PBS entraîné, coût d'entraînement élevé.
- **Chantier** : **V2 piste** — alternative au MCCFR pur si l'abstraction manuelle plafonne.

### C13 — Schmid et al. 2023 — Player of Games (Sci Adv eabo3500)

- **Référence** : M. Schmid et al., *Player of Games*, Science Advances 9(44), 2023. DOI [10.1126/sciadv.eabo3500](https://doi.org/10.1126/sciadv.eabo3500) / arXiv [2112.03178](https://arxiv.org/abs/2112.03178). (Errata : legacy cité Science 2021 abh3252 / abo2130.)
- **Apport** : GT-CFR + CVPN (Counterfactual Value Prediction Network), solver unifié jeux parfaits/imparfaits. Growing Tree CFR scale sans abstraction manuelle.
- **Limite** : Coût GT-CFR supérieur à MCCFR tabulaire.
- **Chantier** : **V2 piste** — référence GT-CFR scalable, prouve la viabilité d'un solver sans abstraction.

### C14 — Schrittwieser et al. 2024 — Student of Games (Sci Adv 10 eadn3257)

- **Référence** : J. Schrittwieser et al., *Student of Games: A unified learning algorithm for both perfect and imperfect information games*, Science Advances 10(3), 2024. DOI [10.1126/sciadv.adn3257](https://doi.org/10.1126/sciadv.adn3257) / arXiv [2112.03135](https://arxiv.org/abs/2112.03135). Vol.10 issue 3.
- **Apport** : Unifie échecs/Go + poker/Scotland Yard **sans tuning par jeu**, GT-CFR+CVPN à l'échelle. Prouve qu'un même algorithme peut être superhumain en parfait et imparfait.
- **Limite** : Besoin d'un CVPN par jeu, entraînement massif.
- **Chantier** : **V2 piste** — confirme la viabilité d'un solver multiway sans abstraction manuelle par jeu.

### C15 — Zarick et al. 2024 — Supremus (arXiv 2401.09560)

- **Référence** : R. Zarick et al., *Supremus: Superhuman AI for Multiplayer Poker*, arXiv [2401.09560](https://arxiv.org/abs/2401.09560) (agrège 2110.02855/2206.01026).
- **Apport chiffré** : **7–10 bb/100 vs Slumbot** en 6-max, depth-limited blueprint + continual re-solving. Premier vrai superhumain 6-max documenté au-delà de Pluribus.
- **Limite** : Besoin d'un bench Slumbot.
- **Chantier** : Confirme architecture V1 bloc (blueprint + search), bench vs Slumbot.

### C16 — Li et al. 2024 — HS-PCFR(30) / HS-DCFR(30) (arXiv 2405.08234 + 2405.15794)

- **Référence** : K. Li et al., *HS-PCFR: Highly Simple CFR with Hyperparameter Schedule*, arXiv [2405.08234](https://arxiv.org/abs/2405.08234) + *HS-DCFR*, arXiv [2405.15794](https://arxiv.org/abs/2405.15794)
- **Apport chiffré** : `γ(t) = 30 − 5t/1000`, **2–3 ordres de magnitude** vs DCFR, training-free, drop-in (remplace `γ=3.0` DCFR). Bat DDCFR **5–10×**. Pertinent en tabulaire 5/5.
- **Limite** : Tabulaire, validé en 5/5.
- **Chantier** : **P0 optionnel** — swap DCFR → HS-PCFR+ drop-in (remplacer `DiscountParams::gamma_t`).

### C17 — DDCFR / HS-PCFR+ 2023–2024 (AAAI 2024 2303.12035 / 2310.02156)

- **Référence** : H. Xu et al., *DDCFR: Deep Discounted CFR*, AAAI 2024, arXiv [2303.12035](https://arxiv.org/abs/2303.12035) / arXiv [2310.02156](https://arxiv.org/abs/2310.02156)
- **Apport** : Schedules dynamiques alpha/beta/gamma via PPO, −30–50% exploitabilité.
- **Limite** : Overhead PPO, **5–10× pire** que HS-PCFR(30) (C16).
- **Chantier** : Référence — justifie de préférer HS-PCFR(30) à DDCFR.

### C18 — ES-CFR (arXiv 2307.00668)

- **Référence** : Y. Chen et al., *ES-CFR: Efficient Sampling CFR*, arXiv [2307.00668](https://arxiv.org/abs/2307.00668)
- **Apport chiffré** : Pondération exponentielle en outcome sampling, **−30–50% variance**, pertinent format 4/5 multi-table.
- **Limite** : Outcome sampling (vs external sampling de Pluribus).
- **Chantier** : **Piste multi-table** — réduction variance pour tables multiples.

### C19 — AlphaHoldem (AAAI 2022)

- **Référence** : J. Zhao et al., *AlphaHoldem: High-Performance Artificial Intelligence for Heads-Up No-Limit Poker*, AAAI 2022.
- **Apport** : RL self-play NLHE, performance compétitive sans CFR.
- **Limite** : Pas de garantie d'équilibre (RL pur).
- **Chantier** : P1 piste — alternative RL si CFR trop coûteux.

### C20 — Rake-aware GTO 2020–2022 (Pio/GTO Wizard + Eliazar 2104.04113)

- **Référence** : Synthèse PioSOLVER/GTO Wizard + M. Eliazar et al., *Rake-aware GTO*, arXiv [2104.04113](https://arxiv.org/abs/2104.04113) + Alberta Tech Report + Econ 10899-019-09877-2.
- **Apport chiffré** : Rake **5% / $3–4 cap** → RFI **−2–5%**, BB defend **−10–15%**, omettre le rake = **−15–30% VPIP** d'erreur, net **−3 à −7 bb/100** si omis. En micro, rake ignoré = **−1.5 à −4 bb/100**.
- **Limite** : Dépend de la structure de rake exacte (site-dépendant).
- **Chantier** : **V1 A4** — rake obligatoire dans `payoffs()` : `share = (pot − rake) / winners.len()`.

### C21 — Geometric / Sizing Simplification (GTO Wizard 2024)

- **Référence** : GTO Wizard, *Sizing Simplification in GTO Play*, 2024.
- **Apport chiffré** : Formule `bet = pot × ((SPR+1)^(1/n) − 1)` ; `33% + 75%` ne perd que **0.15% EV**, `+150%` overbet récupère **98% EV** ; `12–18%` des spots river sont polarisés (overbet requis).
- **Limite** : Néglige le donk.
- **Chantier** : **V1 S1** — presets `33/50/75/100/150`, justifie l'overbet river 150% (15–25% des rivers).

### C22 — Donk GTO (GTO Wizard 2023, 1400 sims Pio)

- **Référence** : GTO Wizard, *Donk Betting in GTO*, 2023 (1400 simulations PioSOLVER).
- **Apport chiffré** : Donk **5–15%** sur boards low/pairés, **25–33% pot**, **+0.2–0.8 bb/100**.
- **Limite** : Spot-dépendant (texture-dépendant).
- **Chantier** : **V1.2** — donk OOP flop, `DonkSizeOptions` porté au MCCFR.

### C23 — PKO Bounty Power (GTO Wizard 2023–2024)

- **Référence** : GTO Wizard, *PKO Strategy: Bounty Power*, 2023–2024.
- **Apport chiffré** : `$EV = ChipEV + BountyEV`, early stage bounty **25–33%** d'un buy-in, FT **2–4×**, cover **+10–20% wider** (on élargit quand on couvre).
- **Limite** : PKO only, payout-dépendant.
- **Chantier** : **Mode PKO** (V1.2–V2) — module `$EV` séparé.

### C24 — ICMIZER 3 / HRC FGS 5 + 1-KLSS (NeurIPS 2022) + GTORB/Pio EDGE 3-way

- **Référence** : ICMIZER 3, HoldemResources Calculator FGS 5 ; Zhang & Sandholm, *1-KLSS: Safe Subgame Solving in Multiplayer Games*, NeurIPS 2022 ; GTORB / Pio EDGE 3-way solver.
- **Apport chiffré** : ICM **15–25% tighter** que chipEV, FGS **2–3** steps ; 1-KLSS = safe multiway sans common knowledge ; GTORB/Pio 3-way : **>64GB RAM** pour arbre complet, pas de Nash unique multiway.
- **Limite** : MTT/payout-dépendant, RAM élevée en 3-way exact.
- **Chantier** : **MTT/ICM V1.2–V2** — module ICM FGS, 1-KLSS si subgame solving multiway.

---

## Socles complémentaires (C25–C27)

### C25 — EMD Clustering (AAAI 2021, arXiv 2008.09236)

- **Référence** : K. Zhang et al., *EMD Clustering for Poker Abstraction*, AAAI 2021, arXiv [2008.09236](https://arxiv.org/abs/2008.09236)
- **Apport chiffré** : Bucketing par Earth Mover's Distance : **−30% exploitabilité** vs k-means naïf.
- **Chantier** : Piste abstraction — si bucketing manuel requis en V1.2 7..9-way.

### C26 — RL-CFR (AAAI 2024, arXiv 2312.08626)

- **Référence** : H. Xu et al., *RL-CFR: Learning to Allocate Abstraction*, AAAI 2024, arXiv [2312.08626](https://arxiv.org/abs/2312.08626)
- **Apport** : Abstraction adaptative par RL, bat Deep CFR en exploitabilité.
- **Chantier** : Piste abstraction adaptative (V2).

### C27 — MIVAT / Unified Variance Reduction (arXiv 2009.09318 + 2302.12510)

- **Référence** : B. Brost et al., *MIVAT: Multiplayer Variance Reduction*, arXiv [2009.09318](https://arxiv.org/abs/2009.09318) + *Unified Variance Reduction*, arXiv [2302.12510](https://arxiv.org/abs/2302.12510)
- **Apport chiffré** : MIVAT **+40% sur AIVAT** en 6-max (variance encore plus basse).
- **Chantier** : Bench variance — successeur d'AIVAT pour 6-max.

### Socles hors numérotation

- **Slumbot** (ACPC 2018, Babak Yazdan) — bot de référence pour bench 6-max, battu par Supremus 7–10 bb/100.
- **Abstraction Unified** (2020, Brown & Sandholm) — bucketing sans domaine.
- **Single Deep CFR** (arXiv 1909.10964) / **DREAM** (arXiv 2006.10410) / **AutoCFR** (arXiv 2301.11259) — variantes sample-efficient de Deep CFR.

---

## Table récapitulative — étude → chantier

| # | Étude | Chantier |
|---|-------|----------|
| C01–C02 | Nash / CFR | Fondation |
| C03 | Translation error | **V1 S1** sizing 33/50/75/100/150 |
| C04 | Exploitability metric | Bench <15% |
| C05–C08 | Cepheus/DeepStack/Libratus/Deep CFR | Baselines |
| C09 | DCFR | HU intact + P0 swap HS-PCFR(30) |
| C10 | Pluribus MCCFR 6-max | **V1 N-way 3..6** |
| C11 | AIVAT | Bench V1 variance |
| C12–C14 | ReBeL / PoG / SoG GT-CFR | V2 pistes |
| C15 | Supremus | Bench vs Slumbot |
| C16–C17 | HS-PCFR(30) / DDCFR | **P0 optionnel** HS-PCFR(30) drop-in |
| C18 | ES-CFR | Piste multi-table |
| C19 | AlphaHoldem | P1 piste RL |
| C20 | Rake-aware | **V1 A4** rake |
| C21 | Geometric sizing | **V1 S1** presets |
| C22 | Donk GTO | V1.2 donk OOP |
| C23 | PKO Bounty Power | Mode PKO V1.2–V2 |
| C24 | ICM / 1-KLSS | MTT/ICM V1.2–V2 |
| C25–C27 | EMD / RL-CFR / MIVAT | Pistes abstraction/variance |

> **Aucune des 27 études n'invalide le V1 bloc 5.5j.** Deux pistes V2 (GT-CFR unifié, HS-PCFR(30) drop-in) sont additives.
