use crate::api_utils::{
    default_use_cache, normalize_range, normalize_solve_board, NormalizedSolveBoard, SimpleLruCache,
};
use crate::{
    card_from_str, compute_current_ev, Action, ActionTree, BetSizeOptions, BoardState, Card,
    CardConfig, PostFlopGame, Range, TreeConfig,
};
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use std::any::Any;
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

/// Paramétrisation de l'abstraction de mises (Phase 4).
///
/// Remplace les tailles figées `"50%,100%"` / `"2.5x"` : bets 33%/50%/75%/100%,
/// raises 2.5x/3x, donks activables. Les chaînes suivent la syntaxe du crate
/// (`"33%,50%,75%"`, `"2.5x,3x"`, `"50%"` pour les donks).
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct BetSizeSpec {
    #[serde(default = "default_bet_sizes")]
    pub bet_sizes: String,
    #[serde(default = "default_raise_sizes")]
    pub raise_sizes: String,
    /// Tailles de donk au turn ("" = désactivé).
    #[serde(default)]
    pub turn_donk_sizes: String,
    /// Tailles de donk au river ("" = désactivé).
    #[serde(default)]
    pub river_donk_sizes: String,
}

impl Default for BetSizeSpec {
    fn default() -> Self {
        Self {
            bet_sizes: default_bet_sizes(),
            raise_sizes: default_raise_sizes(),
            turn_donk_sizes: String::new(),
            river_donk_sizes: String::new(),
        }
    }
}

fn default_bet_sizes() -> String {
    "33%,50%,75%,100%".to_string()
}

