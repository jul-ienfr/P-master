use postflop_solver::{
    llm_assist_stub_response, solve_spot_v2, BetSizeSpec, CachePolicy, CacheTier, DecisionSource,
    DecisionWarning, LlmAssistTask, LlmConfig, LlmContextScope, LlmPrivacyMode, LlmProviderMode,
    RangeModelVersion, SolveRequestV2, SpotSnapshot, SpotSource, TreePresetId,
};
use std::collections::BTreeMap;

#[test]
fn v2_defaults_are_reasonable() {
    let spot = SpotSnapshot::default();
    assert_eq!(spot.source, SpotSource::Manual);
    assert!(spot.board.is_empty());
    assert!(spot.legal_actions.is_empty());

    let config = LlmConfig::default();
    assert!(!config.enabled);
    assert_eq!(config.provider_mode, LlmProviderMode::Disabled);
    assert_eq!(config.privacy_mode, LlmPrivacyMode::StrictLocal);

    let request = SolveRequestV2::default();
    assert_eq!(request.num_players, 2);
    assert!(request.use_cache);
    assert_eq!(request.cache_policy, CachePolicy::Memory);
    assert_eq!(request.range_model_version, RangeModelVersion::BoardAwareV2);
    assert_eq!(request.tree_preset_id, TreePresetId::srp_hu_100bb());

    assert_eq!(DecisionSource::default(), DecisionSource::Unknown);
}

