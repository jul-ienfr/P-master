use crate::api_utils::{
    card_mask, default_use_cache, ensure_disjoint_card_sets, normalize_dead_cards,
    normalize_equity_board, normalize_exact_hole, normalize_range, normalize_range_list,
    SimpleLruCache,
};
use crate::gto_api::SolveError;
use crate::hand::{Hand, HandCategory};
use crate::{Card, Range};
use once_cell::sync::Lazy;
use serde::{Deserialize, Serialize};
use std::any::Any;
use std::cmp::Ordering;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Mutex;
use std::time::Instant;

#[cfg(feature = "bincode")]
use bincode::{Decode, Encode};

const DEFAULT_MAX_SAMPLES: u32 = 5_000;
const EQUITY_CACHE_CAPACITY: usize = 256;

static EQUITY_CACHE: Lazy<Mutex<SimpleLruCache<EquityResponse>>> =
    Lazy::new(|| Mutex::new(SimpleLruCache::new(EQUITY_CACHE_CAPACITY)));

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
#[serde(rename_all = "snake_case")]
pub enum EquityMode {
    Auto,
    Exact,
    MonteCarlo,
}

impl Default for EquityMode {
    fn default() -> Self {
        Self::Auto
    }
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct WinnerTypeDetail {
    pub name: String,
    pub frequency: f32,
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct EquityRequest {
    pub hero_hand: Vec<String>,
    pub villain_ranges: Vec<String>,
    pub board: Vec<String>,
    #[serde(default)]
    pub dead_cards: Vec<String>,
    #[serde(default)]
    pub mode: EquityMode,
    #[serde(default = "default_max_samples")]
    pub max_samples: u32,
    #[serde(default)]
    pub seed: Option<u64>,
    #[serde(default = "default_use_cache")]
    pub use_cache: bool,
}

impl Default for EquityRequest {
    fn default() -> Self {
        Self {
            hero_hand: Vec::new(),
            villain_ranges: Vec::new(),
            board: Vec::new(),
            dead_cards: Vec::new(),
            mode: EquityMode::Auto,
            max_samples: default_max_samples(),
            seed: None,
            use_cache: default_use_cache(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct EquityResponse {
    pub equity: f32,
    pub win_rate: f32,
    pub tie_rate: f32,
    pub mode_used: String,
    pub samples: u64,
    pub elapsed_ms: u64,
    pub cache_hit: bool,
    #[serde(default)]
    pub winner_types: Vec<WinnerTypeDetail>,
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct RangeStrengthRequest {
    pub hero_hand: Vec<String>,
    pub hero_range: String,
    pub villain_ranges: Vec<String>,
    pub board: Vec<String>,
    #[serde(default)]
    pub dead_cards: Vec<String>,
    #[serde(default)]
    pub mode: EquityMode,
    #[serde(default = "default_max_samples")]
    pub max_samples: u32,
    #[serde(default)]
    pub seed: Option<u64>,
    #[serde(default = "default_use_cache")]
    pub use_cache: bool,
}

impl Default for RangeStrengthRequest {
    fn default() -> Self {
        Self {
            hero_hand: Vec::new(),
            hero_range: String::new(),
            villain_ranges: Vec::new(),
            board: Vec::new(),
            dead_cards: Vec::new(),
            mode: EquityMode::Auto,
            max_samples: default_max_samples(),
            seed: None,
            use_cache: default_use_cache(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[cfg_attr(feature = "bincode", derive(Decode, Encode))]
pub struct RangeStrengthResponse {
    pub relative_strength: f32,
    pub hero_equity: f32,
    pub range_average_equity: f32,
    pub weighted_percentile: f32,
    pub combos_ranked: u64,
    pub mode_used: String,
    pub elapsed_ms: u64,
}

pub type EquityResult = Result<EquityResponse, SolveError>;
pub type RangeStrengthResult = Result<RangeStrengthResponse, SolveError>;

#[derive(Clone)]
struct NormalizedEquityRequest {
    hero_hand: [Card; 2],
    hero_hand_text: String,
    villain_ranges: Vec<Range>,
    villain_range_text: Vec<String>,
    board: Vec<Card>,
    board_text: Vec<String>,
    dead_cards: Vec<Card>,
    dead_text: Vec<String>,
    mode: EquityMode,
    max_samples: u32,
    seed: u64,
    use_cache: bool,
}

#[derive(Clone)]
struct NormalizedRangeStrengthRequest {
    equity: NormalizedEquityRequest,
    hero_range: Range,
}

#[derive(Clone, Copy)]
struct WeightedHand {
    cards: [Card; 2],
    weight: f32,
}

#[derive(Clone, Copy)]
enum ResolvedMode {
    Exact,
    MonteCarlo,
}

impl ResolvedMode {
    fn as_str(self) -> &'static str {
        match self {
            ResolvedMode::Exact => "exact",
            ResolvedMode::MonteCarlo => "monte_carlo",
        }
    }
}

#[derive(Default)]
struct EquitySummary {
    total_weight: f64,
    equity_weight: f64,
    win_weight: f64,
    tie_weight: f64,
    category_weights: [f64; 9],
    samples: u64,
}

#[derive(Default)]
struct XorShift64 {
    state: u64,
}

impl XorShift64 {
    fn new(seed: u64) -> Self {
        let state = if seed == 0 {
            0x9E37_79B9_7F4A_7C15
        } else {
            seed
        };
        Self { state }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    fn next_f64(&mut self) -> f64 {
        self.next_u64() as f64 / (u64::MAX as f64 + 1.0)
    }

    fn next_index(&mut self, upper: usize) -> usize {
        if upper <= 1 {
            0
        } else {
            (self.next_u64() % upper as u64) as usize
        }
    }
}

pub fn evaluate_equity(request: EquityRequest) -> EquityResult {
    match catch_unwind(AssertUnwindSafe(|| evaluate_equity_inner(request))) {
        Ok(result) => result,
        Err(payload) => Err(panic_to_error(payload)),
    }
}

pub fn range_relative_strength(request: RangeStrengthRequest) -> RangeStrengthResult {
    match catch_unwind(AssertUnwindSafe(|| range_relative_strength_inner(request))) {
        Ok(result) => result,
        Err(payload) => Err(panic_to_error(payload)),
    }
}

fn evaluate_equity_inner(request: EquityRequest) -> EquityResult {
    let normalized = normalize_equity_request(request)?;
    evaluate_equity_normalized(&normalized)
}

fn range_relative_strength_inner(request: RangeStrengthRequest) -> RangeStrengthResult {
    let start = Instant::now();
    let normalized = normalize_range_strength_request(request)?;
    let base_dead_mask =
        card_mask(&normalized.equity.board) | card_mask(&normalized.equity.dead_cards);
    let (hero_hands, hero_weights) = normalized.hero_range.get_hands_weights(base_dead_mask);

    if hero_hands.is_empty() {
        return Err(SolveError::new(
            "Hero range has no valid combos on the current board",
        ));
    }

    let hero_target = (
        normalized.equity.hero_hand[0],
        normalized.equity.hero_hand[1],
    );
    let mut hero_combo_found = false;
    let mut weighted_total = 0.0f64;
    let mut weighted_average = 0.0f64;
    let mut equities = Vec::with_capacity(hero_hands.len());

    for (index, (&hand, &weight)) in hero_hands.iter().zip(hero_weights.iter()).enumerate() {
        let combo_request = NormalizedEquityRequest {
            hero_hand: [hand.0, hand.1],
            hero_hand_text: crate::hole_to_string(hand)
                .map_err(|err| SolveError::new(format!("Invalid hero combo: {err}")))?,
            seed: normalized.equity.seed.wrapping_add(index as u64),
            ..normalized.equity.clone()
        };
        let response = evaluate_equity_normalized(&combo_request)?;
        let combo_weight = weight as f64;
        weighted_total += combo_weight;
        weighted_average += combo_weight * response.equity as f64;
        if hand == hero_target {
            hero_combo_found = true;
        }
        equities.push((hand, combo_weight, response.equity as f64));
    }

    if !hero_combo_found {
        return Err(SolveError::new(
            "Hero hand is not contained in the normalized hero range",
        ));
    }

    if weighted_total == 0.0 {
        return Err(SolveError::new("Hero range has zero total weight"));
    }

    let hero_equity = equities
        .iter()
        .find(|(hand, _, _)| *hand == hero_target)
        .map(|(_, _, equity)| *equity)
        .unwrap_or_default();

    let mut weaker_weight = 0.0f64;
    let mut equal_weight = 0.0f64;
    for (_, weight, equity) in &equities {
        if *equity + 1e-9 < hero_equity {
            weaker_weight += *weight;
        } else if (*equity - hero_equity).abs() <= 1e-9 {
            equal_weight += *weight;
        }
    }

    let weighted_percentile = ((weaker_weight + equal_weight * 0.5) / weighted_total) as f32;
    let range_average_equity = (weighted_average / weighted_total) as f32;

    Ok(RangeStrengthResponse {
        relative_strength: weighted_percentile,
        hero_equity: hero_equity as f32,
        range_average_equity,
        weighted_percentile,
        combos_ranked: equities.len() as u64,
        mode_used: resolve_mode(
            normalized.equity.mode,
            normalized.equity.villain_ranges.len(),
            normalized.equity.board.len(),
        )?
        .as_str()
        .to_string(),
        elapsed_ms: start.elapsed().as_millis() as u64,
    })
}

fn normalize_equity_request(request: EquityRequest) -> Result<NormalizedEquityRequest, SolveError> {
    let (hero_hand, hero_hand_text) =
        normalize_exact_hole("Hero", &request.hero_hand).map_err(SolveError::new)?;
    let (villain_ranges, villain_range_text) =
        normalize_range_list("Villain", &request.villain_ranges).map_err(SolveError::new)?;
    let (board, board_text) = normalize_equity_board(&request.board).map_err(SolveError::new)?;
    let (dead_cards, dead_text) =
        normalize_dead_cards(&request.dead_cards).map_err(SolveError::new)?;

    ensure_disjoint_card_sets(&[
        ("hero hand", &hero_hand),
        ("board", &board),
        ("dead cards", &dead_cards),
    ])
    .map_err(SolveError::new)?;

    if request.max_samples == 0 {
        return Err(SolveError::new("max_samples must be greater than 0"));
    }

    Ok(NormalizedEquityRequest {
        hero_hand,
        hero_hand_text,
        villain_ranges,
        villain_range_text,
        board,
        board_text,
        dead_cards,
        dead_text,
        mode: request.mode,
        max_samples: request.max_samples,
        seed: request.seed.unwrap_or(0),
        use_cache: request.use_cache,
    })
}

fn normalize_range_strength_request(
    request: RangeStrengthRequest,
) -> Result<NormalizedRangeStrengthRequest, SolveError> {
    let (hero_range, _) = normalize_range("Hero", &request.hero_range).map_err(SolveError::new)?;
    let equity = normalize_equity_request(EquityRequest {
        hero_hand: request.hero_hand,
        villain_ranges: request.villain_ranges,
        board: request.board,
        dead_cards: request.dead_cards,
        mode: request.mode,
        max_samples: request.max_samples,
        seed: request.seed,
        use_cache: request.use_cache,
    })?;

    Ok(NormalizedRangeStrengthRequest { equity, hero_range })
}

fn evaluate_equity_normalized(request: &NormalizedEquityRequest) -> EquityResult {
    let mode = resolve_mode(
        request.mode,
        request.villain_ranges.len(),
        request.board.len(),
    )?;
    let cache_key = equity_cache_key(request, mode);

    if request.use_cache {
        if let Some(mut cached) = EQUITY_CACHE.lock().unwrap().get(&cache_key) {
            cached.cache_hit = true;
            cached.elapsed_ms = 0;
            return Ok(cached);
        }
    }

    let start = Instant::now();
    let summary = match mode {
        ResolvedMode::Exact => compute_exact_equity(request)?,
        ResolvedMode::MonteCarlo => compute_monte_carlo_equity(request),
    };

    let mut response = finalize_equity_summary(summary, mode, start.elapsed().as_millis() as u64);
    if request.use_cache {
        EQUITY_CACHE
            .lock()
            .unwrap()
            .insert(cache_key, response.clone());
    }
    response.cache_hit = false;
    Ok(response)
}

fn resolve_mode(
    requested_mode: EquityMode,
    villain_count: usize,
    board_len: usize,
) -> Result<ResolvedMode, SolveError> {
    match requested_mode {
        EquityMode::Auto => {
            if villain_count == 1 && board_len >= 3 {
                Ok(ResolvedMode::Exact)
            } else {
                Ok(ResolvedMode::MonteCarlo)
            }
        }
        EquityMode::Exact => {
            if villain_count != 1 {
                return Err(SolveError::new(
                    "Exact mode currently supports exactly one villain range",
                ));
            }
            if board_len < 3 {
                return Err(SolveError::new(
                    "Exact mode currently supports postflop boards only",
                ));
            }
            Ok(ResolvedMode::Exact)
        }
        EquityMode::MonteCarlo => Ok(ResolvedMode::MonteCarlo),
    }
}

fn compute_exact_equity(request: &NormalizedEquityRequest) -> Result<EquitySummary, SolveError> {
    let missing_board_cards = 5usize.saturating_sub(request.board.len());
    if missing_board_cards > 2 {
        return Err(SolveError::new(
            "Exact mode currently supports flop, turn, and river boards only",
        ));
    }

    let base_dead_mask =
        card_mask(&request.hero_hand) | card_mask(&request.board) | card_mask(&request.dead_cards);
    let (villain_hands, villain_weights) =
        request.villain_ranges[0].get_hands_weights(base_dead_mask);

    if villain_hands.is_empty() {
        return Err(SolveError::new(
            "Villain range has no valid combos against the current board",
        ));
    }

    let mut summary = EquitySummary::default();

    for (&villain_hand, &villain_weight) in villain_hands.iter().zip(villain_weights.iter()) {
        let hand_weight = villain_weight as f64;
        let dead_mask = base_dead_mask | (1u64 << villain_hand.0) | (1u64 << villain_hand.1);

        match missing_board_cards {
            0 => {
                evaluate_showdown(
                    request.hero_hand,
                    &[villain_hand],
                    &request.board,
                    hand_weight,
                    &mut summary,
                );
            }
            1 => {
                for river in 0..52 {
                    if dead_mask & (1u64 << river) == 0 {
                        let mut board = request.board.clone();
                        board.push(river as Card);
                        evaluate_showdown(
                            request.hero_hand,
                            &[villain_hand],
                            &board,
                            hand_weight,
                            &mut summary,
                        );
                    }
                }
            }
            2 => {
                for turn in 0..52 {
                    if dead_mask & (1u64 << turn) != 0 {
                        continue;
                    }
                    let turn_mask = dead_mask | (1u64 << turn);
                    for river in (turn + 1)..52 {
                        if turn_mask & (1u64 << river) == 0 {
                            let mut board = request.board.clone();
                            board.push(turn as Card);
                            board.push(river as Card);
                            evaluate_showdown(
                                request.hero_hand,
                                &[villain_hand],
                                &board,
                                hand_weight,
                                &mut summary,
                            );
                        }
                    }
                }
            }
            _ => unreachable!(),
        }
    }

    Ok(summary)
}

fn compute_monte_carlo_equity(request: &NormalizedEquityRequest) -> EquitySummary {
    let base_dead_mask =
        card_mask(&request.hero_hand) | card_mask(&request.board) | card_mask(&request.dead_cards);
    let villain_combos = request
        .villain_ranges
        .iter()
        .map(|range| {
            let (hands, weights) = range.get_hands_weights(base_dead_mask);
            hands
                .into_iter()
                .zip(weights)
                .map(|(hand, weight)| WeightedHand {
                    cards: [hand.0, hand.1],
                    weight,
                })
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();

    let mut summary = EquitySummary::default();
    let mut rng = XorShift64::new(request.seed);
    let max_attempts = request
        .max_samples
        .saturating_mul(32)
        .max(request.max_samples);
    let missing_board_cards = 5usize.saturating_sub(request.board.len());

    for _ in 0..max_attempts {
        if summary.samples >= request.max_samples as u64 {
            break;
        }

        let mut dead_mask = base_dead_mask;
        let mut selected_villains = Vec::with_capacity(villain_combos.len());
        let mut valid_sample = true;

        for combos in &villain_combos {
            if let Some(hand) = pick_weighted_hand(combos, dead_mask, &mut rng) {
                dead_mask |= card_mask(&hand.cards);
                selected_villains.push((hand.cards[0], hand.cards[1]));
            } else {
                valid_sample = false;
                break;
            }
        }

        if !valid_sample {
            continue;
        }

        let mut board = request.board.clone();
        if missing_board_cards > 0 {
            let mut remaining_cards = Vec::with_capacity(52 - dead_mask.count_ones() as usize);
            for card in 0..52 {
                if dead_mask & (1u64 << card) == 0 {
                    remaining_cards.push(card as Card);
                }
            }
            for _ in 0..missing_board_cards {
                let index = rng.next_index(remaining_cards.len());
                board.push(remaining_cards.swap_remove(index));
            }
        }

        evaluate_showdown(
            request.hero_hand,
            &selected_villains,
            &board,
            1.0,
            &mut summary,
        );
    }

    if summary.samples == 0 {
        // The caller validated ranges, so this only happens when all ranges are mutually incompatible.
        summary.samples = 1;
    }

    summary
}

fn evaluate_showdown(
    hero_hand: [Card; 2],
    villain_hands: &[(Card, Card)],
    board: &[Card],
    weight: f64,
    summary: &mut EquitySummary,
) {
    let mut base_hand = Hand::new();
    for &card in board {
        base_hand = base_hand.add_card(card as usize);
    }

    let hero = base_hand
        .add_card(hero_hand[0] as usize)
        .add_card(hero_hand[1] as usize);
    let (hero_strength, hero_category) = hero.evaluate_with_category();

    let mut best_villain_strength = 0u16;
    let mut best_villain_count = 0usize;
    for &(card1, card2) in villain_hands {
        let villain_strength = base_hand
            .add_card(card1 as usize)
            .add_card(card2 as usize)
            .evaluate();
        match villain_strength.cmp(&best_villain_strength) {
            Ordering::Greater => {
                best_villain_strength = villain_strength;
                best_villain_count = 1;
            }
            Ordering::Equal => best_villain_count += 1,
            Ordering::Less => {}
        }
    }

    summary.total_weight += weight;
    summary.samples += 1;

    match hero_strength.cmp(&best_villain_strength) {
        Ordering::Greater => {
            summary.equity_weight += weight;
            summary.win_weight += weight;
            summary.category_weights[hero_category as usize] += weight;
        }
        Ordering::Equal => {
            if best_villain_strength != 0 || villain_hands.is_empty() {
                summary.equity_weight += weight / (best_villain_count + 1) as f64;
                summary.tie_weight += weight;
                summary.category_weights[hero_category as usize] += weight;
            }
        }
        Ordering::Less => {}
    }
}

fn pick_weighted_hand(
    combos: &[WeightedHand],
    dead_mask: u64,
    rng: &mut XorShift64,
) -> Option<WeightedHand> {
    let mut total_weight = 0.0f64;
    for combo in combos {
        if dead_mask & card_mask(&combo.cards) == 0 {
            total_weight += combo.weight as f64;
        }
    }

    if total_weight <= 0.0 {
        return None;
    }

    let mut threshold = rng.next_f64() * total_weight;
    for combo in combos {
        if dead_mask & card_mask(&combo.cards) != 0 {
            continue;
        }
        threshold -= combo.weight as f64;
        if threshold <= 0.0 {
            return Some(*combo);
        }
    }

    combos
        .iter()
        .rev()
        .copied()
        .find(|combo| dead_mask & card_mask(&combo.cards) == 0)
}

fn finalize_equity_summary(
    summary: EquitySummary,
    mode: ResolvedMode,
    elapsed_ms: u64,
) -> EquityResponse {
    let total_weight = summary.total_weight.max(1.0);
    let equity = (summary.equity_weight / total_weight) as f32;
    let win_rate = (summary.win_weight / total_weight) as f32;
    let tie_rate = (summary.tie_weight / total_weight) as f32;

    EquityResponse {
        equity,
        win_rate,
        tie_rate,
        mode_used: mode.as_str().to_string(),
        samples: summary.samples,
        elapsed_ms,
        cache_hit: false,
        winner_types: hand_type_details(&summary, total_weight),
    }
}

fn hand_type_details(summary: &EquitySummary, total_weight: f64) -> Vec<WinnerTypeDetail> {
    let mut result = Vec::new();
    for category in HandCategory::ALL {
        let frequency = summary.category_weights[category as usize] / total_weight;
        if frequency > 0.0 {
            result.push(WinnerTypeDetail {
                name: category.as_str().to_string(),
                frequency: frequency as f32,
            });
        }
    }
    result
}

fn equity_cache_key(request: &NormalizedEquityRequest, mode: ResolvedMode) -> String {
    format!(
        "hero={}|villains={}|board={}|dead={}|mode={}|samples={}|seed={}",
        request.hero_hand_text,
        request.villain_range_text.join(";"),
        request.board_text.join(","),
        request.dead_text.join(","),
        mode.as_str(),
        request.max_samples,
        request.seed,
    )
}

fn default_max_samples() -> u32 {
    DEFAULT_MAX_SAMPLES
}

fn panic_to_error(payload: Box<dyn Any + Send>) -> SolveError {
    match payload.downcast::<String>() {
        Ok(message) => SolveError::new(*message),
        Err(payload) => match payload.downcast::<&'static str>() {
            Ok(message) => SolveError::new(*message),
            Err(_) => SolveError::new("equity api panicked"),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_river_equity_is_deterministic() {
        let response = evaluate_equity(EquityRequest {
            hero_hand: vec!["Ah".into(), "Ad".into()],
            villain_ranges: vec!["KcKd".into()],
            board: vec![
                "2c".into(),
                "7d".into(),
                "9h".into(),
                "Js".into(),
                "Qd".into(),
            ],
            mode: EquityMode::Exact,
            ..Default::default()
        })
        .unwrap();

        assert_eq!(response.mode_used, "exact");
        assert!(response.equity > 0.99);
        assert!(response.tie_rate < 0.001);
    }

    #[test]
    fn monte_carlo_is_seeded() {
        let request = EquityRequest {
            hero_hand: vec!["As".into(), "Ks".into()],
            villain_ranges: vec!["22+,A2s+,K9s+,Q9s+,J9s+,T9s,A2o+,K9o+".into()],
            board: vec![],
            mode: EquityMode::MonteCarlo,
            max_samples: 2_000,
            seed: Some(42),
            use_cache: false,
            ..Default::default()
        };

        let first = evaluate_equity(request.clone()).unwrap();
        let second = evaluate_equity(request).unwrap();
        assert_eq!(first.equity, second.equity);
        assert_eq!(first.tie_rate, second.tie_rate);
    }

    #[test]
    fn repeated_equity_requests_hit_cache() {
        let request = EquityRequest {
            hero_hand: vec!["Ah".into(), "Kd".into()],
            villain_ranges: vec!["QQ,JJ,TT,AKs".into()],
            board: vec!["2c".into(), "7d".into(), "9h".into()],
            ..Default::default()
        };

        let first = evaluate_equity(request.clone()).unwrap();
        let second = evaluate_equity(request).unwrap();
        assert!(!first.cache_hit);
        assert!(second.cache_hit);
    }

    #[test]
    fn range_strength_orders_nuts_above_air() {
        let strong = range_relative_strength(RangeStrengthRequest {
            hero_hand: vec!["As".into(), "Ah".into()],
            hero_range: "AsAh,KcQd".into(),
            villain_ranges: vec!["JsJd,TsTd".into()],
            board: vec![
                "Ad".into(),
                "7h".into(),
                "2c".into(),
                "9s".into(),
                "3d".into(),
            ],
            mode: EquityMode::Exact,
            use_cache: false,
            ..Default::default()
        })
        .unwrap();

        let weak = range_relative_strength(RangeStrengthRequest {
            hero_hand: vec!["Kc".into(), "Qd".into()],
            hero_range: "AsAh,KcQd".into(),
            villain_ranges: vec!["JsJd,TsTd".into()],
            board: vec![
                "Ad".into(),
                "7h".into(),
                "2c".into(),
                "9s".into(),
                "3d".into(),
            ],
            mode: EquityMode::Exact,
            use_cache: false,
            ..Default::default()
        })
        .unwrap();

        assert!(strong.relative_strength > weak.relative_strength);
        assert!(strong.relative_strength > 0.5);
        assert!(weak.relative_strength < 0.5);
    }
}
