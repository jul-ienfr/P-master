use axum::{
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use postflop_solver::{
    evaluate_equity, llm_assist_stub_response, range_relative_strength, solve_spot, solve_spot_v2,
    EquityRequest, EquityResponse, LlmAssistResponse, LlmAssistTask, LlmConfig,
    LlmContextScope, LlmPrivacyMode, LlmProviderMode, RangeStrengthRequest,
    RangeStrengthResponse, SolveRequest, SolveRequestV2, SolveResponse, SolveResponseV2,
};
use serde::Deserialize;
use std::{collections::BTreeMap, net::SocketAddr};
use tower_http::cors::CorsLayer;
use tracing::info;

#[derive(Debug, Clone, Deserialize)]
struct LlmAssistRequestV2 {
    task: String,
    prompt: Option<String>,
    provider_mode: Option<String>,
    model: Option<String>,
    base_url: Option<String>,
    enabled: Option<bool>,
    temperature: Option<f64>,
    max_output_tokens: Option<u32>,
    streaming: Option<bool>,
    spot: Option<SolveRequestV2>,
    #[serde(default)]
    context: BTreeMap<String, String>,
}

async fn solve_handler(
    Json(req): Json<SolveRequest>,
) -> Result<Json<SolveResponse>, (StatusCode, String)> {
    info!(
        "Solve request - board: {:?}, pot: {}, stack: {}",
        &req.board, req.starting_pot, req.effective_stack
    );

    let response =
        solve_spot(req).map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    info!(
        "Solve complete - action: {}, EV: {:.2}, exploitability: {:.3}",
        response.recommended_action.as_str(),
        response.hero_ev,
        response.exploitability
    );

    Ok(Json(response))
}

async fn equity_handler(
    Json(req): Json<EquityRequest>,
) -> Result<Json<EquityResponse>, (StatusCode, String)> {
    info!(
        "Equity request - board: {:?}, villains: {}, mode: {:?}",
        &req.board,
        req.villain_ranges.len(),
        req.mode
    );

    let response =
        evaluate_equity(req).map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;

    info!(
        "Equity complete - equity: {:.3}, mode: {}, cache_hit: {}",
        response.equity,
        response.mode_used,
        response.cache_hit
    );

    Ok(Json(response))
}

async fn range_strength_handler(
    Json(req): Json<RangeStrengthRequest>,
) -> Result<Json<RangeStrengthResponse>, (StatusCode, String)> {
    info!(
        "Range strength request - board: {:?}, villains: {}, mode: {:?}",
        &req.board,
        req.villain_ranges.len(),
        req.mode
    );

    let response = range_relative_strength(req)
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;

    info!(
        "Range strength complete - percentile: {:.3}, hero_equity: {:.3}",
        response.relative_strength,
        response.hero_equity
    );

    Ok(Json(response))
}

async fn solve_v2_handler(
    Json(req): Json<SolveRequestV2>,
) -> Result<Json<SolveResponseV2>, (StatusCode, String)> {
    let response =
        solve_spot_v2(req).map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
    Ok(Json(response))
}

async fn llm_assist_v2_handler(
    Json(req): Json<LlmAssistRequestV2>,
) -> Result<Json<LlmAssistResponse>, (StatusCode, String)> {
    let config = build_llm_config(&req);
    let task = parse_llm_task(&req.task);
    let prompt = req.prompt.as_deref();
    let used_context = build_used_context(&req);
    let provider_metadata = build_provider_metadata(&req, &config);
    Ok(Json(llm_assist_stub_response(
        task,
        prompt,
        &config,
        used_context,
        provider_metadata,
    )))
}

async fn health() -> &'static str {
    "gto_server OK"
}

fn build_llm_config(request: &LlmAssistRequestV2) -> LlmConfig {
    LlmConfig {
        enabled: request.enabled.unwrap_or(false),
        provider_mode: parse_provider_mode(request.provider_mode.as_deref()),
        base_url: request
            .base_url
            .as_ref()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty()),
        api_key_ref: None,
        model: request
            .model
            .as_ref()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty()),
        temperature: request.temperature.unwrap_or(0.2) as f32,
        max_output_tokens: request.max_output_tokens.unwrap_or(512),
        streaming: request.streaming.unwrap_or(false),
        roles_enabled: Vec::new(),
        context_scopes_enabled: Vec::new(),
        privacy_mode: if request.enabled.unwrap_or(false) {
            LlmPrivacyMode::RedactedRemote
        } else {
            LlmPrivacyMode::StrictLocal
        },
    }
}

