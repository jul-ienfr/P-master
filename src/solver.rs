use crate::interface::*;
use crate::mutex_like::*;
use crate::sliceop::*;
use crate::utility::*;
use std::io::{self, Write};
use std::mem::MaybeUninit;
use std::time::Instant;

#[cfg(feature = "custom-alloc")]
use crate::alloc::*;

/// Schedule de discount des hyperparamètres CFR.
///
/// Le défaut ([`DiscountSchedule::Dcfr`]) reproduit **exactement** le comportement
/// historique du crate : ses paramètres viennent de [`DiscountParams::new`], qui
/// n'a pas été modifiée. Les variantes `HsDcfr*` appliquent les schedules
/// d'hyperparamètres publiés par Zhang, McAleer et Sandholm (AAAI 2026,
/// arXiv 2404.09097) : au lieu de discounts constants, `α`, `β` et `γ` varient
/// linéairement avec l'itération.
///
/// Le choix est explicite et jamais silencieux : [`DiscountSchedule::from_str`]
/// rejette un nom inconnu au lieu de retomber sur le défaut.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum DiscountSchedule {
    /// DCFR tel qu'implémenté historiquement par le crate (défaut).
    #[default]
    Dcfr,
    /// HS-DCFR(30) : `γ` initial 30 — variante recommandée pour les grands jeux
    /// de poker par les auteurs (HS-PCFR+ est moins bon que DCFR sur ces jeux).
    HsDcfr30,
    /// HS-DCFR(15) : `γ` initial 15, transition plus rapide.
    HsDcfr15,
}

impl DiscountSchedule {
    /// Nom canonique, utilisé pour la traçabilité (métadonnées de réponse).
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Dcfr => "dcfr",
            Self::HsDcfr30 => "hs_dcfr_30",
            Self::HsDcfr15 => "hs_dcfr_15",
        }
    }
}

impl std::str::FromStr for DiscountSchedule {
    type Err = String;

    /// Analyse un nom de schedule (casse et espaces ignorés).
    ///
    /// Un nom inconnu est une **erreur**, jamais un repli sur le défaut : un
    /// schedule mal orthographié qui produirait silencieusement le comportement
    /// historique serait indiscernable d'une mesure du défaut.
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "" | "dcfr" | "default" => Ok(Self::Dcfr),
            "hs_dcfr_30" | "hs-dcfr-30" | "hsdcfr30" | "hs_pcf_30" | "hs-dcfr(30)" => {
                Ok(Self::HsDcfr30)
            }
            "hs_dcfr_15" | "hs-dcfr-15" | "hsdcfr15" | "hs_pcf_15" | "hs-dcfr(15)" => {
                Ok(Self::HsDcfr15)
            }
            other => Err(format!(
                "schedule de discount inconnu: {other:?} (attendu: dcfr, hs_dcfr_30, hs_dcfr_15)"
            )),
        }
    }
}

impl std::fmt::Display for DiscountSchedule {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

struct DiscountParams {
    alpha_t: f32,
    beta_t: f32,
    gamma_t: f32,
}

impl DiscountParams {
    /// Paramètres du DCFR historique du crate.
    ///
    /// **Ne pas modifier** : c'est le comportement de production. Les schedules
    /// expérimentaux passent par [`DiscountParams::for_schedule`].
    pub fn new(current_iteration: u32) -> Self {
        // 0, 1, 4, 16, 64, 256, ...
        let nearest_lower_power_of_4 = match current_iteration {
            0 => 0,
            x => 1 << ((x.leading_zeros() ^ 31) & !1),
        };

        let t_alpha = (current_iteration as i32 - 1).max(0) as f64;
        let t_gamma = (current_iteration - nearest_lower_power_of_4) as f64;

        let pow_alpha = t_alpha * t_alpha.sqrt();
        let pow_gamma = (t_gamma / (t_gamma + 1.0)).powi(3);

        Self {
            alpha_t: (pow_alpha / (pow_alpha + 1.0)) as f32,
            beta_t: 0.5,
            gamma_t: pow_gamma as f32,
        }
    }

