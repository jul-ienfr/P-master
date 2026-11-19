// Vérification d'équivalence : l'EV du joueur lue dans les valeurs stockées
// par `finalize` (expected_values) est-elle identique à `compute_current_ev`
// (parcours complet) ? Si oui, le chemin de production peut éviter ce parcours
// (~250-850 ms sur un flop à range complète).
use postflop_solver::*;
use std::time::Instant;

fn main() {
    let hero_range: Range = "22+,A2s+,K5s+,Q8s+,J8s+,T8s+,98s,87s,76s,ATo+,KJo+,QJo"
        .parse()
        .unwrap();
    let villain_range: Range = "QQ+, AKs, AKo".parse().unwrap();

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
    let action_tree = ActionTree::new(tree_config).unwrap();
    let mut game = PostFlopGame::with_config(card_config, action_tree).unwrap();
    game.allocate_memory(false);

    let expl = solve_with_deadline(&mut game, 10, 0.0, false, None);
    println!("expl_after_10_iters: {expl:.4}");
    game.cache_normalized_weights();

    let t_cev = Instant::now();
    let cev = compute_current_ev(&game);
    let cev_ms = t_cev.elapsed().as_secs_f64() * 1000.0;
    println!("compute_current_ev: {cev:?} ({cev_ms:.1} ms)");
    println!("current_player: {}", game.current_player());
    println!("starting_pot: {}", game.tree_config().starting_pot);

    let t_stored = Instant::now();
    for (p, cev_p) in cev.iter().enumerate() {
        let w = game.initial_weights(p);
        let sum_w: f64 = w.iter().map(|&x| x as f64).sum();
        let evs = game.expected_values(p);
        let weighted: f64 = evs
            .iter()
            .zip(w)
            .map(|(&v, &wt)| v as f64 * wt as f64)
            .sum();
        let normalized = weighted / sum_w;
        println!(
            "player {p}: n_hands={} sum_w={sum_w:.6} evs_len={} weighted={weighted:.6} normalized={normalized:.6}",
            w.len(),
            evs.len()
        );
        println!(
            "  cev[p]={:.6}  weighted-cev={:.6}  normalized-cev={:.6}  (pot/2=3)",
            cev_p,
            weighted - *cev_p as f64,
            normalized - *cev_p as f64
        );
    }
    let stored_ms = t_stored.elapsed().as_secs_f64() * 1000.0;
    println!("stored_read_ms (2 joueurs, expected_values): {stored_ms:.1}");
}
