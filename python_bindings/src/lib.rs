use postflop_solver::{
    evaluate_equity as evaluate_equity_native, llm_assist_stub_response, range_relative_strength as range_relative_strength_native,
    solve_spot as solve_spot_native, solve_spot_v2 as solve_spot_v2_native, ActionOptionV2,
    CachePolicy, CacheTier, DecisionWarning, EquityMode, EquityRequest, EquityResponse,
    LlmAssistResponse, LlmAssistTask, LlmConfig, LlmContextScope, LlmPrivacyMode,
    LlmProviderMode, RangeModelVersion, RangeStrengthRequest, RangeStrengthResponse,
    SolveActionV2, SolveRequest, SolveRequestV2, SolveResponse, SolveResponseV2, TreePresetId,
    WinnerTypeDetail,
};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::{collections::BTreeMap, time::Instant};

#[pyfunction]
#[pyo3(signature = (
    oop_range,
    ip_range,
    board,
    starting_pot,
    effective_stack,
    hero_is_oop,
    max_iterations = 200,
    target_exploitability = 0.5,
    use_cache = true
))]
fn solve_spot(
    py: Python<'_>,
    oop_range: String,
    ip_range: String,
    board: Vec<String>,
    starting_pot: f64,
    effective_stack: f64,
    hero_is_oop: bool,
    max_iterations: u32,
    target_exploitability: f64,
    use_cache: bool,
) -> PyResult<PyObject> {
    let request = SolveRequest {
        oop_range,
        ip_range,
        board: trim_cards(board),
        starting_pot: starting_pot as f32,
        effective_stack: effective_stack as f32,
        hero_is_oop,
        max_iterations,
        target_exploitability: target_exploitability as f32,
        use_cache,
    };

    let response =
        solve_spot_native(request).map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
    solve_response_to_python(py, response)
}

#[pyfunction]
#[pyo3(signature = (
    hero_hand,
    villain_ranges,
    board,
    dead_cards = Vec::new(),
    mode = "auto".to_string(),
    max_samples = 5000,
    seed = None,
    use_cache = true
))]
fn evaluate_equity(
    py: Python<'_>,
    hero_hand: Vec<String>,
    villain_ranges: Vec<String>,
    board: Vec<String>,
    dead_cards: Vec<String>,
    mode: String,
    max_samples: u32,
    seed: Option<u64>,
    use_cache: bool,
) -> PyResult<PyObject> {
    let request = EquityRequest {
        hero_hand: trim_cards(hero_hand),
        villain_ranges: trim_cards(villain_ranges),
        board: trim_cards(board),
        dead_cards: trim_cards(dead_cards),
        mode: parse_mode(&mode)?,
        max_samples,
        seed,
        use_cache,
    };

    let response = evaluate_equity_native(request)
        .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
    equity_response_to_python(py, response)
}

#[pyfunction]
#[pyo3(signature = (
    hero_hand,
    hero_range,
    villain_ranges,
    board,
    dead_cards = Vec::new(),
    mode = "auto".to_string(),
    max_samples = 5000,
    seed = None,
    use_cache = true
))]
fn range_relative_strength(
    py: Python<'_>,
    hero_hand: Vec<String>,
    hero_range: String,
    villain_ranges: Vec<String>,
    board: Vec<String>,
    dead_cards: Vec<String>,
    mode: String,
    max_samples: u32,
    seed: Option<u64>,
    use_cache: bool,
) -> PyResult<PyObject> {
    let request = RangeStrengthRequest {
        hero_hand: trim_cards(hero_hand),
        hero_range: hero_range.trim().to_string(),
        villain_ranges: trim_cards(villain_ranges),
        board: trim_cards(board),
        dead_cards: trim_cards(dead_cards),
        mode: parse_mode(&mode)?,
        max_samples,
        seed,
        use_cache,
    };

    let response = range_relative_strength_native(request)
        .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
    range_strength_response_to_python(py, response)
}

