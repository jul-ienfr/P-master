use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fmt;
use std::time::Instant;

#[cfg(feature = "bincode")]
use bincode::{Decode, Encode};

/// Describes where a spot came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// A generic action option that can be shown in the UI or fed into orchestration layers.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// Source of a decision snapshot.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum DecisionSource {
    NativeSolver,
    HttpFallback,
    LegacyHeuristic,
    Manual,
    LlmAssist,
    Replay,
    Simulation,
    Unknown,
}

impl Default for DecisionSource {
    fn default() -> Self {
        Self::Unknown
    }
}

/// Warnings attached to a decision.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// Declares which equity backend produced a result.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum EquityBackend {
    RustExact,
    RustMonteCarlo,
    OracleBackend,
    Unknown,
}

impl Default for EquityBackend {
    fn default() -> Self {
        Self::Unknown
    }
}

/// Version identifier for villain range models.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// Requested cache policy for canonical V2 calls.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// The cache tier that served a canonical response.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// OCR confidence report attached to a captured spot.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct OcrConfidenceReport {
    pub overall: f32,
    pub hero_cards: f32,
    pub board: f32,
    pub pot: f32,
    pub stack: f32,
    pub actions: f32,
    pub notes: Vec<String>,
}

impl Default for OcrConfidenceReport {
    fn default() -> Self {
        Self {
            overall: 0.0,
            hero_cards: 0.0,
            board: 0.0,
            pot: 0.0,
            stack: 0.0,
            actions: 0.0,
            notes: Vec::new(),
        }
    }
}

/// Decision gate output used to block unsafe live actions.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct DecisionGateResult {
    pub allowed: bool,
    pub confidence: f32,
    pub reason: Option<String>,
    pub warnings: Vec<DecisionWarning>,
    pub metadata: BTreeMap<String, String>,
}

impl Default for DecisionGateResult {
    fn default() -> Self {
        Self {
            allowed: true,
            confidence: 1.0,
            reason: None,
            warnings: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }
}

/// Full snapshot of a poker spot for the unified V2 suite.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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
    pub ocr_confidence: Option<OcrConfidenceReport>,
    pub metadata: BTreeMap<String, String>,
}

impl Default for SpotSnapshot {
    fn default() -> Self {
        Self {
            spot_id: None,
            source: SpotSource::default(),
            hero_hand: Vec::new(),
            board: Vec::new(),
            hero_position: None,
            villain_positions: Vec::new(),
            pot: 0.0,
            effective_stack: 0.0,
            street: None,
            action_history: Vec::new(),
            legal_actions: Vec::new(),
            ranges: Vec::new(),
            state_confidence: None,
            ocr_confidence: None,
            metadata: BTreeMap::new(),
        }
    }
}

/// A solve action with frequency/EV information.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct SolveActionV2 {
    pub name: String,
    pub label: String,
    pub size: Option<f32>,
    pub frequency: f32,
    pub ev: f32,
    pub is_recommended: bool,
}

impl Default for SolveActionV2 {
    fn default() -> Self {
        Self {
            name: String::new(),
            label: String::new(),
            size: None,
            frequency: 0.0,
            ev: 0.0,
            is_recommended: false,
        }
    }
}

/// Tree preset identifier for V2 solve requests.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(transparent)]
pub struct TreePresetId(pub String);

impl TreePresetId {
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn srp_hu_100bb() -> Self {
        Self::new("srp_hu_100bb")
    }

    pub fn three_bp_hu_100bb() -> Self {
        Self::new("3bp_hu_100bb")
    }

    pub fn four_bp_hu_100bb() -> Self {
        Self::new("4bp_hu_100bb")
    }

    pub fn turn_probe_hu() -> Self {
        Self::new("turn_probe_hu")
    }

    pub fn river_jam_low_spr() -> Self {
        Self::new("river_jam_low_spr")
    }
}

impl Default for TreePresetId {
    fn default() -> Self {
        Self::srp_hu_100bb()
    }
}

impl From<&str> for TreePresetId {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl From<String> for TreePresetId {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl fmt::Display for TreePresetId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// Request object for the V2 solver entrypoint.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

/// Response object produced by the V2 solver entrypoint.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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
            backend: "native".to_string(),
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

/// Provider mode for the optional LLM copilot.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum LlmProviderMode {
    Disabled,
    OpenaiCompatibleRemote,
    OpenaiCompatibleLocal,
}

impl Default for LlmProviderMode {
    fn default() -> Self {
        Self::Disabled
    }
}

/// Privacy mode for the optional LLM copilot.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum LlmPrivacyMode {
    StrictLocal,
    RedactedRemote,
    FullRemote,
}