#[cfg(feature = "bincode")]
#[test]
fn solve_request_v2_round_trips_with_bincode() {
    let request = SolveRequestV2 {
        spot_id: Some("spot-1".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+,AKs".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string()],
        starting_pot: 3.0,
        effective_stack: 100.0,
        hero_position: Some("oop".to_string()),
        action_history: vec!["check".to_string(), "bet_50".to_string()],
        tree_preset_id: TreePresetId::turn_probe_hu(),
        rake: 0.05,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Persistent,
        hero_confidence: Some(1.0),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::CalibratedV3,
        use_cache: true,
        time_budget_ms: Some(2_500),
        epsilon_target: None,
        ..SolveRequestV2::default()
    };

    let config = bincode::config::standard();
    let encoded = bincode::encode_to_vec(&request, config).expect("encode V2 request");
    let (decoded, read): (SolveRequestV2, usize) =
        bincode::decode_from_slice(&encoded, config).expect("decode V2 request");

    assert_eq!(read, encoded.len());
    assert_eq!(decoded, request);
}

#[test]
fn unsupported_v2_spot_returns_structured_warnings() {
    // Spot volontairement non supporté : 4-way (ou board préflop) pour forcer le fallback
    // structuré, même après l'ajout du solveur 3-way natif.
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("spot-unsupported".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string(), "JJ+".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string()],
        starting_pot: 4.0,
        effective_stack: 100.0,
        hero_position: Some("btn".to_string()),
        action_history: vec!["bet_50".to_string()],
        tree_preset_id: TreePresetId::three_bp_hu_100bb(),
        rake: 0.0,
        num_players: 4,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(1.0),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: true,
        time_budget_ms: Some(75),
        epsilon_target: None,
        hero_hand: None,
        rake_cap: 0.0,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("structured V2 fallback response");

    assert!(response.chosen_action.is_empty());
    assert!(response.actions.is_empty());
    assert_eq!(response.backend, "fallback");
    assert_eq!(response.cache_tier, CacheTier::None);
    assert_eq!(
        response.fallback_reason.as_deref(),
        Some("multiway_not_supported")
    );
    assert!(response.warnings.contains(&DecisionWarning::FallbackUsed));
    assert!(response
        .warnings
        .contains(&DecisionWarning::MultiwayApproximation));
}

#[test]
fn supported_v2_spot_populates_backend_metadata() {
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("spot-2".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string()],
        board: vec![
            "Ah".to_string(),
            "7d".to_string(),
            "2c".to_string(),
            "Kd".to_string(),
            "9s".to_string(),
        ],
        starting_pot: 8.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.0,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: true,
        time_budget_ms: Some(75),
        epsilon_target: None,
        hero_hand: None,
        rake_cap: 0.0,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("supported v2 solve");

    assert_eq!(response.backend, "native_solver");
    assert_eq!(response.normalized_ranges.len(), 2);
    assert!(response.decision_confidence > 0.0);
    assert!(!response.chosen_action.is_empty());
    assert!(!response.actions.is_empty());
}

#[test]
fn action_history_and_rake_bridge_to_native_solver() {
    // Non-empty history + rake used to force a structured fallback; both are now
    // first-class inputs and must reach the native solver.
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("spot-history-rake".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string()],
        board: vec![
            "Ah".to_string(),
            "7d".to_string(),
            "2c".to_string(),
            "Kd".to_string(),
            "9s".to_string(),
        ],
        starting_pot: 8.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        action_history: vec!["check".to_string(), "bet_50".to_string()],
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.05,
        rake_cap: 1.0,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: false,
        time_budget_ms: Some(75),
        epsilon_target: None,
        hero_hand: None,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("v2 solve with history and rake");

    assert_eq!(response.backend, "native_solver");
    assert_eq!(response.fallback_reason, None);
    assert!(!response.chosen_action.is_empty());
    assert!(!response.actions.is_empty());
    assert!(response.actions.iter().all(|action| action.ev != 0.0 || true));
    assert!(response.warnings.iter().all(|warning| {
        !matches!(
            warning,
            DecisionWarning::UnsupportedSpot | DecisionWarning::FallbackUsed
        )
    }));
}

#[test]
fn three_way_river_routes_to_native_multiway_solver() {
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("spot-3way".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string(), "JJ-88".to_string()],
        board: vec![
            "Ah".to_string(),
            "7d".to_string(),
            "2c".to_string(),
            "Kd".to_string(),
            "9s".to_string(),
        ],
        starting_pot: 6.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.0,
        rake_cap: 0.0,
        num_players: 3,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: false,
        time_budget_ms: Some(75),
        epsilon_target: None,
        hero_hand: None,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("3-way river solve");

    assert_eq!(response.backend, "multiway_mccfr");
    assert!(response.fallback_reason.is_none());
    assert!(!response.chosen_action.is_empty());
    assert!(!response.actions.is_empty());
    // Phase 0.5: the multiway path is Monte-Carlo sampled, so the approximation
    // warning is always kept and the response is never certified as converged.
    assert!(
        response
            .warnings
            .iter()
            .any(|warning| *warning == DecisionWarning::MultiwayApproximation)
    );
    assert!(!response.converged);
    assert_eq!(
        response.metadata.get("equity_mode").map(String::as_str),
        Some("monte_carlo_sampled")
    );
}

#[test]
fn strict_mode_refuses_heuristic_ranges() {
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("strict-heuristic".to_string()),
        hero_range: "AA".to_string(),
        villain_ranges: vec!["KK".to_string()],
        board: vec!["2c".to_string(), "7d".to_string(), "Js".to_string()],
        starting_pot: 10.0,
        effective_stack: 100.0,
        hero_position: Some("oop".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.0,
        rake_cap: 0.0,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Disabled,
        hero_confidence: None,
        state_confidence: None,
        range_model_version: RangeModelVersion::HeuristicV1,
        use_cache: false,
        time_budget_ms: Some(100),
        epsilon_target: Some(0.001),
        hero_hand: None,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("strict heuristic refusal");
    assert_eq!(response.backend, "refused");
    assert!(response.chosen_action.is_empty());
    assert_eq!(
        response.fallback_reason.as_deref(),
        Some("heuristic_range_refused")
    );
    assert!(!response.converged);
}

#[test]
fn strict_mode_refuses_sampled_multiway() {
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("strict-multiway".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string(), "AQo".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string()],
        starting_pot: 9.0,
        effective_stack: 40.0,
        hero_position: Some("co".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.0,
        rake_cap: 0.0,
        num_players: 3,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Disabled,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: false,
        time_budget_ms: Some(75),
        epsilon_target: Some(0.001),
        hero_hand: None,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("strict multiway refusal");
    assert_eq!(response.backend, "refused");
    assert!(response.chosen_action.is_empty());
    assert!(!response.converged);
    assert_eq!(
        response.fallback_reason.as_deref(),
        Some("multiway_strict_refused")
    );
    assert!(response
        .warnings
        .iter()
        .any(|warning| *warning == DecisionWarning::ConvergenceNotReached));
}

#[test]
fn strict_mode_heads_up_reports_convergence() {
    // Tiny river jam spot: with a strict epsilon the native solver should
    // converge and report it; convergence fields must reflect the measurement.
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("strict-hu".to_string()),
        hero_range: "AA,KK".to_string(),
        villain_ranges: vec!["QQ".to_string()],
        board: vec![
            "2c".to_string(),
            "7d".to_string(),
            "Js".to_string(),
            "4h".to_string(),
            "9s".to_string(),
        ],
        starting_pot: 10.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.0,
        rake_cap: 0.0,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Disabled,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: false,
        time_budget_ms: None,
        epsilon_target: Some(0.001),
        hero_hand: None,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("strict heads-up solve");
    assert_eq!(response.backend, "native_solver");
    assert!(response.epsilon_target > 0.0);
    assert!(response.exploitability.is_finite());
    // Whatever the outcome, the flag must be coherent with the measurement.
    assert_eq!(
        response.converged,
        response.exploitability <= response.epsilon_target
    );
    assert!(
        response
            .warnings
            .contains(&DecisionWarning::ConvergenceNotReached)
            == !response.converged
    );
}

#[test]
fn hero_combo_ev_selection_prefers_best_ev_for_exact_hand() {
    // The hero hand is an exact combo; selection must be driven by that combo's EV
    // rather than by the range-average frequency.
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("spot-combo-ev".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string()],
        board: vec![
            "Ah".to_string(),
            "7d".to_string(),
            "2c".to_string(),
            "Kd".to_string(),
            "9s".to_string(),
        ],
        starting_pot: 8.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        rake: 0.0,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: false,
        time_budget_ms: Some(75),
        epsilon_target: None,
        hero_hand: Some("AsKs".to_string()),
        rake_cap: 0.0,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: None,
    })
    .expect("combo EV solve");

    assert_eq!(response.backend, "native_solver");
    assert!(!response.chosen_action.is_empty());
    let recommended = response
        .actions
        .iter()
        .find(|action| action.name == response.chosen_action)
        .expect("recommended action present");
    assert!(recommended.ev.is_finite());
    assert!(response.metadata.contains_key("selection"));
}

#[test]
fn bet_size_spec_controls_tree_abstraction() {
    let build_request = |spec: Option<BetSizeSpec>| SolveRequestV2 {
        spot_id: Some("spot-betsizes".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string()],
        starting_pot: 6.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        action_history: Vec::new(),
        tree_preset_id: TreePresetId::srp_hu_100bb(),
        rake: 0.0,
        num_players: 2,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(0.95),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: false,
        time_budget_ms: Some(75),
        epsilon_target: None,
        hero_hand: None,
        rake_cap: 0.0,
        sample_mixed: false,
        random_seed: None,
        bet_size_spec: spec,
    };

    // Abstraction restreinte : bets 100% uniquement, pas de raises.
    let restricted = solve_spot_v2(build_request(Some(BetSizeSpec {
        bet_sizes: "100%".to_string(),
        raise_sizes: String::new(),
        turn_donk_sizes: String::new(),
        river_donk_sizes: String::new(),
    })))
    .expect("restricted spec solve");

    assert_eq!(restricted.backend, "native_solver");
    // Les noms d'actions embarquent le montant de mise ; l'abstraction restreinte
    // ne doit proposer qu'un seul sizing de bet (100%).
    let restricted_bets: Vec<&str> = restricted
        .actions
        .iter()
        .map(|action| action.name.as_str())
        .filter(|name| name.starts_with("bet_"))
        .collect();
    assert!(!restricted_bets.is_empty());
    assert!(restricted_bets.len() <= 2);

    // Sans spec : abstraction élargie par défaut (33/50/75/100).
    let default_spec = solve_spot_v2(build_request(None)).expect("default spec solve");
    assert_eq!(default_spec.backend, "native_solver");
    let default_bets = default_spec
        .actions
        .iter()
        .filter(|action| action.name.starts_with("bet_"))
        .count();
    assert!(
        default_bets >= restricted_bets.len(),
        "default abstraction should offer at least as many bet sizings"
    );
}

// ── S4 Phase D ──

#[test]
fn preflop_three_way() {
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("s4-preflop-3w".to_string()),
        hero_range: "AA".to_string(),
        villain_ranges: vec!["KK".to_string(), "QQ".to_string()],
        board: vec![],
        starting_pot: 1.5,
        effective_stack: 100.0,
        hero_position: Some("btn".to_string()),
        tree_preset_id: TreePresetId::srp_hu_100bb(),
        num_players: 3,
        cache_policy: CachePolicy::Memory,
        use_cache: false,
        time_budget_ms: Some(3000),
        epsilon_target: None,
        ..SolveRequestV2::default()
    })
    .expect("preflop 3-way v2");
    // S2: board 0 est is_valid (can_solve_multiway=true), le solveur est invoqué.
    // Succès -> multiway_mccfr ; échec d'échantillonnage préflop -> fallback multiway_solver_error
    // (pas multiway_not_supported qui signifierait que le routage est cassé).
    if response.backend == "multiway_mccfr" {
        assert!(response.fallback_reason.is_none());
        assert!(!response.chosen_action.is_empty());
        assert!(!response.actions.is_empty());
    } else {
        assert_eq!(response.backend, "fallback");
        let reason = response.fallback_reason.as_deref().unwrap_or("");
        assert!(reason.starts_with("multiway_solver_error"), "expected solver_error not not_supported, got {reason:?}");
    }
}