fn default_raise_sizes() -> String {
    "2.5x,3x".to_string()
}

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
    #[serde(default)]
    pub hero_hand: Option<String>,
    #[serde(default)]
    pub rake_rate: f32,
    #[serde(default)]
    pub rake_cap: f32,
    #[serde(default)]
    pub sample_mixed: bool,
    #[serde(default)]
    pub random_seed: Option<u64>,
    #[serde(default)]
    pub bet_size_spec: Option<BetSizeSpec>,
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
            hero_hand: None,
            rake_rate: 0.0,
            rake_cap: 0.0,
            sample_mixed: false,
            random_seed: None,
            bet_size_spec: None,
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
    /// EV of the chosen action for the exact hero combo (falls back to `hero_ev`).
    #[serde(default)]
    pub hero_combo_ev: f32,
    /// Seed used for mixed-strategy sampling (`None` when deterministic).
    #[serde(default)]
    pub sample_seed: Option<u64>,
    /// How the action was selected: `combo_ev_max`, `mixed_sample`, or `range_frequency`.
    #[serde(default)]
    pub selection: String,
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
    hero_hand: Option<[Card; 2]>,
    rake_rate: f32,
    rake_cap: f32,
    sample_mixed: bool,
    random_seed: Option<u64>,
    bet_size_spec: BetSizeSpec,
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

    let hero_player = if normalized.hero_is_oop { 0usize } else { 1usize };
    let hero_ev = compute_current_ev(&game)[hero_player];

    let raw_actions = game.available_actions().to_vec();
    let num_actions = raw_actions.len();

    if num_actions == 0 {
        let hero_ev = compute_current_ev(&game)[hero_player];
        return Ok(SolveResponse {
            recommended_action: "check".to_string(),
            hero_ev,
            exploitability,
            actions: Vec::new(),
            cache_hit: false,
            elapsed_ms: start.elapsed().as_millis() as u64,
            hero_combo_ev: hero_ev,
            sample_seed: None,
            selection: "range_frequency".to_string(),
        });
    }

    let root_player = game.current_player();
    let strategy = game.strategy();
    let num_root_hands = strategy.len() / num_actions;

    let frequencies: Vec<f32> = (0..num_actions)
        .map(|index| {
            strategy[index * num_root_hands..(index + 1) * num_root_hands]
                .iter()
                .copied()
                .sum::<f32>()
                / num_root_hands as f32
        })
        .collect();

    // Resolve the exact hero combo within the solved private hands, if provided.
    let combo_index: Option<usize> = normalized
        .hero_hand
        .and_then(|cards| find_combo_index(&game, hero_player, cards));

    // Per-action EV for the hero: exact combo EV when the hero hand is known and matched,
    // otherwise the range-average EV per action.
    let mut action_evs = vec![hero_ev; num_actions];
    let mut combo_action_evs: Option<Vec<f32>> = None;
    let mut combo_matched = false;

    if root_player == hero_player {
        let detail = game.expected_values_detail(hero_player);
        let num_hero_hands = detail.len() / num_actions;
        for index in 0..num_actions {
            let row = &detail[index * num_hero_hands..(index + 1) * num_hero_hands];
            action_evs[index] = row.iter().copied().sum::<f32>() / num_hero_hands as f32;
        }
        if let Some(combo) = combo_index.filter(|&combo| combo < num_hero_hands) {
            combo_matched = true;
            combo_action_evs = Some(
                (0..num_actions)
                    .map(|index| detail[index * num_hero_hands + combo])
                    .collect(),
            );
        }
    } else {
        for index in 0..num_actions {
            let row = &strategy[index * num_root_hands..(index + 1) * num_root_hands];
            if row.iter().all(|&probability| probability <= 1e-9) {
                continue;
            }
            if let Some(values) = evaluate_hero_ev_after_action(&mut game, index, hero_player) {
                action_evs[index] = values.iter().copied().sum::<f32>() / values.len() as f32;
                if let Some(combo) = combo_index.filter(|&combo| combo < values.len()) {
                    if let Some(evs) = combo_action_evs.as_mut() {
                        evs[index] = values[combo];
                    } else {
                        let mut evs = vec![f32::NAN; num_actions];
                        evs[index] = values[combo];
                        combo_matched = true;
                        combo_action_evs = Some(evs);
                    }
                }
            }
        }
    }

    // Select the recommended action.
    let reference_evs = combo_action_evs.clone().unwrap_or_else(|| action_evs.clone());
    let mut sample_seed: Option<u64> = None;
    let selection;

    let recommended_index = if combo_matched && normalized.sample_mixed && root_player == hero_player
    {
        let seed = normalized.random_seed.unwrap_or_else(random_seed_u64);
        sample_seed = Some(seed);
        selection = "mixed_sample";
        let combo = combo_index.unwrap();
        let row: Vec<f32> = (0..num_actions)
            .map(|index| strategy[index * num_root_hands + combo])
            .collect();
        sample_categorical(&row, seed)
    } else if combo_matched {
        selection = "combo_ev_max";
        argmax_by_score(&reference_evs, &frequencies)
    } else {
        selection = "range_frequency";
        argmax_by_score(&frequencies, &[])
    };

    let actions: Vec<ActionDetail> = raw_actions
        .iter()
        .enumerate()
        .map(|(index, action)| ActionDetail {
            name: action_name(action),
            frequency: frequencies[index],
            ev: if combo_matched && reference_evs[index].is_finite() {
                reference_evs[index]
            } else if action_evs[index].is_finite() {
                action_evs[index]
            } else {
                hero_ev
            },
        })
        .collect();

    let chosen_ev = if combo_matched && reference_evs[recommended_index].is_finite() {
        reference_evs[recommended_index]
    } else {
        hero_ev
    };

    let recommended_action = actions
        .get(recommended_index)
        .map(|action| action.name.clone())
        .unwrap_or_else(|| "check".to_string());

    let mut response = SolveResponse {
        recommended_action,
        hero_ev,
        exploitability,
        actions,
        cache_hit: false,
        elapsed_ms: start.elapsed().as_millis() as u64,
        hero_combo_ev: chosen_ev,
        sample_seed,
        selection: selection.to_string(),
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

/// Request used to measure the best-response (MES-style) gap of a policy action.
///
/// The spot is solved to equilibrium, then every root action is evaluated for the hero
/// (exact combo EV when available, range average otherwise). The gap between the policy
/// action's EV and the best available EV replaces the circular pseudo-LBR metric.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct BestResponseRequest {
    pub oop_range: String,
    pub ip_range: String,
    pub board: Vec<String>,
    pub starting_pot: f32,
    pub effective_stack: f32,
    pub hero_is_oop: bool,
    #[serde(default = "default_max_iterations")]
    pub max_iterations: u32,
    #[serde(default)]
    pub policy_action: Option<String>,
}