impl Default for LlmPrivacyMode {
    fn default() -> Self {
        Self::StrictLocal
    }
}

/// High-level copilot role.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum LlmRole {
    Analysis,
    OperatorAssist,
    StrategyCoach,
    ReplayCoach,
    ConfigAssistant,
}

/// Context scopes that may be forwarded to the LLM.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum LlmContextScope {
    Spot,
    Decision,
    Replay,
    Runtime,
    Ui,
    Ocr,
    Solver,
    Metrics,
    Config,
}

/// Public LLM configuration contract for the unified suite.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct LlmConfig {
    pub enabled: bool,
    pub provider_mode: LlmProviderMode,
    pub base_url: Option<String>,
    pub api_key_ref: Option<String>,
    pub model: Option<String>,
    pub temperature: f32,
    pub max_output_tokens: u32,
    pub streaming: bool,
    pub roles_enabled: Vec<LlmRole>,
    pub context_scopes_enabled: Vec<LlmContextScope>,
    pub privacy_mode: LlmPrivacyMode,
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            provider_mode: LlmProviderMode::default(),
            base_url: None,
            api_key_ref: None,
            model: None,
            temperature: 0.2,
            max_output_tokens: 1024,
            streaming: false,
            roles_enabled: Vec::new(),
            context_scopes_enabled: Vec::new(),
            privacy_mode: LlmPrivacyMode::default(),
        }
    }
}

/// Supported copilot request types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
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

impl Default for LlmAssistTask {
    fn default() -> Self {
        Self::SpotExplain
    }
}

/// Response returned by the optional LLM copilot.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct LlmAssistResponse {
    pub task: LlmAssistTask,
    pub summary: String,
    pub recommendations: Vec<String>,
    pub warnings: Vec<DecisionWarning>,
    pub confidence: f32,
    pub used_context: Vec<LlmContextScope>,
    pub latency_ms: u64,
    pub provider_metadata: BTreeMap<String, String>,
}

impl Default for LlmAssistResponse {
    fn default() -> Self {
        Self {
            task: LlmAssistTask::default(),
            summary: String::new(),
            recommendations: Vec::new(),
            warnings: Vec::new(),
            confidence: 0.0,
            used_context: Vec::new(),
            latency_ms: 0,
            provider_metadata: BTreeMap::new(),
        }
    }
}

impl From<&crate::gto_api::SolveRequest> for SolveRequestV2 {
    fn from(request: &crate::gto_api::SolveRequest) -> Self {
        let (hero_range, villain_ranges, hero_position) = if request.hero_is_oop {
            (
                request.oop_range.clone(),
                vec![request.ip_range.clone()],
                Some("oop".to_string()),
            )
        } else {
            (
                request.ip_range.clone(),
                vec![request.oop_range.clone()],
                Some("ip".to_string()),
            )
        };

        Self {
            spot_id: None,
            hero_range,
            villain_ranges,
            board: request.board.clone(),
            starting_pot: request.starting_pot,
            effective_stack: request.effective_stack,
            hero_position,
            action_history: Vec::new(),
            tree_preset_id: TreePresetId::default(),
            rake: 0.0,
            num_players: 2,
            legal_actions: Vec::new(),
            cache_policy: if request.use_cache {
                CachePolicy::Memory
            } else {
                CachePolicy::Disabled
            },
            hero_confidence: None,
            state_confidence: None,
            range_model_version: RangeModelVersion::default(),
            use_cache: request.use_cache,
            time_budget_ms: None,
        }
    }
}

impl From<&crate::gto_api::ActionDetail> for SolveActionV2 {
    fn from(action: &crate::gto_api::ActionDetail) -> Self {
        Self {
            name: action.name.clone(),
            label: action.name.clone(),
            size: action_size_from_name(&action.name),
            frequency: action.frequency,
            ev: action.ev,
            is_recommended: false,
        }
    }
}

