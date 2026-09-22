use axum::{
    http::{HeaderValue, Method, StatusCode},
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
use std::{collections::BTreeMap, net::SocketAddr, sync::OnceLock, time::Duration};
use tokio::sync::Semaphore;
use tower_http::cors::CorsLayer;
use tracing::{debug, info};

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

/// Per-request timeout for long-running solve calls, overridable via the
/// POKER_SOLVE_TIMEOUT_SECS env var (default 300s), in the same style as the
/// POKER_RUST_LOG / POKER_DEBUG configuration used in main.
fn solve_timeout() -> Duration {
    static TIMEOUT: OnceLock<Duration> = OnceLock::new();
    *TIMEOUT.get_or_init(|| {
        let secs = std::env::var("POKER_SOLVE_TIMEOUT_SECS")
            .ok()
            .and_then(|value| value.trim().parse::<u64>().ok())
            .filter(|secs| *secs > 0)
            .unwrap_or(300);
        Duration::from_secs(secs)
    })
}

/// Limits concurrent CPU-bound solver calls to `available_parallelism - 1`
/// (min 1) so Tokio worker threads stay responsive even under solve load.
fn solve_semaphore() -> &'static Semaphore {
    static SEM: OnceLock<Semaphore> = OnceLock::new();
    SEM.get_or_init(|| {
        let limit = std::thread::available_parallelism()
            .map(|n| n.get().saturating_sub(1).max(1))
            .unwrap_or(1);
        Semaphore::new(limit)
    })
}

/// Maximum time a handler waits for a concurrency permit before shedding
/// load with a 503 instead of piling up requests.
const PERMIT_WAIT: Duration = Duration::from_secs(5);

/// Runs a CPU-bound call on Tokio's blocking thread pool so it cannot block
/// the async worker threads. A JoinError (panic/abort in the solver thread)
/// maps to 500; the solver's own error is returned as `Err(String)` for the
/// caller to map with its handler-specific status code.
async fn spawn_cpu<F, R>(f: F) -> Result<Result<R, String>, (StatusCode, String)>
where
    F: FnOnce() -> Result<R, String> + Send + 'static,
    R: Send + 'static,
{
    tokio::task::spawn_blocking(f).await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("solver worker failed: {e}"),
        )
    })
}

/// Acquires a concurrency permit (bounded wait -> 503 when the server is at
/// capacity), runs the solver call off the async runtime, and applies the
/// given overall timeout (504 when exceeded). /health and other handlers are
/// never limited by this.
async fn run_solver<F, R>(
    timeout: Option<Duration>,
    f: F,
) -> Result<Result<R, String>, (StatusCode, String)>
where
    F: FnOnce() -> Result<R, String> + Send + 'static,
    R: Send + 'static,
{
    let permit = match tokio::time::timeout(PERMIT_WAIT, solve_semaphore().acquire()).await {
        Ok(Ok(permit)) => permit,
        Ok(Err(_)) => {
            return Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                "concurrency limiter closed".to_string(),
            ))
        }
        Err(_) => {
            return Err((
                StatusCode::SERVICE_UNAVAILABLE,
                "server busy: too many concurrent solver requests".to_string(),
            ))
        }
    };

    let join = spawn_cpu(f);
    let result = match timeout {
        Some(limit) => tokio::time::timeout(limit, join).await.map_err(|_| {
            (
                StatusCode::GATEWAY_TIMEOUT,
                format!("solver request timed out after {}s", limit.as_secs()),
            )
        })?,
        None => Ok(join.await?),
    };
    drop(permit);
    result
}

#[tracing::instrument(skip(req), fields(board=?req.board, pot=req.starting_pot))]
async fn solve_handler(
    Json(req): Json<SolveRequest>,
) -> Result<Json<SolveResponse>, (StatusCode, String)> {
    debug!(board=?req.board, pot=req.starting_pot, stack=req.effective_stack, hero_hand=?req.hero_hand, "solve request");

    let response = run_solver(Some(solve_timeout()), move || {
        solve_spot(req).map_err(|e| e.to_string())
    })
    .await?
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e))?;

    debug!(action=%response.recommended_action.as_str(), ev=response.hero_ev, exploitability=response.exploitability, "solve complete");

    Ok(Json(response))
}