impl Default for BestResponseRequest {
    fn default() -> Self {
        Self {
            oop_range: String::new(),
            ip_range: String::new(),
            board: Vec::new(),
            starting_pot: 0.0,
            effective_stack: 0.0,
            hero_is_oop: true,
            max_iterations: default_max_iterations(),
            policy_action: None,
        }
    }
}

/// Result of a best-response evaluation of a policy action.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct BestResponseResponse {
    /// Action chosen by the evaluated policy (`None` when not provided or not legal).
    pub policy_action: Option<String>,
    /// EV of the policy action (falls back to the equilibrium hero EV).
    pub policy_ev: f32,
    /// Best achievable EV at this spot against the equilibrium opponent (MES-style).
    pub mes_ev: f32,
    /// `mes_ev - policy_ev`, clamped at zero.
    pub best_response_gap: f32,
    /// Exploitability of the solved equilibrium itself (solver quality check).
    pub exploitability: f32,
    /// Per-action EVs produced by the solver.
    pub actions: Vec<ActionDetail>,
}

/// Measures the best-response gap of a policy action on a single spot via the solver.
pub fn measure_best_response_gap(
    request: BestResponseRequest,
) -> Result<BestResponseResponse, SolveError> {
    let solve_request = SolveRequest {
        oop_range: request.oop_range,
        ip_range: request.ip_range,
        board: request.board,
        starting_pot: request.starting_pot,
        effective_stack: request.effective_stack,
        hero_is_oop: request.hero_is_oop,
        max_iterations: request.max_iterations,
        target_exploitability: 0.5,
        use_cache: true,
        ..SolveRequest::default()
    };

    let response = solve_spot(solve_request)?;

    let policy_ev = response
        .actions
        .iter()
        .find(|action| Some(&action.name) == request.policy_action.as_ref())
        .map(|action| action.ev)
        .unwrap_or(response.hero_ev);

    let mes_ev = response
        .actions
        .iter()
        .map(|action| action.ev)
        .fold(f32::NEG_INFINITY, f32::max);

    let best_response_gap = if response.actions.is_empty() || !mes_ev.is_finite() {
        0.0
    } else {
        (mes_ev - policy_ev).max(0.0)
    };

    Ok(BestResponseResponse {
        policy_action: request.policy_action,
        policy_ev,
        mes_ev: if mes_ev.is_finite() { mes_ev } else { response.hero_ev },
        best_response_gap,
        exploitability: response.exploitability,
        actions: response.actions,
    })
}

fn normalize_solve_request(request: SolveRequest) -> Result<NormalizedSolveRequest, SolveError> {
    let (oop_range, oop_range_text) =
        normalize_range("OOP", &request.oop_range).map_err(SolveError::new)?;
    let (ip_range, ip_range_text) =
        normalize_range("IP", &request.ip_range).map_err(SolveError::new)?;
    let board = normalize_solve_board(&request.board).map_err(SolveError::new)?;

    let hero_hand = match request.hero_hand.as_deref() {
        Some(hand) => Some(parse_hero_hand(hand).map_err(SolveError::new)?),
        None => detect_exact_hand(&request.oop_range)
            .or_else(|| detect_exact_hand(&request.ip_range)),
    };

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
        hero_hand,
        rake_rate: request.rake_rate.clamp(0.0, 1.0),
        rake_cap: request.rake_cap.max(0.0),
        sample_mixed: request.sample_mixed,
        random_seed: request.random_seed,
        bet_size_spec: request.bet_size_spec.unwrap_or_default(),
    })
}

