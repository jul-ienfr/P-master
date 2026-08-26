//! Solveur 3-way flop/turn/river par MCCFR à échantillonnage externe (Phase 3.12).
//!
//! Le moteur DCFR principal est intrinsèquement binaire (weights/cfreach par
//! paires de joueurs) ; le généraliser à N joueurs revient à réécrire
//! base.rs/solver.rs/utility.rs (~1200 points de couplage). Ce module fournit
//! une voie native 3 joueurs sans toucher au moteur HU existant :
//!
//! - arbre multi-street : le board fourni peut contenir 3 (flop), 4 (turn) ou
//!   5 (river) cartes ; les streets suivantes sont des nÅ“uds de chance
//!   échantillonnés uniformément dans le paquet restant ;
//! - abstraction fixe par street : fold / check-call / relance demi-pot /
//!   relance à hauteur du pot (all-in fusionné), max 2 relances par street ;
//! - regrets et stratégie cumulée indexés par (noeud, joueur, combo) ;
//! - showdowns exacts via l'évaluateur `Hand` du crate ;
//! - exploitabilité approchée par Monte-Carlo best-response (graine fixe).
//!
//! Limites assumées : échantillonnage uniforme des cartes de chance (sans
//! repondération par les ranges adverses), exploitabilité estimée (non exacte).

use crate::card_from_str;
use crate::gto_api::ActionDetail;
use crate::hand::Hand;
use crate::range::Range;
use serde::{Deserialize, Serialize};

pub(crate) const N_PLAYERS: usize = 3;
/// Nombre maximum de relances PAR STREET avant check-call/all-in forcé.
pub(crate) const MAX_RAISES_PER_STREET: usize = 2;
/// Nombre de créneaux d'action (fold, call, raise-half, raise-pot).
pub(crate) const ACTION_SLOTS: usize = 4;

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
pub struct MultiwayRequest {
    /// Range du joueur 0, puis joueur 1, puis joueur 2.
    pub ranges: [String; 3],
    /// Board partiel : 3 (flop), 4 (turn) ou 5 (river) cartes.
    pub board: Vec<String>,
    pub starting_pot: f32,
    pub effective_stack: f32,
    /// Index du joueur héro (0..=2).
    pub hero_player: usize,
    #[serde(default = "default_iterations")]
    pub max_iterations: u32,
    #[serde(default)]
    pub random_seed: Option<u64>,
}

fn default_iterations() -> u32 {
    10_000
}