#[pyfunction]
#[pyo3(signature = (
    hero_range,
    villain_ranges,
    board,
    starting_pot,
    effective_stack,
    hero_position = None,
    action_history = Vec::new(),
    tree_preset_id = None,
    rake = None,
    num_players = None,
    spot_id = None,
    legal_actions = Vec::new(),
    cache_policy = None,
    hero_confidence = None,
    state_confidence = None,
    use_cache = true,
    time_budget_ms = None
))]
fn solve_spot_v2(
    py: Python<'_>,
    hero_range: String,
    villain_ranges: Vec<String>,
    board: Vec<String>,
    starting_pot: f64,
    effective_stack: f64,
    hero_position: Option<String>,
    action_history: Vec<String>,
    tree_preset_id: Option<String>,
    rake: Option<f64>,
    num_players: Option<u32>,
    spot_id: Option<String>,
    legal_actions: Vec<String>,
    cache_policy: Option<String>,
    hero_confidence: Option<f64>,
    state_confidence: Option<f64>,
    use_cache: bool,
    time_budget_ms: Option<u64>,
) -> PyResult<PyObject> {
    let request = SolveRequestV2 {
        spot_id: normalize_optional_string(spot_id),
        hero_range,
        villain_ranges: trim_cards(villain_ranges),
        board: trim_cards(board),
        starting_pot: starting_pot as f32,
        effective_stack: effective_stack as f32,
        hero_position: normalize_optional_string(hero_position),
        action_history: trim_cards(action_history),
        tree_preset_id: normalize_optional_string(tree_preset_id)
            .map(TreePresetId::from)
            .unwrap_or_default(),
        rake: rake.unwrap_or(0.0) as f32,
        num_players: num_players.unwrap_or(2) as u8,
        legal_actions: action_options_from_names(legal_actions),
        cache_policy: parse_cache_policy(cache_policy.as_deref()),
        hero_confidence: hero_confidence.map(|value| value as f32),
        state_confidence: state_confidence.map(|value| value as f32),
        range_model_version: RangeModelVersion::BoardAwareV2,
        use_cache,
        time_budget_ms,
    };
    let started = Instant::now();
    let mut response =
        solve_spot_v2_native(request).map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
    response.elapsed_ms = started.elapsed().as_millis() as u64;
    solve_spot_v2_response_to_python(py, response)
}

#[pyfunction]
#[pyo3(signature = (
    task,
    prompt = None,
    provider_mode = None,
    model = None,
    base_url = None,
    enabled = false,
    temperature = None,
    max_output_tokens = None,
    streaming = None,
    spot_summary = None
))]
fn llm_assist_stub(
    py: Python<'_>,
    task: String,
    prompt: Option<String>,
    provider_mode: Option<String>,
    model: Option<String>,
    base_url: Option<String>,
    enabled: bool,
    temperature: Option<f64>,
    max_output_tokens: Option<u32>,
    streaming: Option<bool>,
    spot_summary: Option<String>,
) -> PyResult<PyObject> {
    let config = LlmConfig {
        enabled,
        provider_mode: parse_provider_mode(provider_mode.as_deref()),
        base_url: normalize_optional_string(base_url),
        api_key_ref: None,
        model: normalize_optional_string(model),
        temperature: temperature.unwrap_or(0.2) as f32,
        max_output_tokens: max_output_tokens.unwrap_or(512),
        streaming: streaming.unwrap_or(false),
        roles_enabled: Vec::new(),
        context_scopes_enabled: Vec::new(),
        privacy_mode: if enabled {
            LlmPrivacyMode::RedactedRemote
        } else {
            LlmPrivacyMode::StrictLocal
        },
    };
    let mut metadata = BTreeMap::new();
    if let Some(spot_summary) = normalize_optional_string(spot_summary) {
        metadata.insert("spot_summary".to_string(), truncate_for_log(&spot_summary));
    }

    let started = Instant::now();
    let mut response = llm_assist_stub_response(
        parse_llm_task(&task),
        prompt.as_deref(),
        &config,
        vec![LlmContextScope::Ui],
        metadata,
    );
    response.latency_ms = started.elapsed().as_millis() as u64;
    llm_assist_response_to_python(py, response)
}

fn trim_cards(values: Vec<String>) -> Vec<String> {
    values.into_iter().map(|value| value.trim().to_string()).collect()
}

fn normalize_optional_string(value: Option<String>) -> Option<String> {
    value.and_then(|value| {
        let trimmed = value.trim().to_string();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    })
}

fn parse_mode(mode: &str) -> PyResult<EquityMode> {
    match mode.trim().to_ascii_lowercase().as_str() {
        "" | "auto" => Ok(EquityMode::Auto),
        "exact" => Ok(EquityMode::Exact),
        "monte_carlo" | "montecarlo" | "monte-carlo" => Ok(EquityMode::MonteCarlo),
        value => Err(PyValueError::new_err(format!(
            "unsupported mode '{value}', expected auto|exact|monte_carlo"
        ))),
    }
}

fn solve_response_to_python(py: Python<'_>, response: SolveResponse) -> PyResult<PyObject> {
    let result = PyDict::new(py);
    result.set_item("recommended_action", response.recommended_action)?;
    result.set_item("hero_ev", response.hero_ev)?;
    result.set_item("exploitability", response.exploitability)?;
    result.set_item("cache_hit", response.cache_hit)?;
    result.set_item("elapsed_ms", response.elapsed_ms)?;
    result.set_item("actions", action_list_to_python(py, response.actions)?)?;
    Ok(result.into())
}