/// Parses a two-card hand such as `"AsKs"` into canonical cards.
fn parse_hero_hand(hand: &str) -> Result<[Card; 2], String> {
    let trimmed = hand.trim();
    if trimmed.len() != 4 {
        return Err(format!("Invalid hero hand '{hand}': expected 4 characters"));
    }
    let parse_card = |text: &str| -> Result<Card, String> {
        let normalized = format!(
            "{}{}",
            text[..1].to_ascii_uppercase(),
            text[1..].to_ascii_lowercase()
        );
        card_from_str(&normalized).map_err(|err| format!("Invalid hero hand '{hand}': {err}"))
    };
    let first = parse_card(&trimmed[..2])?;
    let second = parse_card(&trimmed[2..])?;
    if first == second {
        return Err(format!("Invalid hero hand '{hand}': duplicate card"));
    }
    Ok([first.max(second), first.min(second)])
}

/// Detects a single exact hand written as the hero range text (`"AsKs"` style only).
fn detect_exact_hand(range_text: &str) -> Option<[Card; 2]> {
    let trimmed = range_text.trim();
    if trimmed.len() != 4 || trimmed.contains(',') || trimmed.contains('+') {
        return None;
    }
    parse_hero_hand(trimmed).ok()
}

/// Finds the index of the hero combo among the solved private hands of `player`.
///
/// Suit canonicalization may rename suits, so an exact match is attempted first and a
/// rank-pattern fallback (same ranks + same suitedness) is used afterwards.
fn find_combo_index(game: &PostFlopGame, player: usize, hand: [Card; 2]) -> Option<usize> {
    let cards = game.private_cards(player);
    for (index, &(first, second)) in cards.iter().enumerate() {
        let pair = [first.max(second), first.min(second)];
        if pair == hand {
            return Some(index);
        }
    }
    let suited = hand[0] & 3 == hand[1] & 3;
    for (index, &(first, second)) in cards.iter().enumerate() {
        let ranks_match = (first >> 2, second >> 2) == (hand[0] >> 2, hand[1] >> 2);
        let suits_match = (first & 3 == second & 3) == suited;
        if ranks_match && suits_match {
            return Some(index);
        }
    }
    None
}

/// Plays the given action from the root node and returns the equilibrium EV of each hero hand
/// in the resulting subgame. The game state is restored to the root before returning.
fn evaluate_hero_ev_after_action(
    game: &mut PostFlopGame,
    action: usize,
    hero_player: usize,
) -> Option<Vec<f32>> {
    if game.is_terminal_node() {
        return None;
    }
    game.play(action);
    game.cache_normalized_weights();
    let values = game.expected_values(hero_player);
    game.back_to_root();
    if values.is_empty() || values.iter().any(|value| !value.is_finite()) {
        return None;
    }
    Some(values)
}

/// Returns the index of the largest score, breaking ties with the tiebreaker list.
fn argmax_by_score(scores: &[f32], tiebreakers: &[f32]) -> usize {
    let mut best = 0usize;
    for index in 1..scores.len() {
        let candidate = scores[index];
        let current = scores[best];
        let better = match candidate.partial_cmp(&current) {
            Some(std::cmp::Ordering::Greater) => true,
            Some(std::cmp::Ordering::Equal) => {
                tiebreakers.get(index).copied().unwrap_or(0.0)
                    > tiebreakers.get(best).copied().unwrap_or(0.0)
            }
            _ => false,
        };
        if better {
            best = index;
        }
    }
    best
}

