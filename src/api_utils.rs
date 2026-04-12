use crate::{card_from_str, card_to_string, hole_to_string, Card, Range};
use std::collections::{HashMap, VecDeque};

pub(crate) const DEFAULT_USE_CACHE: bool = true;

#[derive(Debug, Clone)]
pub(crate) struct NormalizedSolveBoard {
    pub flop: [Card; 3],
    pub turn: Card,
    pub river: Card,
    pub strings: Vec<String>,
}

pub(crate) fn card_mask(cards: &[Card]) -> u64 {
    cards.iter().fold(0u64, |mask, &card| mask | (1u64 << card))
}

pub(crate) fn default_use_cache() -> bool {
    DEFAULT_USE_CACHE
}

pub(crate) fn normalize_range(label: &str, input: &str) -> Result<(Range, String), String> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Err(format!("{label} range is empty"));
    }

    let range = trimmed
        .parse::<Range>()
        .map_err(|err| format!("Invalid {label} range: {err}"))?;

    if range.is_empty() {
        return Err(format!("{label} range is empty"));
    }

    Ok((range, range.to_string()))
}

pub(crate) fn normalize_range_list(
    label: &str,
    inputs: &[String],
) -> Result<(Vec<Range>, Vec<String>), String> {
    if inputs.is_empty() {
        return Err(format!("{label} range list is empty"));
    }

    let mut ranges = Vec::with_capacity(inputs.len());
    let mut normalized = Vec::with_capacity(inputs.len());

    for (index, input) in inputs.iter().enumerate() {
        let (range, text) = normalize_range(&format!("{label} #{index}"), input)?;
        ranges.push(range);
        normalized.push(text);
    }

    Ok((ranges, normalized))
}

pub(crate) fn normalize_exact_hole(
    label: &str,
    input: &[String],
) -> Result<([Card; 2], String), String> {
    let cards = normalize_card_list(label, input, 2, 2, false)?;
    let mut result = [cards[0], cards[1]];
    result.sort_unstable();
    let normalized = hole_to_string((result[0], result[1]))
        .map_err(|err| format!("Invalid {label} hand: {err}"))?;
    Ok((result, normalized))
}

pub(crate) fn normalize_equity_board(board: &[String]) -> Result<(Vec<Card>, Vec<String>), String> {
    let mut cards = normalize_card_list("Board", board, 0, 5, true)?;
    cards.sort_unstable();
    let strings = cards_to_strings(&cards)?;
    Ok((cards, strings))
}

pub(crate) fn normalize_dead_cards(
    dead_cards: &[String],
) -> Result<(Vec<Card>, Vec<String>), String> {
    let mut cards = normalize_card_list("Dead cards", dead_cards, 0, 52, true)?;
    cards.sort_unstable();
    let strings = cards_to_strings(&cards)?;
    Ok((cards, strings))
}

pub(crate) fn normalize_solve_board(board: &[String]) -> Result<NormalizedSolveBoard, String> {
    let cards = normalize_card_list("Board", board, 3, 5, false)?;
    let mut flop = [cards[0], cards[1], cards[2]];
    flop.sort_unstable();
    let turn = cards.get(3).copied().unwrap_or(crate::NOT_DEALT);
    let river = cards.get(4).copied().unwrap_or(crate::NOT_DEALT);

    let mut strings = cards_to_strings(&flop)?;
    if turn != crate::NOT_DEALT {
        strings.push(card_to_string(turn).map_err(|err| format!("Invalid board card: {err}"))?);
    }
    if river != crate::NOT_DEALT {
        strings.push(card_to_string(river).map_err(|err| format!("Invalid board card: {err}"))?);
    }

    Ok(NormalizedSolveBoard {
        flop,
        turn,
        river,
        strings,
    })
}

pub(crate) fn ensure_disjoint_card_sets(groups: &[(&str, &[Card])]) -> Result<(), String> {
    let mut seen: HashMap<Card, &str> = HashMap::new();

    for (label, cards) in groups {
        for &card in *cards {
            if let Some(previous) = seen.insert(card, label) {
                let card_text = card_to_string(card).unwrap_or_else(|_| format!("card#{card}"));
                return Err(format!(
                    "Duplicate card {card_text} is shared by {previous} and {label}"
                ));
            }
        }
    }

    Ok(())
}

pub(crate) fn cards_to_strings(cards: &[Card]) -> Result<Vec<String>, String> {
    cards
        .iter()
        .map(|&card| card_to_string(card).map_err(|err| format!("Invalid card: {err}")))
        .collect()
}

fn normalize_card_list(
    label: &str,
    input: &[String],
    min_len: usize,
    max_len: usize,
    allow_empty: bool,
) -> Result<Vec<Card>, String> {
    if input.is_empty() && allow_empty {
        return Ok(Vec::new());
    }

    if input.len() < min_len || input.len() > max_len {
        return Err(format!(
            "{label} must contain between {min_len} and {max_len} cards"
        ));
    }

    let mut seen = 0u64;
    let mut cards = Vec::with_capacity(input.len());

    for raw_card in input {
        let normalized = normalize_card_text(raw_card)?;
        let card = card_from_str(&normalized)
            .map_err(|err| format!("Invalid {label} card '{raw_card}': {err}"))?;
        let card_bit = 1u64 << card;
        if seen & card_bit != 0 {
            return Err(format!("Duplicate {label} card: {normalized}"));
        }
        seen |= card_bit;
        cards.push(card);
    }

    Ok(cards)
}

fn normalize_card_text(input: &str) -> Result<String, String> {
    let trimmed = input.trim();
    if trimmed.len() < 2 {
        return Err(format!("Card must have at least 2 characters: '{input}'"));
    }

    let upper = trimmed.to_uppercase();
    if upper.len() == 3 && upper.starts_with("10") {
        let suit = upper
            .chars()
            .nth(2)
            .ok_or_else(|| format!("Invalid card: '{input}'"))?
            .to_ascii_lowercase();
        return Ok(format!("T{suit}"));
    }

    if upper.len() != 2 {
        return Err(format!("Card must have exactly 2 characters: '{input}'"));
    }

    let mut chars = upper.chars();
    let rank = chars
        .next()
        .ok_or_else(|| format!("Invalid card: '{input}'"))?;
    let suit = chars
        .next()
        .ok_or_else(|| format!("Invalid card: '{input}'"))?
        .to_ascii_lowercase();
    Ok(format!("{rank}{suit}"))
}

#[derive(Debug)]
pub(crate) struct SimpleLruCache<V> {
    capacity: usize,
    map: HashMap<String, V>,
    order: VecDeque<String>,
}

impl<V> SimpleLruCache<V> {
    pub(crate) fn new(capacity: usize) -> Self {
        Self {
            capacity,
            map: HashMap::new(),
            order: VecDeque::new(),
        }
    }
}

impl<V: Clone> SimpleLruCache<V> {
    pub(crate) fn get(&mut self, key: &str) -> Option<V> {
        if !self.map.contains_key(key) {
            return None;
        }

        self.promote(key);
        self.map.get(key).cloned()
    }

    pub(crate) fn insert(&mut self, key: String, value: V) {
        self.map.insert(key.clone(), value);
        self.promote(&key);

        while self.map.len() > self.capacity {
            if let Some(oldest) = self.order.pop_front() {
                if self.map.remove(&oldest).is_some() {
                    break;
                }
            } else {
                break;
            }
        }
    }

    fn promote(&mut self, key: &str) {
        self.order.retain(|entry| entry != key);
        self.order.push_back(key.to_string());
    }
}
