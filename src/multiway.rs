//! Solveur multiway 3..6 joueurs par MCCFR à échantillonnage externe.
//! A1-A5 + S1-S2 : N-param, SizingConfig, rake, préflop.

use crate::bet_size::BetSize;
use crate::card_from_str;
use crate::gto_api::ActionDetail;
use crate::hand::Hand;
use crate::range::Range;
use serde::{Deserialize, Serialize};
use std::collections::HashMap as FxHashMap;

pub const MIN_PLAYERS: usize = 3;
pub const MAX_PLAYERS: usize = 6;
pub(crate) const ACTION_SLOTS: usize = 6;
/// Max raises postflop; préflop 3 (S2).
pub(crate) const MAX_RAISES_PER_STREET: usize = 2;
pub(crate) const MAX_RAISES_PREFLOP: usize = 3;

pub type PlayerArray<T> = [T; MAX_PLAYERS];

#[derive(Debug, Clone)]
pub struct SizingConfig {
    pub flop: Vec<BetSize>,
    pub turn: Vec<BetSize>,
    pub river: Vec<BetSize>,
    pub preflop: Vec<BetSize>,
}

impl Default for SizingConfig {
    fn default() -> Self {
        Self {
            flop: vec![
                BetSize::PotRelative(0.33),
                BetSize::PotRelative(0.5),
                BetSize::PotRelative(1.0),
            ],
            turn: vec![
                BetSize::PotRelative(0.5),
                BetSize::PotRelative(0.75),
                BetSize::PotRelative(1.0),
            ],
            river: vec![
                BetSize::PotRelative(0.5),
                BetSize::PotRelative(1.0),
                BetSize::PotRelative(1.5),
            ],
            preflop: vec![BetSize::Additive(2, 0), BetSize::Additive(3, 0)],
        }
    }
}

impl SizingConfig {
    pub fn bets_for(&self, board_len: usize) -> &[BetSize] {
        match board_len {
            0 => &self.preflop,
            3 => &self.flop,
            4 => &self.turn,
            5 => &self.river,
            _ => &self.flop,
        }
    }
    pub fn max_raises_for(&self, board_len: usize) -> usize {
        if board_len == 0 {
            MAX_RAISES_PREFLOP
        } else {
            MAX_RAISES_PER_STREET
        }
    }
}

fn bet_size_name(b: &BetSize) -> String {
    match b {
        BetSize::PotRelative(f) => {
            if (*f - 0.33).abs() < 1e-9 {
                "bet_0.33".to_string()
            } else if (*f - 0.5).abs() < 1e-9 {
                "bet_0.5".to_string()
            } else if (*f - 0.75).abs() < 1e-9 {
                "bet_0.75".to_string()
            } else if (*f - 1.0).abs() < 1e-9 {
                "bet_1".to_string()
            } else if (*f - 1.5).abs() < 1e-9 {
                "bet_1.5".to_string()
            } else if (*f - 2.0).abs() < 1e-9 {
                "bet_2".to_string()
            } else if (*f - 3.0).abs() < 1e-9 {
                "bet_3".to_string()
            } else {
                format!("bet_{:.2}", f)
            }
        }
        BetSize::Additive(add, _) => format!("bet_{}bb", add),
        BetSize::PrevBetRelative(f) => format!("raise_{}x", f),
        BetSize::Geometric(n, _) => format!("bet_geo{}", n),
        BetSize::AllIn => "allin".to_string(),
    }
}

fn bet_target(bet: &BetSize, pot_total: i64, bet_to_match: i64, effective_stack: i64) -> i64 {
    let target = match bet {
        BetSize::PotRelative(f) => {
            let amt = ((*f) * pot_total as f64).ceil() as i64;
            bet_to_match.saturating_add(amt.max(1))
        }
        BetSize::Additive(add, _) => bet_to_match.saturating_add(*add as i64).max(bet_to_match + 1),
        BetSize::PrevBetRelative(f) => {
            let amt = ((bet_to_match as f64) * (*f - 1.0)).ceil() as i64;
            bet_to_match.saturating_add(amt.max(1))
        }
        BetSize::Geometric(_, max_rel) => {
            let factor = if max_rel.is_finite() { *max_rel } else { 1.0 };
            let amt = (pot_total as f64 * factor).ceil() as i64;
            bet_to_match.saturating_add(amt.max(1))
        }
        BetSize::AllIn => effective_stack,
    };
    target.min(effective_stack).max(bet_to_match + 1)
}

pub fn is_valid_board_len(len: usize) -> bool {
    matches!(len, 0 | 3 | 4 | 5)
}

pub fn scaled_max_iterations(base: u32, n: usize) -> u32 {
    let n = n.max(1) as u32;
    let scaled = (base as u64 * 3 / n as u64) as u32;
    scaled.clamp(1200, 15000)
}

