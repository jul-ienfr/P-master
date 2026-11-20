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
    /// Historique d'actions de la rue courante, du plus ancien au plus récent.
    ///
    /// Chaque entrée est soit un token simple (`check`, `call`, `fold`, `bet`,
    /// `raise`, `allin`) soit `player:action:amount` (montant en bb). Le solveur
    /// avance l'arbre résolu jusqu'au nœud correspondant avant de lire la
    /// stratégie : sans cela, un spot « face à une mise » était résolu à la
    /// racine de la rue (check/bet) et répondait à un autre problème.
    #[serde(default)]
    pub action_history: Vec<String>,
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
    /// Échéance murale optionnelle du solve (millisecondes). `None` conserve le
    /// comportement historique : seul `max_iterations` borne le calcul.
    #[serde(default)]
    pub time_budget_ms: Option<u64>,
    /// Compression mémoire de l'arbre (i16 + échelle). Défaut : `true` —
    /// c'est le mode de production ; `false` uniquement pour les diagnostics.
    #[serde(default = "default_compress_tree")]
    pub compress_tree: bool,
    /// Schedule de discount des hyperparamètres CFR (spec `012`).
    ///
    /// Absent ou vide → DCFR historique du crate (comportement inchangé). Un nom
    /// inconnu est une erreur explicite, jamais un repli silencieux sur le défaut.
    #[serde(default)]
    pub discount_schedule: Option<String>,
}

