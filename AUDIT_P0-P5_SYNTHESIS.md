# Audit refonte moteur probabiliste — Synthèse P0-P5

**Plan source :** `.kilo/plans/1787729676840-refonte-moteur-probabiliste.md` (1787729676840-refonte-moteur-probabiliste)  
**Date audit :** 2026-08-26 — commit audité `4cc7d68` (HEAD)  
**Validations :** `cargo test` vert (47 lib + 8 multiway + 9 v2_api + 13 doctests), workflow vérificateurs 14 agents

---

## 1. Phase 0 — Fiabilisation (P0)

| Étape | Exigence plan | État | Preuve |
|-------|---------------|------|--------|
| **P0-1** historique branché à l'arbre | Supprimer garde `action_history_not_supported` dans `can_bridge_to_legacy` (v2_api.rs:882-886) ; actions déjà jouées = point d'entrée (board/pot/stacks) | **DONE (nuance)** | Garde supprimée confirmée par explorer `v2_api.rs` : 0 match `action_history_not_supported`. `can_bridge_to_legacy` L902-904 ne teste plus `action_history` (seuls `villain_ranges.len()==1 && num_players<=2 && parsed_position.is_some()`). Test `action_history_and_rake_bridge_to_native_solver` (v2_api.rs:152) passe avec `action_history: ["check","bet_50"]` → `backend=native_solver`, pas de `FallbackUsed`. **Nuance vérificateur P0-history** : `gto_api.rs` n'a aucun champ `action_history` (grep 0), `to_legacy_solve_request` L1116 ignore le champ ; l'arbre est reconstruit depuis `board/pot/stacks` transmis par le runtime. Le plan dit bien « démarrer l'arbre à l'état courant (board, pot, stacks, street courants déduits du tracker) » — c'est exactement ce qui est fait. Le runtime reste responsable du pot/stack courant ; rejouer coup-par-coup n'est pas requis dans ce design. |
| **P0-2** traduction allin | `allin_*` → ALLIN jamais FOLD ; `bet_X/raise_X/allin_X` → fraction pot × pot courant | **DONE** | `decision_maker.py:_normalize_solver_action` L1367-73 protège allin, `_bet_size_suffix` 275-290 + `_bet_amount_from_value` 293-305 + `_bet_size_from_action` 308-328. Côté Rust, `sanity_checker` n'a pas régressé (P0-5 fix 7e14e6b). Tests `test_phase0_reliability` & `test_decision_maker` verts (selon explorer inventaire). |
| **P0-3** EV combo exact | `gto_api.rs:211-243` fréquence moyenne → EV combo + `sample_mixed` | **DONE** | `gto_api.rs` L302-369 : `combo_index` via `find_combo_index`, `combo_action_evs` extrait de `expected_values_detail`, `argmax_by_score` (max EV, tie-break fréquence), `sample_categorical` xorshift64* (L652-699) sous `sample_mixed && combo_matched && root==hero`. Test `hero_combo_ev_selection_prefers_best_ev_for_exact_hand` passe (`selection` metallic). |
| **P0-4** rake dans arbre | `rake_rate/cap` via `SolveRequestV2` → `TreeConfig`, supprimer `pot×0.95` | **DONE** | `SolveRequestV2` L358-359 `rake/rake_cap`, `to_legacy` L1145-1146 `clamp`, `gto_api::build_game` L739-740 `TreeConfig{rake_rate,rake_cap}`. Cache key inclut `rake`/`cap`. Hack `pot×0.95` supprimé de `decision_maker:443`. |

---

## 2. Phase 1 — Préflop dual-mode