fn build_used_context(request: &LlmAssistRequestV2) -> Vec<LlmContextScope> {
    let mut scopes = Vec::new();

    if request.prompt.as_ref().is_some_and(|value| !value.trim().is_empty()) {
        push_scope(&mut scopes, LlmContextScope::Ui);
    }
    if request.spot.is_some() {
        push_scope(&mut scopes, LlmContextScope::Spot);
        push_scope(&mut scopes, LlmContextScope::Solver);
    }
    if !request.context.is_empty() {
        push_scope(&mut scopes, LlmContextScope::Runtime);
        push_scope(&mut scopes, LlmContextScope::Config);
    }

    scopes
}

fn build_provider_metadata(
    request: &LlmAssistRequestV2,
    config: &LlmConfig,
) -> BTreeMap<String, String> {
    let mut metadata = BTreeMap::new();
    metadata.insert("task".to_string(), request.task.trim().to_string());
    metadata.insert(
        "provider_mode".to_string(),
        provider_mode_name(config.provider_mode).to_string(),
    );
    metadata.insert(
        "privacy_mode".to_string(),
        match config.privacy_mode {
            LlmPrivacyMode::StrictLocal => "strict_local",
            LlmPrivacyMode::RedactedRemote => "redacted_remote",
            LlmPrivacyMode::FullRemote => "full_remote",
        }
        .to_string(),
    );

    if let Some(spot) = request.spot.as_ref() {
        metadata.insert("hero_range".to_string(), spot.hero_range.trim().to_string());
        metadata.insert(
            "villain_ranges".to_string(),
            spot.villain_ranges.len().to_string(),
        );
        metadata.insert("num_players".to_string(), spot.num_players.to_string());
        metadata.insert("preset_id".to_string(), spot.tree_preset_id.to_string());
    }

    for (key, value) in request.context.iter() {
        metadata.insert(format!("context.{key}"), truncate_for_log(value));
    }

    metadata
}

fn parse_provider_mode(value: Option<&str>) -> LlmProviderMode {
    match value.map(|value| value.trim().to_ascii_lowercase()) {
        Some(value) if value == "openai_compatible_remote" => LlmProviderMode::OpenaiCompatibleRemote,
        Some(value) if value == "openai_compatible_local" => LlmProviderMode::OpenaiCompatibleLocal,
        _ => LlmProviderMode::Disabled,
    }
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

fn provider_mode_name(mode: LlmProviderMode) -> &'static str {
    match mode {
        LlmProviderMode::Disabled => "disabled",
        LlmProviderMode::OpenaiCompatibleRemote => "openai_compatible_remote",
        LlmProviderMode::OpenaiCompatibleLocal => "openai_compatible_local",
    }
}

fn truncate_for_log(value: &str) -> String {
    const MAX_LEN: usize = 120;
    let value = value.trim();
    if value.chars().count() <= MAX_LEN {
        value.to_string()
    } else {
        let truncated: String = value.chars().take(MAX_LEN).collect();
        format!("{}...", truncated)
    }
}

fn push_scope(scopes: &mut Vec<LlmContextScope>, scope: LlmContextScope) {
    if !scopes.contains(&scope) {
        scopes.push(scope);
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let app = Router::new()
        .route("/health", get(health))
        .route("/solve", post(solve_handler))
        .route("/equity", post(equity_handler))
        .route("/range-strength", post(range_strength_handler))
        .route("/v2/solve", post(solve_v2_handler))
        .route("/v2/llm/assist", post(llm_assist_v2_handler))
        .layer(CorsLayer::permissive());

    let addr = SocketAddr::from(([127, 0, 0, 1], 8765));
    info!("GTO server listening on http://{addr}");

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
