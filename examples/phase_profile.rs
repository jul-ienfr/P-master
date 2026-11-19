// Probe temporaire (19/11) : décompose le coût réel du spot de production
// `flop_srp_akhk` (hero IP 570 combos, villain OOP 34 combos, pot 6, stack 97,
// arbre 50%/2.5x) au budget 800 ms, en répliquant exactement le chemin de
// `solve_spot_inner` (réserve = exploitabilité initiale, finalisation du seul
// joueur héros, lecture O(combos) de l'EV de range).
use postflop_solver::*;
use std::time::{Duration, Instant};

const MAX_ITERS: u32 = 200;

fn budget_ms() -> u64 {
    std::env::var("PROFILE_BUDGET_MS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(800)
}

fn main() {
    let budget = budget_ms();
    // Ranges exactes du benchmark de production (capture 19/11).
    let villain_range: Range = "55, A2s, K9s, Q9s, J9s, T9s, 98s, 87s, 76s, 65s, ATo, KJo, QJo"
        .parse()
        .unwrap(); // OOP
    let hero_range: Range = "22+, A2s+, K2s+, Q2s+, J5s+, T6s+, 96s+, 85s+, 75s+, 64s+, 54s, A2o+, K8o+, Q9o+, J9o+, T9o"
        .parse()
        .unwrap(); // IP

    let card_config = CardConfig {
        range: [villain_range, hero_range],
        flop: flop_from_str("Jc7s2d").unwrap(),
        turn: NOT_DEALT,
        river: NOT_DEALT,
    };
    let bet_sizes = BetSizeOptions::try_from(("50%", "2.5x")).unwrap();
    let tree_config = TreeConfig {
        initial_state: BoardState::Flop,
        starting_pot: 6,
        effective_stack: 97,
        rake_rate: 0.0,
        rake_cap: 0.0,
        flop_bet_sizes: [bet_sizes.clone(), bet_sizes.clone()],
        turn_bet_sizes: [bet_sizes.clone(), bet_sizes.clone()],
        river_bet_sizes: [bet_sizes.clone(), bet_sizes],
        turn_donk_sizes: None,
        river_donk_sizes: None,
        add_allin_threshold: 1.5,
        force_allin_threshold: 0.15,
        merging_threshold: 0.1,
    };

    let start = Instant::now();
    let t_tree = Instant::now();
    let action_tree = ActionTree::new(tree_config).unwrap();
    let tree_ms = t_tree.elapsed().as_secs_f64() * 1000.0;
    let t_game = Instant::now();
    let mut game = PostFlopGame::with_config(card_config, action_tree).unwrap();
    let game_build_ms = t_game.elapsed().as_secs_f64() * 1000.0;
    let build_ms = start.elapsed().as_secs_f64() * 1000.0;

    // La production alloue l'arbre compressé (i16 + échelle) : c'est le défaut.
    // `PROFILE_UNCOMPRESSED=1` rejoue l'ancien mode pour comparaison.
    let compressed = std::env::var("PROFILE_UNCOMPRESSED").is_err();
    let t = Instant::now();
    game.allocate_memory(compressed);
    let alloc_ms = t.elapsed().as_secs_f64() * 1000.0;
    let (mem, mem_c) = game.memory_usage();

    let hero_player = 1usize; // IP

    let t = Instant::now();
    let expl_initial = compute_exploitability(&game);
    let expl_initial_d = t.elapsed();
    let expl_initial_ms = expl_initial_d.as_secs_f64() * 1000.0;

    // Réplique de solve_with_deadline : échéance = début + budget, moins la
    // réserve (exploitabilité initiale, proxy du coût de finalize).
    let deadline = start + Duration::from_millis(budget);
    let effective = deadline.checked_sub(expl_initial_d).unwrap_or(deadline);
    let mut last_iteration = Duration::ZERO;
    let mut iters: u32 = 0;
    let mut one_step_ms = 0.0_f64;
    for t_idx in 0..MAX_ITERS {
        let now = Instant::now();
        if now >= effective {
            break;
        }
        // Première itération : estimation par la réserve (même règle que
        // solve_with_deadline_storing).
        let expected = if last_iteration.is_zero() {
            expl_initial_d
        } else {
            last_iteration
        };
        if now + expected >= effective {
            break;
        }
        let t0 = Instant::now();
        solve_step(&game, t_idx);
        last_iteration = t0.elapsed();
        if iters == 0 {
            one_step_ms = last_iteration.as_secs_f64() * 1000.0;
        }
        iters += 1;
    }
    let loop_ms = start.elapsed().as_secs_f64() * 1000.0;

    // finalize_players(&[hero]) : seul le joueur héros est stocké.
    let t = Instant::now();
    finalize_players(&mut game, &[hero_player]);
    let finalize_ms = t.elapsed().as_secs_f64() * 1000.0;

    let t = Instant::now();
    game.cache_normalized_weights();
    let cache_ms = t.elapsed().as_secs_f64() * 1000.0;

    let t = Instant::now();
    let values = game.expected_values(hero_player);
    let weights = game.normalized_weights(hero_player);
    let mut weighted = 0.0f64;
    let mut total_w = 0.0f64;
    for (&v, &w) in values.iter().zip(weights) {
        weighted += v as f64 * w as f64;
        total_w += w as f64;
    }
    let hero_ev = (weighted / total_w) as f32 - game.tree_config().starting_pot as f32 * 0.5;
    let ev_read_ms = t.elapsed().as_secs_f64() * 1000.0;

    // Total « production » : tout ce que `solve_spot_inner` fait avant de
    // construire la réponse (hors sondes ci-dessous).
    let prod_equiv_ms = start.elapsed().as_secs_f64() * 1000.0;

    let pot_half = game.tree_config().starting_pot as f64 * 0.5;
    let cev = compute_current_ev(&game);

    println!(
        "== spot de production flop_srp_akhk, budget {budget} ms (compressed={compressed}) =="
    );
    println!(
        "memory: {:.2}GB (compressed {:.2}GB)",
        mem as f64 / (1024.0 * 1024.0 * 1024.0),
        mem_c as f64 / (1024.0 * 1024.0 * 1024.0)
    );
    println!("build_ms: {build_ms:.1} (arbre + game) [tree={tree_ms:.1} game={game_build_ms:.1}]");
    println!("alloc_ms: {alloc_ms:.1}");
    println!("expl_initial_ms: {expl_initial_ms:.1} (value {expl_initial:.4})");
    println!("iterations_dans_budget: {iters} (une iteration = {one_step_ms:.1} ms)");
    println!("loop_ms (apres {iters} iterations): {loop_ms:.1}");
    println!("finalize_ms (1 joueur): {finalize_ms:.1}");
    println!("cache_weights_ms: {cache_ms:.1}");
    println!("ev_read_ms: {ev_read_ms:.1} (hero_ev {hero_ev:.6})");
    println!("compute_current_ev_ms: {:.1} (cev {cev:?})", {
        let t = Instant::now();
        compute_current_ev(&game);
        t.elapsed().as_secs_f64() * 1000.0
    });
    println!("prod_equiv_ms (build+alloc+expl+iters+finalize+cache+ev): {prod_equiv_ms:.1}");

    let t = Instant::now();
    drop(game);
    let drop_ms = t.elapsed().as_secs_f64() * 1000.0;
    println!("drop_ms: {drop_ms:.1}");
    println!(
        "ecart_hero_ev_vs_cev: {:+.6} (pot/2={pot_half})",
        hero_ev - cev[hero_player]
    );
}
