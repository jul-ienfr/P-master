use postflop_solver::{solve_multiway, MultiwayRequest};

fn main() {
    let request = MultiwayRequest {
        ranges: ["92o".to_string(), "KK".to_string(), "QQ".to_string()],
        board: vec!["Jh".to_string(), "7d".to_string(), "2c".to_string()],
        starting_pot: 6.0,
        effective_stack: 20.0,
        hero_player: 0,
        max_iterations: 100_000,
        random_seed: Some(42),
    };
    let response = solve_multiway(request).expect("solve");
    println!("action: {}", response.recommended_action);
    println!("ev: {:.4}", response.hero_ev);
    println!(
        "actions: {:?}",
        response
            .actions
            .iter()
            .map(|a| (a.name.clone(), a.frequency))
            .collect::<Vec<_>>()
    );
}
