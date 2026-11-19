# Research Lab

This folder hosts the offline evaluation layer for the V2 runtime:

- `automation.py`: artifact catalog and automation payload helpers for the phase-2 validation stack.
- `benchmark_harness.py`: canonical benchmark runner for native solver/equity outputs and optional oracle backends.
- `best_response.py`: native MES/best-response measurement, 169-range expansion, and disjoint-range guards.
- `mes_spot.py`: measures one tree preset with the native Rust solver and records any range normalization.
- `slumbot_benchmark.py`: external HU benchmark of the research `hero_heuristic` policy against the public Slumbot HTTP API, with JSONL hand logs and 95% confidence intervals.
- `slumbot_runtime_benchmark.py`: external HU benchmark of the production `DecisionMaker` (preflop store, Rust solver, cache, fallbacks) against Slumbot, with the same JSONL/CI format plus per-decision source and latency. It replays the current street history (`street`, `actor`, total contribution in bb) so facing-bet nodes are solved correctly.
- `../scripts/bench_production_runtime.py`: headless benchmark of the production `DecisionMaker` (gate, preflop store, Rust solver, cache) on fixed preflop/flop/turn/river spots.
- `../scripts/check_perf_gate.py`: CI performance gate (constat F-09). Runs the benchmark in a fresh process per repetition, keeps the cold-latency minimum per spot (load noise only adds time, so the minimum estimates real machine capacity without false positives), and compares it to `results/perf_baseline.json` with a 10% regression threshold plus machine-noise tolerance. A fixed CPU workload calibrates the reference to the current machine, so a slower CI runner does not fail the gate. Hard invariants are zero fallbacks and a multiway backend. `--update` rewrites the baseline (review the diff).
- `calibration.py`: calibration profile fitting and range-model promotion helpers.
- `challengers.py`: lazy registry and loaders for optional offline challengers such as PokerKit, PyPokerEngine, RLCard, PokerRL, neuron_poker, and poker_ai.
- `node_oracle_runner.js`: Node bridge for JS oracle backends such as `pokersolver`, with optional on-demand vendoring.
- `oracle_randomized_compare.js`: fast batch comparison between `pokersolver` and `poker-evaluator` on randomized hands.
- `opponent_datasets.py`: dataset builders for replay-derived opponent modeling rows.
- `postflop_vendor.py`: compatibility bridge that exports the canonical preset catalog as `desktop-postflop` / `wasm-postflop` bundles.
- `policy_compare.py`: offline comparator for named policies over replay fixtures/corpora, with pairwise summaries and disagreement samples.
- `replay_adapters.py`: converters from `SpotSnapshot`/`DecisionSnapshot` into lightweight replay and simulator payloads.
- `rl_lab.py`: extended replay tournament, challenger smoke suite, and RL-lab summary builders.
- `run_rl_lab.py`: persists `research/results/rl_lab_summary.json`.
- `run_validation_suite.py`: consolidated runner for randomized oracle parity and representative replay safety checks.
- `self_play.py`: replay-based head-to-head and simplified local best-response estimates.
- `validation.py`: reusable parity, latency, and replay-safety validation suites.

The adapters are intentionally optional. If external packages such as `pokerkit`, `pypokerengine`, `rlcard`, `PokerRL`, `neuron_poker`, or `poker_ai` are installed later, the same canonical payloads can be promoted into richer environments without changing the live runtime contract.

Oracle notes:

- `phevaluator` is the preferred Python oracle for exact showdown ranking when available.
- `pokersolver` can be used through the bundled Node bridge. If the package is not installed locally, the bridge can vendor the JS source on demand when `POKERMASTER_ALLOW_ORACLE_DOWNLOAD=1`.
- `poker-evaluator` and `SKPokerEval` stay optional and are exposed through availability checks rather than being forced into the live runtime.

Postflop bridge notes:

- `write_postflop_bundle()` materializes `research/vendor/postflop/desktop-postflop.presets.json` and `research/vendor/postflop/wasm-postflop.presets.json` from the canonical preset catalog.
- The generated bundle keeps the live runtime contract (`SpotSnapshot` / `SolveRequestV2`) attached to each preset so desktop/web tooling can replay the same scenarios offline.

Validation notes:

- `python3 research/run_validation_suite.py` writes `research/results/validation_suite.json`.
- `python3 research/run_policy_compare.py tests/fixtures/policy_compare_sample_corpus.json --baseline gto_solver --challenger rl_validated` writes `research/results/policy_compare_summary.json`.
- `python3 research/run_rl_lab.py` writes `research/results/rl_lab_summary.json`.
- `python3 research/mes_spot.py --preset 4bp_hu_100bb --max-iterations 50` writes `research/results/mes_4bp_hu_100bb.json`.
- `python3 research/slumbot_benchmark.py --hands 1000 --output research/results/slumbot_1000.jsonl` writes the JSONL hand log and `slumbot_1000.summary.json`.
- `python3 -m research.slumbot_runtime_benchmark --hands 100 --output research/results/slumbot_runtime_100.jsonl` benchmarks the production `DecisionMaker` against Slumbot and writes the same JSONL/summary pair plus per-decision sources.
- `python3 scripts/bench_production_runtime.py --bet-sizes 50%` writes `research/results/runtime_benchmark.json` (cold/warm latency, fallbacks, exploitability).
- `cargo run --example native_latency` writes the native latency summary used for p95 checks.
- `python3 scripts/run_refonte_ci.py` runs the full phase-2 stack and writes `research/results/refonte_ci_summary.json`.