    /// Paramètres pour un schedule donné, à l'itération `t` sur un total `n`.
    ///
    /// Les formules publiées donnent des **exposants** (`α = 1 + 3t/n`,
    /// `β = −1 − 2t/n`, `γ = 30 − 5t/n`) ; les champs de cette structure sont les
    /// **facteurs de rétention** appliqués aux valeurs cumulées, exactement comme
    /// pour le DCFR du crate (`t^α/(t^α+1)`, `t^β/(t^β+1)`, `(t/(t+1))^γ`).
    /// La conversion est donc obligatoire : écrire `γ = 30` dans `gamma_t`
    /// ferait *croître* la stratégie cumulée au lieu de la réduire.
    pub fn for_schedule(schedule: DiscountSchedule, t: u32, total_iterations: u32) -> Self {
        match schedule {
            DiscountSchedule::Dcfr => Self::new(t),
            DiscountSchedule::HsDcfr30 => Self::hs_dcfr(t, total_iterations, 30.0),
            DiscountSchedule::HsDcfr15 => Self::hs_dcfr(t, total_iterations, 15.0),
        }
    }

    fn hs_dcfr(t: u32, total_iterations: u32, gamma_initial: f64) -> Self {
        let t = t as f64;
        let n = (total_iterations.max(1)) as f64;

        // `t = 0` : aucune valeur cumulée à réduire (les regrets et la stratégie
        // cumulée sont nuls). La formule publiée donne `β = −1`, et `t^β` n'y est
        // pas défini ; on pose les limites (α→0, β→1, γ→0) plutôt qu'un `NaN`,
        // qui se propagerait à toutes les itérations suivantes.
        if t < 1.0 {
            return Self {
                alpha_t: 0.0,
                beta_t: 1.0,
                gamma_t: 0.0,
            };
        }

        let alpha = 1.0 + 3.0 * t / n;
        let beta = -1.0 - 2.0 * t / n;
        let gamma = gamma_initial - 5.0 * t / n;

        let pow_alpha = t.powf(alpha);
        let pow_beta = t.powf(beta);
        let pow_gamma = (t / (t + 1.0)).powf(gamma);

        Self {
            alpha_t: (pow_alpha / (pow_alpha + 1.0)) as f32,
            beta_t: (pow_beta / (pow_beta + 1.0)) as f32,
            gamma_t: pow_gamma as f32,
        }
    }
}

/// Performs Discounted CFR algorithm until the given number of iterations or exploitability is
/// satisfied.
///
/// This method returns the exploitability of the obtained strategy.
pub fn solve<T: Game>(
    game: &mut T,
    max_num_iterations: u32,
    target_exploitability: f32,
    print_progress: bool,
) -> f32 {
    solve_with_deadline(
        game,
        max_num_iterations,
        target_exploitability,
        print_progress,
        None,
    )
}

/// Variante de [`solve`] avec une échéance murale optionnelle.
///
/// Le budget est vérifié **entre deux itérations** : une itération déjà
/// commencée n'est pas interrompue (le DCFR n'est pas réentrant). C'est le
/// compromis nécessaire pour qu'un `time_budget_ms` côté API corresponde à une
/// latence réelle au lieu d'un simple plafond d'itérations.
pub fn solve_with_deadline<T: Game>(
    game: &mut T,
    max_num_iterations: u32,
    target_exploitability: f32,
    print_progress: bool,
    deadline: Option<Instant>,
) -> f32 {
    solve_with_deadline_storing(
        game,
        max_num_iterations,
        target_exploitability,
        print_progress,
        deadline,
        None,
    )
}

/// Variante de [`solve_with_deadline`] qui ne stocke les valeurs finales que
/// pour `stored_player` (ou les deux joueurs si `None`).
///
/// La finalisation parcourt l'arbre une fois par joueur stocké ; sur un flop à
/// range complète (~600 ms pour deux joueurs) c'est le poste dominant du
/// budget. Le chemin de production ne lit que les valeurs du héros : stocker
/// un seul joueur divise le coût par deux. Les valeurs de l'autre joueur
/// restent périmées, donc le jeu ne doit pas survivre à l'appel.
pub fn solve_with_deadline_storing<T: Game>(
    game: &mut T,
    max_num_iterations: u32,
    target_exploitability: f32,
    print_progress: bool,
    deadline: Option<Instant>,
    stored_player: Option<usize>,
) -> f32 {
    solve_with_schedule(
        game,
        max_num_iterations,
        target_exploitability,
        print_progress,
        deadline,
        stored_player,
        DiscountSchedule::default(),
    )
}

/// Variante de [`solve_with_deadline_storing`] avec un schedule de discount
/// explicite.
///
/// Le schedule par défaut ([`DiscountSchedule::Dcfr`]) reproduit exactement le
/// comportement de [`solve_with_deadline_storing`] : les appelants existants
/// n'ont pas à changer. `n` (le total d'itérations des schedules HS) est
/// `max_num_iterations` — en mode budget c'est un plafond, pas le compte réel,
/// ce qui est documenté dans la spec `012`.
pub fn solve_with_schedule<T: Game>(
    game: &mut T,
    max_num_iterations: u32,
    target_exploitability: f32,
    print_progress: bool,
    deadline: Option<Instant>,
    stored_player: Option<usize>,
    schedule: DiscountSchedule,
) -> f32 {
    if game.is_solved() {
        panic!("Game is already solved");
    }

    if !game.is_ready() {
        panic!("Game is not ready");
    }

    let mut root = game.root();
    let expl_start = Instant::now();
    let mut exploitability = compute_exploitability(game);
    let initial_expl = expl_start.elapsed();

    // `finalize` reparcourt l'arbre pour stocker les EV après l'échéance : sans
    // réserve, il s'ajoute au budget mural (mesuré : 85–110 ms sur un flop froid).
    // Le premier calcul d'exploitabilité fait un parcours comparable, sa durée
    // est donc une bonne estimation, disponible dès le premier appel.
    let deadline = deadline.map(|d| d.checked_sub(initial_expl).unwrap_or(d));

    if print_progress {
        print!("iteration: 0 / {max_num_iterations} ");
        print!("(exploitability = {exploitability:.4e})");
        io::stdout().flush().unwrap();
    }

    // Durée de la dernière itération complète (itérations + calcul
    // d'exploitabilité périodique). Elle sert à ne pas démarrer une itération
    // qui dépasserait l'échéance : sans cela, `time_budget_ms` pouvait être
    // dépassé de 100 à 200 ms sur un flop.
    let mut last_iteration = std::time::Duration::ZERO;

    for t in 0..max_num_iterations {
        if exploitability <= target_exploitability {
            break;
        }

        if let Some(deadline) = deadline {
            let now = Instant::now();
            if now >= deadline {
                break;
            }
            // Première itération : aucune durée passée n'est connue, et sur un
            // arbre à range complète une itération peut coûter plus que le
            // budget restant. La réserve de l'exploitabilité initiale
            // (effectuée ci-dessus) a la même forme que la boucle DCFR, sa
            // durée en est donc un majorant raisonnable : on ne démarre la
            // première itération que si elle a une chance de finir.
            let expected = if last_iteration.is_zero() {
                initial_expl
            } else {
                last_iteration
            };
            if now + expected >= deadline {
                break;
            }
        }

        let iteration_start = Instant::now();
        let params = DiscountParams::for_schedule(schedule, t, max_num_iterations);

        // alternating updates
        for player in 0..2 {
            let mut result = Vec::with_capacity(game.num_private_hands(player));
            solve_recursive(
                result.spare_capacity_mut(),
                game,
                &mut root,
                player,
                game.initial_weights(player ^ 1),
                &params,
            );
        }

        if (t + 1) % 10 == 0 || t + 1 == max_num_iterations {
            exploitability = compute_exploitability(game);
        }

        if (t + 1) % 100 == 0 || t + 1 == max_num_iterations {
            tracing::debug!(iter = t + 1, exploitability, "CFR progress");
        }

        if print_progress {
            print!("\riteration: {} / {} ", t + 1, max_num_iterations);
            print!("(exploitability = {exploitability:.4e})");
            io::stdout().flush().unwrap();
        }

        last_iteration = iteration_start.elapsed();
    }

    if print_progress {
        println!();
        io::stdout().flush().unwrap();
    }

    match stored_player {
        Some(player) => finalize_players(game, &[player]),
        None => finalize(game),
    }

    exploitability
}

/// Proceeds Discounted CFR algorithm for one iteration.
#[inline]
pub fn solve_step<T: Game>(game: &T, current_iteration: u32) {
    solve_step_with_schedule(
        game,
        current_iteration,
        DiscountSchedule::default(),
        current_iteration.saturating_add(1),
    );
}

/// Variante de [`solve_step`] avec un schedule de discount explicite.
///
/// `total_iterations` alimente les schedules HS (`n` dans les formules
/// publiées) ; les appelants qui itèrent par paliers le connaissent. Le défaut
/// conserve le comportement historique.
#[inline]
pub fn solve_step_with_schedule<T: Game>(
    game: &T,
    current_iteration: u32,
    schedule: DiscountSchedule,
    total_iterations: u32,
) {
    if game.is_solved() {
        panic!("Game is already solved");
    }

    if !game.is_ready() {
        panic!("Game is not ready");
    }

    let mut root = game.root();
    let params = DiscountParams::for_schedule(schedule, current_iteration, total_iterations);

    // alternating updates
    for player in 0..2 {
        let mut result = Vec::with_capacity(game.num_private_hands(player));
        solve_recursive(
            result.spare_capacity_mut(),
            game,
            &mut root,
            player,
            game.initial_weights(player ^ 1),
            &params,
        );
    }
}

/// Recursively solves the counterfactual values.
fn solve_recursive<T: Game>(
    result: &mut [MaybeUninit<f32>],
    game: &T,
    node: &mut T::Node,
    player: usize,
    cfreach: &[f32],
    params: &DiscountParams,
) {
    // PRUNING OPTIMIZATION (CFR+ / CFR Pruning)
    // Si la probabilité d'atteindre cette branche est nulle pour toutes les mains possibles,
    // on coupe immédiatement l'exploration de ce sous-arbre.
    // L'itération s'arrête au premier élément valide, donc le surcoût CPU est minime.
    if cfreach.iter().all(|&p| p < 1e-6) {
        for r in result.iter_mut() {
            r.write(0.0);
        }
        return;
    }

    // return the counterfactual values when the `node` is terminal
    if node.is_terminal() {
        game.evaluate(result, node, player, cfreach);
        return;
    }

    let num_actions = node.num_actions();
    let num_hands = result.len();

    // simply recurse when the number of actions is one
    if num_actions == 1 && !node.is_chance() {
        let child = &mut node.play(0);
        solve_recursive(result, game, child, player, cfreach, params);
        return;
    }

    // allocate memory for storing the counterfactual values
    #[cfg(feature = "custom-alloc")]
    let cfv_actions = MutexLike::new(Vec::with_capacity_in(num_actions * num_hands, StackAlloc));
    #[cfg(not(feature = "custom-alloc"))]
    let cfv_actions = MutexLike::new(Vec::with_capacity(num_actions * num_hands));

    // if the `node` is chance
    if node.is_chance() {
        // update the reach probabilities
        #[cfg(feature = "custom-alloc")]
        let mut cfreach_updated = Vec::with_capacity_in(cfreach.len(), StackAlloc);
        #[cfg(not(feature = "custom-alloc"))]
        let mut cfreach_updated = Vec::with_capacity(cfreach.len());
        mul_slice_scalar_uninit(
            cfreach_updated.spare_capacity_mut(),
            cfreach,
            1.0 / game.chance_factor(node) as f32,
        );
        unsafe { cfreach_updated.set_len(cfreach.len()) };

        // compute the counterfactual values of each action
        for_each_child(node, |action| {
            solve_recursive(
                row_mut(cfv_actions.lock().spare_capacity_mut(), action, num_hands),
                game,
                &mut node.play(action),
                player,
                &cfreach_updated,
                params,
            );
        });

        // use 64-bit floating point values
        #[cfg(feature = "custom-alloc")]
        let mut result_f64 = Vec::with_capacity_in(num_hands, StackAlloc);
        #[cfg(not(feature = "custom-alloc"))]
        let mut result_f64 = Vec::with_capacity(num_hands);

        // sum up the counterfactual values
        let mut cfv_actions = cfv_actions.lock();
        unsafe { cfv_actions.set_len(num_actions * num_hands) };
        sum_slices_f64_uninit(result_f64.spare_capacity_mut(), &cfv_actions);
        unsafe { result_f64.set_len(num_hands) };

        // get information about isomorphic chances
        let isomorphic_chances = game.isomorphic_chances(node);

        // process isomorphic chances
        for (i, &isomorphic_index) in isomorphic_chances.iter().enumerate() {
            let swap_list = &game.isomorphic_swap(node, i)[player];
            let tmp = row_mut(&mut cfv_actions, isomorphic_index as usize, num_hands);

            apply_swap(tmp, swap_list);

            result_f64.iter_mut().zip(&*tmp).for_each(|(r, &v)| {
                *r += v as f64;
            });

            apply_swap(tmp, swap_list);
        }

        result.iter_mut().zip(&result_f64).for_each(|(r, &v)| {
            r.write(v as f32);
        });
    }
    // if the current player is `player`
    else if node.player() == player {
        // compute the counterfactual values of each action
        for_each_child(node, |action| {
            solve_recursive(
                row_mut(cfv_actions.lock().spare_capacity_mut(), action, num_hands),
                game,
                &mut node.play(action),
                player,
                cfreach,
                params,
            );
        });

        // compute the strategy by regret-maching algorithm
        let mut strategy = if game.is_compression_enabled() {
            regret_matching_compressed(node.regrets_compressed(), num_actions)
        } else {
            regret_matching(node.regrets(), num_actions)
        };

        // node-locking
        let locking = game.locking_strategy(node);
        apply_locking_strategy(&mut strategy, locking);

        // sum up the counterfactual values
        let mut cfv_actions = cfv_actions.lock();
        unsafe { cfv_actions.set_len(num_actions * num_hands) };
        let result = fma_slices_uninit(result, &strategy, &cfv_actions);

        if game.is_compression_enabled() {
            // update the cumulative strategy
            let scale = node.strategy_scale();
            let decoder = params.gamma_t * scale / u16::MAX as f32;
            let cum_strategy = node.strategy_compressed_mut();

            strategy.iter_mut().zip(&*cum_strategy).for_each(|(x, y)| {
                *x += (*y as f32) * decoder;
            });

            if !locking.is_empty() {
                strategy.iter_mut().zip(locking).for_each(|(d, s)| {
                    if s.is_sign_positive() {
                        *d = 0.0;
                    }
                })
            }

            let new_scale = encode_unsigned_slice(cum_strategy, &strategy);
            node.set_strategy_scale(new_scale);

            // update the cumulative regret
            let scale = node.regret_scale();
            let alpha_decoder = params.alpha_t * scale / i16::MAX as f32;
            let beta_decoder = params.beta_t * scale / i16::MAX as f32;
            let cum_regret = node.regrets_compressed_mut();

            cfv_actions.iter_mut().zip(&*cum_regret).for_each(|(x, y)| {
                *x += *y as f32 * if *y >= 0 { alpha_decoder } else { beta_decoder };
            });

            cfv_actions.chunks_exact_mut(num_hands).for_each(|row| {
                sub_slice(row, result);
            });

            if !locking.is_empty() {
                cfv_actions.iter_mut().zip(locking).for_each(|(d, s)| {
                    if s.is_sign_positive() {
                        *d = 0.0;
                    }
                })
            }

            let new_scale = encode_signed_slice(cum_regret, &cfv_actions);
            node.set_regret_scale(new_scale);
        } else {
            // update the cumulative strategy
            let gamma = params.gamma_t;
            let cum_strategy = node.strategy_mut();
            cum_strategy.iter_mut().zip(&strategy).for_each(|(x, y)| {
                *x = *x * gamma + *y;
            });

            // update the cumulative regret
            let (alpha, beta) = (params.alpha_t, params.beta_t);
            let cum_regret = node.regrets_mut();
            cum_regret.iter_mut().zip(&*cfv_actions).for_each(|(x, y)| {
                let coef = if x.is_sign_positive() { alpha } else { beta };
                *x = *x * coef + *y;
            });
            cum_regret.chunks_exact_mut(num_hands).for_each(|row| {
                sub_slice(row, result);
            });
        }
    }
    // if the current player is not `player`
    else {
        // compute the strategy by regret-matching algorithm
        let mut cfreach_actions = if game.is_compression_enabled() {
            regret_matching_compressed(node.regrets_compressed(), num_actions)
        } else {
            regret_matching(node.regrets(), num_actions)
        };

        // node-locking
        let locking = game.locking_strategy(node);
        apply_locking_strategy(&mut cfreach_actions, locking);

        // update the reach probabilities
        let row_size = cfreach.len();
        cfreach_actions.chunks_exact_mut(row_size).for_each(|row| {
            mul_slice(row, cfreach);
        });

        // compute the counterfactual values of each action
        for_each_child(node, |action| {
            solve_recursive(
                row_mut(cfv_actions.lock().spare_capacity_mut(), action, num_hands),
                game,
                &mut node.play(action),
                player,
                row(&cfreach_actions, action, row_size),
                params,
            );
        });

        // sum up the counterfactual values
        let mut cfv_actions = cfv_actions.lock();
        unsafe { cfv_actions.set_len(num_actions * num_hands) };
        sum_slices_uninit(result, &cfv_actions);
    }
}

/// Computes the strategy by regret-matching algorithm.
#[cfg(feature = "custom-alloc")]
#[inline]
fn regret_matching(regret: &[f32], num_actions: usize) -> Vec<f32, StackAlloc> {
    let mut strategy = Vec::with_capacity_in(regret.len(), StackAlloc);
    let uninit = strategy.spare_capacity_mut();
    uninit.iter_mut().zip(regret).for_each(|(s, r)| {
        s.write(max(*r, 0.0));
    });
    unsafe { strategy.set_len(regret.len()) };

    let row_size = regret.len() / num_actions;
    let mut denom = Vec::with_capacity_in(row_size, StackAlloc);
    sum_slices_uninit(denom.spare_capacity_mut(), &strategy);
    unsafe { denom.set_len(row_size) };

    let default = 1.0 / num_actions as f32;
    strategy.chunks_exact_mut(row_size).for_each(|row| {
        div_slice(row, &denom, default);
    });

    strategy
}

/// Computes the strategy by regret-matching algorithm.
#[cfg(not(feature = "custom-alloc"))]
#[inline]
fn regret_matching(regret: &[f32], num_actions: usize) -> Vec<f32> {
    let mut strategy = Vec::with_capacity(regret.len());
    let uninit = strategy.spare_capacity_mut();
    uninit.iter_mut().zip(regret).for_each(|(s, r)| {
        s.write(max(*r, 0.0));
    });
    unsafe { strategy.set_len(regret.len()) };

    let row_size = regret.len() / num_actions;
    let mut denom = Vec::with_capacity(row_size);
    sum_slices_uninit(denom.spare_capacity_mut(), &strategy);
    unsafe { denom.set_len(row_size) };

    let default = 1.0 / num_actions as f32;
    strategy.chunks_exact_mut(row_size).for_each(|row| {
        div_slice(row, &denom, default);
    });

    strategy
}

/// Computes the strategy by regret-matching algorithm.
#[cfg(feature = "custom-alloc")]
#[inline]
fn regret_matching_compressed(regret: &[i16], num_actions: usize) -> Vec<f32, StackAlloc> {
    let mut strategy = Vec::with_capacity_in(regret.len(), StackAlloc);
    strategy.extend(regret.iter().map(|&r| r.max(0) as f32));

    let row_size = strategy.len() / num_actions;
    let mut denom = Vec::with_capacity_in(row_size, StackAlloc);
    sum_slices_uninit(denom.spare_capacity_mut(), &strategy);
    unsafe { denom.set_len(row_size) };

    let default = 1.0 / num_actions as f32;
    strategy.chunks_exact_mut(row_size).for_each(|row| {
        div_slice(row, &denom, default);
    });

    strategy
}

/// Computes the strategy by regret-matching algorithm.
#[cfg(not(feature = "custom-alloc"))]
#[inline]
fn regret_matching_compressed(regret: &[i16], num_actions: usize) -> Vec<f32> {
    let mut strategy = Vec::with_capacity(regret.len());
    strategy.extend(regret.iter().map(|&r| r.max(0) as f32));

    let row_size = strategy.len() / num_actions;
    let mut denom = Vec::with_capacity(row_size);
    sum_slices_uninit(denom.spare_capacity_mut(), &strategy);
    unsafe { denom.set_len(row_size) };

    let default = 1.0 / num_actions as f32;
    strategy.chunks_exact_mut(row_size).for_each(|row| {
        div_slice(row, &denom, default);
    });

    strategy
}

#[cfg(test)]
mod schedule_tests {
    use super::*;
    use std::str::FromStr;

