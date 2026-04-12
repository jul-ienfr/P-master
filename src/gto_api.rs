use crate::api_utils::{
    default_use_cache, normalize_range, normalize_solve_board, NormalizedSolveBoard, SimpleLruCache,
};
use crate::{
    compute_current_ev, Action, ActionTree, BetSizeOptions, BoardState, CardConfig, PostFlopGame,
    Range, TreeConfig,
};
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use std::any::Any;
use std::cmp::Ordering;
use std::error::Error;
use std::fmt;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Mutex;
use std::time::Instant;

#[cfg(feature = "bincode")]
use bincode::{Decode, Encode};

const SOLVE_CACHE_CAPACITY: usize = 64;

static SOLVE_CACHE: Lazy<Mutex<SimpleLruCache<SolveResponse>>> =
    Lazy::new(|| Mutex::new(SimpleLruCache::new(SOLVE_CACHE_CAPACITY)));

/// Request object for a postflop solve.
///
/// This mirrors the former HTTP payload while keeping the API usable from pure Rust.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct SolveRequest {
    pub oop_range: String,
    pub ip_range: String,
    pub board: Vec<String>,
    pub starting_pot: f32,
    pub effective_stack: f32,
    pub hero_is_oop: bool,
    #[serde(default = "default_max_iterations")]
    pub max_iterations: u32,
    #[serde(default = "default_target_exploitability")]
    pub target_exploitability: f32,
    #[serde(default = "default_use_cache")]
    pub use_cache: bool,
}

impl Default for SolveRequest {
    fn default() -> Self {
        Self {
            oop_range: String::new(),
            ip_range: String::new(),
            board: Vec::new(),
            starting_pot: 0.0,
            effective_stack: 0.0,
            hero_is_oop: true,
            max_iterations: 200,
            target_exploitability: 0.5,
            use_cache: default_use_cache(),
        }
    }
}

/// A single action candidate in the response payload.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct ActionDetail {
    pub name: String,
    pub frequency: f32,
    pub ev: f32,
}

/// Response object produced by [`solve_spot`].
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct SolveResponse {
    pub recommended_action: String,
    pub hero_ev: f32,
    pub exploitability: f32,
    pub actions: Vec<ActionDetail>,
    #[serde(default)]
    pub cache_hit: bool,
    #[serde(default)]
    pub elapsed_ms: u64,
}

fn default_max_iterations() -> u32 {
    200
}

fn default_target_exploitability() -> f32 {
    0.5
}

/// Error type returned by the reusable solve API.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SolveError {
    pub message: String,
}

impl SolveError {
    #[inline]
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }

    fn from_panic(payload: Box<dyn Any + Send>) -> Self {
        let message = match payload.downcast::<String>() {
            Ok(message) => *message,
            Err(payload) => match payload.downcast::<&'static str>() {
                Ok(message) => (*message).to_string(),
                Err(_) => "solver panicked".to_string(),
            },
        };

        Self { message }
    }
}

impl fmt::Display for SolveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl Error for SolveError {}

impl From<String> for SolveError {
    #[inline]
    fn from(message: String) -> Self {
        Self::new(message)
    }
}

impl From<&str> for SolveError {
    #[inline]
    fn from(message: &str) -> Self {
        Self::new(message)
    }
}

/// Convenience alias for the reusable solve result.
pub type SolveResult = Result<SolveResponse, SolveError>;

#[derive(Clone)]
struct NormalizedSolveRequest {
    oop_range: Range,
    oop_range_text: String,
    ip_range: Range,
    ip_range_text: String,
    board: NormalizedSolveBoard,
    starting_pot: f32,
    effective_stack: f32,
    hero_is_oop: bool,
    max_iterations: u32,
    target_exploitability: f32,
    use_cache: bool,
}

/// Runs the postflop solver directly from Rust.
///
/// The request is validated, the game is built, the solver is executed, and the final response is
/// returned in a compact, serializable-friendly shape.
pub fn solve_spot(request: SolveRequest) -> SolveResult {
    match catch_unwind(AssertUnwindSafe(|| solve_spot_inner(request))) {
        Ok(result) => result,
        Err(payload) => Err(SolveError::from_panic(payload)),
    }
}