TimesFM offline experiment notes:

- Vendored upstream snapshot lives under `research/vendor/timesfm/` and is frozen to the SHA documented in `research/vendor/timesfm/UPSTREAM.md`.
- Upstream `master` was re-resolved once at implementation start with `git ls-remote https://github.com/google-research/timesfm.git refs/heads/master`, then frozen to `d720daa6786539c2566a44464fbda1019c0a82c0`.
- This POC is research-only and does not change the live runtime path in `src/main.py` or `src/runtime/loop.py`.
- Runtime metric extraction is implemented in `research/timesfm_runtime_dataset.py` and reads `log/runtime_history.jsonl`, keeping only `stream == "metrics"` records.
- Invalid values are ignored, including unparsable payloads and non-finite numbers such as `NaN` and `Infinity`.
- The thin wrapper in `research/timesfm_adapter.py` exposes `load_timesfm_model()`, `forecast_series()`, `forecast_runtime_metric()`, and `forecast_runtime_metrics()` while keeping the vendored model API close to upstream.
- Install requirements from `requirements_2026.txt` so `torch`, `huggingface_hub`, and `safetensors` are available before first run.
- Example command: `python .\research\run_timesfm_experiment.py --metric fallback_rate --horizon 12 --max-context 256`
- The runner prints the chosen metric, series length, holdout horizon, TimesFM forecast, two simple baselines, and MAE on the holdout tail.
- Runtime API exposure is optional behind `timesfm.enabled=true` in `config.json` or `POKER_ENABLE_TIMESFM=1`, then available at `GET /runtime-forecast/timesfm` without altering the live decision path by default.
- To resnapshot later, re-resolve `master` once, copy only the approved files from that frozen SHA into `research/vendor/timesfm/`, then update `UPSTREAM.md` without mixing local project code into the vendored tree.

Runtime review contract notes:

- `runtime_review` is now the explicit canonical wrapper shared by review/export/compare artifacts. It is versioned (`name="runtime_review"`, `version="v1"`) and carries a strict `artifact_type` plus a normalized `artifact` payload.
- Canonical wrapper access is now stable across families: `runtime_review.artifact.records` for flat corpora, `runtime_review.artifact.bundle.records` for runtime replay sessions, and `runtime_review.artifact.sessions[*].records` for multi-session review packs.
- Loader/import priority is now explicit: backend and research tools resolve `runtime_review` first, dispatch from its `artifact_type`, and only then fall back to legacy top-level aliases.
- Legacy top-level families remain exported for compatibility: `records`, `bundle`, `review_session`, `review_pack`, `policy_compare_corpus`, and `policy_compare_corpus_batch` are still present so older tools do not need to migrate immediately.
- `POST /runtime-history/import` and `RuntimeHistoryStore.coerce_records_payload()` now resolve the canonical wrapper first, then fall back to the legacy aliases.
- `research/policy_compare.py` now resolves `runtime_review` first when present, then dispatches by `artifact_type` (`review_session`, `review_pack`, `policy_compare_corpus`, `policy_compare_batch`) before trying legacy wrapper heuristics.
- `GET /runtime-history/export` keeps the legacy top-level `format="runtime_history_v1"` payload and now also exposes `format_version="v1"` plus `contract={name:"runtime_review", version:"v1", artifact_type:...}` metadata.
- Export payloads also mirror contract hints under `meta` (`contract_name`, `contract_version`, `artifact_type`, `kind`) so `policy_compare`, `review_pack`, and website mappers can coerce a shared contract shape without depending on one wrapper key.
- Bundle exports now also include `review_session`, a stable wrapper for one local review session. The canonical records remain available at both top-level `records` and `review_session.bundle.records` for backward compatibility.
- Batch policy-compare exports now also include `review_pack`, a stable wrapper for multi-session local review packs. Records remain available at top-level `records` and under `review_pack.sessions[*].records`.
- The offline `research/policy_compare.py` loader now accepts either the explicit corpus kinds or contract-wrapped `review_session` / `review_pack` payloads when their version resolves to `v1` through `contract`, `format_version`, `version`, or `meta` aliases.
- `POST /runtime-history/import` is intentionally tolerant and accepts records from `records`, `bundle.records`, `sessions[*].records`, `review_session.records`, `review_session.bundle.records`, `review_pack.records`, and `review_pack.sessions[*].records`.
- `research/policy_compare.py` now treats `review_pack` as an explicit input family rather than only a best-effort fallback. The loader first resolves the stable `review_pack` envelope, then consumes one of these shapes directly: `review_pack.sessions[*].records`, `review_pack.records`, `review_pack.raw` runtime bundles, and frontend `review_pack.currentReplay` / `review_pack.current_replay` timelines.
- Version and contract aliases can live either at the top level or inside the nested `review_pack` envelope. `policy_compare` resolves `contract`, `format_version`, `version`, `version_tag`, and `meta.*` aliases before deciding how to load the pack.
- Backend and research tools still keep a best-effort path for richer frontend `review_pack` variants: they recurse into embedded `raw` payloads when present, and can fall back to `review_pack.currentReplay.timeline[*]` or `current_replay.timeline[*]` as partial decision records.
- This fallback stays intentionally partial: timeline-derived records preserve `spot_id`, `timestamp`, `street`, `action`, `heroEv`, `incidents`, and a compact metadata subset, but do not recreate a full runtime replay bundle.