    /// T001 — le défaut ne bouge pas : les valeurs d'avant la spec `012`.
    ///
    /// Ces nombres sont ceux de `DiscountParams::new` avant l'ajout des
    /// schedules (formule historique : `t^1,5/(t^1,5+1)`, `β = 0,5`,
    /// `(t_γ/(t_γ+1))³` avec `t_γ` remis à zéro à chaque puissance de 4).
    /// Toute dérive du chemin de production casse ce test.
    #[test]
    fn default_discount_params_are_frozen() {
        let cases: [(u32, f32, f32, f32); 5] = [
            (0, 0.0, 0.5, 0.0),
            (1, 0.0, 0.5, 0.0),
            (2, 0.5, 0.5, 0.125),
            (10, 0.964_285_73, 0.5, 0.629_737_6),
            (100, 0.998_985_8, 0.5, 0.921_090_54),
        ];
        for (t, alpha, beta, gamma) in cases {
            let params = DiscountParams::new(t);
            assert_eq!(params.alpha_t, alpha, "alpha_t à t = {t}");
            assert_eq!(params.beta_t, beta, "beta_t à t = {t}");
            assert_eq!(params.gamma_t, gamma, "gamma_t à t = {t}");
        }
    }

    /// T001 (suite) — `Dcfr` délègue à `new`, sans duplication de formule.
    #[test]
    fn dcfr_schedule_delegates_to_historical_new() {
        for t in [0u32, 1, 2, 10, 100, 1000] {
            let via_new = DiscountParams::new(t);
            let via_schedule = DiscountParams::for_schedule(DiscountSchedule::Dcfr, t, 1000);
            assert_eq!(via_new.alpha_t, via_schedule.alpha_t, "alpha_t à t = {t}");
            assert_eq!(via_new.beta_t, via_schedule.beta_t, "beta_t à t = {t}");
            assert_eq!(via_new.gamma_t, via_schedule.gamma_t, "gamma_t à t = {t}");
        }
    }