/// Samples an action index proportionally to the provided weights using a seeded xorshift64*.
fn sample_categorical(weights: &[f32], seed: u64) -> usize {
    let total = weights.iter().filter(|w| **w > 0.0).sum::<f32>();
    if !total.is_finite() || total <= 0.0 {
        return uniform_sample(weights.len(), seed);
    }
    let mut state = seed | 1;
    let draw = (next_random_f64(&mut state)) * total as f64;
    let mut cumulative = 0.0f64;
    for (index, &weight) in weights.iter().enumerate() {
        if weight <= 0.0 {
            continue;
        }
        cumulative += weight as f64;
        if draw < cumulative {
            return index;
        }
    }
    weights
        .iter()
        .rposition(|&weight| weight > 0.0)
        .unwrap_or(0)
}

fn uniform_sample(len: usize, seed: u64) -> usize {
    if len == 0 {
        return 0;
    }
    let mut state = seed | 1;
    (next_random_f64(&mut state) * len as f64) as usize % len
}

fn next_random_f64(state: &mut u64) -> f64 {
    // xorshift64*
    *state ^= *state >> 12;
    *state ^= *state << 25;
    *state ^= *state >> 27;
    let result = state.wrapping_mul(0x2545_F491_4F6C_DD1D);
    (result >> 11) as f64 / (1u64 << 53) as f64
}

fn random_seed_u64() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as u64)
        .unwrap_or(0x9E37_79B9_7F4A_7C15)
}

fn build_game(request: &NormalizedSolveRequest) -> Result<PostFlopGame, SolveError> {
    let card_config = CardConfig {
        range: [request.oop_range, request.ip_range],
        flop: request.board.flop,
        turn: request.board.turn,
        river: request.board.river,
    };

    let spec = &request.bet_size_spec;
    let flop_sizes = BetSizeOptions::try_from((spec.bet_sizes.as_str(), spec.raise_sizes.as_str()))
        .map_err(|err| SolveError::new(format!("Bet size config: {err}")))?;
    let turn_donk = if spec.turn_donk_sizes.is_empty() {
        None
    } else {
        Some(
            crate::DonkSizeOptions::try_from(spec.turn_donk_sizes.as_str())
                .map_err(|err| SolveError::new(format!("Turn donk config: {err}")))?,
        )
    };
    let river_donk = if spec.river_donk_sizes.is_empty() {
        None
    } else {
        Some(
            crate::DonkSizeOptions::try_from(spec.river_donk_sizes.as_str())
                .map_err(|err| SolveError::new(format!("River donk config: {err}")))?,
        )
    };

    let initial_state = match request.board.strings.len() {
        3 => BoardState::Flop,
        4 => BoardState::Turn,
        _ => BoardState::River,
    };

    let tree_config = TreeConfig {
        initial_state,
        starting_pot: request.starting_pot.round() as i32,
        effective_stack: request.effective_stack.round() as i32,
        rake_rate: request.rake_rate as f64,
        rake_cap: request.rake_cap as f64,
        flop_bet_sizes: [flop_sizes.clone(), flop_sizes.clone()],
        turn_bet_sizes: [flop_sizes.clone(), flop_sizes.clone()],
        river_bet_sizes: [flop_sizes.clone(), flop_sizes.clone()],
        turn_donk_sizes: turn_donk.clone(),
        river_donk_sizes: river_donk,
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
    let spec = &request.bet_size_spec;
    format!(
        "oop={}|ip={}|board={}|pot={:.3}|stack={:.3}|hero_oop={}|iters={}|target={:.6}|hand={}|rake={:.4}|cap={:.3}|mixed={}|bets={}|raises={}|donks={},{}",
        request.oop_range_text,
        request.ip_range_text,
        request.board.strings.join(","),
        request.starting_pot,
        request.effective_stack,
        request.hero_is_oop,
        request.max_iterations,
        request.target_exploitability,
        request
            .hero_hand
            .map(|cards| crate::hole_to_string((cards[0], cards[1])).unwrap_or_default())
            .unwrap_or_default(),
        request.rake_rate,
        request.rake_cap,
        request.sample_mixed,
        spec.bet_sizes,
        spec.raise_sizes,
        spec.turn_donk_sizes,
        spec.river_donk_sizes,
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