fn solve_spot_inner(request: SolveRequest) -> SolveResult {
    let normalized = normalize_solve_request(request)?;
    let cache_key = solve_cache_key(&normalized);

    if normalized.use_cache {
        if let Some(mut cached) = SOLVE_CACHE.lock().unwrap().get(&cache_key) {
            cached.cache_hit = true;
            cached.elapsed_ms = 0;
            return Ok(cached);
        }
    }

    let start = Instant::now();
    let mut game = build_game(&normalized)?;

    let exploitability = crate::solve(
        &mut game,
        normalized.max_iterations,
        normalized.target_exploitability,
        true,
    );

    game.cache_normalized_weights();

    let raw_actions = game.available_actions().to_vec();
    let strategy = game.strategy();
    let hero_player = if normalized.hero_is_oop {
        0usize
    } else {
        1usize
    };
    let hero_ev = compute_current_ev(&game)[hero_player];

    let num_actions = raw_actions.len();
    let num_combos = if num_actions == 0 {
        1
    } else {
        strategy.len() / num_actions
    };

    let mut actions: Vec<ActionDetail> = raw_actions
        .iter()
        .enumerate()
        .map(|(index, action)| {
            let frequency = if num_combos > 0 {
                strategy[index * num_combos..(index + 1) * num_combos]
                    .iter()
                    .copied()
                    .sum::<f32>()
                    / num_combos as f32
            } else {
                0.0
            };

            ActionDetail {
                name: action_name(action),
                frequency,
                ev: hero_ev,
            }
        })
        .collect();

    actions.sort_by(|left, right| {
        right
            .frequency
            .partial_cmp(&left.frequency)
            .unwrap_or(Ordering::Equal)
    });

    let recommended_action = actions
        .first()
        .map(|action| action.name.clone())
        .unwrap_or_else(|| "check".to_string());

    let mut response = SolveResponse {
        recommended_action,
        hero_ev,
        exploitability,
        actions,
        cache_hit: false,
        elapsed_ms: start.elapsed().as_millis() as u64,
    };

    if normalized.use_cache {
        SOLVE_CACHE
            .lock()
            .unwrap()
            .insert(cache_key, response.clone());
    }

    response.cache_hit = false;
    Ok(response)
}

fn normalize_solve_request(request: SolveRequest) -> Result<NormalizedSolveRequest, SolveError> {
    let (oop_range, oop_range_text) =
        normalize_range("OOP", &request.oop_range).map_err(SolveError::new)?;
    let (ip_range, ip_range_text) =
        normalize_range("IP", &request.ip_range).map_err(SolveError::new)?;
    let board = normalize_solve_board(&request.board).map_err(SolveError::new)?;

    Ok(NormalizedSolveRequest {
        oop_range,
        oop_range_text,
        ip_range,
        ip_range_text,
        board,
        starting_pot: request.starting_pot,
        effective_stack: request.effective_stack,
        hero_is_oop: request.hero_is_oop,
        max_iterations: request.max_iterations,
        target_exploitability: request.target_exploitability,
        use_cache: request.use_cache,
    })
}

fn build_game(request: &NormalizedSolveRequest) -> Result<PostFlopGame, SolveError> {
    let card_config = CardConfig {
        range: [request.oop_range, request.ip_range],
        flop: request.board.flop,
        turn: request.board.turn,
        river: request.board.river,
    };

    let bet_sizes = BetSizeOptions::try_from(("50%,100%", "2.5x"))
        .map_err(|err| SolveError::new(format!("Bet size config: {err}")))?;

    let initial_state = match request.board.strings.len() {
        3 => BoardState::Flop,
        4 => BoardState::Turn,
        _ => BoardState::River,
    };

    let tree_config = TreeConfig {
        initial_state,
        starting_pot: request.starting_pot.round() as i32,
        effective_stack: request.effective_stack.round() as i32,
        rake_rate: 0.0,
        rake_cap: 0.0,
        flop_bet_sizes: [bet_sizes.clone(), bet_sizes.clone()],
        turn_bet_sizes: [bet_sizes.clone(), bet_sizes.clone()],
        river_bet_sizes: [bet_sizes.clone(), bet_sizes.clone()],
        turn_donk_sizes: None,
        river_donk_sizes: None,
        add_allin_threshold: 1.5,
        force_allin_threshold: 0.15,
        merging_threshold: 0.1,
    };

    let action_tree = ActionTree::new(tree_config)
        .map_err(|err| SolveError::new(format!("ActionTree: {err}")))?;
    let mut game = PostFlopGame::with_config(card_config, action_tree)
        .map_err(|err| SolveError::new(format!("PostFlopGame: {err}")))?;

    game.allocate_memory(false);
    Ok(game)
}

fn solve_cache_key(request: &NormalizedSolveRequest) -> String {
    format!(
        "oop={}|ip={}|board={}|pot={:.3}|stack={:.3}|hero_oop={}|iters={}|target={:.6}",
        request.oop_range_text,
        request.ip_range_text,
        request.board.strings.join(","),
        request.starting_pot,
        request.effective_stack,
        request.hero_is_oop,
        request.max_iterations,
        request.target_exploitability,
    )
}

fn action_name(action: &Action) -> String {
    match action {
        Action::Fold => "fold".into(),
        Action::Check => "check".into(),
        Action::Call => "call".into(),
        Action::Bet(size) => format!("bet_{size}"),
        Action::Raise(size) => format!("raise_{size}"),
        Action::AllIn(size) => format!("allin_{size}"),
        Action::Chance(_) => "chance".into(),
        Action::None => "none".into(),
    }
}
