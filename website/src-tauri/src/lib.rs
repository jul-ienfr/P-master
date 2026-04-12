use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::Emitter;
use tauri::Manager;

const RUNTIME_PORT_CANDIDATES: [u16; 2] = [8080, 8005];

struct ManagedRuntimeProcess {
    child: Child,
}

struct AppState {
    started_at: SystemTime,
    started_instant: Instant,
    llm_config: Mutex<LlmConfig>,
    ocr_config: Mutex<OcrConfig>,
    auto_annotator_config: Mutex<AutoAnnotatorConfig>,
    managed_runtime: Mutex<Option<ManagedRuntimeProcess>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub uptime_ms: u64,
    pub started_at_unix_ms: u128,
    pub version: &'static str,
    pub mode: &'static str,
}

#[derive(Debug, Clone, Serialize)]
pub struct VersionResponse {
    pub app_name: &'static str,
    pub version: &'static str,
    pub build_profile: &'static str,
    pub runtime: &'static str,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeConfigResponse {
    pub app_name: &'static str,
    pub version: &'static str,
    pub runtime: &'static str,
    pub dev_mode: bool,
    pub http_fallback_enabled: bool,
    pub llm: LlmConfig,
    pub ocr: OcrConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrConfig {
    pub enabled_engines: Vec<String>,
    pub mode: String,
    pub parallel: bool,
    pub use_gpu: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct OcrStatusResponse {
    pub supported_engines: Vec<String>,
    pub requested_engines: Vec<String>,
    pub loaded_engines: Vec<String>,
    pub unavailable_engines: BTreeMap<String, String>,
    pub mode: String,
    pub parallel: bool,
    pub use_gpu: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrProbeRequest {
    pub image_name: String,
    pub image_base64: String,
    pub field: String,
    pub engines: Vec<String>,
    pub mode: String,
    pub parallel: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrProbeResponse {
    pub success: bool,
    pub field: String,
    pub result: serde_json::Value,
    pub metadata: serde_json::Value,
    pub message: Option<String>,
}

impl Default for OcrConfig {
    fn default() -> Self {
        Self {
            enabled_engines: vec!["doctr".to_string()],
            mode: "consensus_amounts".to_string(),
            parallel: true,
            use_gpu: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderMode {
    Disabled,
    OpenaiCompatibleRemote,
    OpenaiCompatibleLocal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PrivacyMode {
    StrictLocal,
    RedactedRemote,
    FullRemote,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LlmAssistTask {
    SpotExplain,
    LineCompare,
    DecisionRationale,
    OcrDiagnostic,
    FallbackDiagnostic,
    SessionSummary,
    StrategyReview,
    ReplayCoach,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmConfig {
    pub enabled: bool,
    pub provider_mode: ProviderMode,
    pub base_url: Option<String>,
    pub api_key_ref: Option<String>,
    pub model: Option<String>,
    pub temperature: f32,
    pub max_output_tokens: u32,
    pub streaming: bool,
    pub roles_enabled: Vec<String>,
    pub context_scopes_enabled: Vec<String>,
    pub privacy_mode: PrivacyMode,
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            provider_mode: ProviderMode::Disabled,
            base_url: None,
            api_key_ref: None,
            model: None,
            temperature: 0.2,
            max_output_tokens: 512,
            streaming: false,
            roles_enabled: vec![
                "spot_explain".to_string(),
                "line_compare".to_string(),
                "decision_rationale".to_string(),
                "ocr_diagnostic".to_string(),
                "fallback_diagnostic".to_string(),
                "session_summary".to_string(),
                "strategy_review".to_string(),
                "replay_coach".to_string(),
            ],
            context_scopes_enabled: vec![
                "spot_snapshot".to_string(),
                "decision_snapshot".to_string(),
                "runtime_metrics".to_string(),
                "replay".to_string(),
            ],
            privacy_mode: PrivacyMode::StrictLocal,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmAssistRequest {
    pub task: LlmAssistTask,
    pub context_summary: Option<String>,
    pub notes: Option<String>,
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LlmAssistResponse {
    pub summary: String,
    pub recommendations: Vec<String>,
    pub warnings: Vec<String>,
    pub confidence: f32,
    pub used_context: Vec<String>,
    pub latency_ms: u64,
    pub provider_metadata: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SpotSource {
    Manual,
    Ocr,
    Replay,
    Import,
    Api,
    Solver,
    Unknown,
}

impl Default for SpotSource {
    fn default() -> Self {
        Self::Manual
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ActionOptionV2 {
    pub name: String,
    pub label: String,
    pub size: Option<f32>,
    pub available: bool,
    pub metadata: BTreeMap<String, String>,
}

impl Default for ActionOptionV2 {
    fn default() -> Self {
        Self {
            name: String::new(),
            label: String::new(),
            size: None,
            available: true,
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct SpotSnapshot {
    pub spot_id: Option<String>,
    pub source: SpotSource,
    pub hero_hand: Vec<String>,
    pub board: Vec<String>,
    pub hero_position: Option<String>,
    pub villain_positions: Vec<String>,
    pub pot: f32,
    pub effective_stack: f32,
    pub street: Option<String>,
    pub action_history: Vec<String>,
    pub legal_actions: Vec<ActionOptionV2>,
    pub ranges: Vec<String>,
    pub state_confidence: Option<f32>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(transparent)]
pub struct TreePresetId(pub String);

impl TreePresetId {
    fn srp_hu_100bb() -> Self {
        Self("srp_hu_100bb".to_string())
    }

    fn named(value: &str) -> Self {
        Self(value.to_string())
    }
}

impl Default for TreePresetId {
    fn default() -> Self {
        Self::srp_hu_100bb()
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CachePolicy {
    Disabled,
    Memory,
    Persistent,
}

impl Default for CachePolicy {
    fn default() -> Self {
        Self::Memory
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CacheTier {
    None,
    Memory,
    Disk,
}

impl Default for CacheTier {
    fn default() -> Self {
        Self::None
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RangeModelVersion {
    HeuristicV1,
    BoardAwareV2,
    CalibratedV3,
}

impl Default for RangeModelVersion {
    fn default() -> Self {
        Self::BoardAwareV2
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct SolveRequestV2 {
    pub spot_id: Option<String>,
    pub hero_range: String,
    pub villain_ranges: Vec<String>,
    pub board: Vec<String>,
    pub starting_pot: f32,
    pub effective_stack: f32,
    pub hero_position: Option<String>,
    pub action_history: Vec<String>,
    pub tree_preset_id: TreePresetId,
    pub rake: f32,
    pub num_players: u8,
    pub legal_actions: Vec<ActionOptionV2>,
    pub cache_policy: CachePolicy,
    pub hero_confidence: Option<f32>,
    pub state_confidence: Option<f32>,
    pub range_model_version: RangeModelVersion,
    pub use_cache: bool,
    pub time_budget_ms: Option<u64>,
}

impl Default for SolveRequestV2 {
    fn default() -> Self {
        Self {
            spot_id: None,
            hero_range: String::new(),
            villain_ranges: Vec::new(),
            board: Vec::new(),
            starting_pot: 0.0,
            effective_stack: 0.0,
            hero_position: None,
            action_history: Vec::new(),
            tree_preset_id: TreePresetId::default(),
            rake: 0.0,
            num_players: 2,
            legal_actions: Vec::new(),
            cache_policy: CachePolicy::default(),
            hero_confidence: None,
            state_confidence: None,
            range_model_version: RangeModelVersion::default(),
            use_cache: true,
            time_budget_ms: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct SolveActionV2 {
    pub name: String,
    pub label: String,
    pub size: Option<f32>,
    pub frequency: f32,
    pub ev: f32,
    pub is_recommended: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum DecisionWarning {
    UnsupportedSpot,
    ApproximateRanges,
    MultiwayApproximation,
    Timeout,
    CacheMiss,
    FallbackUsed,
    OcrLowConfidence,
    ModelUnavailable,
    ManualOverride,
    Unknown,
}

impl Default for DecisionWarning {
    fn default() -> Self {
        Self::Unknown
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct SolveResponseV2 {
    pub chosen_action: String,
    pub actions: Vec<SolveActionV2>,
    pub hero_ev: f32,
    pub exploitability: f32,
    pub backend: String,
    pub cache_tier: CacheTier,
    pub normalized_ranges: Vec<String>,
    pub decision_confidence: f32,
    pub fallback_reason: Option<String>,
    pub cache_hit: bool,
    pub elapsed_ms: u64,
    pub preset_id: TreePresetId,
    pub warnings: Vec<DecisionWarning>,
}

impl Default for SolveResponseV2 {
    fn default() -> Self {
        Self {
            chosen_action: String::new(),
            actions: Vec::new(),
            hero_ev: 0.0,
            exploitability: 0.0,
            backend: "stub".to_string(),
            cache_tier: CacheTier::None,
            normalized_ranges: Vec::new(),
            decision_confidence: 0.0,
            fallback_reason: None,
            cache_hit: false,
            elapsed_ms: 0,
            preset_id: TreePresetId::default(),
            warnings: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct SolverStudioDefaultPayload {
    pub spot: SpotSnapshot,
    pub solve_request: SolveRequestV2,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct BotCockpitRuntimeMetadata {
    pub app_name: &'static str,
    pub version: &'static str,
    pub runtime: &'static str,
    pub build_profile: &'static str,
    pub dev_mode: bool,
    pub mode: &'static str,
    pub uptime_ms: u64,
    pub started_at_unix_ms: u128,
    pub http_fallback_enabled: bool,
    pub llm: LlmConfig,
}

#[derive(Debug, Clone, Serialize)]
pub struct BotCockpitOperatorMetadata {
    pub profile_name: String,
    pub surface: String,
    pub capture_source: SpotSource,
    pub auto_refresh_enabled: bool,
    pub shadow_mode_enabled: bool,
    pub manual_override_enabled: bool,
    pub status: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct BotCockpitDefaultPayload {
    pub spot: SpotSnapshot,
    pub decision: SolveResponseV2,
    pub runtime: BotCockpitRuntimeMetadata,
    pub operator: BotCockpitOperatorMetadata,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct BotCockpitRefreshResponse {
    pub status: &'static str,
    pub refreshed_at_unix_ms: u128,
    pub heartbeat_ms: u64,
    pub payload: BotCockpitDefaultPayload,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReplayAnalyticsSessionSummary {
    pub session_id: String,
    pub title: String,
    pub date_label: String,
    pub source: SpotSource,
    pub hands_played: u32,
    pub net_bb: f32,
    pub ev_bb: f32,
    pub mistakes: u32,
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReplayAnalyticsDefaultPayload {
    pub runtime: BotCockpitRuntimeMetadata,
    pub selected_session_id: String,
    pub sessions: Vec<ReplayAnalyticsSessionSummary>,
    pub replay_spot: SpotSnapshot,
    pub replay_decision: SolveResponseV2,
    pub summary_metrics: BTreeMap<String, f32>,
    pub highlights: Vec<String>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReplayAnalyticsRefreshResponse {
    pub status: &'static str,
    pub refreshed_at_unix_ms: u128,
    pub heartbeat_ms: u64,
    pub payload: ReplayAnalyticsDefaultPayload,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConfigLabPresetSummary {
    pub preset_id: TreePresetId,
    pub title: String,
    pub description: String,
    pub street_focus: String,
    pub player_count: u8,
    pub memory_mode: String,
    pub recommended: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConfigLabBenchmarkStat {
    pub name: String,
    pub value: f32,
    pub unit: String,
    pub target: Option<f32>,
    pub healthy: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConfigLabDefaultPayload {
    pub runtime: RuntimeConfigResponse,
    pub active_preset: TreePresetId,
    pub available_presets: Vec<ConfigLabPresetSummary>,
    pub benchmark_stats: Vec<ConfigLabBenchmarkStat>,
    pub provider_modes: Vec<ProviderMode>,
    pub privacy_modes: Vec<PrivacyMode>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConfigLabRefreshResponse {
    pub status: &'static str,
    pub refreshed_at_unix_ms: u128,
    pub heartbeat_ms: u64,
    pub payload: ConfigLabDefaultPayload,
}

fn normalize_llm_config(mut config: LlmConfig) -> LlmConfig {
    if !config.enabled {
        config.provider_mode = ProviderMode::Disabled;
        config.base_url = None;
        config.api_key_ref = None;
    }

    config
}

fn build_default_solver_studio_payload() -> SolverStudioDefaultPayload {
    let mut spot_metadata = BTreeMap::new();
    spot_metadata.insert("preset_id".to_string(), "srp_hu_100bb".to_string());
    spot_metadata.insert("sample".to_string(), "solver_studio_default".to_string());
    spot_metadata.insert("mode".to_string(), "offline_safe".to_string());

    let legal_actions = vec![
        ActionOptionV2 {
            name: "check".to_string(),
            label: "Check".to_string(),
            size: None,
            available: true,
            metadata: BTreeMap::new(),
        },
        ActionOptionV2 {
            name: "bet_50".to_string(),
            label: "Bet 50%".to_string(),
            size: Some(50.0),
            available: true,
            metadata: BTreeMap::new(),
        },
        ActionOptionV2 {
            name: "bet_100".to_string(),
            label: "Bet 100%".to_string(),
            size: Some(100.0),
            available: true,
            metadata: BTreeMap::new(),
        },
    ];

    let solve_request = SolveRequestV2 {
        spot_id: Some("solver-studio-demo".to_string()),
        hero_range: "AsKd".to_string(),
        villain_ranges: vec!["QQ+,AKs,AKo,AQs-AJs,KQs".to_string()],
        board: vec!["Qs".to_string(), "Jh".to_string(), "4c".to_string()],
        starting_pot: 7.5,
        effective_stack: 96.5,
        hero_position: Some("ip".to_string()),
        action_history: vec!["check".to_string()],
        tree_preset_id: TreePresetId::srp_hu_100bb(),
        rake: 0.0,
        num_players: 2,
        legal_actions: legal_actions.clone(),
        cache_policy: CachePolicy::Persistent,
        hero_confidence: Some(1.0),
        state_confidence: Some(0.94),
        range_model_version: RangeModelVersion::CalibratedV3,
        use_cache: true,
        time_budget_ms: Some(1200),
    };

    let spot = SpotSnapshot {
        spot_id: Some("solver-studio-demo".to_string()),
        source: SpotSource::Manual,
        hero_hand: vec!["As".to_string(), "Kd".to_string()],
        board: solve_request.board.clone(),
        hero_position: solve_request.hero_position.clone(),
        villain_positions: vec!["oop".to_string()],
        pot: solve_request.starting_pot,
        effective_stack: solve_request.effective_stack,
        street: Some("flop".to_string()),
        action_history: solve_request.action_history.clone(),
        legal_actions,
        ranges: vec![
            solve_request.hero_range.clone(),
            solve_request
                .villain_ranges
                .first()
                .cloned()
                .unwrap_or_default(),
        ],
        state_confidence: Some(0.94),
        metadata: spot_metadata,
    };

    SolverStudioDefaultPayload {
        spot,
        solve_request,
        notes: vec![
            "Sample payload for Solver Studio bootstrap.".to_string(),
            "Offline-safe and deterministic: no network provider is required.".to_string(),
            "Designed to match the shared V2 contract shape for gradual integration.".to_string(),
        ],
    }
}

fn build_bot_cockpit_runtime_metadata(state: &AppState) -> BotCockpitRuntimeMetadata {
    let started_at_unix_ms = state
        .started_at
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    BotCockpitRuntimeMetadata {
        app_name: env!("CARGO_PKG_NAME"),
        version: env!("CARGO_PKG_VERSION"),
        runtime: "tauri",
        build_profile: if cfg!(debug_assertions) {
            "debug"
        } else {
            "release"
        },
        dev_mode: cfg!(debug_assertions),
        mode: "offline_safe",
        uptime_ms: state.started_instant.elapsed().as_millis() as u64,
        started_at_unix_ms,
        http_fallback_enabled: true,
        llm: state
            .llm_config
            .lock()
            .expect("llm config lock poisoned")
            .clone(),
    }
}

fn build_runtime_config_response(state: &AppState) -> RuntimeConfigResponse {
    RuntimeConfigResponse {
        app_name: env!("CARGO_PKG_NAME"),
        version: env!("CARGO_PKG_VERSION"),
        runtime: "tauri",
        dev_mode: cfg!(debug_assertions),
        http_fallback_enabled: true,
        llm: state
            .llm_config
            .lock()
            .expect("llm config lock poisoned")
            .clone(),
        ocr: state
            .ocr_config
            .lock()
            .expect("ocr config lock poisoned")
            .clone(),
    }
}

fn candidate_search_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();

    let mut push_ancestors = |path: PathBuf| {
        for ancestor in path.ancestors() {
            let candidate = ancestor.to_path_buf();
            if !roots.iter().any(|known| known == &candidate) {
                roots.push(candidate);
            }
        }
    };

    if let Ok(current_dir) = std::env::current_dir() {
        push_ancestors(current_dir);
    }
    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            push_ancestors(parent.to_path_buf());
        }
    }

    roots
}

fn resolve_project_root() -> Result<PathBuf, String> {
    for directory in candidate_search_roots() {
        if directory.join("config.json").is_file()
            && directory.join("src").join("main.py").is_file()
        {
            return Ok(directory);
        }
    }

    Err("failed to locate project root containing config.json and src/main.py".to_string())
}

fn config_path() -> Result<PathBuf, String> {
    resolve_project_root().map(|root| root.join("config.json"))
}

fn runtime_endpoint_available() -> bool {
    RUNTIME_PORT_CANDIDATES.iter().any(|port| {
        let addr = SocketAddr::from(([127, 0, 0, 1], *port));
        TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
    })
}

fn python_launch_candidates(project_root: &PathBuf) -> Vec<(String, Vec<String>)> {
    let mut candidates = Vec::new();

    if let Ok(explicit) = std::env::var("POKERMASTER_PYTHON_BIN") {
        let explicit = explicit.trim();
        if !explicit.is_empty() {
            candidates.push((explicit.to_string(), Vec::new()));
        }
    }

    for relative in [
        ".venv/Scripts/python.exe",
        ".venv/bin/python",
        "venv/Scripts/python.exe",
        "venv/bin/python",
    ] {
        let candidate = project_root.join(relative);
        if candidate.is_file() {
            candidates.push((candidate.to_string_lossy().to_string(), Vec::new()));
        }
    }

    if cfg!(target_os = "windows") {
        candidates.push(("python".to_string(), Vec::new()));
        candidates.push(("py".to_string(), vec!["-3".to_string()]));
    } else {
        candidates.push(("python3".to_string(), Vec::new()));
        candidates.push(("python".to_string(), Vec::new()));
    }

    candidates
}

fn spawn_python_runtime(
    project_root: &PathBuf,
    program: &str,
    base_args: &[String],
) -> Result<ManagedRuntimeProcess, String> {
    let entrypoint = project_root.join("src").join("main.py");
    if !entrypoint.is_file() {
        return Err(format!(
            "runtime entrypoint not found at {}",
            entrypoint.display()
        ));
    }

    let mut command = Command::new(program);
    command
        .current_dir(project_root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .args(base_args)
        .arg(entrypoint.as_os_str());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
        .spawn()
        .map_err(|err| format!("failed to launch python runtime via {program}: {err}"))?;

    std::thread::sleep(Duration::from_millis(250));
    match child.try_wait() {
        Ok(Some(status)) => Err(format!(
            "python runtime exited early with status {} via {}",
            status, program
        )),
        Ok(None) => Ok(ManagedRuntimeProcess { child }),
        Err(err) => Err(format!(
            "failed to inspect python runtime process launched via {program}: {err}"
        )),
    }
}

fn ensure_python_runtime_started(state: &AppState) -> Result<(), String> {
    if runtime_endpoint_available() {
        return Ok(());
    }

    let mut guard = state
        .managed_runtime
        .lock()
        .map_err(|_| "managed runtime lock poisoned".to_string())?;
    if guard.is_some() {
        return Ok(());
    }

    let project_root = resolve_project_root()?;
    let mut last_error = "no python launcher candidate succeeded".to_string();

    for (program, base_args) in python_launch_candidates(&project_root) {
        match spawn_python_runtime(&project_root, &program, &base_args) {
            Ok(process) => {
                *guard = Some(process);
                return Ok(());
            }
            Err(err) => {
                last_error = err;
            }
        }
    }

    Err(last_error)
}

fn stop_managed_runtime(state: &AppState) {
    if let Ok(mut guard) = state.managed_runtime.lock() {
        if let Some(mut process) = guard.take() {
            let _ = process.child.kill();
            let _ = process.child.wait();
        }
    }
}

fn normalize_ocr_config(mut config: OcrConfig) -> OcrConfig {
    config.enabled_engines = config
        .enabled_engines
        .into_iter()
        .map(|engine| engine.trim().to_string())
        .filter(|engine| !engine.is_empty())
        .collect();

    if config.enabled_engines.is_empty() {
        config.enabled_engines = OcrConfig::default().enabled_engines;
    }

    config.mode = if config.mode.trim().is_empty() {
        OcrConfig::default().mode
    } else {
        config.mode.trim().to_string()
    };

    config
}

fn load_ocr_config_from_disk() -> OcrConfig {
    let path = match config_path() {
        Ok(path) => path,
        Err(_) => return OcrConfig::default(),
    };

    let raw = match fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(_) => return OcrConfig::default(),
    };

    let parsed: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(value) => value,
        Err(_) => return OcrConfig::default(),
    };

    parsed
        .get("ocr")
        .cloned()
        .and_then(|value| serde_json::from_value::<OcrConfig>(value).ok())
        .map(normalize_ocr_config)
        .unwrap_or_default()
}

fn persist_ocr_config_to_disk(config: &OcrConfig) -> Result<(), String> {
    let path = config_path()?;
    let raw =
        fs::read_to_string(&path).map_err(|err| format!("failed to read config.json: {err}"))?;
    let mut parsed: serde_json::Value =
        serde_json::from_str(&raw).map_err(|err| format!("invalid config.json: {err}"))?;

    let root = parsed
        .as_object_mut()
        .ok_or_else(|| "config.json root must be an object".to_string())?;
    root.insert(
        "ocr".to_string(),
        serde_json::to_value(config)
            .map_err(|err| format!("failed to serialize OCR config: {err}"))?,
    );

    let next_raw = serde_json::to_string_pretty(&parsed)
        .map_err(|err| format!("failed to format config.json: {err}"))?;
    fs::write(path, next_raw).map_err(|err| format!("failed to write config.json: {err}"))
}

fn load_auto_annotator_config_from_disk() -> AutoAnnotatorConfig {
    let path = match config_path() {
        Ok(path) => path,
        Err(_) => return AutoAnnotatorConfig::default(),
    };

    let raw = match fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(_) => return AutoAnnotatorConfig::default(),
    };

    let parsed: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(value) => value,
        Err(_) => return AutoAnnotatorConfig::default(),
    };

    parsed
        .get("auto_annotator")
        .cloned()
        .and_then(|value| serde_json::from_value::<AutoAnnotatorConfig>(value).ok())
        .map(normalize_auto_annotator_config)
        .unwrap_or_default()
}

fn persist_auto_annotator_config_to_disk(config: &AutoAnnotatorConfig) -> Result<(), String> {
    let path = config_path()?;
    let raw =
        fs::read_to_string(&path).map_err(|err| format!("failed to read config.json: {err}"))?;
    let mut parsed: serde_json::Value =
        serde_json::from_str(&raw).map_err(|err| format!("invalid config.json: {err}"))?;

    let root = parsed
        .as_object_mut()
        .ok_or_else(|| "config.json root must be an object".to_string())?;
    root.insert(
        "auto_annotator".to_string(),
        serde_json::to_value(config)
            .map_err(|err| format!("failed to serialize auto annotator config: {err}"))?,
    );

    let next_raw = serde_json::to_string_pretty(&parsed)
        .map_err(|err| format!("failed to format config.json: {err}"))?;
    fs::write(path, next_raw).map_err(|err| format!("failed to write config.json: {err}"))
}

fn build_default_bot_cockpit_payload(state: &AppState) -> BotCockpitDefaultPayload {
    let solver_payload = build_default_solver_studio_payload();
    let mut spot = solver_payload.spot.clone();
    spot.metadata
        .insert("surface".to_string(), "bot_cockpit".to_string());
    spot.metadata
        .insert("boot_mode".to_string(), "offline_safe".to_string());
    spot.metadata
        .insert("operator_profile".to_string(), "local-shadow".to_string());

    let mut decision = build_solver_studio_stub_response(solver_payload.solve_request.clone());
    let mut warnings = std::mem::take(&mut decision.warnings);
    push_warning(&mut warnings, DecisionWarning::ManualOverride);
    decision.warnings = warnings;

    BotCockpitDefaultPayload {
        spot,
        decision,
        runtime: build_bot_cockpit_runtime_metadata(state),
        operator: BotCockpitOperatorMetadata {
            profile_name: "local-shadow".to_string(),
            surface: "bot_cockpit".to_string(),
            capture_source: SpotSource::Manual,
            auto_refresh_enabled: true,
            shadow_mode_enabled: true,
            manual_override_enabled: false,
            status: "ready".to_string(),
        },
        notes: vec![
            "Sample payload for Bot Cockpit bootstrap.".to_string(),
            "Offline-safe and deterministic: no server connection is required.".to_string(),
            "Uses the shared V2 spot and decision shapes so the cockpit can render immediately."
                .to_string(),
        ],
    }
}

fn build_bot_cockpit_refresh_response(state: &AppState) -> BotCockpitRefreshResponse {
    let payload = build_default_bot_cockpit_payload(state);
    let heartbeat_ms = state.started_instant.elapsed().as_millis() as u64;
    let refreshed_at_unix_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    BotCockpitRefreshResponse {
        status: "ok",
        refreshed_at_unix_ms,
        heartbeat_ms,
        payload,
    }
}

fn build_default_replay_analytics_payload(state: &AppState) -> ReplayAnalyticsDefaultPayload {
    let solver_payload = build_default_solver_studio_payload();
    let mut replay_spot = solver_payload.spot.clone();
    replay_spot
        .metadata
        .insert("surface".to_string(), "replay_analytics".to_string());
    replay_spot
        .metadata
        .insert("view".to_string(), "timeline_preview".to_string());

    let replay_decision = build_solver_studio_stub_response(solver_payload.solve_request.clone());

    let sessions = vec![
        ReplayAnalyticsSessionSummary {
            session_id: "session-2026-04-11-a".to_string(),
            title: "Weekend review".to_string(),
            date_label: "2026-04-11".to_string(),
            source: SpotSource::Replay,
            hands_played: 284,
            net_bb: 21.4,
            ev_bb: 17.8,
            mistakes: 9,
            tags: vec![
                "postflop".to_string(),
                "srp".to_string(),
                "review".to_string(),
            ],
        },
        ReplayAnalyticsSessionSummary {
            session_id: "session-2026-04-10-b".to_string(),
            title: "Exploit pass".to_string(),
            date_label: "2026-04-10".to_string(),
            source: SpotSource::Import,
            hands_played: 142,
            net_bb: -3.6,
            ev_bb: 5.1,
            mistakes: 14,
            tags: vec!["regression".to_string(), "line-comparison".to_string()],
        },
        ReplayAnalyticsSessionSummary {
            session_id: "session-2026-04-09-c".to_string(),
            title: "Bot shadow run".to_string(),
            date_label: "2026-04-09".to_string(),
            source: SpotSource::Ocr,
            hands_played: 96,
            net_bb: 8.2,
            ev_bb: 7.9,
            mistakes: 4,
            tags: vec!["ocr".to_string(), "shadow".to_string()],
        },
    ];

    let mut summary_metrics = BTreeMap::new();
    summary_metrics.insert("hands_reviewed".to_string(), 522.0);
    summary_metrics.insert("net_bb".to_string(), 25.999_998);
    summary_metrics.insert("ev_bb".to_string(), 30.8);
    summary_metrics.insert("mistake_rate".to_string(), 0.049);
    summary_metrics.insert("fallback_rate".to_string(), 0.11);
    summary_metrics.insert("p95_latency_ms".to_string(), 184.0);

    ReplayAnalyticsDefaultPayload {
        runtime: build_bot_cockpit_runtime_metadata(state),
        selected_session_id: "session-2026-04-11-a".to_string(),
        sessions,
        replay_spot,
        replay_decision,
        summary_metrics,
        highlights: vec![
            "Offline-safe sample replay timeline is available immediately.".to_string(),
            "Use the same V2 spot and decision shapes as Solver Studio and Bot Cockpit."
                .to_string(),
            "Session metrics are deterministic so the page can render without a server."
                .to_string(),
        ],
        notes: vec![
            "Bootstrap payload for Replay & Analytics.".to_string(),
            "All content is local and non-blocking.".to_string(),
        ],
    }
}

fn build_replay_analytics_refresh_response(state: &AppState) -> ReplayAnalyticsRefreshResponse {
    let payload = build_default_replay_analytics_payload(state);
    let heartbeat_ms = state.started_instant.elapsed().as_millis() as u64;
    let refreshed_at_unix_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    ReplayAnalyticsRefreshResponse {
        status: "ok",
        refreshed_at_unix_ms,
        heartbeat_ms,
        payload,
    }
}

fn build_default_config_lab_payload(state: &AppState) -> ConfigLabDefaultPayload {
    let runtime = build_runtime_config_response(state);
    let available_presets = vec![
        ConfigLabPresetSummary {
            preset_id: TreePresetId::srp_hu_100bb(),
            title: "Single-raised pot HU".to_string(),
            description: "Balanced default with common flop lines and conservative memory use."
                .to_string(),
            street_focus: "flop".to_string(),
            player_count: 2,
            memory_mode: "balanced".to_string(),
            recommended: true,
        },
        ConfigLabPresetSummary {
            preset_id: TreePresetId::named("srp_hu_texture_wet"),
            title: "SRP wet texture".to_string(),
            description: "Wet-board SRP study profile for larger sizing mixes.".to_string(),
            street_focus: "flop".to_string(),
            player_count: 2,
            memory_mode: "texture-aware".to_string(),
            recommended: false,
        },
        ConfigLabPresetSummary {
            preset_id: TreePresetId::named("turn_probe_hu"),
            title: "Turn probe heads-up".to_string(),
            description: "Useful for turn node inspection and delayed aggression trees."
                .to_string(),
            street_focus: "turn".to_string(),
            player_count: 2,
            memory_mode: "compact".to_string(),
            recommended: false,
        },
        ConfigLabPresetSummary {
            preset_id: TreePresetId::named("turn_delayed_cbet_hu"),
            title: "Turn delayed c-bet".to_string(),
            description: "Delayed c-bet tree after a checked flop.".to_string(),
            street_focus: "turn".to_string(),
            player_count: 2,
            memory_mode: "compact".to_string(),
            recommended: false,
        },
        ConfigLabPresetSummary {
            preset_id: TreePresetId::named("river_jam_low_spr"),
            title: "River jam low SPR".to_string(),
            description: "High-pressure finishing tree for shallow stacks and simplified rivers."
                .to_string(),
            street_focus: "river".to_string(),
            player_count: 2,
            memory_mode: "aggressive-compression".to_string(),
            recommended: false,
        },
        ConfigLabPresetSummary {
            preset_id: TreePresetId::named("river_overbet_polar_hu"),
            title: "River overbet polar".to_string(),
            description: "Polarized river endgame for overbet-or-check branches.".to_string(),
            street_focus: "river".to_string(),
            player_count: 2,
            memory_mode: "polar-endgame".to_string(),
            recommended: false,
        },
    ];

    let benchmark_stats = vec![
        ConfigLabBenchmarkStat {
            name: "solve_p95_ms".to_string(),
            value: 128.0,
            unit: "ms".to_string(),
            target: Some(150.0),
            healthy: true,
        },
        ConfigLabBenchmarkStat {
            name: "equity_exact_hits".to_string(),
            value: 98.6,
            unit: "%".to_string(),
            target: Some(95.0),
            healthy: true,
        },
        ConfigLabBenchmarkStat {
            name: "fallback_rate".to_string(),
            value: 0.12,
            unit: "%".to_string(),
            target: Some(1.0),
            healthy: true,
        },
        ConfigLabBenchmarkStat {
            name: "tree_cache_hit".to_string(),
            value: 87.0,
            unit: "%".to_string(),
            target: Some(80.0),
            healthy: true,
        },
    ];

    ConfigLabDefaultPayload {
        runtime,
        active_preset: TreePresetId::srp_hu_100bb(),
        available_presets,
        benchmark_stats,
        provider_modes: vec![
            ProviderMode::Disabled,
            ProviderMode::OpenaiCompatibleLocal,
            ProviderMode::OpenaiCompatibleRemote,
        ],
        privacy_modes: vec![
            PrivacyMode::StrictLocal,
            PrivacyMode::RedactedRemote,
            PrivacyMode::FullRemote,
        ],
        notes: vec![
            "Bootstrap payload for Config & Lab.".to_string(),
            "Preset and benchmark data are deterministic so the page can render offline."
                .to_string(),
            "LLM provider and privacy options are exposed in a UI-friendly form.".to_string(),
        ],
    }
}

fn build_config_lab_refresh_response(state: &AppState) -> ConfigLabRefreshResponse {
    let payload = build_default_config_lab_payload(state);
    let heartbeat_ms = state.started_instant.elapsed().as_millis() as u64;
    let refreshed_at_unix_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    ConfigLabRefreshResponse {
        status: "ok",
        refreshed_at_unix_ms,
        heartbeat_ms,
        payload,
    }
}

fn build_stub_actions(request: &SolveRequestV2) -> Vec<SolveActionV2> {
    let mut actions = if history_is_aggressive(&request.action_history) {
        vec![
            SolveActionV2 {
                name: "fold".to_string(),
                label: "Fold".to_string(),
                size: None,
                frequency: 0.12,
                ev: -0.48,
                is_recommended: false,
            },
            SolveActionV2 {
                name: "call".to_string(),
                label: "Call".to_string(),
                size: None,
                frequency: 0.54,
                ev: 0.34,
                is_recommended: false,
            },
            SolveActionV2 {
                name: "raise_250".to_string(),
                label: "Raise 2.5x".to_string(),
                size: Some(250.0),
                frequency: 0.34,
                ev: 0.29,
                is_recommended: false,
            },
        ]
    } else if request.board.len() >= 5 {
        vec![
            SolveActionV2 {
                name: "check".to_string(),
                label: "Check".to_string(),
                size: None,
                frequency: 0.49,
                ev: 0.41,
                is_recommended: false,
            },
            SolveActionV2 {
                name: "bet_75".to_string(),
                label: "Bet 75%".to_string(),
                size: Some(75.0),
                frequency: 0.36,
                ev: 0.57,
                is_recommended: false,
            },
            SolveActionV2 {
                name: "bet_125".to_string(),
                label: "Overbet 125%".to_string(),
                size: Some(125.0),
                frequency: 0.15,
                ev: 0.44,
                is_recommended: false,
            },
        ]
    } else {
        vec![
            SolveActionV2 {
                name: "check".to_string(),
                label: "Check".to_string(),
                size: None,
                frequency: 0.31,
                ev: 0.24,
                is_recommended: false,
            },
            SolveActionV2 {
                name: "bet_50".to_string(),
                label: "Bet 50%".to_string(),
                size: Some(50.0),
                frequency: 0.47,
                ev: 0.39,
                is_recommended: false,
            },
            SolveActionV2 {
                name: "bet_100".to_string(),
                label: "Bet 100%".to_string(),
                size: Some(100.0),
                frequency: 0.22,
                ev: 0.28,
                is_recommended: false,
            },
        ]
    };

    if request.board.len() == 4 {
        for action in &mut actions {
            if action.name == "bet_50" {
                action.frequency = 0.43;
                action.ev = 0.33;
            }
            if action.name == "bet_100" {
                action.frequency = 0.17;
                action.ev = 0.26;
            }
        }
    }

    if !hero_is_ip(request.hero_position.as_deref()) {
        for action in &mut actions {
            if action.name == "check" {
                action.frequency = (action.frequency + 0.08).min(0.72);
            }
        }
    }

    if let Some(recommended_index) = actions
        .iter()
        .enumerate()
        .max_by(|(_, left), (_, right)| {
            left.frequency
                .partial_cmp(&right.frequency)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(index, _)| index)
    {
        actions[recommended_index].is_recommended = true;
    }

    actions
}

fn build_solver_studio_stub_response(request: SolveRequestV2) -> SolveResponseV2 {
    let started = Instant::now();
    let mut warnings = Vec::new();

    if request.villain_ranges.is_empty() {
        push_warning(&mut warnings, DecisionWarning::UnsupportedSpot);
        push_warning(&mut warnings, DecisionWarning::ApproximateRanges);
    }

    if request.num_players > 2 {
        push_warning(&mut warnings, DecisionWarning::MultiwayApproximation);
    }

    if request.rake > 0.0 {
        push_warning(&mut warnings, DecisionWarning::UnsupportedSpot);
    }

    if !request.use_cache {
        push_warning(&mut warnings, DecisionWarning::CacheMiss);
    }

    if request.time_budget_ms.is_some_and(|budget| budget < 100) {
        push_warning(&mut warnings, DecisionWarning::Timeout);
    }

    push_warning(&mut warnings, DecisionWarning::FallbackUsed);

    let actions = build_stub_actions(&request);
    let chosen_action = actions
        .iter()
        .find(|action| action.is_recommended)
        .map(|action| action.name.clone())
        .unwrap_or_else(|| "check".to_string());

    let hero_ev = actions
        .iter()
        .map(|action| action.ev)
        .fold(f32::MIN, f32::max)
        .max(0.0)
        + street_ev_adjustment(request.board.len());

    SolveResponseV2 {
        chosen_action,
        actions,
        hero_ev,
        exploitability: if request.num_players > 2 { 1.8 } else { 0.42 },
        backend: "stub".to_string(),
        cache_tier: if request.use_cache {
            CacheTier::Memory
        } else {
            CacheTier::None
        },
        normalized_ranges: {
            let mut ranges = Vec::with_capacity(1 + request.villain_ranges.len());
            ranges.push(request.hero_range.clone());
            ranges.extend(request.villain_ranges.clone());
            ranges
        },
        decision_confidence: if request.num_players > 2 { 0.25 } else { 0.88 },
        fallback_reason: if request.num_players > 2 {
            Some("multiway_not_supported".to_string())
        } else {
            None
        },
        cache_hit: request.use_cache && request.num_players <= 2 && request.board.len() >= 3,
        elapsed_ms: started.elapsed().as_millis() as u64,
        preset_id: if request.tree_preset_id.0.trim().is_empty() {
            TreePresetId::srp_hu_100bb()
        } else {
            request.tree_preset_id
        },
        warnings,
    }
}

fn history_is_aggressive(action_history: &[String]) -> bool {
    action_history.iter().any(|action| {
        let normalized = action.to_ascii_lowercase();
        normalized.contains("bet") || normalized.contains("raise") || normalized.contains("jam")
    })
}

fn hero_is_ip(hero_position: Option<&str>) -> bool {
    matches!(
      hero_position.map(|value| value.trim().to_ascii_lowercase()),
      Some(position)
        if matches!(
          position.as_str(),
          "ip" | "in_position" | "in-position" | "btn" | "button" | "dealer"
        )
    )
}

fn street_ev_adjustment(board_len: usize) -> f32 {
    match board_len {
        0 => 0.04,
        3 => 0.08,
        4 => 0.06,
        5 => 0.02,
        _ => 0.0,
    }
}

fn push_warning(warnings: &mut Vec<DecisionWarning>, warning: DecisionWarning) {
    if !warnings.iter().any(|current| current == &warning) {
        warnings.push(warning);
    }
}

#[tauri::command]
fn health(state: tauri::State<'_, AppState>) -> HealthResponse {
    let started_at_unix_ms = state
        .started_at
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    HealthResponse {
        status: "ok",
        uptime_ms: state.started_instant.elapsed().as_millis() as u64,
        started_at_unix_ms,
        version: env!("CARGO_PKG_VERSION"),
        mode: "tauri_shell",
    }
}

#[tauri::command]
fn version() -> VersionResponse {
    VersionResponse {
        app_name: env!("CARGO_PKG_NAME"),
        version: env!("CARGO_PKG_VERSION"),
        build_profile: if cfg!(debug_assertions) {
            "debug"
        } else {
            "release"
        },
        runtime: "tauri",
    }
}

#[tauri::command]
fn runtime_config(state: tauri::State<'_, AppState>) -> RuntimeConfigResponse {
    build_runtime_config_response(&state)
}

#[tauri::command]
fn get_llm_config(state: tauri::State<'_, AppState>) -> LlmConfig {
    state
        .llm_config
        .lock()
        .expect("llm config lock poisoned")
        .clone()
}

#[tauri::command]
fn set_llm_config(
    state: tauri::State<'_, AppState>,
    config: LlmConfig,
) -> Result<LlmConfig, String> {
    let normalized = normalize_llm_config(config);
    let mut guard = state
        .llm_config
        .lock()
        .map_err(|_| "llm config lock poisoned".to_string())?;

    *guard = normalized.clone();
    Ok(normalized)
}

#[tauri::command]
fn set_ocr_config(
    state: tauri::State<'_, AppState>,
    config: OcrConfig,
) -> Result<OcrConfig, String> {
    let normalized = normalize_ocr_config(config);
    persist_ocr_config_to_disk(&normalized)?;
    let mut guard = state
        .ocr_config
        .lock()
        .map_err(|_| "ocr config lock poisoned".to_string())?;

    *guard = normalized.clone();
    Ok(normalized)
}

#[tauri::command]
fn get_ocr_config(state: tauri::State<'_, AppState>) -> OcrConfig {
    state
        .ocr_config
        .lock()
        .expect("ocr config lock poisoned")
        .clone()
}

#[tauri::command]
fn get_auto_annotator_config(state: tauri::State<'_, AppState>) -> AutoAnnotatorConfig {
    state
        .auto_annotator_config
        .lock()
        .expect("auto annotator config lock poisoned")
        .clone()
}

#[tauri::command]
fn set_auto_annotator_config(
    state: tauri::State<'_, AppState>,
    config: AutoAnnotatorConfig,
) -> Result<AutoAnnotatorConfig, String> {
    let normalized = normalize_auto_annotator_config(config);
    persist_auto_annotator_config_to_disk(&normalized)?;
    let mut guard = state
        .auto_annotator_config
        .lock()
        .map_err(|_| "auto annotator config lock poisoned".to_string())?;

    *guard = normalized.clone();
    Ok(normalized)
}

#[tauri::command]
fn get_ocr_status(state: tauri::State<'_, AppState>) -> OcrStatusResponse {
    let config = state
        .ocr_config
        .lock()
        .expect("ocr config lock poisoned")
        .clone();

    let python_cmd = if cfg!(target_os = "windows") {
        "python"
    } else {
        "python3"
    };
    let args = vec![
    "-c".to_string(),
    "from src.vision.ocr import PokerOCR; import json; print(json.dumps(PokerOCR.from_config({'enabled_engines':['doctr','tesseract','easyocr'],'mode':'consensus_amounts','parallel':True}).get_metadata(), ensure_ascii=True))".to_string(),
  ];

    let output = std::process::Command::new(python_cmd)
        .current_dir("../../")
        .args(&args)
        .output();

    let parsed = output
        .ok()
        .and_then(|result| serde_json::from_slice::<serde_json::Value>(&result.stdout).ok())
        .unwrap_or_else(|| serde_json::json!({}));

    let supported_engines = parsed
        .get("supported_engines")
        .and_then(|value| value.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_else(|| {
            vec![
                "doctr".to_string(),
                "tesseract".to_string(),
                "easyocr".to_string(),
            ]
        });
    let loaded_engines = parsed
        .get("loaded_engines")
        .and_then(|value| value.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let unavailable_engines = parsed
        .get("unavailable_engines")
        .and_then(|value| value.as_object())
        .map(|items| {
            items
                .iter()
                .map(|(key, value)| {
                    (
                        key.clone(),
                        value.as_str().unwrap_or("unavailable").to_string(),
                    )
                })
                .collect::<BTreeMap<String, String>>()
        })
        .unwrap_or_default();

    OcrStatusResponse {
        supported_engines,
        requested_engines: config.enabled_engines,
        loaded_engines,
        unavailable_engines,
        mode: config.mode,
        parallel: config.parallel,
        use_gpu: config.use_gpu,
    }
}

#[tauri::command]
fn run_ocr_probe(request: OcrProbeRequest) -> Result<OcrProbeResponse, String> {
    let encoded = request
        .image_base64
        .split(',')
        .next_back()
        .unwrap_or(request.image_base64.as_str());
    let image_bytes = {
        use base64::Engine as _;
        base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|e| format!("Failed to decode image payload: {}", e))?
    };
    let temp_path = std::env::temp_dir().join(format!("pokermaster-ocr-{}", request.image_name));
    fs::write(&temp_path, image_bytes)
        .map_err(|e| format!("Failed to write temp OCR image: {}", e))?;

    let python_cmd = if cfg!(target_os = "windows") {
        "python"
    } else {
        "python3"
    };
    let args = vec![
        "src/vision/ocr_probe.py".to_string(),
        "--image".to_string(),
        temp_path.to_string_lossy().to_string(),
        "--field".to_string(),
        request.field.clone(),
        "--engines".to_string(),
        request.engines.join(","),
        "--mode".to_string(),
        request.mode.clone(),
    ];

    let mut command = std::process::Command::new(python_cmd);
    command.current_dir("../../").args(&args);
    if request.parallel {
        command.arg("--parallel");
    }

    let output = command
        .output()
        .map_err(|e| format!("Failed to execute OCR probe: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        return Ok(OcrProbeResponse {
            success: false,
            field: request.field,
            result: serde_json::Value::Null,
            metadata: serde_json::json!({}),
            message: Some(stderr),
        });
    }

    let parsed = serde_json::from_slice::<OcrProbeResponse>(&output.stdout)
        .map_err(|e| format!("Failed to parse OCR probe output: {}", e));
    let _ = fs::remove_file(temp_path);
    parsed
}

#[tauri::command]
fn solver_studio_default_payload() -> SolverStudioDefaultPayload {
    build_default_solver_studio_payload()
}

#[tauri::command]
fn solver_studio_solve_stub(request: SolveRequestV2) -> SolveResponseV2 {
    build_solver_studio_stub_response(request)
}

#[tauri::command]
fn bot_cockpit_default_payload(state: tauri::State<'_, AppState>) -> BotCockpitDefaultPayload {
    build_default_bot_cockpit_payload(&state)
}

#[tauri::command]
fn bot_cockpit_refresh_stub(state: tauri::State<'_, AppState>) -> BotCockpitRefreshResponse {
    build_bot_cockpit_refresh_response(&state)
}

#[tauri::command]
fn replay_analytics_default_payload(
    state: tauri::State<'_, AppState>,
) -> ReplayAnalyticsDefaultPayload {
    build_default_replay_analytics_payload(&state)
}

#[tauri::command]
fn replay_analytics_refresh_stub(
    state: tauri::State<'_, AppState>,
) -> ReplayAnalyticsRefreshResponse {
    build_replay_analytics_refresh_response(&state)
}

#[tauri::command]
fn config_lab_default_payload(state: tauri::State<'_, AppState>) -> ConfigLabDefaultPayload {
    build_default_config_lab_payload(&state)
}

#[tauri::command]
fn config_lab_refresh_stub(state: tauri::State<'_, AppState>) -> ConfigLabRefreshResponse {
    build_config_lab_refresh_response(&state)
}

#[tauri::command]
fn llm_mock_assist(
    state: tauri::State<'_, AppState>,
    request: LlmAssistRequest,
) -> LlmAssistResponse {
    let config = state
        .llm_config
        .lock()
        .expect("llm config lock poisoned")
        .clone();

    let mode_label = match config.provider_mode {
        ProviderMode::Disabled => "disabled",
        ProviderMode::OpenaiCompatibleRemote => "openai_compatible_remote",
        ProviderMode::OpenaiCompatibleLocal => "openai_compatible_local",
    };

    let summary = match request.task {
        LlmAssistTask::SpotExplain => "Spot explanation scaffold ready.",
        LlmAssistTask::LineCompare => "Line comparison scaffold ready.",
        LlmAssistTask::DecisionRationale => "Decision rationale scaffold ready.",
        LlmAssistTask::OcrDiagnostic => "OCR diagnostic scaffold ready.",
        LlmAssistTask::FallbackDiagnostic => "Fallback diagnostic scaffold ready.",
        LlmAssistTask::SessionSummary => "Session summary scaffold ready.",
        LlmAssistTask::StrategyReview => "Strategy review scaffold ready.",
        LlmAssistTask::ReplayCoach => "Replay coach scaffold ready.",
    }
    .to_string();

    let mut recommendations = vec![
        "Keep the runtime deterministic when LLM assistance is disabled.".to_string(),
        "Route OpenAI-compatible calls through an isolated gateway.".to_string(),
    ];

    if let Some(context) = request.context_summary.as_deref() {
        recommendations.push(format!("Context received: {context}"));
    }

    if let Some(notes) = request.notes.as_deref() {
        recommendations.push(format!("Notes received: {notes}"));
    }

    LlmAssistResponse {
        summary,
        recommendations,
        warnings: if config.enabled {
            Vec::new()
        } else {
            vec!["LLM is disabled by default.".to_string()]
        },
        confidence: if config.enabled { 0.42 } else { 0.15 },
        used_context: request.tags,
        latency_ms: 0,
        provider_metadata: serde_json::json!({
          "provider_mode": mode_label,
          "enabled": config.enabled,
          "privacy_mode": config.privacy_mode,
          "runtime": "mock",
        }),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AutoAnnotatorProvider {
    pub base_url: String,
    pub model: String,
    pub api_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AutoAnnotatorConfig {
    pub providers: Vec<AutoAnnotatorProvider>,
}

impl Default for AutoAnnotatorConfig {
    fn default() -> Self {
        Self {
            providers: vec![
                AutoAnnotatorProvider {
                    base_url: "https://api.groq.com/openai/v1".to_string(),
                    model: "llama-3.2-90b-vision-preview".to_string(),
                    api_key: String::new(),
                },
                AutoAnnotatorProvider {
                    base_url: "https://api.openai.com/v1".to_string(),
                    model: "gpt-4o".to_string(),
                    api_key: String::new(),
                },
            ],
        }
    }
}

fn normalize_auto_annotator_config(config: AutoAnnotatorConfig) -> AutoAnnotatorConfig {
    let providers = config
        .providers
        .into_iter()
        .map(|provider| AutoAnnotatorProvider {
            base_url: provider.base_url.trim().to_string(),
            model: provider.model.trim().to_string(),
            api_key: provider.api_key.trim().to_string(),
        })
        .collect::<Vec<_>>();

    if providers.is_empty() {
        AutoAnnotatorConfig::default()
    } else {
        AutoAnnotatorConfig { providers }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct AutoAnnotatorResponse {
    pub success: bool,
    pub message: String,
}

#[tauri::command]
async fn run_auto_annotator(
    state: tauri::State<'_, AppState>,
    config: AutoAnnotatorConfig,
) -> Result<AutoAnnotatorResponse, String> {
    let normalized = normalize_auto_annotator_config(config);
    persist_auto_annotator_config_to_disk(&normalized)?;
    {
        let mut guard = state
            .auto_annotator_config
            .lock()
            .map_err(|_| "auto annotator config lock poisoned".to_string())?;
        *guard = normalized.clone();
    }

    let runnable_providers = normalized
        .providers
        .into_iter()
        .filter(|provider| {
            !provider.base_url.is_empty()
                || !provider.model.is_empty()
                || !provider.api_key.is_empty()
        })
        .collect::<Vec<_>>();

    if runnable_providers.is_empty() {
        return Ok(AutoAnnotatorResponse {
            success: false,
            message: "Aucun fournisseur valide n'est configure pour l'auto-annotation.".to_string(),
        });
    }

    if runnable_providers
        .iter()
        .any(|provider| provider.model.is_empty())
    {
        return Ok(AutoAnnotatorResponse {
            success: false,
            message: "Chaque fournisseur utilise pour l'auto-annotation doit definir un modele."
                .to_string(),
        });
    }

    let providers_json = serde_json::to_string(&runnable_providers)
        .map_err(|e| format!("Failed to serialize providers: {}", e))?;

    let args = vec![
        "src/vision/auto_annotator.py".to_string(),
        "--providers-json".to_string(),
        providers_json,
    ];

    let python_cmd = if cfg!(target_os = "windows") {
        "python"
    } else {
        "python3"
    };

    println!("Running auto-annotator with dynamic providers list.");

    let output = std::process::Command::new(python_cmd)
        .current_dir("../../")
        .args(&args)
        .output()
        .map_err(|e| format!("Failed to execute python script: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    if !stderr.is_empty() {
        println!("Python Stderr: {}", stderr);
    }

    if output.status.success() {
        Ok(AutoAnnotatorResponse {
            success: true,
            message: "Annotation en cascade terminée avec succès.".to_string(),
        })
    } else {
        Ok(AutoAnnotatorResponse {
            success: false,
            message: format!(
                "Échec du script (Code {}). Erreur: {}",
                output.status.code().unwrap_or(-1),
                stderr
            ),
        })
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(AppState {
            started_at: SystemTime::now(),
            started_instant: Instant::now(),
            llm_config: Mutex::new(LlmConfig::default()),
            ocr_config: Mutex::new(load_ocr_config_from_disk()),
            auto_annotator_config: Mutex::new(load_auto_annotator_config_from_disk()),
            managed_runtime: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            health,
            version,
            runtime_config,
            get_llm_config,
            set_llm_config,
            get_ocr_config,
            set_ocr_config,
            get_auto_annotator_config,
            set_auto_annotator_config,
            get_ocr_status,
            run_ocr_probe,
            solver_studio_default_payload,
            solver_studio_solve_stub,
            bot_cockpit_default_payload,
            bot_cockpit_refresh_stub,
            replay_analytics_default_payload,
            replay_analytics_refresh_stub,
            config_lab_default_payload,
            config_lab_refresh_stub,
            llm_mock_assist,
            run_auto_annotator
        ])
        .setup(|app| {
            {
                let state = app.state::<AppState>();
                if let Err(err) = ensure_python_runtime_started(&state) {
                    eprintln!("PokerMaster runtime bootstrap warning: {err}");
                }
            }

            if let Some(window) = app.get_webview_window("main") {
                #[cfg(debug_assertions)]
                {
                    let _ = window.open_devtools();
                }
                let _ = window.eval(
                    r#"
                      window.addEventListener('error', (event) => {
                        const message = event?.error?.stack || event?.message || 'unknown window error';
                        console.error('PokerMaster window error:', message);
                      });
                      window.addEventListener('unhandledrejection', (event) => {
                        const reason = event?.reason?.stack || event?.reason?.message || String(event?.reason ?? 'unknown rejection');
                        console.error('PokerMaster unhandled rejection:', reason);
                      });
                    "#,
                );
                let _ = window.emit(
                    "pokermaster-shell-ready",
                    serde_json::json!({
                      "build_profile": if cfg!(debug_assertions) { "debug" } else { "release" },
                    }),
                );
            }
            Ok(())
        })
        .on_page_load(|window, payload| {
            println!(
                "PokerMaster page load: window={} url={}",
                window.label(),
                payload.url()
            );
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            let state = app_handle.state::<AppState>();
            stop_managed_runtime(&state);
        }
    });
}