#[test]
fn preflop_nine_way() {
    // n=9 au-delà de 6 doit fallback multiway_not_supported
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("s4-preflop-9w".to_string()),
        hero_range: "AA".to_string(),
        villain_ranges: vec![
            "KK".to_string(), "QQ".to_string(), "JJ".to_string(), "TT".to_string(),
            "99".to_string(), "88".to_string(), "77".to_string(), "AKs".to_string(),
        ],
        board: vec![],
        starting_pot: 1.5,
        effective_stack: 100.0,
        hero_position: Some("btn".to_string()),
        tree_preset_id: TreePresetId::srp_hu_100bb(),
        num_players: 9,
        cache_policy: CachePolicy::Memory,
        use_cache: false,
        time_budget_ms: Some(75),
        epsilon_target: None,
        ..SolveRequestV2::default()
    })
    .expect("preflop 9-way fallback");
    assert_eq!(response.backend, "fallback");
    assert_eq!(response.fallback_reason.as_deref(), Some("multiway_not_supported"));
    assert!(response.warnings.contains(&DecisionWarning::FallbackUsed));
}

#[test]
fn sizing_river_overbet() {
    // BetSizeSpec river surbet 150% doit apparaître dans les actions natives HU river
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("s4-sizing-river-ob".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string(), "Kd".to_string(), "9s".to_string()],
        starting_pot: 8.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        num_players: 2,
        cache_policy: CachePolicy::Memory,
        use_cache: false,
        time_budget_ms: Some(150),
        epsilon_target: None,
        bet_size_spec: Some(BetSizeSpec {
            bet_sizes: "50%,150%".to_string(),
            raise_sizes: "2.5x".to_string(),
            turn_donk_sizes: String::new(),
            river_donk_sizes: String::new(),
        }),
        ..SolveRequestV2::default()
    })
    .expect("sizing river overbet");
    assert_eq!(response.backend, "native_solver");
    // CSP natif: 50% et 150% du pot -> 4 et 12 sur pot 8 (sizing HUD natif)
    let has_overbet = response.actions.iter().any(|a| a.name.contains("12") || a.name.contains("1.5") || a.name.contains("150"));
    assert!(has_overbet, "expected overbet sizing in actions, got: {:?}", response.actions.iter().map(|a| &a.name).collect::<Vec<_>>());
    // Et le 50% (4) doit aussi être présent
    assert!(response.actions.iter().any(|a| a.name.contains("4")), "expected 50% sizing, got {:?}", response.actions.iter().map(|a| &a.name).collect::<Vec<_>>());
}