fn default_compress_tree() -> bool {
    true
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
            action_history: Vec::new(),
            rake_rate: 0.0,
            rake_cap: 0.0,
            sample_mixed: false,
            random_seed: None,
            bet_size_spec: None,
            time_budget_ms: None,
            compress_tree: default_compress_tree(),
            discount_schedule: None,
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
    #[serde(default)]
    pub ev_bb: Option<f32>,
    #[serde(default)]
    pub ev_bb_per_100: Option<f32>,
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
    #[serde(default)]
    pub ev_bb: Option<f32>,
    #[serde(default)]
    pub ev_bb_per_100: Option<f32>,
    #[serde(default)]
    pub ev_dollars: Option<f32>,
    #[serde(default)]
    pub dollar_ev_note: Option<String>,
    #[serde(default)]
    pub combo_ev_bb: Option<f32>,
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
    action_history: Vec<String>,
    rake_rate: f32,
    rake_cap: f32,
    sample_mixed: bool,
    random_seed: Option<u64>,
    bet_size_spec: BetSizeSpec,
    time_budget_ms: Option<u64>,
    /// Compression mémoire de l'arbre (i16 + échelle) : ~2× moins de RAM et
    /// parcours plus rapides sur les gros arbres. Défaut : activée.
    compress_tree: bool,
    /// Schedule de discount effectivement appliqué (spec `012`).
    discount_schedule: crate::solver::DiscountSchedule,
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

fn bb_for_request(effective_stack: f32) -> (Option<f32>, Option<String>) {
    if effective_stack.is_finite() && effective_stack > 0.0 {
        let (bb, _) = crate::ev::bb_from_effective_stack(effective_stack);
        if bb > 0.0 {
            // Convention 100bb deep, tracée une fois par requête.
            tracing::warn!(
                effective_stack,
                bb,
                "bb dérivé de effective_stack/100 (fallback 100bb deep)"
            );
            return (
                Some(bb),
                Some("bb=effective_stack/100 (fallback 100bb deep)".to_string()),
            );
        }
    }
    (None, None)
}

type EvFields = (
    Option<f32>,
    Option<f32>,
    Option<f32>,
    Option<String>,
    Option<f32>,
);

fn enrich_ev_fields(
    hero_ev: f32,
    hero_combo_ev: f32,
    actions: &mut [ActionDetail],
    effective_stack: f32,
) -> EvFields {
    let (bb_opt, note) = bb_for_request(effective_stack);
    let bb = bb_opt;
    let summary = crate::ev::ev_summary(hero_ev, bb, None, note.clone());
    for a in actions.iter_mut() {
        let s = crate::ev::ev_summary(a.ev, bb, None, None);
        a.ev_bb = s.ev_bb;
        a.ev_bb_per_100 = s.ev_bb_per_100;
    }
    let combo_ev_bb = bb.and_then(|b| crate::ev::ev_chips_to_bb(hero_combo_ev, b));
    (
        summary.ev_bb,
        summary.ev_bb_per_100,
        summary.ev_dollars,
        summary.dollar_ev_note,
        combo_ev_bb,
    )
}

/// Type d'action attendu dans un token d'historique.
#[derive(Clone, Copy, PartialEq, Eq)]
enum HistoryActionKind {
    Fold,
    Check,
    Call,
    Bet,
    Raise,
    AllIn,
}

/// Parse un token d'historique (`check`, `oop:bet:4.0`, `raise 2.5`, ...).
/// Le montant, quand il est présent, est une contribution totale de rue.
fn parse_history_token(token: &str) -> Option<(HistoryActionKind, Option<f32>)> {
    let lower = token.trim().to_ascii_lowercase();
    if lower.is_empty() {
        return None;
    }
    let fields: Vec<&str> = lower.split(':').collect();
    let (label, amount) = if fields.len() >= 2 {
        (
            fields[1].trim(),
            fields
                .get(2)
                .and_then(|value| value.trim().parse::<f32>().ok()),
        )
    } else {
        (fields[0].trim(), None)
    };
    let label = label.split_whitespace().next().unwrap_or(label);
    let kind = if label.starts_with("fold") {
        HistoryActionKind::Fold
    } else if label.starts_with("check") {
        HistoryActionKind::Check
    } else if label.starts_with("call") {
        HistoryActionKind::Call
    } else if label.contains("all-in")
        || label.contains("allin")
        || label.contains("all_in")
        || label.starts_with("jam")
        || label.starts_with("shove")
    {
        HistoryActionKind::AllIn
    } else if label.starts_with("raise") {
        HistoryActionKind::Raise
    } else if label.starts_with("bet") {
        HistoryActionKind::Bet
    } else {
        return None;
    };
    Some((kind, amount))
}

/// Contribution totale de rue portée par une action agressive, pour la
/// comparer aux jetons d'historique (mise ou « relance à »).
fn history_action_total(action: &Action) -> Option<f32> {
    match action {
        Action::Bet(size) | Action::Raise(size) | Action::AllIn(size) => Some(*size as f32),
        _ => None,
    }
}

/// Choisit l'action de l'arbre la plus proche du token : même classe d'abord,
/// puis all-in en repli (une mise observée peut correspondre à un jam abstrait).
fn best_history_action(
    actions: &[Action],
    kind: HistoryActionKind,
    amount: Option<f32>,
) -> Option<usize> {
    let class_matches = |action: &Action| match kind {
        HistoryActionKind::Fold => matches!(action, Action::Fold),
        HistoryActionKind::Check => matches!(action, Action::Check),
        HistoryActionKind::Call => matches!(action, Action::Call),
        HistoryActionKind::Bet => matches!(action, Action::Bet(_)),
        HistoryActionKind::Raise => matches!(action, Action::Raise(_)),
        HistoryActionKind::AllIn => matches!(action, Action::AllIn(_)),
    };
    let pick = |allow_allin: bool| -> Option<usize> {
        let mut best: Option<(usize, f32)> = None;
        for (index, action) in actions.iter().enumerate() {
            let eligible =
                class_matches(action) || (allow_allin && matches!(action, Action::AllIn(_)));
            if !eligible {
                continue;
            }
            let score = amount
                .map(|value| (history_action_total(action).unwrap_or(0.0) - value).abs())
                .unwrap_or(0.0);
            if best.is_none_or(|(_, best_score)| score < best_score) {
                best = Some((index, score));
            }
        }
        best.map(|(index, _)| index)
    };
    pick(false).or_else(|| pick(true))
}

fn parse_history_card(token: &str) -> Option<Card> {
    let trimmed = token.trim();
    if trimmed.len() != 2 {
        return None;
    }
    let normalized = format!(
        "{}{}",
        trimmed[..1].to_ascii_uppercase(),
        trimmed[1..].to_ascii_lowercase()
    );
    card_from_str(&normalized).ok()
}

/// Avance l'arbre résolu jusqu'au nœud décrit par `history`.
///
/// Le solveur résout toujours l'arbre complet de la rue ; appliquer l'historique
/// ensuite conditionne les ranges et lit la stratégie du bon nœud. En cas
/// d'historique incompatible (taille absente, joueur inattendu, nœud terminal),
/// l'arbre est remis à la racine et la réponse reste celle du nœud racine.
fn apply_action_history(
    game: &mut PostFlopGame,
    history: &[String],
    hero_player: usize,
) -> Result<(), SolveError> {
    game.back_to_root();
    for token in history {
        if game.is_terminal_node() {
            game.back_to_root();
            return Err(SolveError::new("action_history after terminal node"));
        }
        if game.is_chance_node() {
            let Some(card) = parse_history_card(token) else {
                game.back_to_root();
                return Err(SolveError::new(format!(
                    "chance node without a card token: '{token}'"
                )));
            };
            game.play(card as usize);
            continue;
        }
        let Some((kind, amount)) = parse_history_token(token) else {
            game.back_to_root();
            return Err(SolveError::new(format!(
                "unsupported action_history token: '{token}'"
            )));
        };
        let actions = game.available_actions();
        let Some(index) = best_history_action(&actions, kind, amount) else {
            game.back_to_root();
            return Err(SolveError::new(format!(
                "no matching action in tree for token: '{token}'"
            )));
        };
        game.play(index);
    }

    if game.is_terminal_node() || game.is_chance_node() {
        game.back_to_root();
        return Err(SolveError::new(
            "action_history ends at a non-decision node",
        ));
    }
    if game.current_player() != hero_player {
        game.back_to_root();
        return Err(SolveError::new(
            "action_history does not end on the hero's decision",
        ));
    }
    Ok(())
}

/// EV de range du joueur à la racine, lue dans les valeurs stockées par
/// `finalize` (lecture O(#mains)) au lieu d'un parcours complet de l'arbre.
///
/// Équivalence avec `compute_current_ev(game)[player]` : la valeur stockée est
/// le counterfactual value mis à l'échelle (`expected_values_detail`) ; sa
/// moyenne pondérée par les poids normalisés vaut l'EV de range plus `pot/2`
/// (biais retiré par `compute_current_ev`). Vérifié sur le spot de production
/// dans `examples/ev_equiv.rs` et `examples/phase_profile.rs` (écart nul).
fn root_range_ev(game: &PostFlopGame, player: usize) -> f32 {
    let values = game.expected_values(player);
    let weights = game.normalized_weights(player);
    let mut weighted = 0.0f64;
    let mut total = 0.0f64;
    for (&value, &weight) in values.iter().zip(weights) {
        weighted += value as f64 * weight as f64;
        total += weight as f64;
    }
    if total <= 0.0 || !weighted.is_finite() {
        return compute_current_ev(game)[player];
    }
    (weighted / total) as f32 - game.tree_config().starting_pot as f32 * 0.5
}

fn solve_spot_inner(request: SolveRequest) -> SolveResult {
    let normalized = normalize_solve_request(request)?;
    let cache_key = solve_cache_key(&normalized);

    if normalized.use_cache {
        if let Some(mut cached) = SOLVE_CACHE.lock().unwrap().get(&cache_key) {
            cached.cache_hit = true;
            cached.elapsed_ms = 0;
            // Recalcule ev_bb si l'effective_stack/bb diffère du cache (évite bb périmé).
            let (ev_bb, ev_bb_per_100, ev_dollars, dollar_ev_note, combo_ev_bb) = enrich_ev_fields(
                cached.hero_ev,
                cached.hero_combo_ev,
                &mut cached.actions,
                normalized.effective_stack,
            );
            cached.ev_bb = ev_bb;
            cached.ev_bb_per_100 = ev_bb_per_100;
            cached.ev_dollars = ev_dollars;
            cached.dollar_ev_note = dollar_ev_note;
            cached.combo_ev_bb = combo_ev_bb;
            return Ok(cached);
        }
    }

    let start = Instant::now();
    let mut game = build_game(&normalized)?;

    let hero_player = if normalized.hero_is_oop {
        0usize
    } else {
        1usize
    };

    let deadline = normalized
        .time_budget_ms
        .map(|ms| start + std::time::Duration::from_millis(ms));
    // Pas de sortie `print!` sur le chemin de production : chaque décision
    // écrirait des milliers de caractères sur stdout (coût I/O et logs
    // illisibles). Les binaires de debug gardent leur propre boucle.
    // Seules les valeurs du héros sont stockées : c'est le seul joueur lu par
    // la réponse, et la finalisation ne parcourt l'arbre qu'une fois au lieu de
    // deux (~300 ms économisées sur un flop à range complète).
    let exploitability = crate::solve_with_schedule(
        &mut game,
        normalized.max_iterations,
        normalized.target_exploitability,
        false,
        deadline,
        Some(hero_player),
        normalized.discount_schedule,
    );

    // L'arbre est résolu depuis la racine de la rue ; on avance ensuite au
    // nœud réellement joué pour conditionner les ranges et lire la bonne
    // stratégie. Un historique incompatible laisse la réponse au nœud racine.
    if !normalized.action_history.is_empty() {
        if let Err(err) = apply_action_history(&mut game, &normalized.action_history, hero_player) {
            tracing::debug!(%err, "action_history ignoré, réponse au nœud racine");
        }
    }

    game.cache_normalized_weights();

    // EV de range lue dans les valeurs stockées par `finalize` : lecture
    // O(#mains) au lieu d'un parcours complet de l'arbre (~440 ms sur le flop
    // de production à range complète). L'équivalence exacte avec
    // `compute_current_ev` est démontrée à la racine du spot
    // (`examples/ev_equiv.rs`) ; au-delà (historique joué), les ranges sont
    // conditionnées et le calcul complet reste utilisé.
    let hero_ev = if normalized.action_history.is_empty() {
        root_range_ev(&game, hero_player)
    } else {
        compute_current_ev(&game)[hero_player]
    };

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
            ev_bb: None,
            ev_bb_per_100: None,
            ev_dollars: None,
            dollar_ev_note: None,
            combo_ev_bb: None,
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
    let reference_evs = combo_action_evs
        .clone()
        .unwrap_or_else(|| action_evs.clone());
    let mut sample_seed: Option<u64> = None;
    let selection;

    let recommended_index =
        if combo_matched && normalized.sample_mixed && root_player == hero_player {
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
            ev_bb: None,
            ev_bb_per_100: None,
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

    let mut actions = actions;
    let (ev_bb, ev_bb_per_100, ev_dollars, dollar_ev_note, combo_ev_bb) =
        enrich_ev_fields(hero_ev, chosen_ev, &mut actions, normalized.effective_stack);
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
        ev_bb,
        ev_bb_per_100,
        ev_dollars,
        dollar_ev_note,
        combo_ev_bb,
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
    /// Optional comma-separated bet sizes (e.g. `"25%,50%"`) used to build the tree.
    /// `None` keeps the solver default (`33%,50%,75%,100%`).
    #[serde(default)]
    pub bet_sizes: Option<String>,
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
            bet_sizes: None,
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
        bet_size_spec: request.bet_sizes.map(|sizes| BetSizeSpec {
            bet_sizes: sizes,
            ..BetSizeSpec::default()
        }),
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
        mes_ev: if mes_ev.is_finite() {
            mes_ev
        } else {
            response.hero_ev
        },
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
        None => {
            detect_exact_hand(&request.oop_range).or_else(|| detect_exact_hand(&request.ip_range))
        }
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
        action_history: request.action_history,
        rake_rate: request.rake_rate.clamp(0.0, 1.0),
        rake_cap: request.rake_cap.max(0.0),
        sample_mixed: request.sample_mixed,
        random_seed: request.random_seed,
        bet_size_spec: request.bet_size_spec.unwrap_or_default(),
        time_budget_ms: request.time_budget_ms,
        compress_tree: request.compress_tree,
        discount_schedule: parse_discount_schedule(request.discount_schedule.as_deref())?,
    })
}