impl From<&crate::gto_api::SolveResponse> for SolveResponseV2 {
    fn from(response: &crate::gto_api::SolveResponse) -> Self {
        let mut actions: Vec<SolveActionV2> =
            response.actions.iter().map(SolveActionV2::from).collect();
        for action in &mut actions {
            action.is_recommended = action.name == response.recommended_action;
        }

        Self {
            chosen_action: response.recommended_action.clone(),
            actions,
            hero_ev: response.hero_ev,
            exploitability: response.exploitability,
            backend: "legacy_bridge".to_string(),
            cache_tier: if response.cache_hit {
                CacheTier::Memory
            } else {
                CacheTier::None
            },
            normalized_ranges: Vec::new(),
            decision_confidence: if response.recommended_action.is_empty() {
                0.0
            } else {
                0.85
            },
            fallback_reason: None,
            cache_hit: response.cache_hit,
            elapsed_ms: response.elapsed_ms,
            preset_id: TreePresetId::default(),
            warnings: Vec::new(),
        }
    }
}

impl From<&SolveResponseV2> for crate::gto_api::SolveResponse {
    fn from(response: &SolveResponseV2) -> Self {
        Self {
            recommended_action: response.chosen_action.clone(),
            hero_ev: response.hero_ev,
            exploitability: response.exploitability,
            actions: response
                .actions
                .iter()
                .map(|action| crate::gto_api::ActionDetail {
                    name: action.name.clone(),
                    frequency: action.frequency,
                    ev: action.ev,
                })
                .collect(),
            cache_hit: response.cache_hit,
            elapsed_ms: response.elapsed_ms,
        }
    }
}

impl From<&SolveRequestV2> for SpotSnapshot {
    fn from(request: &SolveRequestV2) -> Self {
        let mut metadata = BTreeMap::new();
        metadata.insert(
            "tree_preset_id".to_string(),
            request.tree_preset_id.as_str().to_string(),
        );
        metadata.insert("num_players".to_string(), request.num_players.to_string());
        metadata.insert("rake".to_string(), request.rake.to_string());
        metadata.insert(
            "cache_policy".to_string(),
            match request.cache_policy {
                CachePolicy::Disabled => "disabled",
                CachePolicy::Memory => "memory",
                CachePolicy::Persistent => "persistent",
            }
            .to_string(),
        );
        metadata.insert(
            "range_model_version".to_string(),
            match request.range_model_version {
                RangeModelVersion::HeuristicV1 => "heuristic_v1",
                RangeModelVersion::BoardAwareV2 => "board_aware_v2",
                RangeModelVersion::CalibratedV3 => "calibrated_v3",
            }
            .to_string(),
        );
        if let Some(time_budget_ms) = request.time_budget_ms {
            metadata.insert("time_budget_ms".to_string(), time_budget_ms.to_string());
        }
        if let Some(hero_confidence) = request.hero_confidence {
            metadata.insert("hero_confidence".to_string(), hero_confidence.to_string());
        }

        let mut ranges = Vec::with_capacity(1 + request.villain_ranges.len());
        ranges.push(request.hero_range.clone());
        ranges.extend(request.villain_ranges.iter().cloned());

        Self {
            spot_id: request.spot_id.clone(),
            source: SpotSource::Solver,
            hero_hand: Vec::new(),
            board: request.board.clone(),
            hero_position: request.hero_position.clone(),
            villain_positions: Vec::new(),
            pot: request.starting_pot,
            effective_stack: request.effective_stack,
            street: None,
            action_history: request.action_history.clone(),
            legal_actions: request.legal_actions.clone(),
            ranges,
            state_confidence: request.state_confidence,
            ocr_confidence: None,
            metadata,
        }
    }
}

impl From<&SolveResponseV2> for DecisionSnapshot {
    fn from(response: &SolveResponseV2) -> Self {
        let chosen_action = response
            .actions
            .iter()
            .find(|action| action.is_recommended || action.name == response.chosen_action)
            .cloned();

        let mut metadata = BTreeMap::new();
        metadata.insert(
            "preset_id".to_string(),
            response.preset_id.as_str().to_string(),
        );
        metadata.insert("backend".to_string(), response.backend.clone());
        metadata.insert(
            "cache_tier".to_string(),
            match response.cache_tier {
                CacheTier::None => "none",
                CacheTier::Memory => "memory",
                CacheTier::Disk => "disk",
            }
            .to_string(),
        );
        if let Some(reason) = response.fallback_reason.as_ref() {
            metadata.insert("fallback_reason".to_string(), reason.clone());
        }

        Self {
            source: DecisionSource::NativeSolver,
            spot: SpotSnapshot::default(),
            chosen_action,
            alternatives: response.actions.clone(),
            exploitability: Some(response.exploitability),
            warnings: response.warnings.clone(),
            latency_ms: response.elapsed_ms,
            confidence: Some(response.decision_confidence),
            gate: None,
            metadata,
        }
    }
}