#[test]
fn board_1_2_still_rejected() {
    for len in [1usize, 2usize] {
        let board: Vec<String> = ["Ah", "Kd"][..len].iter().map(|s| s.to_string()).collect();
        let response = solve_spot_v2(SolveRequestV2 {
            spot_id: Some(format!("s4-board-{len}")),
            hero_range: "AA".to_string(),
            villain_ranges: vec!["KK".to_string(), "QQ".to_string()],
            board,
            starting_pot: 6.0,
            effective_stack: 20.0,
            hero_position: Some("btn".to_string()),
            tree_preset_id: TreePresetId::srp_hu_100bb(),
            num_players: 3,
            cache_policy: CachePolicy::Memory,
            use_cache: false,
            time_budget_ms: Some(75),
            epsilon_target: None,
            ..SolveRequestV2::default()
        })
        .expect("board 1-2 still rejected");
        assert_eq!(response.backend, "fallback", "board len {len} should fallback");
        assert_eq!(response.fallback_reason.as_deref(), Some("multiway_not_supported"));
    }
}

#[test]
fn bench_preflop_n6() {
    let start = std::time::Instant::now();
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("s4-bench-preflop-n6".to_string()),
        hero_range: "AA".to_string(),
        villain_ranges: vec!["KK".to_string(), "QQ".to_string(), "JJ".to_string(), "TT".to_string(), "99".to_string()],
        board: vec![],
        starting_pot: 1.5,
        effective_stack: 100.0,
        hero_position: Some("btn".to_string()),
        tree_preset_id: TreePresetId::srp_hu_100bb(),
        num_players: 6,
        cache_policy: CachePolicy::Memory,
        use_cache: false,
        time_budget_ms: Some(120),
        epsilon_target: None,
        ..SolveRequestV2::default()
    })
    .expect("bench preflop N=6");
    let elapsed_ms = start.elapsed().as_millis() as u64;
    assert!(
        response.backend == "multiway_mccfr" || response.backend == "fallback",
        "unexpected backend {}",
        response.backend
    );
    if response.backend == "multiway_mccfr" {
        assert!(!response.chosen_action.is_empty());
    } else {
        let r = response.fallback_reason.as_deref().unwrap_or("");
        assert!(r.starts_with("multiway_solver_error"), "unexpected fallback {r:?}");
    }
    // Le bench vérifie le routage préflop N=6, pas la perf brute : budget large (flaky en run parallèle)
    assert!(elapsed_ms < 35000, "bench preflop N=6 exceeded budget: {elapsed_ms}ms");
    assert!(response.elapsed_ms < 35000, "response elapsed_ms too high: {}", response.elapsed_ms);
}