/// Analyse un nom de schedule de discount (spec `012`).
///
/// `None` ou vide → DCFR historique. Un nom inconnu remonte une erreur : un
/// schedule mal orthographié ne doit pas produire silencieusement le défaut.
fn parse_discount_schedule(value: Option<&str>) -> Result<crate::solver::DiscountSchedule, String> {
    use std::str::FromStr;
    match value {
        None => Ok(crate::solver::DiscountSchedule::default()),
        Some(text) => crate::solver::DiscountSchedule::from_str(text),
    }
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
            Some(std::cmp::Ordering::Less) => false,
            // NaN = action non évaluée (fréquence nulle dans la stratégie
            // courante : `evaluate_hero_ev_after_action` n'est pas appelé).
            // Elle ne doit jamais gagner par défaut contre une action
            // réellement évaluée ; si la meilleure courante est NaN, la
            // candidate finie gagne. Deux NaN se départagent par les
            // tiebreakers (fréquences).
            None => {
                if !current.is_nan() {
                    false
                } else if !candidate.is_nan() {
                    true
                } else {
                    tiebreakers.get(index).copied().unwrap_or(0.0)
                        > tiebreakers.get(best).copied().unwrap_or(0.0)
                }
            }
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

    game.allocate_memory(request.compress_tree);
    Ok(game)
}