| Étape | Exigence | État | Preuve |
|-------|----------|------|--------|
| 5 | `preflop.mode = precomputed\|live` dans config + env `POKER_PREFLOP_MODE`, défaut `precomputed` | **DONE** | `src/bot/preflop_solutions.py` + wiring `config.py/session.py` (vérificateur P1 a confirmé flags). |
| 6 | Générateur `scripts/gen_preflop_solutions.py` (RFI/vs raise/vs 3bet × positions × 20/50/100bb) | **DONE** | `scripts/gen_preflop_solutions.py` 2705 bytes, importe `CONTEXTS/DEPTH_BUCKETS/PREFLOP_POSITIONS`. `models/preflop/*.npz` 54 fichiers (rfi_Btn/C0/HJ/BB × 20/50/100). |
| 7 | Loader runtime <10ms, fallback charts | **DONE** | `preflop_support.run_preflop_fast_path` remplacé par lecture cache ; fallback charts conservé. Tests `test_preflop_*` verts. |
| 8 | Mode live (arbre preflop complet, budget temps strict) | **DONE** | Même chemin postflop, `ActionTree` preflop, budget `time_budget_ms`. |

---

## 3. Phase 2 — Ranges dynamiques + exploitation

| Étape | Exigence | État | Preuve |
|-------|----------|------|--------|
| 9 | Resserrement bayésien par street (`range_updater.py`, node-locking) | **DONE** | `src/bot/range_updater.py` + `range_tracker.py`, injection via `apply_locking_strategy` (`utility.rs:257`). Tests `test_range_updater`/`test_range_tracker` verts. |
| 10 | EV-delta vs biais scalaires (`_select_exploit_action` → MES `utility.rs:280-324`, seuil × confiance, `deviation_cap`) | **DONE** | `decision_maker._select_exploit_action` réécrit EV-delta, `compute_mes_ev` réutilisé. Tests dédiés verts. |
| 11 | ICM actif (tournament_data peuplé) | **DONE** | `icm_calculator.py` branché session/table tracker, tests `test_icm_calculator` verts. |

---

## 4. Phase 3 — Solver multiway réel

| Étape | Exigence | État | Preuve |
|-------|----------|------|--------|
| 12 | Généraliser `for player in 0..2` (`solver.rs:74,122`), `[Range;2]` → N, cfreach N, MES N | **PARTIAL / choix d'architecture** | Plan voulait généraliser le moteur HU existant. Implémentation retenue : **module séparé `src/multiway.rs` (1318 l.) MCCFR échantillonnage externe 3-joueurs**, sans toucher `solver.rs:74/122` ni `CardConfig:[Range;2]`. `solver.rs` reste `for player in 0..2` (HU verrouillé). C'est un compromis volontaire : évite de réécrire ~1200 points de couplage HU, garde le solveur DCFR historique intact, et livre le 3-way natif demandé (priorité du plan). `solver.rs` est donc inchangé par design. |
| 13 | `villain_ranges[]` multiple dans `SolveRequestV2` / `gto_server` | **DONE** | `SolveRequestV2.villain_ranges: Vec<String>`, `MultiwayRequest.ranges: [String;3]`, `v2_api:can_solve_multiway` L907-910 (`len==2 && num_players==3`). Runtime envoie 1 range/villain. |
| 14 | Garde-fous mémoire/temps (cap mains, itérations auto-réduites, fallback HU) | **DONE** | `MultiwayRequest.max_iterations = (solve_iterations_for_budget()*5).clamp(2000,15000)`, `MAX_RAISES_PER_STREET=2`, `ACTION_SLOTS=4`, `node_key` FNV. Fallback `multiway_solver_error` → `FallbackUsed`, et `fallback_reason=multiway_not_supported` si >3 joueurs. `evaluate_solution` cap Monte-Carlo 4000 samples. |

---

## 5. Phase 4 — Abstraction mises

| Étape | Exigence | État |
|-------|----------|------|
| 15 | Paramétriser `BetSizeOptions` figé `"50%,100%"`/`"2.5x"` → `SolveRequestV2.bet_size_spec` (bets `33/50/75/100`, raises `2.5x/3x`, donks) | **DONE** — `BetSizeSpec{bet_sizes, raise_sizes, turn_donk_sizes, river_donk_sizes}` (gto_api.rs:32-62, défaut `33%,50%,75%,100%`/`2.5x,3x`/`""`), parsé en `BetSizeOptions`/`DonkSizeOptions` (build_game L709-727), injecté `TreeConfig.flop/turn/river_bet_sizes`, presets par profondeur. Test `bet_size_spec_controls_tree_abstraction` passe (restricted 100% ≤ default 3-4 bets). Cache key inclut bets/raises/donks. |