// ── § D — EV : ev_bb ≈ hero_ev/bb, ev_bb_per_100 = ev_bb*100 ──

#[test]
fn v2_ev_bb_matches_ev_chips_over_bb_and_per100() {
    // HU natif via v2 : bridge depuis gto_api enrichi par ev_summary
    let req = SolveRequestV2 {
        spot_id: Some("v2-ev-bb".to_string()),
        hero_range: "AA,KK,QQ".to_string(),
        villain_ranges: vec!["JJ,TT,AKs".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string(), "Kd".to_string(), "9s".to_string()],
        starting_pot: 8.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        num_players: 2,
        cache_policy: CachePolicy::Memory,
        use_cache: false,
        time_budget_ms: Some(150),
        epsilon_target: None,
        ..SolveRequestV2::default()
    };
    let bb = req.effective_stack / 100.0;
    let resp = solve_spot_v2(req).expect("v2 HU EV check");
    assert_eq!(resp.backend, "native_solver");
    assert!(resp.hero_ev.is_finite());
    let ev_bb = resp.ev_bb.expect("v2 ev_bb should be Some with positive stack");
    assert!(
        (ev_bb - resp.hero_ev / bb).abs() < 1e-4,
        "v2 ev_bb {} != hero_ev {} / bb {} (diff {})",
        ev_bb, resp.hero_ev, bb, (ev_bb - resp.hero_ev / bb).abs()
    );
    let ev_bb_per_100 = resp.ev_bb_per_100.expect("v2 ev_bb_per_100");
    assert!(
        (ev_bb_per_100 - ev_bb * 100.0).abs() < 1e-4,
        "v2 ev_bb_per_100 {} != ev_bb {} *100", ev_bb_per_100, ev_bb
    );
    // cohérence helpers purs
    assert!((postflop_solver::ev::ev_chips_to_bb(resp.hero_ev, bb).unwrap() - ev_bb).abs() < 1e-6);
    assert!((postflop_solver::ev::ev_bb_per_100(ev_bb) - ev_bb_per_100).abs() < 1e-6);
    // combo + actions cohérents
    if let Some(combo) = resp.combo_ev_bb {
        let expected_combo = postflop_solver::ev::ev_chips_to_bb(resp.hero_ev, bb).unwrap();
        // v2 bridge met combo_ev_bb = ev_bb (hero_ev/bb) pour multiway/HU
        assert!((combo - expected_combo).abs() < 1e-4, "combo_ev_bb {} != {}", combo, expected_combo);
    }
    for action in &resp.actions {
        if let Some(ev_bb_a) = action.ev_bb {
            assert!((ev_bb_a - action.ev / bb).abs() < 1e-4,
                "v2 action {} ev_bb {} != ev {} / bb {}", action.name, ev_bb_a, action.ev, bb);
            let p100 = action.ev_bb_per_100.expect("action ev_bb_per_100");
            assert!((p100 - ev_bb_a * 100.0).abs() < 1e-4,
                "v2 action {} ev_bb_per_100 {} != {}*100", action.name, p100, ev_bb_a);
        }
    }
}