fn solve_cache_key(request: &NormalizedSolveRequest) -> String {
    let spec = &request.bet_size_spec;
    format!(
        "oop={}|ip={}|board={}|pot={:.3}|stack={:.3}|hero_oop={}|iters={}|target={:.6}|hand={}|rake={:.4}|cap={:.3}|mixed={}|bets={}|raises={}|donks={},{}|budget={}|history={}|schedule={}",
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
        request
            .time_budget_ms
            .map(|value| value.to_string())
            .unwrap_or_default(),
        request.action_history.join(","),
        request.discount_schedule.as_str(),
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

#[cfg(test)]
mod selection_tests {
    use super::argmax_by_score;

    /// Une action jamais évaluée (fréquence nulle → EV NaN) ne doit pas gagner
    /// l'argmax par défaut : c'est ce qui faisait recommander `check` (freq 0.0)
    /// alors que `bet_3` (freq 1.0) avait un EV fini et supérieur, sur le flop
    /// de production à budget 800 ms.
    #[test]
    fn nan_score_never_wins_against_finite_score() {
        let scores = [f32::NAN, -13.374];
        assert_eq!(argmax_by_score(&scores, &[0.0, 1.0]), 1);
    }

    #[test]
    fn nan_score_wins_when_every_score_is_nan_and_tiebreaker_decides() {
        let scores = [f32::NAN, f32::NAN];
        assert_eq!(argmax_by_score(&scores, &[0.2, 0.8]), 1);
    }

    #[test]
    fn finite_best_score_still_wins() {
        let scores = [-5.0, -1.0, f32::NAN];
        assert_eq!(argmax_by_score(&scores, &[1.0, 0.0, 0.0]), 1);
    }

    /// Le cas mesuré : `check` non évalué (NaN) contre `bet_3` fini, supérieur
    /// en EV (−13,37 > −14,80).
    #[test]
    fn production_flop_prefers_evaluated_action() {
        let scores = [-14.798, -13.374];
        assert_eq!(argmax_by_score(&scores, &[0.0, 1.0]), 1);
    }
}
