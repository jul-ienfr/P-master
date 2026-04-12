"""Offline research helpers for the PokerMaster V2 pipeline."""

from .automation import build_automation_payload
from .benchmark_harness import BenchmarkHarness, HandRankCase, SolverProbe
from .calibration import benchmark_range_model_versions, fit_calibration_profile
from .challengers import challenger_payload, challenger_registry, load_challenger
from .opponent_datasets import build_opponent_dataset
from .postflop_vendor import build_postflop_bundle, summarize_postflop_bundle, write_postflop_bundle
from .policy_compare import (
    build_policy_compare_summary,
    discover_policies,
    load_policy_compare_corpus,
    load_policy_compare_records,
    summarize_policy_matchup,
    write_policy_compare_summary,
)
from .replay_adapters import (
    replay_record_from_snapshots,
    spot_to_pokerkit_payload,
    spot_to_pokerrl_payload,
    spot_to_pypokerengine_payload,
    spot_to_rlcard_payload,
)
from .self_play import (
    BestAlternativePolicy,
    ReplayDecisionPolicy,
    StaticActionPolicy,
    estimate_local_best_response,
    run_head_to_head,
)
from .rl_lab import build_rl_lab_payload, run_challenger_smoke_suite, run_policy_round_robin, write_rl_lab_summary
from .validation import (
    build_default_hand_rank_cases,
    build_validation_lab_payload,
    measure_solver_probe_latency,
    run_oracle_conformance_suite,
    validate_replay_decision_suite,
)