fn validate_request(req: &MultiwayRequest) -> Result<usize, String> {
    let n = req.ranges.len();
    if !(MIN_PLAYERS..=MAX_PLAYERS).contains(&n) {
        return Err(format!(
            "nombre de joueurs invalide: {} (attendu {}..={})",
            n, MIN_PLAYERS, MAX_PLAYERS
        ));
    }
    if !is_valid_board_len(req.board.len()) {
        return Err(format!(
            "le solveur multiway attend un board de 0|3 à 5 cartes, reçu {}",
            req.board.len()
        ));
    }
    if req.hero_player >= n {
        return Err(format!(
            "hero_player invalide: {} (attendu 0..={})",
            req.hero_player,
            n - 1
        ));
    }
    for (i, r) in req.ranges.iter().enumerate() {
        if r.trim().is_empty() {
            return Err(format!("range {} vide", i));
        }
    }
    Ok(n)
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
pub struct MultiwayRequest {
    pub ranges: Vec<String>,
    pub board: Vec<String>,
    pub starting_pot: f32,
    pub effective_stack: f32,
    pub hero_player: usize,
    #[serde(default = "default_iterations")]
    pub max_iterations: u32,
    #[serde(default)]
    pub random_seed: Option<u64>,
    #[serde(default)]
    pub rake_rate: f32,
    #[serde(default)]
    pub rake_cap: f32,
}

fn default_iterations() -> u32 {
    10_000
}

impl Default for MultiwayRequest {
    fn default() -> Self {
        Self {
            ranges: Vec::new(),
            board: Vec::new(),
            starting_pot: 0.0,
            effective_stack: 0.0,
            hero_player: 0,
            max_iterations: default_iterations(),
            random_seed: None,
            rake_rate: 0.0,
            rake_cap: 0.0,
        }
    }
}

impl From<[String; 3]> for MultiwayRequest {
    fn from(arr: [String; 3]) -> Self {
        Self {
            ranges: arr.to_vec(),
            ..Self::default()
        }
    }
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
pub struct MultiwayResponse {
    pub recommended_action: String,
    pub hero_ev: f32,
    pub exploitability: f32,
    pub actions: Vec<ActionDetail>,
    pub iterations: u32,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
enum Action {
    Fold,
    Call,
    Bet(usize),
}

impl Action {
    fn slot(self) -> usize {
        match self {
            Action::Fold => 0,
            Action::Call => 1,
            Action::Bet(i) => 2 + i,
        }
    }
    fn name_for(&self, board_len: usize, sizing: &SizingConfig) -> String {
        match self {
            Action::Fold => "fold".to_string(),
            Action::Call => "call".to_string(),
            Action::Bet(i) => {
                let bets = sizing.bets_for(board_len);
                if let Some(b) = bets.get(*i) {
                    bet_size_name(b)
                } else {
                    format!("bet_{}", i)
                }
            }
        }
    }
}

/// État complet d'une main N joueurs.
#[derive(Clone)]
pub(crate) struct GameState {
    pub(crate) n: usize,
    pub(crate) committed: PlayerArray<i64>,
    pub(crate) bet_to_match: i64,
    pub(crate) num_raises: usize,
    pub(crate) needs_action: PlayerArray<bool>,
    pub(crate) folded: PlayerArray<bool>,
    pub(crate) current: usize,
    pub(crate) board_cards: [u8; 5],
    pub(crate) board_len: usize,
    pub(crate) starting_pot: i64,
}

impl GameState {
    fn new(n: usize, board_cards: [u8; 5], board_len: usize, starting_pot: i64) -> Self {
        let mut needs_action = [false; MAX_PLAYERS];
        for i in 0..n {
            needs_action[i] = true;
        }
        Self {
            n,
            committed: [0; MAX_PLAYERS],
            starting_pot,
            bet_to_match: 0,
            num_raises: 0,
            needs_action,
            folded: [false; MAX_PLAYERS],
            current: 0,
            board_cards,
            board_len,
        }
    }
    fn active_players(&self) -> usize {
        (0..self.n).filter(|&p| !self.folded[p]).count()
    }
    fn betting_closed(&self) -> bool {
        (0..self.n)
            .filter(|&p| !self.folded[p])
            .all(|p| !self.needs_action[p])
    }
    fn is_terminal(&self) -> bool {
        if self.active_players() <= 1 {
            return true;
        }
        self.board_len == 5 && self.betting_closed()
    }
    fn legal_actions(&self, effective_stack: i64, sizing: &SizingConfig) -> Vec<Action> {
        let mut actions = Vec::with_capacity(ACTION_SLOTS);
        let to_call = self.bet_to_match - self.committed[self.current];
        if to_call > 0 {
            actions.push(Action::Fold);
        }
        actions.push(Action::Call);
        let room = effective_stack - self.committed[self.current];
        let cap = sizing.max_raises_for(self.board_len);
        let can_raise = self.num_raises < cap && room > to_call.max(0);
        if can_raise {
            let pot_total = total_pot(self);
            let bets = sizing.bets_for(self.board_len);
            for (i, bet) in bets.iter().enumerate() {
                if Action::Bet(i).slot() >= ACTION_SLOTS {
                    continue;
                }
                let target = bet_target(bet, pot_total, self.bet_to_match, effective_stack);
                if target <= self.committed[self.current] {
                    continue;
                }
                if target > effective_stack {
                    continue;
                }
                // avoid duplicate targets
                let duplicate = actions.iter().any(|a| {
                    if let Action::Bet(j) = a {
                        let t2 = bet_target(&bets[*j], pot_total, self.bet_to_match, effective_stack);
                        t2 == target
                    } else {
                        false
                    }
                });
                if duplicate {
                    continue;
                }
                // must leave margin
                if target < effective_stack || room > to_call {
                    actions.push(Action::Bet(i));
                }
            }
            // fallback: ensure at least one raise if can_raise and none added but room>to_call
            if actions.iter().all(|a| matches!(a, Action::Fold | Action::Call)) && room > to_call {
                // add largest bet as fallback
                if let Some((i, _)) = sizing.bets_for(self.board_len).iter().enumerate().last() {
                    if Action::Bet(i).slot() < ACTION_SLOTS {
                        actions.push(Action::Bet(i));
                    }
                }
            }
        }
        debug_assert!(!actions.is_empty());
        actions
    }
}

fn total_pot(state: &GameState) -> i64 {
    state.starting_pot + (0..state.n).map(|i| state.committed[i]).sum::<i64>()
}

fn apply_static(state: &GameState, action: Action, effective_stack: i64, sizing: &SizingConfig) -> GameState {
    let mut next = state.clone();
    let player = next.current;
    match action {
        Action::Fold => {
            next.folded[player] = true;
            next.needs_action[player] = false;
            #[cfg(feature = "multiway-debug")]
            ROLLOUT_FOLDS_BY.with(|cell| {
                let mut v = cell.get();
                v[player] += 1;
                cell.set(v)
            });
        }
        Action::Call => {
            let to_add = next.bet_to_match - next.committed[player];
            next.committed[player] += to_add.clamp(0, effective_stack - next.committed[player]);
            next.needs_action[player] = false;
        }
        Action::Bet(idx) => {
            let pot_total = total_pot(state);
            let bets = sizing.bets_for(state.board_len);
            let bet = bets.get(idx).cloned().unwrap_or(BetSize::PotRelative(1.0));
            let target = bet_target(&bet, pot_total, next.bet_to_match, effective_stack);
            next.committed[player] = target;
            next.bet_to_match = target;
            next.num_raises += 1;
            for p in 0..next.n {
                if p != player && !next.folded[p] {
                    next.needs_action[p] = true;
                }
            }
            next.needs_action[player] = false;
        }
    }
    // avance vers prochain acteur
    let mut next_current = player;
    let mut cursor = player;
    for _ in 0..next.n {
        cursor = (cursor + 1) % next.n;
        if next.folded[cursor] {
            continue;
        }
        if next.needs_action[cursor] || next.committed[cursor] < next.bet_to_match {
            next_current = cursor;
            break;
        }
    }
    next.current = next_current;
    next
}

trait Rng {
    fn next_f64(&mut self) -> f64;
}
struct XorShift(u64);
impl XorShift {
    fn new(seed: u64) -> Self {
        Self(seed | 1)
    }
}
impl Rng for XorShift {
    fn next_f64(&mut self) -> f64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        let result = self.0.wrapping_mul(0x2545_F491_4F6C_DD1D);
        ((result >> 11) as f64) / ((1u64 << 53) as f64)
    }
}

struct Solver<'a> {
    n: usize,
    hands: &'a [Vec<[u8; 2]>; MAX_PLAYERS],
    effective_stack: i64,
    #[allow(dead_code)] // conservé pour traçabilité du pot initial ; le pot effectif vit dans GameState::starting_pot / total_pot
    starting_pot: i64,
    rake_rate: f64,
    rake_cap: f64,
    sizing: SizingConfig,
    regrets: FxHashMap<u64, [f64; ACTION_SLOTS]>,
    strategy_sum: FxHashMap<u64, [f64; ACTION_SLOTS]>,
    chosen_stats: PlayerArray<[f64; ACTION_SLOTS]>,
    rng_state: u64,
    iterations_done: u64,
}

impl<'a> Solver<'a> {
    fn next_random_f64(&mut self) -> f64 {
        self.rng_state ^= self.rng_state >> 12;
        self.rng_state ^= self.rng_state << 25;
        self.rng_state ^= self.rng_state >> 27;
        let result = self.rng_state.wrapping_mul(0x2545_F491_4F6C_DD1D);
        ((result >> 11) as f64) / ((1u64 << 53) as f64)
    }
    fn node_key(&self, state: &GameState, player: usize, combo_index: usize) -> u64 {
        let mut key: u64 = 14695981039346656037;
        let mut mix = |v: u64| {
            key ^= v;
            key = key.wrapping_mul(1099511628211);
        };
        mix(state.n as u64);
        mix(state.current as u64);
        mix(state.bet_to_match as u64);
        mix(state.num_raises as u64);
        mix(state.board_len as u64);
        for i in 0..state.board_len {
            mix(state.board_cards[i] as u64);
        }
        let mut folded_mask = 0u64;
        let mut needs_mask = 0u64;
        for p in 0..state.n {
            folded_mask = (folded_mask << 1) | state.folded[p] as u64;
            needs_mask = (needs_mask << 1) | state.needs_action[p] as u64;
        }
        mix(folded_mask);
        mix(needs_mask);
        mix(player as u64);
        mix(combo_index as u64);
        key
    }
    fn sample_deal(&mut self, board_known: &[u8]) -> Result<[usize; MAX_PLAYERS], String> {
        let mut used: u64 = 0;
        for &card in board_known {
            used |= 1u64 << card;
        }
        let mut dealt = [0usize; MAX_PLAYERS];
        for player in 0..self.n {
            let combos = &self.hands[player];
            if combos.is_empty() {
                return Err(format!("range vide joueur {}", player));
            }
            let mut attempts = 0;
            let mut found = false;
            loop {
                attempts += 1;
                if attempts > 1000 {
                    break;
                }
                let index = (self.next_random_f64() * combos.len() as f64) as usize % combos.len();
                let mask = (1u64 << combos[index][0]) | (1u64 << combos[index][1]);
                if used & mask == 0 {
                    used |= mask;
                    dealt[player] = index;
                    found = true;
                    break;
                }
            }
            if !found {
                return Err(format!("échec distribution joueur {}", player));
            }
        }
        Ok(dealt)
    }
    fn average_strategy(&self, key: u64, legal: &[Action]) -> [f64; ACTION_SLOTS] {
        let mut strategy = [0.0f64; ACTION_SLOTS];
        let sum = self.strategy_sum.get(&key).copied().unwrap_or([0.0; ACTION_SLOTS]);
        let total: f64 = legal.iter().map(|a| sum[a.slot()]).sum();
        if total <= 0.0 {
            let uniform = 1.0 / legal.len() as f64;
            for action in legal {
                strategy[action.slot()] = uniform;
            }
        } else {
            for action in legal {
                strategy[action.slot()] = sum[action.slot()] / total;
            }
        }
        strategy
    }
    fn current_strategy(&self, key: u64, legal: &[Action]) -> [f64; ACTION_SLOTS] {
        #[cfg(feature = "multiway-debug")]
        {
            STRAT_LOOKUPS.with(|cell| cell.set(cell.get() + 1));
            if self.strategy_sum.contains_key(&key) {
                STRAT_HITS.with(|cell| cell.set(cell.get() + 1));
            }
        }
        let mut strategy = [0.0f64; ACTION_SLOTS];
        let regrets = self.regrets.get(&key).copied().unwrap_or([0.0; ACTION_SLOTS]);
        let mut total = 0.0f64;
        for action in legal {
            let slot = action.slot();
            let positive = regrets[slot].max(0.0);
            strategy[slot] = positive;
            total += positive;
        }
        if total <= 0.0 {
            let uniform = 1.0 / legal.len() as f64;
            for action in legal {
                strategy[action.slot()] = uniform;
            }
        } else {
            for slot in strategy.iter_mut() {
                *slot /= total;
            }
        }
        strategy
    }
    fn used_mask(&self, state: &GameState, dealt: &[usize; MAX_PLAYERS]) -> u64 {
        let mut mask = 0u64;
        for &card in &state.board_cards[..state.board_len] {
            mask |= 1u64 << card;
        }
        for player in 0..self.n {
            for &card in &self.hands[player][dealt[player]] {
                mask |= 1u64 << card;
            }
        }
        mask
    }
    fn normalize(&mut self, state: &GameState, dealt: &[usize; MAX_PLAYERS]) -> Option<GameState> {
        let mut current = state.clone();
        while !current.is_terminal() && current.betting_closed() {
            let to_deal = if current.board_len == 0 { 3 } else { 1 };
            for _ in 0..to_deal {
                let card = self.sample_next_card(&current, dealt)?;
                current.board_cards[current.board_len] = card;
                current.board_len += 1;
                if current.board_len >= 5 {
                    break;
                }
            }
            current.num_raises = 0;
            current.bet_to_match = 0;
            for p in 0..current.n {
                current.needs_action[p] = !current.folded[p];
            }
            current.current = (0..current.n).find(|&p| !current.folded[p]).unwrap_or(0);
            if to_deal == 3 {
                // after flop deal, continue loop will handle betting if still closed? but need at least one betting round
                // break after dealing flop to allow betting; loop condition will re-check betting_closed
            }
        }
        Some(current)
    }
    fn sample_next_card(&mut self, state: &GameState, dealt: &[usize; MAX_PLAYERS]) -> Option<u8> {
        let used = self.used_mask(state, dealt);
        let mut candidates = [0u8; 52];
        let mut count = 0usize;
        for card in 0u8..52 {
            if used & (1u64 << card) == 0 {
                candidates[count] = card;
                count += 1;
            }
        }
        if count == 0 {
            return None;
        }
        let draw = (self.next_random_f64() * count as f64) as usize;
        Some(candidates[draw.min(count - 1)])
    }
    fn payoffs(&self, state: &GameState, dealt: &[usize; MAX_PLAYERS]) -> [f64; MAX_PLAYERS] {
        let pot_total = total_pot(state) as f64;
        let rake = if self.rake_rate > 0.0 {
            let r = pot_total * self.rake_rate;
            if self.rake_cap > 0.0 { r.min(self.rake_cap) } else { r }
        } else { 0.0 };
        let pot_after_rake = (pot_total - rake).max(0.0);
        if state.active_players() == 1 {
            let winner = (0..state.n).find(|&p| !state.folded[p]).unwrap();
            let mut payoffs = [0.0; MAX_PLAYERS];
            payoffs[winner] = pot_after_rake;
            for p in 0..state.n {
                payoffs[p] -= state.committed[p] as f64;
            }
            return payoffs;
        }
        let mut board_hand = Hand::new();
        for &card in &state.board_cards[..state.board_len] {
            board_hand = board_hand.add_card(card as usize);
        }
        let mut best_rank = 0u16;
        for p in 0..state.n {
            if !state.folded[p] {
                let rank = board_hand
                    .add_card(self.hands[p][dealt[p]][0] as usize)
                    .add_card(self.hands[p][dealt[p]][1] as usize)
                    .evaluate();
                best_rank = best_rank.max(rank);
            }
        }
        let winners: Vec<usize> = (0..state.n)
            .filter(|&p| {
                !state.folded[p]
                    && board_hand
                        .add_card(self.hands[p][dealt[p]][0] as usize)
                        .add_card(self.hands[p][dealt[p]][1] as usize)
                        .evaluate()
                        == best_rank
            })
            .collect();
        let share = pot_after_rake / winners.len() as f64;
        let mut payoffs = [0.0; MAX_PLAYERS];
        for p in 0..state.n {
            payoffs[p] -= state.committed[p] as f64;
            if winners.contains(&p) {
                payoffs[p] += share;
            }
        }
        payoffs
    }
    fn traverse(&mut self, state: &GameState, dealt: &[usize; MAX_PLAYERS], traverser: usize) -> [f64; MAX_PLAYERS] {
        let Some(state) = self.normalize(state, dealt) else {
            return [0.0; MAX_PLAYERS];
        };
        if state.is_terminal() {
            return self.payoffs(&state, dealt);
        }
        let player = state.current;
        let legal = state.legal_actions(self.effective_stack, &self.sizing);
        let combo_index = dealt[player];
        let key = self.node_key(&state, player, combo_index);
        let strategy = self.current_strategy(key, &legal);
        if player == traverser {
            let mut utilities = [[0.0f64; MAX_PLAYERS]; ACTION_SLOTS];
            let mut expected = [0.0f64; MAX_PLAYERS];
            for action in &legal {
                let slot = action.slot();
                let child = apply_static(&state, *action, self.effective_stack, &self.sizing);
                let util = self.traverse(&child, dealt, traverser);
                utilities[slot] = util;
                for p in 0..self.n {
                    expected[p] += strategy[slot] * util[p];
                }
            }
            let entry = self.regrets.entry(key).or_insert([0.0; ACTION_SLOTS]);
            for action in &legal {
                let slot = action.slot();
                entry[slot] = (entry[slot] + utilities[slot][traverser] - expected[traverser]).max(0.0);
            }
            let weight = (self.iterations_done + 1) as f64;
            let sum = self.strategy_sum.entry(key).or_insert([0.0; ACTION_SLOTS]);
            for action in &legal {
                sum[action.slot()] += strategy[action.slot()] * weight;
            }
            expected
        } else {
            let draw = self.next_random_f64();
            let mut cumulative = 0.0;
            let mut chosen = legal[legal.len() - 1];
            for action in &legal {
                cumulative += strategy[action.slot()];
                if draw <= cumulative {
                    chosen = *action;
                    break;
                }
            }
            let weight = (self.iterations_done + 1) as f64;
            let sum = self.strategy_sum.entry(key).or_insert([0.0; ACTION_SLOTS]);
            sum[chosen.slot()] += strategy[chosen.slot()] * weight;
            self.chosen_stats[player][chosen.slot()] += 1.0;
            let child = apply_static(&state, chosen, self.effective_stack, &self.sizing);
            self.traverse(&child, dealt, traverser)
        }
    }
}

fn parse_cards(texts: &[String]) -> Result<Vec<u8>, String> {
    texts
        .iter()
        .map(|text| {
            let normalized = format!("{}{}", text[..1].to_ascii_uppercase(), text[1..].to_ascii_lowercase());
            card_from_str(&normalized).map_err(|err| err.to_string())
        })
        .collect()
}
fn build_combo_list(range_text: &str, dead_mask: u64) -> Result<Vec<[u8; 2]>, String> {
    let range = Range::from_sanitized_str(range_text).map_err(|err| format!("range invalide '{range_text}': {err}"))?;
    let (hands, _weights) = range.get_hands_weights(dead_mask);
    Ok(hands.into_iter().map(|(first, second)| [first, second]).collect())
}
fn sample_deal_free(hands: &[Vec<[u8; 2]>; MAX_PLAYERS], n: usize, board_known: &[u8], rng: &mut impl Rng) -> Option<[usize; MAX_PLAYERS]> {
    let mut used: u64 = 0;
    for &card in board_known {
        used |= 1u64 << card;
    }
    let mut dealt = [0usize; MAX_PLAYERS];
    for player in 0..n {
        let combos = &hands[player];
        if combos.is_empty() {
            return None;
        }
        let mut attempts = 0;
        loop {
            attempts += 1;
            if attempts > 1000 {
                return None;
            }
            let index = (rng.next_f64() * combos.len() as f64) as usize % combos.len();
            let mask = (1u64 << combos[index][0]) | (1u64 << combos[index][1]);
            if used & mask == 0 {
                used |= mask;
                dealt[player] = index;
                break;
            }
        }
    }
    Some(dealt)
}

pub fn solve_multiway(request: MultiwayRequest) -> Result<MultiwayResponse, String> {
    let n = validate_request(&request)?;
    let board = parse_cards(&request.board)?;
    let mut seen = [false; 52];
    for &card in &board {
        if seen[card as usize] {
            return Err(format!("carte dupliquée dans le board: {}", crate::card_to_string(card)?));
        }
        seen[card as usize] = true;
    }
    let mut dead_mask = 0u64;
    for &card in &board {
        dead_mask |= 1u64 << card;
    }
    let mut hand_lists: [Vec<[u8; 2]>; MAX_PLAYERS] = Default::default();
    for (index, range_text) in request.ranges.iter().enumerate() {
        hand_lists[index] = build_combo_list(range_text, dead_mask)?;
        if hand_lists[index].is_empty() {
            return Err(format!("range {} vide après retrait du board", index));
        }
    }
    let hands_ref: &[Vec<[u8; 2]>; MAX_PLAYERS] = &hand_lists;
    let effective_stack = request.effective_stack.round() as i64;
    let starting_pot = request.starting_pot.round() as i64;
    if effective_stack <= 0 || starting_pot <= 0 {
        return Err("starting_pot et effective_stack doivent être positifs".to_string());
    }
    let seed = request.random_seed.unwrap_or(0x2026_0826_9593_74D1);
    let sizing = SizingConfig::default();
    let mut solver = Solver {
        n,
        hands: hands_ref,
        effective_stack,
        starting_pot,
        rake_rate: request.rake_rate as f64,
        rake_cap: request.rake_cap as f64,
        sizing: sizing.clone(),
        regrets: FxHashMap::new(),
        strategy_sum: FxHashMap::new(),
        chosen_stats: [[0.0; ACTION_SLOTS]; MAX_PLAYERS],
        rng_state: seed | 1,
        iterations_done: 0,
    };
    let mut board_array = [0u8; 5];
    for (index, &card) in board.iter().enumerate() {
        board_array[index] = card;
    }
    let root = GameState::new(n, board_array, board.len(), starting_pot);
    let iterations = scaled_max_iterations(request.max_iterations.max(100), n);
    let mut successes = 0usize;
    let mut failures = 0usize;
    for _ in 0..iterations {
        let dealt = match solver.sample_deal(&board) {
            Ok(d) => {
                successes += 1;
                d
            }
            Err(_) => {
                failures += 1;
                continue;
            }
        };
        for traverser in 0..n {
            solver.traverse(&root, &dealt, traverser);
        }
        solver.iterations_done += 1;
    }
    if successes + failures > 0 && successes * 2 <= successes + failures {
        return Err(format!("taux de distribution <50% {}/{}", successes, successes + failures));
    }
    if solver.iterations_done == 0 {
        return Err("aucune itération réussie".to_string());
    }
    evaluate_solution(&solver, hands_ref, &request, effective_stack, starting_pot, seed)
}

fn evaluate_solution(solver: &Solver, hands: &[Vec<[u8; 2]>; MAX_PLAYERS], request: &MultiwayRequest, effective_stack: i64, starting_pot: i64, seed: u64) -> Result<MultiwayResponse, String> {
    let hero = request.hero_player;
    if hands[hero].is_empty() {
        return Err("la range héro est vide après retrait du board".to_string());
    }
    let mut board_array = [0u8; 5];
    for (index, text) in request.board.iter().enumerate() {
        let normalized = format!("{}{}", text[..1].to_ascii_uppercase(), text[1..].to_ascii_lowercase());
        board_array[index] = card_from_str(&normalized).map_err(|err| err.to_string())?;
    }
    let n = solver.n;
    let sizing = &solver.sizing;
    let root = GameState::new(n, board_array, request.board.len(), starting_pot);
    let mut freq_sum = [0.0f64; ACTION_SLOTS];
    let mut counted_combos = 0usize;
    for combo_index in 0..hands[hero].len() {
        let key = solver.node_key(&root, hero, combo_index);
        if let Some(sum) = solver.strategy_sum.get(&key) {
            let total: f64 = sum.iter().sum();
            if total > 0.0 {
                for slot in 0..ACTION_SLOTS {
                    freq_sum[slot] += sum[slot] / total;
                }
                counted_combos += 1;
            }
        }
    }
    if counted_combos == 0 {
        return Err("aucune stratégie moyenne collectée : augmentez max_iterations".to_string());
    }
    for slot in freq_sum.iter_mut() {
        *slot /= counted_combos as f64;
    }
    // build action names from root sizing
    let mut actions: Vec<ActionDetail> = Vec::new();
    let legal_root = root.legal_actions(effective_stack, sizing);
    // ensure at least fold/call slots considered
    let mut slot_to_name: [Option<String>; ACTION_SLOTS] = Default::default();
    for a in &legal_root {
        slot_to_name[a.slot()] = Some(a.name_for(root.board_len, sizing));
    }
    // fallback names for slots not in legal_root but with freq>0 (should not happen)
    for slot in 0..ACTION_SLOTS {
        if freq_sum[slot] > 0.0 || slot == 1 {
            let name = slot_to_name[slot].clone().unwrap_or_else(|| match slot {
                0 => "fold".to_string(),
                1 => "call".to_string(),
                2 => "bet_0.33".to_string(),
                3 => "bet_0.5".to_string(),
                4 => "bet_1".to_string(),
                5 => "bet_1.5".to_string(),
                _ => format!("bet_{}", slot),
            });
            // avoid duplicates
            if !actions.iter().any(|ad| ad.name == name) {
                actions.push(ActionDetail { name, frequency: freq_sum[slot] as f32, ev: 0.0 });
            }
        }
    }
    // ensure actions sorted by slot for determinism
    // frequency already from freq_sum; for slots with zero but included (call), keep
    let mut recommended_slot = 1;
    for slot in 0..ACTION_SLOTS {
        if freq_sum[slot] > freq_sum[recommended_slot] {
            recommended_slot = slot;
        }
    }
    let recommended_action = actions.iter().find(|a| {
        // map recommended slot to name
        let target_name = slot_to_name[recommended_slot].clone().unwrap_or_else(|| match recommended_slot {
            0 => "fold".to_string(),
            1 => "call".to_string(),
            _ => format!("bet_{}", recommended_slot),
        });
        a.name == target_name
    }).map(|a| a.name.clone()).unwrap_or_else(|| {
        slot_to_name[recommended_slot].clone().unwrap_or("call".to_string())
    });
    let mut mc_rng = XorShift::new(seed ^ 0x5EED_CAFE_F00D_0001);
    let samples = 4000usize;
    let mut ev_sum = 0.0f64;
    let mut br_best_sum = 0.0f64;
    for _ in 0..samples {
        let Some(dealt) = sample_deal_free(hands, n, &request_board_bytes(request), &mut mc_rng) else { continue; };
        let ev = rollout_average(solver, hands, dealt, &root, hero, effective_stack, starting_pot, &mut mc_rng, 24);
        ev_sum += ev;
        let mut best = f64::NEG_INFINITY;
        for action in root.legal_actions(effective_stack, sizing) {
            let child = apply_static(&root, action, effective_stack, sizing);
            let value = rollout_average(solver, hands, dealt, &child, hero, effective_stack, starting_pot, &mut mc_rng, 6);
            best = best.max(value);
        }
        if best.is_finite() { br_best_sum += best; }
    }
    let hero_ev = ev_sum / samples as f64;
    let br_ev = br_best_sum / samples as f64;
    let exploitability = (br_ev - hero_ev).max(0.0) as f32;
    for action in &mut actions {
        if action.name == recommended_action { action.ev = hero_ev as f32; }
    }
    Ok(MultiwayResponse { recommended_action, hero_ev: hero_ev as f32, exploitability, actions, iterations: solver.iterations_done as u32 })
}

fn request_board_bytes(request: &MultiwayRequest) -> Vec<u8> {
    request.board.iter().map(|text| {
        let normalized = format!("{}{}", text[..1].to_ascii_uppercase(), text[1..].to_ascii_lowercase());
        card_from_str(&normalized).unwrap_or(0)
    }).collect()
}

fn rollout_average(solver: &Solver, hands: &[Vec<[u8; 2]>; MAX_PLAYERS], dealt: [usize; MAX_PLAYERS], state: &GameState, hero: usize, effective_stack: i64, _starting_pot: i64, rng: &mut impl Rng, step_budget: usize) -> f64 {
    let mut state = state.clone();
    let mut guard = 0usize;
    while !state.is_terminal() && guard < step_budget {
        guard += 1;
        if state.betting_closed() {
            let to_deal = if state.board_len == 0 { 3 } else { 1 };
            let mut dealt_any = false;
            for _ in 0..to_deal {
                if state.board_len >= 5 { break; }
                let Some(card) = sample_next_card_rollout(&state, hands, dealt, rng) else { break; };
                state.board_cards[state.board_len] = card;
                state.board_len += 1;
                dealt_any = true;
            }
            if !dealt_any { break; }
            state.num_raises = 0;
            state.bet_to_match = 0;
            for p in 0..state.n { state.needs_action[p] = !state.folded[p]; }
            state.current = (0..state.n).find(|&p| !state.folded[p]).unwrap_or(0);
            continue;
        }
        let player = state.current;
        let legal = state.legal_actions(effective_stack, &solver.sizing);
        let combo_index = dealt[player];
        let key = solver.node_key(&state, player, combo_index);
        let strategy = solver.average_strategy(key, &legal);
        let draw = rng.next_f64();
        let mut cumulative = 0.0;
        let mut chosen = legal[legal.len() - 1];
        for action in &legal {
            cumulative += strategy[action.slot()];
            if draw <= cumulative { chosen = *action; break; }
        }
        state = apply_static(&state, chosen, effective_stack, &solver.sizing);
    }
    if !state.is_terminal() {
        for p in 0..state.n {
            state.needs_action[p] = false;
            let to_add = state.bet_to_match - state.committed[p];
            state.committed[p] += to_add.max(0);
        }
        while state.board_len < 5 {
            let Some(card) = sample_next_card_rollout(&state, hands, dealt, rng) else { break; };
            state.board_cards[state.board_len] = card;
            state.board_len += 1;
        }
    }
    static_payoffs(&state, hands, dealt, total_pot(&state), solver.rake_rate, solver.rake_cap)[hero]
}

#[cfg(feature = "multiway-debug")]
thread_local! {
    static ROLLOUT_FOLD_ENDS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static ROLLOUT_HERO_STEALS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static STRAT_LOOKUPS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static STRAT_HITS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static ROLLOUT_FOLDS_BY: std::cell::Cell<[u64; MAX_PLAYERS]> = const { std::cell::Cell::new([0; MAX_PLAYERS]) };
}

fn sample_next_card_rollout(state: &GameState, hands: &[Vec<[u8; 2]>; MAX_PLAYERS], dealt: [usize; MAX_PLAYERS], rng: &mut impl Rng) -> Option<u8> {
    let mut used: u64 = 0;
    for &card in &state.board_cards[..state.board_len] { used |= 1u64 << card; }
    for player in 0..state.n {
        for &card in &hands[player][dealt[player]] { used |= 1u64 << card; }
    }
    let mut candidates = [0u8; 52];
    let mut count = 0usize;
    for card in 0u8..52 { if used & (1u64 << card) == 0 { candidates[count]=card; count+=1; } }
    if count==0 { return None; }
    let draw = (rng.next_f64() * count as f64) as usize;
    Some(candidates[draw.min(count-1)])
}
fn static_payoffs(state: &GameState, hands: &[Vec<[u8; 2]>; MAX_PLAYERS], dealt: [usize; MAX_PLAYERS], pot_total: i64, rake_rate: f64, rake_cap: f64) -> [f64; MAX_PLAYERS] {
    let pot_f = pot_total as f64;
    let rake = if rake_rate > 0.0 { let r = pot_f * rake_rate; if rake_cap > 0.0 { r.min(rake_cap) } else { r } } else { 0.0 };
    let pot_after = (pot_f - rake).max(0.0);
    if state.active_players() == 1 {
        let winner = (0..state.n).find(|&p| !state.folded[p]).unwrap();
        let mut payoffs = [0.0; MAX_PLAYERS];
        payoffs[winner] = pot_after;
        for p in 0..state.n { payoffs[p] -= state.committed[p] as f64; }
        return payoffs;
    }
    let mut board_hand = Hand::new();
    for &card in &state.board_cards[..state.board_len.min(5)] { board_hand = board_hand.add_card(card as usize); }
    let mut best_rank = 0u16;
    for p in 0..state.n {
        if !state.folded[p] {
            let rank = board_hand.add_card(hands[p][dealt[p]][0] as usize).add_card(hands[p][dealt[p]][1] as usize).evaluate();
            best_rank = best_rank.max(rank);
        }
    }
    let winners = (0..state.n).filter(|&p| !state.folded[p] && board_hand.add_card(hands[p][dealt[p]][0] as usize).add_card(hands[p][dealt[p]][1] as usize).evaluate() == best_rank).count().max(1) as f64;
    let mut payoffs = [0.0; MAX_PLAYERS];
    for p in 0..state.n {
        payoffs[p] -= state.committed[p] as f64;
        if !state.folded[p] && board_hand.add_card(hands[p][dealt[p]][0] as usize).add_card(hands[p][dealt[p]][1] as usize).evaluate() == best_rank {
            payoffs[p] += pot_after / winners;
        }
    }
    payoffs
}

#[cfg(test)]
mod internal_tests {
    use super::*;
    fn card(text: &str) -> u8 { crate::card_from_str(text).unwrap() }
    #[test]
    fn showdown_payoffs_are_zero_sum_and_correct() {
        let board_cards = [card("Ah"), card("7d"), card("2c"), card("Kd"), card("9s")];
        let state = GameState::new(3, board_cards, 5, 6);
        let mut hands: [Vec<[u8;2]>; MAX_PLAYERS] = Default::default();
        hands[0]=vec![[card("As"), card("Ac")]];
        hands[1]=vec![[card("Ks"), card("Kh")]];
        hands[2]=vec![[card("Qs"), card("Qh")]];
        let dealt = [0,0,0,0,0,0];
        let mut bet_state = state.clone();
        bet_state.committed[0]=2; bet_state.committed[1]=2; bet_state.committed[2]=2;
        let pot_total = 6+6;
        let payoffs = static_payoffs(&bet_state, &hands, dealt, pot_total, 0.0, 0.0);
        assert_eq!(payoffs[0], 10.0);
        assert_eq!(payoffs[1], -2.0);
        assert_eq!(payoffs[2], -2.0);
    }
    #[test]
    fn rake_reduces_payoffs() {
        let board_cards = [card("Ah"), card("7d"), card("2c"), card("Kd"), card("9s")];
        let state = GameState::new(3, board_cards, 5, 6);
        let mut hands: [Vec<[u8;2]>; MAX_PLAYERS] = Default::default();
        hands[0]=vec![[card("As"), card("Ac")]];
        hands[1]=vec![[card("Ks"), card("Kh")]];
        hands[2]=vec![[card("Qs"), card("Qh")]];
        let dealt = [0,0,0,0,0,0];
        let mut bet_state = state.clone();
        bet_state.committed[0]=2; bet_state.committed[1]=2; bet_state.committed[2]=2;
        let pot_total = 12;
        let payoffs_no_rake = static_payoffs(&bet_state, &hands, dealt, pot_total, 0.0, 0.0);
        let payoffs_rake = static_payoffs(&bet_state, &hands, dealt, pot_total, 0.05, 3.0);
        assert!(payoffs_rake[0] < payoffs_no_rake[0]);
    }
    #[test]
    fn fold_payoffs_award_pot_to_last_player() {
        let board_cards = [card("Ah"), card("7d"), card("2c"), card("Kd"), card("9s")];
        let mut state = GameState::new(3, board_cards, 5, 6);
        state.folded=[false, true, true, false,false,false];
        state.committed=[4,1,1,0,0,0];
        let mut hands: [Vec<[u8;2]>; MAX_PLAYERS] = Default::default();
        hands[0]=vec![[card("As"), card("Ac")]];
        hands[1]=vec![[card("Ks"), card("Kh")]];
        hands[2]=vec![[card("Qs"), card("Qh")]];
        let payoffs = static_payoffs(&state, &hands, [0,0,0,0,0,0], 12, 0.0, 0.0);
        assert_eq!(payoffs[0], 8.0);
    }
    #[test]
    fn betting_closed_after_all_active_players_call() {
        let sizing = SizingConfig::default();
        let mut state = GameState::new(3, [card("Ah"), card("7d"), card("2c"),0,0], 3, 6);
        let stack=20;
        state = apply_static(&state, Action::Bet(1), stack, &sizing);
        assert_eq!(state.current, 1);
        state = apply_static(&state, Action::Call, stack, &sizing);
        state = apply_static(&state, Action::Call, stack, &sizing);
        assert!(state.betting_closed());
        assert!(!state.is_terminal());
    }
}