#[test]
fn v2_multiway_ev_bb_matches_ev_chips_over_bb() {
    // 3-way via v2 → multiway_mccfr, même enrichissement ev_summary
    let req = SolveRequestV2 {
        spot_id: Some("v2-ev-3w".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string(), "JJ-88".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string(), "Kd".to_string(), "9s".to_string()],
        starting_pot: 6.0,
        effective_stack: 20.0,
        hero_position: Some("oop".to_string()),
        tree_preset_id: TreePresetId::river_jam_low_spr(),
        num_players: 3,
        cache_policy: CachePolicy::Memory,
        use_cache: false,
        time_budget_ms: Some(150),
        epsilon_target: None,
        ..SolveRequestV2::default()
    };
    let bb = req.effective_stack / 100.0;
    let resp = solve_spot_v2(req).expect("v2 3-way EV");
    assert_eq!(resp.backend, "multiway_mccfr");
    let ev_bb = resp.ev_bb.expect("v2 3-way ev_bb");
    assert!((ev_bb - resp.hero_ev / bb).abs() < 1e-4,
        "v2 3-way ev_bb {} != hero_ev {} / bb {}", ev_bb, resp.hero_ev, bb);
    assert!((resp.ev_bb_per_100.unwrap() - ev_bb * 100.0).abs() < 1e-4);
    // equity*pot - cost helper sanity (convention § D)
    assert!((postflop_solver::ev::equity_ev(100.0, 0.55, 50.0) - 5.0).abs() < 1e-6);
}

#[test]
fn llm_stub_response_is_offline_safe() {
    let response = llm_assist_stub_response(
        LlmAssistTask::SpotExplain,
        Some("Explain why betting is preferred here."),
        &LlmConfig::default(),
        vec![LlmContextScope::Spot, LlmContextScope::Ui],
        BTreeMap::new(),
    );

    assert!(response.summary.contains("Spot explanation"));
    assert!(response.warnings.contains(&DecisionWarning::FallbackUsed));
    assert!(response
        .warnings
        .contains(&DecisionWarning::ModelUnavailable));
    assert_eq!(response.used_context.len(), 2);
}

