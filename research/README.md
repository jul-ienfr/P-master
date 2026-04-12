# Research Lab

This folder hosts the offline evaluation layer for the V2 runtime:

- `automation.py`: artifact catalog and automation payload helpers for the phase-2 validation stack.
- `benchmark_harness.py`: canonical benchmark runner for native solver/equity outputs and optional oracle backends.
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
- `cargo run --example native_latency` writes the native latency summary used for p95 checks.
- `python3 scripts/run_refonte_ci.py` runs the full phase-2 stack and writes `research/results/refonte_ci_summary.json`.

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