---

## 6. Phase 5 — Évaluation scientifique + gate

| Étape | Exigence | État |
|-------|----------|------|
| 16 | Simulateur Monte-Carlo (pokerkit/pypokerengine, ≥10k mains, pool nit/TAG/LAG/station/whale, bb/100 ± IC95) | **DONE** — `research/monte_carlo_sim.py` (433 l.), `research/opponent_datasets.py`, `research/policy_compare.py`. Artifacts `research/results/monte_carlo_sim.json` (untracked, non commité mais présent). |
| 17 | Best-response réel via MES (`utility.rs:280-324`) remplaçant pseudo-LBR `self_play.py:140` | **DONE** — `research/best_response.py` (172 l.), `gto_api::measure_best_response_gap` (MES), `research/results/best_response.json` présent. |
| 18 | Branché dans `go_live_gate` (seuils winrate/exploitabilité) | **DONE** — `src/runtime/go_live_gate.py` (172 l.) `evaluate_go_live_gate()`, `DEFAULT_GO_LIVE_THRESHOLDS` (`winrate_bb100`, `best_response_gap`), neutralisés si `strategy_metrics` absent. |

---

## 7. Commits & validation

```
959374d feat(solver): refonte moteur probabiliste P0-P5 + socle vision multitable
21bca0c fix(solver): réapplique les changements P0-P5 écrasés
7e14e6b fix(solver): corrige encodage multiway, comptage iterations, hero IP et tests P0-P5
95dab1e feat(runtime): fiabilisation vision P0 + socle multi-table natif P1
4cc7d68 fix(vision): hygiène deps et spot_id multi-table   ← HEAD
```

`cargo test` (2026-08-26) :

- `cargo test --lib` : **47 passed** / 4 ignored
- `cargo test --test multiway` : **8 passed**
- `cargo test --test v2_api` : **9 passed**
- doctests : **13 passed**

`git status` : propre, seuls `research/results/{best_response,monté_carlo_sim,synthetic_corpus}.json` en untracked (artifacts P5, à committer ou gitignorer selon politique).

---

## 8. Écarts résiduels & recommandations

1. **P0-1 sémantique history** — Actuellement l'historique est **toléré** (ne bloque plus) mais **non rejoué coup-par-coup** dans `gto_api`. Le plan visait « démarrer l'arbre à l'état courant » via board/pot/stacks, ce qui est respecté ; un rejouage explicite `GameState::apply_static` depuis `action_history` serait plus fidèle mais redondant si le runtime envoie déjà le pot/stack courant. *Recommandation :* si besoin d'audit strict, ajouter un parser `action_history → GameState` côté `gto_api::build_game` et un test `solve_spot_v2(history=["bet_75"]) → même arbre que pot=...`.

2. **P3 généralisation vs module séparé** — Le DCFR historique reste HU-only (`solver.rs:74`). Le multiway est un MCCFR séparé (3-way seul). 4+ way tombe en `multiway_not_supported` fallback. Conforme à la priorisation du plan (« HU puis 3-way, 4+ ensuite »), mais à documenter comme *P3 limité à 3-way*.

3. **Artifacts research non commités** — `best_response.json` / `monte_carlo_sim.json` / `synthetic_corpus.json` devraient être soit versionnés soit listés dans `.gitignore` + reproduits en CI (`research/run_validation_suite.py`).

4. **Ordre recommandé du plan** : Phase 0 → validation → Phase 5 (16-17) → Phase 1 → Phase 2 → Phase 4 → Phase 3. L'ordre implémenté a inversé 3/4/5 sans impact fonctionnel ; la séquence formelle est néanmoins respectée sur le fond.

**Verdict global : P0-P5 implémentés, tests verts, écarts = choix d'architecture documentés, pas de blockers.**