fn equity_response_to_python(py: Python<'_>, response: EquityResponse) -> PyResult<PyObject> {
    let result = PyDict::new(py);
    result.set_item("equity", response.equity)?;
    result.set_item("win_rate", response.win_rate)?;
    result.set_item("tie_rate", response.tie_rate)?;
    result.set_item("mode_used", response.mode_used)?;
    result.set_item("samples", response.samples)?;
    result.set_item("cache_hit", response.cache_hit)?;
    result.set_item("elapsed_ms", response.elapsed_ms)?;
    result.set_item("winner_types", winner_types_to_python(py, response.winner_types)?)?;
    Ok(result.into())
}

fn range_strength_response_to_python(
    py: Python<'_>,
    response: RangeStrengthResponse,
) -> PyResult<PyObject> {
    let result = PyDict::new(py);
    result.set_item("relative_strength", response.relative_strength)?;
    result.set_item("hero_equity", response.hero_equity)?;
    result.set_item("range_average_equity", response.range_average_equity)?;
    result.set_item("weighted_percentile", response.weighted_percentile)?;
    result.set_item("combos_ranked", response.combos_ranked)?;
    result.set_item("mode_used", response.mode_used)?;
    result.set_item("elapsed_ms", response.elapsed_ms)?;
    Ok(result.into())
}

fn solve_spot_v2_response_to_python(
    py: Python<'_>,
    response: SolveResponseV2,
) -> PyResult<PyObject> {
    let result = PyDict::new(py);
    result.set_item("chosen_action", response.chosen_action)?;
    result.set_item("actions", solve_actions_v2_to_python(py, response.actions)?)?;
    result.set_item("hero_ev", response.hero_ev)?;
    result.set_item("exploitability", response.exploitability)?;
    result.set_item("backend", response.backend)?;
    result.set_item("cache_tier", cache_tier_name(response.cache_tier))?;
    result.set_item(
        "normalized_ranges",
        strings_to_python_list(py, response.normalized_ranges)?,
    )?;
    result.set_item("decision_confidence", response.decision_confidence)?;
    result.set_item("fallback_reason", response.fallback_reason)?;
    result.set_item("cache_hit", response.cache_hit)?;
    result.set_item("elapsed_ms", response.elapsed_ms)?;
    result.set_item("preset_id", response.preset_id.to_string())?;
    result.set_item("warnings", warning_list_to_python(py, response.warnings)?)?;
    Ok(result.into())
}

fn llm_assist_response_to_python(
    py: Python<'_>,
    response: LlmAssistResponse,
) -> PyResult<PyObject> {
    let result = PyDict::new(py);
    result.set_item("summary", response.summary)?;
    result.set_item(
        "recommendations",
        strings_to_python_list(py, response.recommendations)?,
    )?;
    result.set_item("warnings", warning_list_to_python(py, response.warnings)?)?;
    result.set_item("confidence", response.confidence)?;
    result.set_item(
        "used_context",
        llm_context_list_to_python(py, response.used_context)?,
    )?;
    result.set_item("latency_ms", response.latency_ms)?;
    result.set_item("provider_metadata", map_to_python_dict(py, response.provider_metadata)?)?;
    Ok(result.into())
}

fn solve_actions_v2_to_python(
    py: Python<'_>,
    actions: Vec<SolveActionV2>,
) -> PyResult<Bound<'_, PyList>> {
    let list = PyList::empty(py);
    for action in actions {
        let item = PyDict::new(py);
        item.set_item("name", action.name)?;
        item.set_item("label", action.label)?;
        item.set_item("size", action.size)?;
        item.set_item("frequency", action.frequency)?;
        item.set_item("ev", action.ev)?;
        item.set_item("is_recommended", action.is_recommended)?;
        list.append(item)?;
    }
    Ok(list)
}

fn strings_to_python_list(py: Python<'_>, values: Vec<String>) -> PyResult<Bound<'_, PyList>> {
    let list = PyList::empty(py);
    for value in values {
        list.append(value)?;
    }
    Ok(list)
}

fn map_to_python_dict(
    py: Python<'_>,
    values: BTreeMap<String, String>,
) -> PyResult<Bound<'_, PyDict>> {
    let result = PyDict::new(py);
    for (key, value) in values {
        result.set_item(key, value)?;
    }
    Ok(result)
}

fn truncate_for_log(value: &str) -> String {
    let value = value.trim();
    const MAX_LEN: usize = 120;
    if value.len() <= MAX_LEN {
        value.to_string()
    } else {
        let truncated: String = value.chars().take(MAX_LEN).collect();
        format!("{}...", truncated)
    }
}

fn warning_list_to_python(
    py: Python<'_>,
    warnings: Vec<DecisionWarning>,
) -> PyResult<Bound<'_, PyList>> {
    let list = PyList::empty(py);
    for warning in warnings {
        list.append(decision_warning_name(warning))?;
    }
    Ok(list)
}