/// Snapshot of a decision made from a spot.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct DecisionSnapshot {
    pub source: DecisionSource,
    pub spot: SpotSnapshot,
    pub chosen_action: Option<SolveActionV2>,
    pub alternatives: Vec<SolveActionV2>,
    pub exploitability: Option<f32>,
    pub warnings: Vec<DecisionWarning>,
    pub latency_ms: u64,
    pub confidence: Option<f32>,
    pub gate: Option<DecisionGateResult>,
    pub metadata: BTreeMap<String, String>,
}

impl Default for DecisionSnapshot {
    fn default() -> Self {
        Self {
            source: DecisionSource::default(),
            spot: SpotSnapshot::default(),
            chosen_action: None,
            alternatives: Vec::new(),
            exploitability: None,
            warnings: Vec::new(),
            latency_ms: 0,
            confidence: None,
            gate: None,
            metadata: BTreeMap::new(),
        }
    }
}

/// Replay record derived from a canonical spot and decision.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct ReplayRecord {
    pub replay_id: String,
    pub spot: SpotSnapshot,
    pub decision: DecisionSnapshot,
    pub result_metadata: BTreeMap<String, String>,
    pub tags: Vec<String>,
}

impl Default for ReplayRecord {
    fn default() -> Self {
        Self {
            replay_id: String::new(),
            spot: SpotSnapshot::default(),
            decision: DecisionSnapshot::default(),
            result_metadata: BTreeMap::new(),
            tags: Vec::new(),
        }
    }
}

/// Benchmark result for offline parity and performance checks.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(default)]
pub struct BenchmarkResult {
    pub name: String,
    pub backend: String,
    pub metric: String,
    pub score: f32,
    pub elapsed_ms: u64,
    pub passed: bool,
    pub metadata: BTreeMap<String, String>,
}

impl Default for BenchmarkResult {
    fn default() -> Self {
        Self {
            name: String::new(),
            backend: String::new(),
            metric: String::new(),
            score: 0.0,
            elapsed_ms: 0,
            passed: false,
            metadata: BTreeMap::new(),
        }
    }
}

pub type SolveV2Result = Result<SolveResponseV2, crate::gto_api::SolveError>;

/// Runs the shared V2 solve bridge.
///
/// The current implementation maps compatible heads-up spots onto the existing
/// solver request and returns a structured V2 response for unsupported spots
/// instead of forcing callers to special-case legacy constraints.
pub fn solve_spot_v2(request: SolveRequestV2) -> SolveV2Result {
    let started = Instant::now();
    let parsed_position = parse_hero_position(request.hero_position.as_deref());
    let mut warnings = Vec::new();
    let normalized_ranges = canonical_ranges(&request);

    if request.villain_ranges.is_empty() {
        push_warning(&mut warnings, DecisionWarning::UnsupportedSpot);
    }
    if request.villain_ranges.len() > 1 || request.num_players > 2 {
        push_warning(&mut warnings, DecisionWarning::MultiwayApproximation);
    }
    if !request.action_history.is_empty() || request.rake > 0.0 {
        push_warning(&mut warnings, DecisionWarning::UnsupportedSpot);
    }
    if parsed_position.is_none() {
        push_warning(&mut warnings, DecisionWarning::UnsupportedSpot);
    }
    if request.state_confidence.is_some_and(|value| value < 0.65)
        || request.hero_confidence.is_some_and(|value| value < 0.7)
    {
        push_warning(&mut warnings, DecisionWarning::OcrLowConfidence);
    }

    let can_bridge_to_legacy = request.villain_ranges.len() == 1
        && request.num_players <= 2
        && request.action_history.is_empty()
        && request.rake <= 0.0
        && parsed_position.is_some();

    if !can_bridge_to_legacy {
        push_warning(&mut warnings, DecisionWarning::FallbackUsed);
        return Ok(SolveResponseV2 {
            chosen_action: String::new(),
            actions: Vec::new(),
            hero_ev: 0.0,
            exploitability: 0.0,
            backend: "fallback".to_string(),
            cache_tier: CacheTier::None,
            normalized_ranges,
            decision_confidence: decision_confidence_hint(&request, warnings.len()),
            fallback_reason: Some(fallback_reason(&request, parsed_position.is_some())),
            cache_hit: false,
            elapsed_ms: started.elapsed().as_millis() as u64,
            preset_id: request.tree_preset_id,
            warnings,
        });
    }

    let legacy_request = to_legacy_solve_request(&request, parsed_position.unwrap_or(true));
    let legacy_response = crate::gto_api::solve_spot(legacy_request)?;
    let mut response = SolveResponseV2::from(&legacy_response);
    response.elapsed_ms = started.elapsed().as_millis() as u64;
    response.preset_id = request.tree_preset_id.clone();
    response.warnings = warnings;
    response.backend = "native_solver".to_string();
    response.cache_tier = if response.cache_hit {
        CacheTier::Memory
    } else {
        CacheTier::None
    };
    response.normalized_ranges = normalized_ranges;
    response.decision_confidence = decision_confidence_hint(&request, response.warnings.len());
    response.fallback_reason = None;
    Ok(response)
}