impl Default for MultiwayRequest {
    fn default() -> Self {
        Self {
            ranges: [String::new(), String::new(), String::new()],
            board: Vec::new(),
            starting_pot: 0.0,
            effective_stack: 0.0,
            hero_player: 0,
            max_iterations: default_iterations(),
            random_seed: None,
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

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum Action {
    Fold,
    Call,
    RaiseHalf,
    RaisePot,
}

impl Action {
    fn slot(self) -> usize {
        match self {
            Action::Fold => 0,
            Action::Call => 1,
            Action::RaiseHalf => 2,
            Action::RaisePot => 3,
        }
    }

    fn name(self) -> &'static str {
        match self {
            Action::Fold => "fold",
            Action::Call => "call",
            Action::RaiseHalf => "bet_0.5",
            Action::RaisePot => "bet_1",
        }
    }
}

/// État complet d'une main 3 joueurs (multi-street).
#[derive(Clone)]
pub(crate) struct GameState {
    /// Mises engagées, cumulées sur toutes les streets.
    pub(crate) committed: [i64; N_PLAYERS],
    pub(crate) bet_to_match: i64,
    pub(crate) num_raises: usize,
    pub(crate) needs_action: [bool; N_PLAYERS],
    pub(crate) folded: [bool; N_PLAYERS],
    pub(crate) current: usize,
    /// Cartes de board connues/distribuées (les non-distribuées sont à 0).
    pub(crate) board_cards: [u8; 5],
    pub(crate) board_len: usize,
    /// Pot déjà en jeu au début de la main (inclut les streets précédentes).
    pub(crate) starting_pot: i64,
}

impl GameState {
    fn new(board_cards: [u8; 5], board_len: usize, starting_pot: i64) -> Self {
        Self {
            committed: [0; N_PLAYERS],
            starting_pot,
            bet_to_match: 0,
            num_raises: 0,
            needs_action: [true; N_PLAYERS],
            folded: [false; N_PLAYERS],
            current: 0,
            board_cards,
            board_len,
        }
    }

    fn active_players(&self) -> usize {
        self.folded.iter().filter(|&&f| !f).count()
    }

    /// Fin des enchères sur la street courante : plus personne n'a d'action due.
    fn betting_closed(&self) -> bool {
        (0..N_PLAYERS)
            .filter(|&p| !self.folded[p])
            .all(|p| !self.needs_action[p])
    }

    fn is_terminal(&self) -> bool {
        if self.active_players() <= 1 {
            return true;
        }
        // Abattu uniquement une fois le board complet ; sinon c'est un nÅ“ud de chance.
        self.board_len == 5 && self.betting_closed()
    }

    fn legal_actions(&self, effective_stack: i64) -> Vec<Action> {
        let mut actions = Vec::with_capacity(ACTION_SLOTS);
        let to_call = self.bet_to_match - self.committed[self.current];
        if to_call > 0 {
            actions.push(Action::Fold);
        }
        actions.push(Action::Call);

        let room = effective_stack - self.committed[self.current];
        let can_raise =
            self.num_raises < MAX_RAISES_PER_STREET && room > to_call.max(0);
        if can_raise {
            let pot_total = total_pot(self);
            let half_target = self.bet_to_match + (pot_total / 2).max(1);
            let pot_target = self.bet_to_match + pot_total.max(1);
            // Une taille n'est proposée que si elle laisse de la marge (sinon
            // elle dégénère en all-in déjà couvert par l'autre taille).
            if half_target <= effective_stack && half_target < pot_target.min(effective_stack) {
                actions.push(Action::RaiseHalf);
            }
            if pot_target <= effective_stack || room > to_call {
                actions.push(Action::RaisePot);
            }
        }
        debug_assert!(!actions.is_empty());
        actions
    }
}

fn total_pot(state: &GameState) -> i64 {
    state.starting_pot + state.committed.iter().sum::<i64>()
}

/// Applique une action (règles pures, avance bornée vers le prochain acteur).
fn apply_static(state: &GameState, action: Action, effective_stack: i64) -> GameState {
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
        Action::RaiseHalf | Action::RaisePot => {
            let pot_total = total_pot(state);
            let size_factor = if action == Action::RaiseHalf { 0.5 } else { 1.0 };
            let raise_amount = ((pot_total as f64) * size_factor).ceil() as i64;
            let target = next
                .bet_to_match
                .saturating_add(raise_amount.max(1))
                .min(effective_stack)
                .max(next.bet_to_match + 1);
            next.committed[player] = target;
            next.bet_to_match = target;
            next.num_raises += 1;
            for p in 0..N_PLAYERS {
                if p != player && !next.folded[p] {
                    next.needs_action[p] = true;
                }
            }
            next.needs_action[player] = false;
        }
    }
    // Avance vers le prochain joueur actif devant agir ; s'il n'y en a aucun,
    // l'état est en fin de street (chance ou terminal) et current reste tel quel.
    let mut next_current = player;
    let mut cursor = player;
    for _ in 0..N_PLAYERS {
        cursor = (cursor + 1) % N_PLAYERS;
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
    hands: &'a [Vec<[u8; 2]>; N_PLAYERS],
    effective_stack: i64,
    starting_pot: i64,
    regrets: std::collections::HashMap<u64, [f64; ACTION_SLOTS]>,
    strategy_sum: std::collections::HashMap<u64, [f64; ACTION_SLOTS]>,
    /// Actions effectivement jouées par joueur pendant l'entraînement (diagnostic).
    chosen_stats: [[f64; ACTION_SLOTS]; N_PLAYERS],
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
        {
            let mut mix = |v: u64| {
                key ^= v;
                key = key.wrapping_mul(1099511628211);
            };
            mix(state.current as u64);
            mix(state.bet_to_match as u64);
            mix(state.num_raises as u64);
            mix(state.board_len as u64);
            // Dernière carte du board : deux flops différents ne partagent pas d'infoset.
            if state.board_len > 0 {
                mix(state.board_cards[state.board_len - 1] as u64);
            }
            mix(state.folded.iter().fold(0u64, |acc, &f| (acc << 1) | f as u64));
            mix(
                state
                    .needs_action
                    .iter()
                    .fold(0u64, |acc, &a| (acc << 1) | a as u64),
            );
            mix(player as u64);
            mix(combo_index as u64);
        }
        key
    }

    /// Tire une main privée cohérente pour chaque joueur (sans conflit de cartes).
    fn sample_deal(&mut self, board_known: &[u8]) -> Option<[usize; N_PLAYERS]> {
        let mut used: u64 = 0;
        for &card in board_known {
            used |= 1u64 << card;
        }
        let mut dealt = [0usize; N_PLAYERS];

        for player in 0..N_PLAYERS {
            let combos = &self.hands[player];
            if combos.is_empty() {
                return None;
            }
            let mut attempts = 0;
            loop {
                attempts += 1;
                if attempts > 1000 {
                    return None;
                }
                let index =
                    (self.next_random_f64() * combos.len() as f64) as usize % combos.len();
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

    /// Stratégie MOYENNE cumulée (celle qui converge vers l'équilibre) ;
    /// utilisée pour l'évaluation, distincte du regret matching d'entraînement.
    fn average_strategy(&self, key: u64, legal: &[Action]) -> [f64; ACTION_SLOTS] {
        let mut strategy = [0.0f64; ACTION_SLOTS];
        let sum = self
            .strategy_sum
            .get(&key)
            .copied()
            .unwrap_or([0.0; ACTION_SLOTS]);
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

    fn used_mask(&self, state: &GameState, dealt: &[usize; N_PLAYERS]) -> u64 {
        let mut mask = 0u64;
        for &card in &state.board_cards[..state.board_len] {
            mask |= 1u64 << card;
        }
        for player in 0..N_PLAYERS {
            for &card in &self.hands[player][dealt[player]] {
                mask |= 1u64 << card;
            }
        }
        mask
    }

    /// Résout les transitions de chance (distribution des streets suivantes).
    fn normalize(&mut self, state: &GameState, dealt: &[usize; N_PLAYERS]) -> Option<GameState> {
        let mut current = state.clone();
        while !current.is_terminal() && current.betting_closed() {
            let card = self.sample_next_card(&current, dealt)?;
            current.board_cards[current.board_len] = card;
            current.board_len += 1;
            // Nouvelle street : remise à zéro de l'agression locale.
            current.num_raises = 0;
            current.bet_to_match = 0;
            for p in 0..N_PLAYERS {
                current.needs_action[p] = !current.folded[p];
            }
            current.current = (0..N_PLAYERS).find(|&p| !current.folded[p]).unwrap_or(0);
        }
        Some(current)
    }

    fn sample_next_card(
        &mut self,
        state: &GameState,
        dealt: &[usize; N_PLAYERS],
    ) -> Option<u8> {
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

    fn payoffs(&self, state: &GameState, dealt: &[usize; N_PLAYERS]) -> [f64; N_PLAYERS] {
        let pot_total = total_pot(state);

        if state.active_players() == 1 {
            let winner = (0..N_PLAYERS).find(|&p| !state.folded[p]).unwrap();
            let mut payoffs = [0.0; N_PLAYERS];
            payoffs[winner] = pot_total as f64;
            for p in 0..N_PLAYERS {
                payoffs[p] -= state.committed[p] as f64;
            }
            return payoffs;
        }

        // Abattu : rangs calculés sur le board complet.
        let mut board_hand = Hand::new();
        for &card in &state.board_cards[..state.board_len] {
            board_hand = board_hand.add_card(card as usize);
        }
        let mut best_rank = 0u16;
        for p in 0..N_PLAYERS {
            if !state.folded[p] {
                let rank = board_hand
                    .add_card(self.hands[p][dealt[p]][0] as usize)
                    .add_card(self.hands[p][dealt[p]][1] as usize)
                    .evaluate();
                best_rank = best_rank.max(rank);
            }
        }
        let winners: Vec<usize> = (0..N_PLAYERS)
            .filter(|&p| {
                !state.folded[p]
                    && board_hand
                        .add_card(self.hands[p][dealt[p]][0] as usize)
                        .add_card(self.hands[p][dealt[p]][1] as usize)
                        .evaluate()
                        == best_rank
            })
            .collect();
        let share = pot_total as f64 / winners.len() as f64;

        let mut payoffs = [0.0; N_PLAYERS];
        for p in 0..N_PLAYERS {
            payoffs[p] -= state.committed[p] as f64;
            if winners.contains(&p) {
                payoffs[p] += share;
            }
        }
        payoffs
    }

    /// Un pas de MCCFR à échantillonnage externe. Retourne l'utilité atteinte.
    fn traverse(
        &mut self,
        state: &GameState,
        dealt: &[usize; N_PLAYERS],
        traverser: usize,
    ) -> [f64; N_PLAYERS] {
        let Some(state) = self.normalize(state, dealt) else {
            return [0.0; N_PLAYERS];
        };
        if state.is_terminal() {
            return self.payoffs(&state, dealt);
        }

        let player = state.current;
        let legal = state.legal_actions(self.effective_stack);
        let combo_index = dealt[player];
        let key = self.node_key(&state, player, combo_index);
        let strategy = self.current_strategy(key, &legal);

        if player == traverser {
            let mut utilities = [[0.0f64; N_PLAYERS]; ACTION_SLOTS];
            let mut expected = [0.0f64; N_PLAYERS];
            for action in &legal {
                let slot = action.slot();
                let child = apply_static(&state, *action, self.effective_stack);
                let util = self.traverse(&child, dealt, traverser);
                utilities[slot] = util;
                for p in 0..N_PLAYERS {
                    expected[p] += strategy[slot] * util[p];
                }
            }
            let entry = self.regrets.entry(key).or_insert([0.0; ACTION_SLOTS]);
            for action in &legal {
                let slot = action.slot();
                // Clipping CFR+ : les regrets négatifs sont remis à zéro, ce qui
                // accélère nettement la convergence en multiway.
                entry[slot] = (entry[slot] + utilities[slot][traverser] - expected[traverser])
                    .max(0.0);
            }
            // Pondération linéaire classique : la moyenne privilégie les
            // stratégies tardives et se décolle vite du prior uniforme.
            let weight = (self.iterations_done + 1) as f64;
            let sum = self.strategy_sum.entry(key).or_insert([0.0; ACTION_SLOTS]);
            for action in &legal {
                sum[action.slot()] += strategy[action.slot()] * weight;
            }
            expected
        } else {
            // Joueur hors traversée : échantillonne une action selon sa stratégie.
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
            let child = apply_static(&state, chosen, self.effective_stack);
            self.traverse(&child, dealt, traverser)
        }
    }
}

fn parse_cards(texts: &[String]) -> Result<Vec<u8>, String> {
    texts
        .iter()
        .map(|text| {
            let normalized = format!(
                "{}{}",
                text[..1].to_ascii_uppercase(),
                text[1..].to_ascii_lowercase()
            );
            card_from_str(&normalized).map_err(|err| err.to_string())
        })
        .collect()
}

fn build_combo_list(range_text: &str, dead_mask: u64) -> Result<Vec<[u8; 2]>, String> {
    let range = Range::from_sanitized_str(range_text)
        .map_err(|err| format!("range invalide '{range_text}': {err}"))?;
    let (hands, _weights) = range.get_hands_weights(dead_mask);
    Ok(hands
        .into_iter()
        .map(|(first, second)| [first, second])
        .collect())
}

/// Tirage de mains privées avec un rng externe (évaluation Monte-Carlo).
fn sample_deal_free(
    hands: &[Vec<[u8; 2]>; N_PLAYERS],
    board_known: &[u8],
    rng: &mut impl Rng,
) -> Option<[usize; N_PLAYERS]> {
    let mut used: u64 = 0;
    for &card in board_known {
        used |= 1u64 << card;
    }
    let mut dealt = [0usize; N_PLAYERS];

    for player in 0..N_PLAYERS {
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

/// Résout un spot flop/turn/river 3 joueurs par MCCFR à échantillonnage externe.
pub fn solve_multiway(request: MultiwayRequest) -> Result<MultiwayResponse, String> {
    if !(3..=5).contains(&request.board.len()) {
        return Err(format!(
            "le solveur multiway attend un board de 3 à 5 cartes, reçu {}",
            request.board.len()
        ));
    }
    if !(0..N_PLAYERS).contains(&request.hero_player) {
        return Err(format!(
            "hero_player invalide: {} (attendu 0..={})",
            request.hero_player,
            N_PLAYERS - 1
        ));
    }

    let board = parse_cards(&request.board)?;
    let mut seen = [false; 52];
    for &card in &board {
        if seen[card as usize] {
            return Err(format!(
                "carte dupliquée dans le board: {}",
                crate::card_to_string(card)?
            ));
        }
        seen[card as usize] = true;
    }
    let mut dead_mask = 0u64;
    for &card in &board {
        dead_mask |= 1u64 << card;
    }

    let mut hand_lists: [Vec<[u8; 2]>; N_PLAYERS] = [Vec::new(), Vec::new(), Vec::new()];
    for (index, range_text) in request.ranges.iter().enumerate() {
        hand_lists[index] = build_combo_list(range_text, dead_mask)?;
    }
    let hands_ref: &[Vec<[u8; 2]>; N_PLAYERS] = &hand_lists;

    let effective_stack = request.effective_stack.round() as i64;
    let starting_pot = request.starting_pot.round() as i64;
    if effective_stack <= 0 || starting_pot <= 0 {
        return Err("starting_pot et effective_stack doivent être positifs".to_string());
    }

    let seed = request.random_seed.unwrap_or(0x2026_0826_9593_74D1);
    let mut solver = Solver {
        hands: hands_ref,
        effective_stack,
        starting_pot,
        regrets: std::collections::HashMap::new(),
        strategy_sum: std::collections::HashMap::new(),
        chosen_stats: [[0.0; ACTION_SLOTS]; N_PLAYERS],
        rng_state: seed | 1,
        iterations_done: 0,
    };

    let mut board_array = [0u8; 5];
    for (index, &card) in board.iter().enumerate() {
        board_array[index] = card;
    }
    let root = GameState::new(board_array, board.len(), starting_pot);

    let iterations = request.max_iterations.max(100);
    for _ in 0..iterations {
        // Un tirage de mains sert aux trois traversées : chaque joueur est
        // traversant sur le même deal, ce qui triple le volume d'updates
        // adverses pour un coût de tirage négligeable.
        let Some(dealt) = solver.sample_deal(&board) else {
            continue;
        };
        for traverser in 0..N_PLAYERS {
            solver.traverse(&root, &dealt, traverser);
        }
        solver.iterations_done += 1;
    }

    evaluate_solution(&solver, hands_ref, &request, effective_stack, starting_pot, seed)
}

/// Évalue la stratégie moyenne : fréquences racine, EV héro et gap BR approximé.
fn evaluate_solution(
    solver: &Solver,
    hands: &[Vec<[u8; 2]>; N_PLAYERS],
    request: &MultiwayRequest,
    effective_stack: i64,
    starting_pot: i64,
    seed: u64,
) -> Result<MultiwayResponse, String> {
    let hero = request.hero_player;
    if hands[hero].is_empty() {
        return Err("la range héro est vide après retrait du board".to_string());
    }

    let mut board_array = [0u8; 5];
    for (index, text) in request.board.iter().enumerate() {
        let normalized = format!(
            "{}{}",
            text[..1].to_ascii_uppercase(),
            text[1..].to_ascii_lowercase()
        );
        board_array[index] = card_from_str(&normalized).map_err(|err| err.to_string())?;
    }
    let root = GameState::new(board_array, request.board.len(), starting_pot);
    #[cfg(feature = "multiway-debug")]
    eprintln!(
        "EVALROOT board_bytes={:?} board_len={}",
        &root.board_cards[..root.board_len],
        root.board_len
    );

    // Fréquences racine moyennes du héro, agrégées sur ses combos.
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

    let slot_names = [
        Action::Fold.name(),
        Action::Call.name(),
        Action::RaiseHalf.name(),
        Action::RaisePot.name(),
    ];
    let mut actions: Vec<ActionDetail> = (0..ACTION_SLOTS)
        .filter(|&slot| freq_sum[slot] > 0.0 || slot == 1)
        .map(|slot| ActionDetail {
            name: slot_names[slot].to_string(),
            frequency: freq_sum[slot] as f32,
            ev: 0.0,
        })
        .collect();

    let mut recommended_slot = 1;
    for slot in 0..ACTION_SLOTS {
        if freq_sum[slot] > freq_sum[recommended_slot] {
            recommended_slot = slot;
        }
    }
    let recommended_action = slot_names[recommended_slot].to_string();

    // EV héro + gap BR par simulation Monte-Carlo sous stratégie moyenne.
    let mut mc_rng = XorShift::new(seed ^ 0x5EED_CAFE_F00D_0001);
    let samples = 4_000usize;
    #[cfg(feature = "multiway-debug")]
    let samples_dbg = true;
    let mut ev_sum = 0.0f64;
    let mut br_best_sum = 0.0f64;

    for _ in 0..samples {
        let Some(dealt) = sample_deal_free(hands, &request_board_bytes(request), &mut mc_rng)
        else {
            continue;
        };

        let ev = rollout_average(
            solver, hands, dealt, &root, hero, effective_stack, starting_pot, &mut mc_rng, 24,
        );
        ev_sum += ev;

        // Meilleure réponse : max sur les actions racine légales du héro.
        let mut best = f64::NEG_INFINITY;
        for action in root.legal_actions(effective_stack) {
            let child = apply_static(&root, action, effective_stack);
            let value = rollout_average(
                solver, hands, dealt, &child, hero, effective_stack, starting_pot, &mut mc_rng, 6,
            );
            best = best.max(value);
        }
        if best.is_finite() {
            br_best_sum += best;
        }
    }

    let hero_ev = ev_sum / samples as f64;
    let br_ev = br_best_sum / samples as f64;
    let exploitability = (br_ev - hero_ev).max(0.0) as f32;

    #[cfg(feature = "multiway-debug")]
    {
        let folds = ROLLOUT_FOLD_ENDS.with(|cell| cell.get());
        let steals = ROLLOUT_HERO_STEALS.with(|cell| cell.get());
        eprintln!(
            "ROLLOUTS: fold_ends={} hero_steals={} / samples={}",
            folds, steals, samples
        );
        eprintln!(
            "STRAT lookups={} hits={:.1}%",
            STRAT_LOOKUPS.with(|cell| cell.get()),
            100.0 * STRAT_HITS.with(|cell| cell.get()) as f64
                / STRAT_LOOKUPS.with(|cell| cell.get()).max(1) as f64
        );
        let by = ROLLOUT_FOLDS_BY.with(|cell| cell.get());
        eprintln!("FOLDS_BY p0={} p1={} p2={}", by[0], by[1], by[2]);
        ROLLOUT_FOLDS_BY.with(|cell| cell.set([0; N_PLAYERS]));
        ROLLOUT_FOLD_ENDS.with(|cell| cell.set(0));
        ROLLOUT_HERO_STEALS.with(|cell| cell.set(0));
        STRAT_LOOKUPS.with(|cell| cell.set(0));
        STRAT_HITS.with(|cell| cell.set(0));
        ROLLOUT_FOLDS_BY.with(|cell| cell.set([0; N_PLAYERS]));
        let _ = &solver.chosen_stats;
        #[cfg(feature = "multiway-debug")]
        {
            // stats par joueur imprimées après la boucle MC ci-dessous
        }
    }

    #[cfg(feature = "multiway-debug")]
    eprintln!(
        "EVAL hero={} ev={:.4} br={:.4} gap={:.4}",
        hero, hero_ev, br_ev, exploitability
    );
    #[cfg(feature = "multiway-debug")]
    {
        // Dump de la stratégie moyenne agrégée par joueur au premier noeud
        // de décision (racine), tous combos confondus.
        for p in 0..N_PLAYERS {
            let mut agg = [0.0f64; ACTION_SLOTS];
            let mut n = 0usize;
            for combo_index in 0..hands[p].len() {
                let key = solver.node_key(&root, p, combo_index);
                if let Some(sum) = solver.strategy_sum.get(&key) {
                    let total: f64 = sum.iter().sum();
                    if total > 0.0 {
                        for slot in 0..ACTION_SLOTS {
                            agg[slot] += sum[slot] / total;
                        }
                        n += 1;
                    }
                }
            }
            if n > 0 {
                for slot in agg.iter_mut() {
                    *slot /= n as f64;
                }
                eprintln!(
                    "ROOTSTRAT p{} n={} fold={:.3} call={:.3} half={:.3} pot={:.3}",
                    p, n, agg[0], agg[1], agg[2], agg[3]
                );
            } else {
                eprintln!("ROOTSTRAT p{} : aucune entrée", p);
            }
        }
        let totals: [f64; ACTION_SLOTS] = {
            let mut t = [0.0; ACTION_SLOTS];
            for stats in &solver.chosen_stats {
                for (slot, &count) in stats.iter().enumerate() {
                    t[slot] += count;
                }
            }
            t
        };
        eprintln!(
            "CHOSEN all: fold={:.0} call={:.0} half={:.0} pot={:.0}",
            totals[0], totals[1], totals[2], totals[3]
        );
        for p in 0..N_PLAYERS {
            eprintln!(
                "CHOSEN p{}: fold={:.0} call={:.0} half={:.0} pot={:.0}",
                p,
                solver.chosen_stats[p][0],
                solver.chosen_stats[p][1],
                solver.chosen_stats[p][2],
                solver.chosen_stats[p][3]
            );
        }
    }

    for action in &mut actions {
        if action.name == recommended_action {
            action.ev = hero_ev as f32;
        }
    }

    Ok(MultiwayResponse {
        recommended_action,
        hero_ev: hero_ev as f32,
        exploitability,
        actions,
        iterations: solver.iterations_done as u32,
    })
}

fn request_board_bytes(request: &MultiwayRequest) -> Vec<u8> {
    request
        .board
        .iter()
        .map(|text| {
            let normalized = format!(
                "{}{}",
                text[..1].to_ascii_uppercase(),
                text[1..].to_ascii_lowercase()
            );
            card_from_str(&normalized).unwrap_or(0)
        })
        .collect()
}

/// Simule une main complète où chacun joue selon sa stratégie moyenne (échantillonnée),
/// en résolvant les distributions de cartes au fil des streets.
fn rollout_average(
    solver: &Solver,
    hands: &[Vec<[u8; 2]>; N_PLAYERS],
    dealt: [usize; N_PLAYERS],
    state: &GameState,
    hero: usize,
    effective_stack: i64,
    starting_pot: i64,
    rng: &mut impl Rng,
    step_budget: usize,
) -> f64 {
    let mut state = state.clone();
    let mut guard = 0usize;
    #[cfg(feature = "multiway-debug")]
    let trace: bool = std::env::var("MW_TRACE").is_ok();
    while !state.is_terminal() && guard < step_budget {
        guard += 1;
        if state.betting_closed() {
            // Distribution de la street suivante.
            let Some(card) = sample_next_card(&state, hands, dealt, rng) else {
                break;
            };
            #[cfg(feature = "multiway-debug")]
            if trace {
                eprintln!(
                    "  DEAL street->{} byte={} (board avant={:?})",
                    state.board_len + 1,
                    card,
                    &state.board_cards[..state.board_len]
                );
            }
            state.board_cards[state.board_len] = card;
            state.board_len += 1;
            state.num_raises = 0;
            state.bet_to_match = 0;
            for p in 0..N_PLAYERS {
                state.needs_action[p] = !state.folded[p];
            }
            state.current = (0..N_PLAYERS).find(|&p| !state.folded[p]).unwrap_or(0);
            continue;
        }

        let player = state.current;
        let legal = state.legal_actions(effective_stack);
        let combo_index = dealt[player];
        let key = solver.node_key(&state, player, combo_index);
        let strategy = solver.average_strategy(key, &legal);
        #[cfg(feature = "multiway-debug")]
        if trace {
            eprintln!(
                "  step{} cur={} bet={} board_len={} legal={:?} strat={:?}",
                guard,
                state.current,
                state.bet_to_match,
                state.board_len,
                legal.iter().map(|a| a.name()).collect::<Vec<_>>(),
                legal.iter().map(|a| strategy[a.slot()]).collect::<Vec<_>>(),
            );
        }

        let draw = rng.next_f64();
        let mut cumulative = 0.0;
        let mut chosen = legal[legal.len() - 1];
        for action in &legal {
            cumulative += strategy[action.slot()];
            if draw <= cumulative {
                chosen = *action;
                break;
            }
        }
        state = apply_static(&state, chosen, effective_stack);
    }
    if !state.is_terminal() {
        // Filet de sécurité : égalise les mises et va au showdown.
        for p in 0..N_PLAYERS {
            state.needs_action[p] = false;
            let to_add = state.bet_to_match - state.committed[p];
            state.committed[p] += to_add.max(0);
        }
        while state.board_len < 5 {
            let Some(card) = sample_next_card(&state, hands, dealt, rng) else {
                break;
            };
            state.board_cards[state.board_len] = card;
            state.board_len += 1;
        }
    }
    let pot_total = total_pot(&state);
    #[cfg(feature = "multiway-debug")]
    {
        let mut folders = Vec::new();
        for p in 0..N_PLAYERS {
            if state.folded[p] {
                folders.push(p);
            }
        }
        let payoffs_dbg = static_payoffs(&state, hands, dealt, pot_total);
        let board_text: Vec<String> = state.board_cards[..state.board_len]
            .iter()
            .map(|&c| crate::card_to_string(c).unwrap_or_default())
            .collect();
        eprintln!(
            "  END board_bytes={:?} board={:?} holes={:?} active={} folders={:?} committed={:?} payoffs={:?}",
            &state.board_cards[..state.board_len],
            board_text,
            [hands[0][dealt[0]], hands[1][dealt[1]], hands[2][dealt[2]]],
            state.active_players(),
            folders,
            state.committed,
            payoffs_dbg
        );
    }
    static_payoffs(&state, hands, dealt, pot_total)[hero]
}

#[cfg(feature = "multiway-debug")]
thread_local! {
    static ROLLOUT_FOLD_ENDS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static ROLLOUT_HERO_STEALS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static STRAT_LOOKUPS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static STRAT_HITS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    static ROLLOUT_FOLDS_BY: std::cell::Cell<[u64; N_PLAYERS]> =
        const { std::cell::Cell::new([0; N_PLAYERS]) };
}

fn sample_next_card(
    state: &GameState,
    hands: &[Vec<[u8; 2]>; N_PLAYERS],
    dealt: [usize; N_PLAYERS],
    rng: &mut impl Rng,
) -> Option<u8> {
    let mut used: u64 = 0;
    for &card in &state.board_cards[..state.board_len] {
        used |= 1u64 << card;
    }
    for player in 0..N_PLAYERS {
        for &card in &hands[player][dealt[player]] {
            used |= 1u64 << card;
        }
    }
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
    let draw = (rng.next_f64() * count as f64) as usize;
    Some(candidates[draw.min(count - 1)])
}

fn static_payoffs(
    state: &GameState,
    hands: &[Vec<[u8; 2]>; N_PLAYERS],
    dealt: [usize; N_PLAYERS],
    pot_total: i64,
) -> [f64; N_PLAYERS] {    if state.active_players() == 1 {
        let winner = (0..N_PLAYERS).find(|&p| !state.folded[p]).unwrap();
        let mut payoffs = [0.0; N_PLAYERS];
        payoffs[winner] = pot_total as f64;
        for p in 0..N_PLAYERS {
            payoffs[p] -= state.committed[p] as f64;
        }
        return payoffs;
    }

    let mut board_hand = Hand::new();
    for &card in &state.board_cards[..state.board_len.min(5)] {
        board_hand = board_hand.add_card(card as usize);
    }
    let mut best_rank = 0u16;
    for p in 0..N_PLAYERS {
        if !state.folded[p] {
            let rank = board_hand
                .add_card(hands[p][dealt[p]][0] as usize)
                .add_card(hands[p][dealt[p]][1] as usize)
                .evaluate();
            best_rank = best_rank.max(rank);
        }
    }
    let winners = (0..N_PLAYERS)
        .filter(|&p| {
            !state.folded[p]
                && board_hand
                    .add_card(hands[p][dealt[p]][0] as usize)
                    .add_card(hands[p][dealt[p]][1] as usize)
                    .evaluate()
                    == best_rank
        })
        .count()
        .max(1) as f64;
    let mut payoffs = [0.0; N_PLAYERS];
    for p in 0..N_PLAYERS {
        payoffs[p] -= state.committed[p] as f64;
        if !state.folded[p]
            && board_hand
                .add_card(hands[p][dealt[p]][0] as usize)
                .add_card(hands[p][dealt[p]][1] as usize)
                .evaluate()
                == best_rank
        {
            payoffs[p] += pot_total as f64 / winners;
        }
    }
    payoffs
}


#[cfg(test)]
mod internal_tests {
    use super::*;

    fn card(text: &str) -> u8 {
        crate::card_from_str(text).unwrap()
    }

    #[test]
    fn showdown_payoffs_are_zero_sum_and_correct() {
        let board_cards = [
            card("Ah"),
            card("7d"),
            card("2c"),
            card("Kd"),
            card("9s"),
        ];
        let state = GameState::new(board_cards, 5, 6);
        let hands: [Vec<[u8; 2]>; N_PLAYERS] = [
            vec![[card("As"), card("Ac")]],
            vec![[card("Ks"), card("Kh")]],
            vec![[card("Qs"), card("Qh")]],
        ];
        let dealt = [0, 0, 0];

        let mut bet_state = state.clone();
        bet_state.committed = [2, 2, 2];
        let pot_total = 6 + 6;
        let payoffs = static_payoffs(&bet_state, &hands, dealt, pot_total);
        assert_eq!(payoffs[0], 10.0);
        assert_eq!(payoffs[1], -2.0);
        assert_eq!(payoffs[2], -2.0);
    }

    #[test]
    fn fold_payoffs_award_pot_to_last_player() {
        let board_cards = [
            card("Ah"),
            card("7d"),
            card("2c"),
            card("Kd"),
            card("9s"),
        ];
        let mut state = GameState::new(board_cards, 5, 6);
        state.folded = [false, true, true];
        state.committed = [4, 1, 1];
        let hands: [Vec<[u8; 2]>; N_PLAYERS] = [
            vec![[card("As"), card("Ac")]],
            vec![[card("Ks"), card("Kh")]],
            vec![[card("Qs"), card("Qh")]],
        ];
        let payoffs = static_payoffs(&state, &hands, [0, 0, 0], 6 + 6);
        assert_eq!(payoffs[0], 8.0);
        assert_eq!(payoffs[1], -1.0);
        assert_eq!(payoffs[2], -1.0);
    }

    #[test]
    fn weak_hand_cannot_print_money_against_nuts_ranges() {
        // 92o (quasi aucune équité) face à KK+QQ sur flop J-high : l'EV doit
        // rester modeste et nettement inférieure à celle d'un monstre.
        let board = vec![card("Jh"), card("7d"), card("2c")];
        let mut dead = 0u64;
        for &c in &board {
            dead |= 1u64 << c;
        }
        let mut hands: [Vec<[u8; 2]>; N_PLAYERS] = Default::default();
        hands[0] = build_combo_list("92o", dead).unwrap();
        hands[1] = build_combo_list("KK", dead).unwrap();
        hands[2] = build_combo_list("QQ", dead).unwrap();

        let mut solver = Solver {
            hands: &hands,
            effective_stack: 20,
            starting_pot: 6,
            regrets: std::collections::HashMap::new(),
            strategy_sum: std::collections::HashMap::new(),
            chosen_stats: [[0.0; ACTION_SLOTS]; N_PLAYERS],
            rng_state: 42 | 1,
            iterations_done: 0,
        };
        let mut board_array = [0u8; 5];
        board_array[..3].copy_from_slice(&board);
        let root = GameState::new(board_array, 3, 6);

        for _ in 0..4000 {
            if let Some(dealt) = solver.sample_deal(&board) {
                for t in 0..N_PLAYERS {
                    solver.traverse(&root, &dealt, t);
                    solver.iterations_done += 1;
                }
            }
        }

        // Le villain en face d'un bet doit préférer CALL au FOLD avec KK
        // contre une range connue comme inférieure.
        let hero_bets = apply_static(&root, Action::RaisePot, 20);
        assert_eq!(hero_bets.current, 1);
        let key = solver.node_key(&hero_bets, 1, 0);
        if let Some(sum) = solver.strategy_sum.get(&key) {
            let total: f64 = sum.iter().sum();
            assert!(
                total <= 0.0 || sum[1] / total > sum[0] / total,
                "KK doit préférer call au fold vs range inférieure"
            );
        }
    }

    #[test]
    fn betting_closed_after_all_active_players_call() {
        let mut state = GameState::new([card("Ah"), card("7d"), card("2c"), 0, 0], 3, 6);
        let stack = 20;
        state = apply_static(&state, Action::RaiseHalf, stack);
        assert_eq!(state.current, 1);
        state = apply_static(&state, Action::Call, stack);
        state = apply_static(&state, Action::Call, stack);
        assert!(state.betting_closed());
        assert!(!state.is_terminal());
    }

    #[test]
    fn normalize_deals_exactly_one_street_per_closure() {
        let mut state = GameState::new([card("Ah"), card("7d"), card("2c"), 0, 0], 3, 6);
        let stack = 20;
        state = apply_static(&state, Action::RaiseHalf, stack);
        state = apply_static(&state, Action::Fold, stack);
        state = apply_static(&state, Action::Call, stack);
        assert!(state.betting_closed());

        let hands: [Vec<[u8; 2]>; N_PLAYERS] = [
            vec![[card("As"), card("Ac")]],
            vec![[card("Ks"), card("Kh")]],
            vec![[card("Qs"), card("Qh")]],
        ];
        let mut solver = Solver {
            hands: &hands,
            effective_stack: stack,
            starting_pot: 6,
            regrets: std::collections::HashMap::new(),
            strategy_sum: std::collections::HashMap::new(),
            chosen_stats: [[0.0; ACTION_SLOTS]; N_PLAYERS],
            rng_state: 12345 | 1,
            iterations_done: 0,
        };
        let normalized = solver.normalize(&state, &[0, 0, 0]).expect("deal ok");
        // Une seule street distribuée par fermeture (turn), river plus tard.
        assert_eq!(normalized.board_len, 4);
        assert!(!normalized.betting_closed());
        assert_eq!(normalized.num_raises, 0);
    }
}