fn llm_context_list_to_python(
    py: Python<'_>,
    contexts: Vec<LlmContextScope>,
) -> PyResult<Bound<'_, PyList>> {
    let list = PyList::empty(py);
    for context in contexts {
        list.append(llm_context_name(context))?;
    }
    Ok(list)
}

fn parse_provider_mode(mode: Option<&str>) -> LlmProviderMode {
    match mode.map(|value| value.trim().to_ascii_lowercase()) {
        Some(value) if value == "openai_compatible_remote" => {
            LlmProviderMode::OpenaiCompatibleRemote
        }
        Some(value) if value == "openai_compatible_local" => {
            LlmProviderMode::OpenaiCompatibleLocal
        }
        _ => LlmProviderMode::Disabled,
    }
}

fn parse_cache_policy(policy: Option<&str>) -> CachePolicy {
    match policy.map(|value| value.trim().to_ascii_lowercase()) {
        Some(value) if value == "disabled" => CachePolicy::Disabled,
        Some(value) if value == "persistent" => CachePolicy::Persistent,
        _ => CachePolicy::Memory,
    }
}

fn action_options_from_names(values: Vec<String>) -> Vec<ActionOptionV2> {
    values
        .into_iter()
        .filter_map(|value| {
            let normalized = value.trim().to_string();
            if normalized.is_empty() {
                None
            } else {
                Some(ActionOptionV2 {
                    name: normalized.clone(),
                    label: normalized,
                    size: None,
                    available: true,
                    metadata: BTreeMap::new(),
                })
            }
        })
        .collect()
}

fn parse_llm_task(value: &str) -> LlmAssistTask {
    match value.trim().to_ascii_lowercase().as_str() {
        "line_compare" => LlmAssistTask::LineCompare,
        "decision_rationale" => LlmAssistTask::DecisionRationale,
        "ocr_diagnostic" => LlmAssistTask::OcrDiagnostic,
        "fallback_diagnostic" => LlmAssistTask::FallbackDiagnostic,
        "session_summary" => LlmAssistTask::SessionSummary,
        "strategy_review" => LlmAssistTask::StrategyReview,
        "replay_coach" => LlmAssistTask::ReplayCoach,
        _ => LlmAssistTask::SpotExplain,
    }
}

fn decision_warning_name(warning: DecisionWarning) -> &'static str {
    match warning {
        DecisionWarning::UnsupportedSpot => "unsupported_spot",
        DecisionWarning::ApproximateRanges => "approximate_ranges",
        DecisionWarning::MultiwayApproximation => "multiway_approximation",
        DecisionWarning::Timeout => "timeout",
        DecisionWarning::CacheMiss => "cache_miss",
        DecisionWarning::FallbackUsed => "fallback_used",
        DecisionWarning::OcrLowConfidence => "ocr_low_confidence",
        DecisionWarning::ModelUnavailable => "model_unavailable",
        DecisionWarning::ManualOverride => "manual_override",
        DecisionWarning::Unknown => "unknown",
    }
}

fn cache_tier_name(tier: CacheTier) -> &'static str {
    match tier {
        CacheTier::None => "none",
        CacheTier::Memory => "memory",
        CacheTier::Disk => "disk",
    }
}

fn llm_context_name(scope: LlmContextScope) -> &'static str {
    match scope {
        LlmContextScope::Spot => "spot",
        LlmContextScope::Decision => "decision",
        LlmContextScope::Replay => "replay",
        LlmContextScope::Runtime => "runtime",
        LlmContextScope::Ui => "ui",
        LlmContextScope::Ocr => "ocr",
        LlmContextScope::Solver => "solver",
        LlmContextScope::Metrics => "metrics",
        LlmContextScope::Config => "config",
    }
}

fn action_list_to_python(
    py: Python<'_>,
    actions: Vec<postflop_solver::ActionDetail>,
) -> PyResult<Bound<'_, PyList>> {
    let list = PyList::empty(py);
    for action in actions {
        let item = PyDict::new(py);
        item.set_item("name", action.name)?;
        item.set_item("frequency", action.frequency)?;
        item.set_item("ev", action.ev)?;
        list.append(item)?;
    }
    Ok(list)
}

fn winner_types_to_python(
    py: Python<'_>,
    winner_types: Vec<WinnerTypeDetail>,
) -> PyResult<Bound<'_, PyDict>> {
    let result = PyDict::new(py);
    for winner_type in winner_types {
        result.set_item(winner_type.name, winner_type.frequency)?;
    }
    Ok(result)
}

#[pymodule]
fn postflop_solver_py(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(solve_spot, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_equity, m)?)?;
    m.add_function(wrap_pyfunction!(range_relative_strength, m)?)?;
    m.add_function(wrap_pyfunction!(solve_spot_v2, m)?)?;
    m.add_function(wrap_pyfunction!(llm_assist_stub, m)?)?;
    Ok(())
}