/// Builds a structured offline-safe LLM response.
///
/// The suite can consume this helper from bindings or shell layers while
/// keeping the deterministic solver path fully independent from any provider.
pub fn llm_assist_stub_response(
    task: LlmAssistTask,
    prompt: Option<&str>,
    config: &LlmConfig,
    used_context: Vec<LlmContextScope>,
    mut provider_metadata: BTreeMap<String, String>,
) -> LlmAssistResponse {
    if !provider_metadata.contains_key("provider_mode") {
        provider_metadata.insert(
            "provider_mode".to_string(),
            llm_provider_mode_name(config.provider_mode).to_string(),
        );
    }
    if let Some(model) = config.model.as_ref() {
        provider_metadata
            .entry("model".to_string())
            .or_insert_with(|| model.clone());
    }
    if let Some(base_url) = config.base_url.as_ref() {
        provider_metadata
            .entry("base_url".to_string())
            .or_insert_with(|| base_url.clone());
    }
    provider_metadata.insert(
        "enabled".to_string(),
        if config.enabled { "true" } else { "false" }.to_string(),
    );
    provider_metadata
        .entry("backend".to_string())
        .or_insert_with(|| "stub".to_string());

    let mut warnings = vec![DecisionWarning::FallbackUsed];
    if !config.enabled || matches!(config.provider_mode, LlmProviderMode::Disabled) {
        push_warning(&mut warnings, DecisionWarning::ModelUnavailable);
    }

    let summary = if let Some(prompt) = prompt.filter(|value| !value.trim().is_empty()) {
        format!(
            "{} Prompt accepted in consultative mode: '{}'.",
            llm_task_summary(task),
            truncate_text(prompt)
        )
    } else {
        format!(
            "{} Local stub returned a typed consultative response.",
            llm_task_summary(task)
        )
    };

    LlmAssistResponse {
        task,
        summary,
        recommendations: vec![
            "Keep the solver and equity paths authoritative for live play.".to_string(),
            "Treat copilot output as optional guidance layered on top of the runtime.".to_string(),
        ],
        warnings,
        confidence: if config.enabled { 0.25 } else { 0.15 },
        used_context,
        latency_ms: 0,
        provider_metadata,
    }
}

fn to_legacy_solve_request(
    request: &SolveRequestV2,
    hero_is_oop: bool,
) -> crate::gto_api::SolveRequest {
    let hero_range = request.hero_range.trim().to_string();
    let villain_range = request
        .villain_ranges
        .first()
        .map(|value| value.trim().to_string())
        .unwrap_or_default();
    let (oop_range, ip_range) = if hero_is_oop {
        (hero_range, villain_range)
    } else {
        (villain_range, hero_range)
    };

    let max_iterations = solve_iterations_for_budget(request.time_budget_ms);

    crate::gto_api::SolveRequest {
        oop_range,
        ip_range,
        board: request.board.clone(),
        starting_pot: request.starting_pot,
        effective_stack: request.effective_stack,
        hero_is_oop,
        max_iterations,
        target_exploitability: 0.5,
        use_cache: request.use_cache && !matches!(request.cache_policy, CachePolicy::Disabled),
    }
}