#[tracing::instrument(skip(req))]
async fn equity_handler(
    Json(req): Json<EquityRequest>,
) -> Result<Json<EquityResponse>, (StatusCode, String)> {
    debug!(board=?req.board, villains=req.villain_ranges.len(), mode=?req.mode, "equity request");

    let response = run_solver(Some(solve_timeout()), move || {
        evaluate_equity(req).map_err(|e| e.to_string())
    })
    .await?
    .map_err(|e| (StatusCode::BAD_REQUEST, e))?;

    debug!(equity=response.equity, mode=%response.mode_used, cache_hit=response.cache_hit, "equity complete");

    Ok(Json(response))
}

#[tracing::instrument(skip(req))]
async fn range_strength_handler(
    Json(req): Json<RangeStrengthRequest>,
) -> Result<Json<RangeStrengthResponse>, (StatusCode, String)> {
    debug!(board=?req.board, villains=req.villain_ranges.len(), mode=?req.mode, "range strength request");

    let response = spawn_cpu(move || range_relative_strength(req).map_err(|e| e.to_string()))
        .await?
        .map_err(|e| (StatusCode::BAD_REQUEST, e))?;

    debug!(percentile=response.relative_strength, hero_equity=response.hero_equity, "range strength complete");

    Ok(Json(response))
}

#[tracing::instrument(skip(req))]
async fn solve_v2_handler(
    Json(req): Json<SolveRequestV2>,
) -> Result<Json<SolveResponseV2>, (StatusCode, String)> {
    debug!(hero_range=%req.hero_range, board=?req.board, num_players=req.num_players, "solve_v2 request");
    let response = run_solver(Some(solve_timeout()), move || {
        solve_spot_v2(req).map_err(|e| e.to_string())
    })
    .await?
    .map_err(|e| (StatusCode::BAD_REQUEST, e))?;
    debug!(action=%response.chosen_action, ev=response.hero_ev, "solve_v2 complete");
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

fn is_truthy_debug(value: &str) -> bool {
    matches!(
        value.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}

#[tokio::main]
async fn main() {
    let filter = tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| {
        if let Ok(value) = std::env::var("POKER_RUST_LOG") {
            if !value.trim().is_empty() {
                return tracing_subscriber::EnvFilter::new(value);
            }
        }
        let is_debug = std::env::var("POKER_DEBUG")
            .map(|value| is_truthy_debug(&value))
            .unwrap_or(false);
        tracing_subscriber::EnvFilter::new(if is_debug { "debug" } else { "info" })
    });
    tracing_subscriber::fmt().with_env_filter(filter).init();

    let app = Router::new()
        .route("/health", get(health))
        .route("/solve", post(solve_handler))
        .route("/equity", post(equity_handler))
        .route("/range-strength", post(range_strength_handler))
        .route("/v2/solve", post(solve_v2_handler))
        .route("/v2/llm/assist", post(llm_assist_v2_handler))
        .layer(
            CorsLayer::new()
                .allow_origin([
                    "http://127.0.0.1:8765".parse::<HeaderValue>().unwrap(),
                    "http://localhost:8765".parse::<HeaderValue>().unwrap(),
                    "http://127.0.0.1:8005".parse::<HeaderValue>().unwrap(),
                    "http://localhost:8005".parse::<HeaderValue>().unwrap(),
                    "http://127.0.0.1:8006".parse::<HeaderValue>().unwrap(),
                    "http://localhost:8006".parse::<HeaderValue>().unwrap(),
                    "http://127.0.0.1:8080".parse::<HeaderValue>().unwrap(),
                    "http://localhost:8080".parse::<HeaderValue>().unwrap(),
                    "http://127.0.0.1:5173".parse::<HeaderValue>().unwrap(),
                    "http://localhost:5173".parse::<HeaderValue>().unwrap(),
                    "http://127.0.0.1:1420".parse::<HeaderValue>().unwrap(),
                    "http://localhost:1420".parse::<HeaderValue>().unwrap(),
                    "http://tauri.localhost".parse::<HeaderValue>().unwrap(),
                    "https://tauri.localhost".parse::<HeaderValue>().unwrap(),
                ])
                .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
                .allow_headers([
                    axum::http::header::CONTENT_TYPE,
                    axum::http::header::AUTHORIZATION,
                ]),
        );

    let addr = SocketAddr::from(([127, 0, 0, 1], 8765));
    info!("GTO server listening on http://{addr}");

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