    /// T002 — sélection : casse et espaces tolérés, inconnu rejeté.
    #[test]
    fn schedule_parsing_accepts_known_names_and_rejects_unknown() {
        for text in ["dcfr", "DCFR", "  Dcfr  ", "default", ""] {
            assert_eq!(
                DiscountSchedule::from_str(text).unwrap(),
                DiscountSchedule::Dcfr,
                "« {text} » doit sélectionner DCFR"
            );
        }
        for text in ["hs_dcfr_30", "HS_DCFR_30", " hs-dcfr-30 ", "HsDcfr30"] {
            assert_eq!(
                DiscountSchedule::from_str(text).unwrap(),
                DiscountSchedule::HsDcfr30,
                "« {text} » doit sélectionner HS-DCFR(30)"
            );
        }
        for text in ["hs_dcfr_15", "HS-DCFR-15", "hsdcfr15"] {
            assert_eq!(
                DiscountSchedule::from_str(text).unwrap(),
                DiscountSchedule::HsDcfr15,
                "« {text} » doit sélectionner HS-DCFR(15)"
            );
        }

        // Un nom inconnu est une erreur explicite, jamais un repli sur le défaut :
        // un schedule mal orthographié indiscernable du défaut serait un mensonge
        // de mesure (FR-004).
        for text in ["hs_dcfr_20", "dcfr_30", "hspcfr", "30", "true"] {
            let err =
                DiscountSchedule::from_str(text).expect_err("un schedule inconnu doit être refusé");
            assert!(
                err.contains("inconnu"),
                "l'erreur doit nommer le problème, reçu : {err}"
            );
            assert!(
                err.contains("hs_dcfr_30"),
                "l'erreur doit lister les valeurs attendues, reçu : {err}"
            );
        }
    }