fn solve_iterations_for_budget(time_budget_ms: Option<u64>) -> u32 {
    match time_budget_ms {
        // Small explicit budgets are common in tests and UI probes; keep them cheap
        // while still exercising the native solver path.
        Some(0..=99) => 8,
        Some(100..=249) => 16,
        Some(250..=499) => 32,
        Some(budget) => ((budget / 10).clamp(48, 2_000)) as u32,
        None => 200,
    }
}

fn parse_hero_position(value: Option<&str>) -> Option<bool> {
    let normalized = value?.trim().to_ascii_lowercase();
    match normalized.as_str() {
        "oop" | "out_of_position" | "out-of-position" | "sb" | "small_blind" | "small blind" => {
            Some(true)
        }
        "ip" | "in_position" | "in-position" | "btn" | "button" | "bb" | "big_blind"
        | "big blind" => Some(false),
        _ => None,
    }
}

fn canonical_ranges(request: &SolveRequestV2) -> Vec<String> {
    let mut ranges = Vec::with_capacity(1 + request.villain_ranges.len());
    if !request.hero_range.trim().is_empty() {
        ranges.push(request.hero_range.trim().to_string());
    }
    for range in request.villain_ranges.iter() {
        let normalized = range.trim();
        if !normalized.is_empty() {
            ranges.push(normalized.to_string());
        }
    }
    ranges
}

fn decision_confidence_hint(request: &SolveRequestV2, warning_count: usize) -> f32 {
    let state = request.state_confidence.unwrap_or(0.85);
    let hero = request.hero_confidence.unwrap_or(0.9);
    let warning_penalty = (warning_count as f32) * 0.08;
    (state.min(hero) - warning_penalty).clamp(0.0, 1.0)
}

fn fallback_reason(request: &SolveRequestV2, has_position: bool) -> String {
    if request.villain_ranges.is_empty() {
        return "missing_villain_range".to_string();
    }
    if request.num_players > 2 || request.villain_ranges.len() > 1 {
        return "multiway_not_supported".to_string();
    }
    if !request.action_history.is_empty() {
        return "action_history_not_supported".to_string();
    }
    if request.rake > 0.0 {
        return "rake_not_supported".to_string();
    }
    if !has_position {
        return "hero_position_required".to_string();
    }
    "unsupported_v2_spot".to_string()
}

fn action_size_from_name(name: &str) -> Option<f32> {
    let normalized = name.trim().to_ascii_lowercase();
    if matches!(normalized.as_str(), "fold" | "check" | "call" | "allin") {
        return None;
    }

    let raw_suffix = normalized.rsplit('_').next()?;
    let raw_suffix = raw_suffix.trim_end_matches('%');
    raw_suffix.parse::<f32>().ok()
}

fn llm_provider_mode_name(mode: LlmProviderMode) -> &'static str {
    match mode {
        LlmProviderMode::Disabled => "disabled",
        LlmProviderMode::OpenaiCompatibleRemote => "openai_compatible_remote",
        LlmProviderMode::OpenaiCompatibleLocal => "openai_compatible_local",
    }
}

fn llm_task_summary(task: LlmAssistTask) -> &'static str {
    match task {
        LlmAssistTask::SpotExplain => "Spot explanation scaffold ready.",
        LlmAssistTask::LineCompare => "Line comparison scaffold ready.",
        LlmAssistTask::DecisionRationale => "Decision rationale scaffold ready.",
        LlmAssistTask::OcrDiagnostic => "OCR diagnostic scaffold ready.",
        LlmAssistTask::FallbackDiagnostic => "Fallback diagnostic scaffold ready.",
        LlmAssistTask::SessionSummary => "Session summary scaffold ready.",
        LlmAssistTask::StrategyReview => "Strategy review scaffold ready.",
        LlmAssistTask::ReplayCoach => "Replay coach scaffold ready.",
    }
}

fn truncate_text(value: &str) -> String {
    const MAX_LEN: usize = 120;
    if value.chars().count() <= MAX_LEN {
        value.trim().to_string()
    } else {
        let truncated: String = value.chars().take(MAX_LEN).collect();
        format!("{}...", truncated.trim())
    }
}

fn push_warning(warnings: &mut Vec<DecisionWarning>, warning: DecisionWarning) {
    if !warnings.contains(&warning) {
        warnings.push(warning);
    }
}
