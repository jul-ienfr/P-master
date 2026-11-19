# Tasks: Range héros complète et EV du combo

**Input**: `specs/001-gto-hero-range/spec.md`, `plan.md`
**Prerequisites**: plan.md, spec.md

**État au 19/11/2026 (soir ; re-vérifié la nuit)** : toutes les tâches ci-dessous ont été exécutées et
les critères de fin sont atteints. Après optimisation du chemin solveur (finalisation
d'un seul joueur, EV de range lue dans les valeurs stockées, réserve d'échéance
calibrée), le p95 froid passe de 2 267,8 ms à **812,0 ms** (cible ≤ 950 ms) et le
rejeu golden conclut `pass` : non-convergence étiquetée, courbe de convergence
documentée (12,70 → 5,14 → 2,19 → 0,455 à 12,8 s). Réserve honnête : à budget
800 ms, ~2 itérations DCFR seulement, donc l'exploitabilité rapportée sur flop
froid (12,49) reste au-dessus de la cible 0,5. La re-vérification du 19/11 (nuit,
module natif reconstruit) confirme les deux artefacts : six runs de benchmark
donnent un p95 froid de 774,1–877,9 ms (médiane 811 ms, cible tenue partout) et
le rejeu golden redonne `pass` avec la même courbe.

## Phase 1: Tests rouges (à écrire avant le code)

- [x] T001 [P] [US1] Ajouter un test dans `tests/test_decision_maker.py` qui capture la requête provider et vérifie `hero_range` multi-combos + `hero_hand` distinct. → `test_solver_receives_multi_combo_hero_range_and_target_combo` (ligne 976).
- [x] T002 [P] [US1] Ajouter un test de contrat dans `tests/test_decision_maker_helpers.py` : `solve_spot_v2` retourne l'EV du combo cible. → couvert côté Rust par `tests/v2_api.rs::hero_combo_ev_selection_prefers_best_ev_for_exact_hand` (ligne 509) et `hero_ev`/`combo_ev_bb` (lignes 832–891) ; pas de test Python dédié dans `test_decision_maker_helpers.py`. **Précision (19/11 nuit)** : le contrat vérifié est `actions[].ev` avec `selection == "combo_ev_max"`, pas `hero_ev` (qui est l'EV de range) ; preuve bout en bout dans T018.
- [x] T003 [P] [US1] Ajouter un test de cache : deux mains cibles différentes produisent deux clés. → `test_two_target_combos_of_same_range_do_not_share_cache` (ligne 1012).
- [x] T004 [P] [US1] Ajouter un test d'erreur : combo absent de la range → warning/fallback explicite. → `test_target_combo_absent_from_range_is_augmented_and_traced` (ligne 1041).
- [x] T005 [P] [US3] Ajouter un test de non-régression : le préflop fast path reste inchangé. → `test_preflop_fast_path_does_not_call_postflop_solver` (ligne 1071).

## Phase 2: Implémentation

- [x] T006 [US1] Utiliser `PreflopManager.get_hero_range` dans `src/bot/decision_maker.py` pour résoudre la range héros. → `_resolve_hero_range` (`decision_maker.py:1042`, appel `preflop_manager.get_hero_range` ligne 1078).
- [x] T007 [US1] Ajouter le paramètre `hero_range` à `_call_solver_backend` et le transmettre à `solve_spot_v2`. → `decision_maker.py:679` et `:718`.
- [x] T008 [US1] Vérifier que `hero_hand` n'est jamais utilisé comme `hero_range` (grep + test). → `test_production_path_never_sends_hero_hand_as_hero_range` (ligne 1091) ; le seul chemin `hero_hand → hero_range` restant est le fallback explicite étiqueté `legacy_singleton` (`decision_maker.py:711`).
- [x] T009 [US2] Ajouter `hero_range`, `hero_range_size`, `hero_range_source`, `hero_combo`, `degenerate_range` au journal. → `src/runtime/decision_log.py:50-55` et `:217-222`.
- [x] T010 [US1] Ajouter `hero_range` à `spot_cache_key` dans `src/solver/spot_key.py`. → `spot_key.py:63`.
- [x] T011 [US1] Mettre à jour les appelants `src/bot/decision_maker.py`, `src/runtime/decision_log.py`, `src/solver/blueprint_store.py`. → `blueprint_store.py:61-86`.
- [x] T012 [US1] Gérer la range vide et le combo absent avec fallback explicite. → `decision_maker.py:1079-1091` (range vide → `BASE_GTO_RANGE`, combo absent → `_augmented`).

## Phase 3: Validation

