# Refonte Maximaliste de PokerMaster

Mise a jour du 11 avril 2026.

Legende:
- `[x]` Fait
- `[ ]` A faire

Note importante:
- Les validations d'execution V2/refonte ont maintenant ete lancees dans cet environnement Linux local avec un Python autonome et un linker `zig cc`.
- Les integrations RL et le bridge `desktop-postflop` / `wasm-postflop` sont maintenant relies au code et au lab offline, mais leur validation complete depend encore des packages externes et des suites d'execution.
- Resultats de validation enregistres:
  `research/results/validation_suite.json` et `research/results/native_latency.json`

## 1. Contrat canonique V2

- [x] Faire de `SpotSnapshot`, `DecisionSnapshot`, `SolveRequestV2` et `SolveResponseV2` le contrat canonique partage entre orchestration Python, bindings Rust, HTTP V2 et couche Tauri/web.
- [x] Ajouter les types publics partages `EquityBackend`, `RangeModelVersion`, `ReplayRecord`, `BenchmarkResult`, `OcrConfidenceReport` et `DecisionGateResult`.
- [x] Etendre `SpotSnapshot` avec `spot_id`, `state_confidence`, `ocr_confidence` et `range_model_version`.
- [x] Etendre `SolveRequestV2` avec `spot_id`, `legal_actions`, `cache_policy`, `hero_confidence`, `state_confidence`, `range_model_version` et `time_budget_ms` explicite dans le chemin canonique.
- [x] Etendre `SolveResponseV2` avec `backend`, `cache_tier`, `normalized_ranges`, `decision_confidence`, `fallback_reason` et warnings structures.
- [x] Etendre `DecisionSnapshot` pour transporter la confiance et le resultat de gate.
- [x] Exposer un service unique de decision qui consomme `SpotSnapshot` et retourne `DecisionSnapshot`.
- [x] Conserver les anciennes APIs preflop/postflop comme wrappers autour du chemin canonique.

## 2. Solveur natif, fallback et cache

- [x] Basculer le chemin prioritaire vers le binding Python natif pour le solveur V2.
- [x] Garder `gto_server` comme fallback sante/interop.
- [x] Normaliser les cles de cache de solve.
- [x] Ajouter un cache disque persistant pour les solves V2.
- [x] Ajouter un mecanisme de prechauffage du cache.
- [x] Propager `cache_policy` et `cache_tier` dans le pipeline de decision.
- [x] Reprendre les presets d'arbres de `desktop-postflop` et `wasm-postflop` via un catalogue canonique de presets et leur exposition UI/runtime.
- [x] Industrialiser un prechargement massif des arbres/solves les plus frequents via le catalogue de prewarm et l'inspection de cache.

## 3. Range model

- [x] Remplacer l'ancien `range_tracker` heuristique par une base `RangeModel` en plusieurs etages.
- [x] Ajouter des priors preflop par position et type de ligne.
- [x] Ajouter une mise a jour board-aware basee sur l'historique d'actions postflop.
- [x] Produire des sorties de ranges normalisees pour le solveur et l'analyse.
- [x] Exporter des lignes de calibration offline.
- [x] Boucler une calibration automatique sur des replays/simulations reels via le pipeline `research/calibration.py`.
- [x] Mesurer et promouvoir une version de `RangeModel` par benchmark hors ligne.

## 4. Equity backends

- [x] Introduire une selection explicite de backends d'equity.
- [x] Normaliser les reponses d'equity avec metadata de backend et de cache.
- [x] Poser la structure pour differencier `rust_exact`, `rust_monte_carlo` et `oracle_backend` dans le chemin Python.
- [x] Integrer `HenryRLee/PokerHandEvaluator` comme backend optionnel reel pour le showdown exact via `phevaluator`.
- [x] Brancher `SKPokerEval`, `poker-evaluator` et `pokersolver` comme oracles de conformance optionnels via detection et runner Node.
- [x] Basculer automatiquement entre exact et Monte Carlo selon la fermeture du spot et le budget temps.

## 5. Research, replay et benchmark