    /// T002 (suite) — le nom canonique est stable et se relit.
    #[test]
    fn canonical_names_round_trip() {
        for schedule in [
            DiscountSchedule::Dcfr,
            DiscountSchedule::HsDcfr30,
            DiscountSchedule::HsDcfr15,
        ] {
            let name = schedule.as_str();
            assert_eq!(DiscountSchedule::from_str(name).unwrap(), schedule);
            assert_eq!(schedule.to_string(), name);
        }
        assert_eq!(DiscountSchedule::default(), DiscountSchedule::Dcfr);
    }

    /// T003 — les formules publiées, aux points de contrôle numériques.
    ///
    /// `for_schedule` convertit les **exposants** publiés (`α = 1 + 3t/n`,
    /// `β = −1 − 2t/n`, `γ = 30 − 5t/n`) en **facteurs de rétention**
    /// (`t^α/(t^α+1)`, `t^β/(t^β+1)`, `(t/(t+1))^γ`), la forme lue par la boucle.
    /// Les valeurs attendues sont recalculées sur cette conversion, pas recopiées.
    #[test]
    fn hs_dcfr_formulas_match_published_checkpoints() {
        let t = 10u32;
        let n = 1000u32;
        // α = 1 + 3·10/1000 = 1,03 ; β = −1 − 0,02 = −1,02 ; γ = 30 − 0,05 = 29,95
        let alpha = 1.0 + 3.0 * 10.0 / 1000.0;
        let beta = -1.0 - 2.0 * 10.0 / 1000.0;
        let gamma30 = 30.0 - 5.0 * 10.0 / 1000.0;
        let gamma15 = 15.0 - 5.0 * 10.0 / 1000.0;

        let params30 = DiscountParams::for_schedule(DiscountSchedule::HsDcfr30, t, n);
        assert!(
            (params30.alpha_t - retention(10.0f64.powf(alpha))).abs() < 1e-6,
            "alpha_t HS-DCFR(30) à t = 10"
        );
        assert!(
            (params30.beta_t - retention(10.0f64.powf(beta))).abs() < 1e-6,
            "beta_t HS-DCFR(30) à t = 10"
        );
        assert!(
            (params30.gamma_t - (10.0f64 / 11.0).powf(gamma30) as f32).abs() < 1e-6,
            "gamma_t HS-DCFR(30) à t = 10"
        );

        // γ initial 15 : mêmes α et β, γ différent — c'est le seul paramètre qui
        // distingue les deux variantes.
        let params15 = DiscountParams::for_schedule(DiscountSchedule::HsDcfr15, t, n);
        assert_eq!(params15.alpha_t, params30.alpha_t);
        assert_eq!(params15.beta_t, params30.beta_t);
        assert!(
            (params15.gamma_t - (10.0f64 / 11.0).powf(gamma15) as f32).abs() < 1e-6,
            "gamma_t HS-DCFR(15) à t = 10"
        );
        assert!(
            params15.gamma_t > params30.gamma_t,
            "γ15 < γ30 ⇒ la rétention de la stratégie est plus forte avec γ30"
        );
    }