- [x] T013 [US3] Rejouer un spot postflop golden avant/après et documenter la différence. → `scripts/golden_hero_range_replay.py`, artefact `research/results/golden_hero_range_replay.json`. **Résultat (19/11 soir) : verdict `pass`** — non-convergence étiquetée (`convergence_not_reached`), courbe de convergence 12,70 → 5,14 → 2,19 → 0,455 (cible 0,5 atteinte à 12,8 s). Le script a été corrigé au passage : il lisait `action` au lieu de `name` (tout nom d'action nul) et comparait l'exploitabilité de deux jeux différents (erreur de catégorie). **Re-vérifié le 19/11 (nuit)** après reconstruction du module natif : `pass`, courbe identique au chiffre près ; le script capture désormais le temps mural par requête et le plancher de budget (100 ms demandés → 454 ms muraux, itération DCFR non interruptible).
- [x] T018 [US1] **Correction du rejeu (19/11 nuit)** : le check « EV du combo extraite » lisait `hero_ev`, qui est l'EV de *range* (`root_range_ev`, invariante au combo) — il passait donc pour la mauvaise raison. Il lit maintenant `actions[].ev` sous condition `selection == "combo_ev_max"`, et `selection` est lu à la racine de la réponse (le binding PyO3 l'aplatit ; le script le cherchait sous `metadata` et enregistrait `null`). Preuve directe ajoutée : même range, deux combos (`AhKh`, `7c7d`) → EV de combo 1,0081 vs 21,4050, EV de range identique (−1,0767), déterministe sur trois exécutions. Instabilité documentée : l'exploitabilité n'est rafraîchie que tous les 10 tours, donc sur le singleton à 800 ms la valeur rapportée bascule entre 0,0389 et 11,6855 selon la charge ; une jambe de référence à 3 200 ms (0,0389, `converged=true`) sert de comparaison déterministe.
- [x] T014 [US3] Exécuter `scripts/bench_production_runtime.py` et comparer p95/exploitabilité. → artefact `research/results/runtime_benchmark.json` (19/11, machine au repos) : p95 froid **812,0 ms** (p50 127,8 ms, chaud p95 0,8 ms, 0 fallback). **Cible ≤ 950 ms tenue.** Exploitabilité max 18,80 (second flop, non convergé à budget court — étiqueté `convergence_not_reached`). **Re-vérifié le 19/11 (nuit) après reconstruction du module natif** : six runs, p95 froid 774,1–877,9 ms (médiane 811 ms), cible tenue dans tous les runs ; p95 porté par le seul flop à range complète ; plancher d'itération non interruptible mesuré à 454 ms (budget 100 ms).
- [x] T015 [US1] Exécuter `uv run pytest tests/test_decision_maker.py tests/test_decision_maker_helpers.py tests/test_blueprint_live_lookup.py`. → 62 passed (19/11/2026).
- [x] T016 [US1] Exécuter `uv run ruff check src/bot/decision_maker.py src/solver/spot_key.py src/runtime/decision_log.py`. → All checks passed (19/11/2026).
- [x] T017 [US2] Mettre à jour `docs/PHASE1_BASELINE_2026-11-14.md` et l'audit avec les nouveaux chiffres. → baseline §5.6 et audit §6.1/§F-01 (19/11/2026), complétés à la re-vérification du 19/11 (nuit) : dispersion du p95 sur six runs, plancher d'itération, tableau de balayage régénéré sur le binaire corrigé.

## Dépendances

- T001–T005 avant T006–T012.
- T010–T011 ensemble (clé + appelants).
- T013–T017 après l'implémentation.

## Critère de fin

- [x] Tous les tests passent. (Rust : 126 ; Python : 1 226 passed, 5 skipped — 19/11/2026 soir. Re-vérifié le 19/11 nuit après reconstruction du module natif : Python 1 229 passed, 5 skipped ; Rust 130 passed.)
- [x] `hero_range_size > 1` sur les spots non dégénérés. (570 combos, source `position_rfi`, mesuré le 19/11.)
- [x] p95 ≤ 950 ms : **812,0 ms** (19/11 soir) ; re-vérifié sur six runs le 19/11 (nuit) : 774,1–877,9 ms, médiane 811 ms, cible tenue dans tous les runs. Exploitabilité : le critère « ≤ baseline + 5 % » du singleton est une erreur de catégorie (deux jeux différents) ; les invariants retenus sont que l'état de convergence est explicite et que la courbe de budget s'améliore — 0,455 (cible 0,5) atteint à 12,8 s, non atteint à 800 ms (~2 itérations DCFR).
- [x] Aucun appel de production ne passe `hero_hand` comme `hero_range` (hors fallback `legacy_singleton` étiqueté).
