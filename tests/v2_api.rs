use postflop_solver::{
    llm_assist_stub_response, solve_spot_v2, CachePolicy, CacheTier, DecisionSource,
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
    let response = solve_spot_v2(SolveRequestV2 {
        spot_id: Some("spot-unsupported".to_string()),
        hero_range: "AsKs".to_string(),
        villain_ranges: vec!["QQ+".to_string(), "JJ+".to_string()],
        board: vec!["Ah".to_string(), "7d".to_string(), "2c".to_string()],
        starting_pot: 4.0,
        effective_stack: 100.0,
        hero_position: Some("btn".to_string()),
        action_history: vec!["bet_50".to_string()],
        tree_preset_id: TreePresetId::three_bp_hu_100bb(),
        rake: 0.0,
        num_players: 3,
        legal_actions: Vec::new(),
        cache_policy: CachePolicy::Memory,
        hero_confidence: Some(1.0),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: true,
        time_budget_ms: Some(75),
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
        hero_confidence: Some(1.0),
        state_confidence: Some(0.95),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache: true,
        time_budget_ms: Some(75),
    })
    .expect("supported v2 solve");

    assert_eq!(response.backend, "native_solver");
    assert_eq!(response.normalized_ranges.len(), 2);
    assert!(response.decision_confidence > 0.0);
    assert!(!response.chosen_action.is_empty());
    assert!(!response.actions.is_empty());
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