- [x] Creer l'espace `research/` pour la simulation, le replay et les benchmarks.
- [x] Ajouter des adaptateurs `SpotSnapshot -> PokerKit` et `SpotSnapshot -> PyPokerEngine` au niveau payload.
- [x] Ajouter un harnais de benchmark (`SolverProbe`, `BenchmarkHarness`).
- [x] Ajouter des structures de `ReplayRecord` et `BenchmarkResult` reutilisables dans le pipeline.
- [x] Brancher effectivement les oracles externes dans le benchmark croise.
- [x] Ajouter du self-play et du head-to-head automatises.
- [x] Ajouter des approximations LBR/BR simplifiees sur petits jeux.
- [x] Generer des datasets d'adversaires et une calibration de ranges a partir de replays reels.
- [x] Integrer `RLCard`, `PokerRL`, `neuron_poker` ou `poker_ai` comme challengers hors boucle live.

## 6. Gate de confiance et robustesse live

- [x] Inserer une machine d'etat de confiance avant toute action.
- [x] Valider la coherence cartes/pot/stacks/actions legales.
- [x] Detecter des cas invalides comme cartes dupliquees, cartes hero manquantes, board incomplet, actions legales absentes et valeurs negatives.
- [x] Retourner `NoAction` sur un spot douteux.
- [x] Empecher le clic live quand la decision est `NoAction`.
- [x] Enregistrer `backend`, `cache_tier`, `fallback_reason`, `decision_confidence` et le gate dans `DecisionSnapshot`.
- [x] Ajouter une validation temporelle multi-frame.
- [x] Ajouter une detection de contradictions OCR sur historique court.

## 7. UI, inspection et observabilite

- [x] Aligner les payloads Tauri/web sur le contrat V2 enrichi.
- [x] Ajouter un navigateur de spots.
- [x] Ajouter la relecture des solves caches.
- [x] Ajouter un panneau EV/frequences.
- [x] Ajouter un historique visuel des warnings/fallbacks.
- [x] Ajouter une explication utilisateur detaillee attachee a chaque decision.

## 8. Tests et validation

- [x] Ajouter des tests V2 sur les contrats Python.
- [x] Ajouter des tests sur `CanonicalDecisionService`.
- [x] Ajouter des tests sur le nouveau `range_tracker`.
- [x] Ajouter des tests transcriptifs pour verifier les sequences gate/fallback.
- [x] Ajouter ou etendre les tests Rust `v2_api`.
- [x] Executer la suite Python V2/refonte dans cet environnement.
- [x] Executer la suite Rust dans cet environnement.
- [x] Verifier la conformance equity sur un grand corpus randomise avec oracles externes.
- [x] Mesurer la performance p95 sur cache hit natif et solve froid.
- [x] Verifier zero action illegale sur une suite de replay OCR representative.

## 9. Reutilisation des depots externes

- [x] Reprendre des patterns d'architecture de solveur natif/V2/couche adaptatrice inspires des depots `postflop-solver`, `desktop-postflop` et `wasm-postflop`.
- [x] Preparer l'ouverture vers `PokerKit` et `PyPokerEngine` via des adaptateurs de replay/simulation.
- [x] Vendor ou binder directement `desktop-postflop` / `wasm-postflop` via un bridge de bundles de compatibilite.
- [x] Integrer directement `PokerHandEvaluator` comme backend dans le runtime.
- [x] Brancher les autres evaluateurs externes dans le benchmark et la conformance.
- [x] Integrer effectivement les frameworks RL dans le lab offline.

## 10. Point d'etat global

- [x] La fondation V2 canonique est en place.
- [x] Le chemin de decision live est plus sur grace au gate et a `NoAction`.
- [x] La base du cache persistant, du range model et du lab offline est en place.
- [x] La validation d'execution complete et la comparaison quantitative face aux oracles externes sont posees pour la refonte V2.
- [x] L'execution complete des validations Python/Rust et la validation quantitative finale sont realisees pour la refonte V2.

## 11. Phase 2

- [x] Nettoyer les warnings Rust de lifetimes dans le coeur solver.
- [x] Ajouter un runner unifie `scripts/run_refonte_ci.py` pour rejouer les validations V2/refonte.
- [x] Ajouter une CI `refonte-v2.yml` dediee a la phase 2.
- [x] Etendre le lab offline avec un tournoi de policies et un smoke suite challengers.
- [x] Exposer les artefacts d'automatisation et le RL lab pousse dans le payload `research`.