    /// Facteur de rétention `x/(x+1)`, la conversion utilisée par `for_schedule`.
    fn retention(x: f64) -> f32 {
        (x / (x + 1.0)) as f32
    }

    /// T004 — finitude : aucun `NaN`, aucun `∞`, sur toute la plage d'itérations.
    ///
    /// `t = 0` est le cas dangereux : `β = −1` et `0^β` n'est pas défini. Le code
    /// doit produire un paramètre fini, jamais `NaN` (qui se propagerait à toutes
    /// les itérations suivantes via les regrets cumulés).
    #[test]
    fn schedule_params_are_finite_and_bounded_for_every_iteration() {
        for schedule in [
            DiscountSchedule::Dcfr,
            DiscountSchedule::HsDcfr30,
            DiscountSchedule::HsDcfr15,
        ] {
            for n in [1u32, 2, 10, 1000, 10000] {
                for t in 0..=n {
                    let params = DiscountParams::for_schedule(schedule, t, n);
                    for (label, value) in [
                        ("alpha_t", params.alpha_t),
                        ("beta_t", params.beta_t),
                        ("gamma_t", params.gamma_t),
                    ] {
                        assert!(
                            value.is_finite(),
                            "{schedule:?} {label} non fini à t = {t}, n = {n} : {value}"
                        );
                        assert!(
                            (0.0..=1.0).contains(&value),
                            "{schedule:?} {label} hors de [0, 1] à t = {t}, n = {n} : {value}"
                        );
                    }
                }
            }
        }
    }

    /// T004 (suite) — `t = 0` explicitement : itération sans discount.
    #[test]
    fn first_iteration_is_discount_free_and_finite() {
        for schedule in [DiscountSchedule::HsDcfr30, DiscountSchedule::HsDcfr15] {
            let params = DiscountParams::for_schedule(schedule, 0, 1000);
            assert_eq!(params.alpha_t, 0.0, "{schedule:?} à t = 0");
            assert_eq!(params.beta_t, 1.0, "{schedule:?} à t = 0");
            assert_eq!(params.gamma_t, 0.0, "{schedule:?} à t = 0");
        }
    }
}
