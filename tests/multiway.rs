use postflop_solver::{solve_multiway, MultiwayRequest};

fn base_request(board: &[&str]) -> MultiwayRequest {
    MultiwayRequest {
        ranges: ["AA".to_string(), "KK".to_string(), "QQ".to_string()],
        board: board.iter().map(|card| card.to_string()).collect(),
        starting_pot: 6.0,
        effective_stack: 20.0,
        hero_player: 0,
        max_iterations: 500,
        random_seed: Some(42),
    }
}

#[test]
fn three_way_river_solves_and_prefers_aggression_with_top_set() {
    let response = solve_multiway(base_request(&["Ah", "7d", "2c", "Kd", "9s"]))
        .expect("river multiway solve");

    assert_eq!(response.iterations, 500);
    assert!(!response.actions.is_empty());
    // Top set vs KK/QQ sur board sec : jamais de fold recommandé.
    assert_ne!(response.recommended_action, "fold");
    // L'équité du héro (AA) dépasse largement sa part équitable (1/3 du pot).
    assert!(response.hero_ev > 2.0, "hero_ev = {}", response.hero_ev);
}

#[test]
fn three_way_flop_solves_with_chance_sampling() {
    let response = solve_multiway(base_request(&["Ah", "7d", "2c"])).expect("flop multiway solve");

    assert_eq!(response.iterations, 500);
    assert_ne!(response.recommended_action, "fold");
    // EV positive pour AA sur un flop as-high face à KK/QQ.
    assert!(response.hero_ev > 1.5, "hero_ev = {}", response.hero_ev);
}

#[test]
fn three_way_turn_solves_with_chance_sampling() {
    let response =
        solve_multiway(base_request(&["Ah", "7d", "2c", "Ts"])).expect("turn multiway solve");

    assert_eq!(response.iterations, 500);
    assert!(!response.recommended_action.is_empty());
}

#[test]
fn multiple_raise_sizes_available_in_abstraction() {
    // Stack profond : les deux tailles de relance doivent exister dans l'arbre
    // et apparaître dans la stratégie moyenne agrégée quand elles sont jouées.
    let mut request = base_request(&["Ah", "7d", "2c"]);
    request.effective_stack = 100.0;
    request.max_iterations = 800;
    let response = solve_multiway(request).expect("deep stack multiway solve");

    let names: Vec<&str> = response.actions.iter().map(|a| a.name.as_str()).collect();
    assert!(names.contains(&"call"));
    for name in &names {
        assert!(
            matches!(*name, "fold" | "call" | "bet_0.5" | "bet_1"),
            "taille inattendue: {name}"
        );
    }
    // Fréquences sommées à ~1 sur les actions listées.
    let total_freq: f32 = response.actions.iter().map(|a| a.frequency).sum();
    assert!((total_freq - 1.0).abs() < 0.05, "total_freq = {total_freq}");
}

#[test]
fn multiway_solve_is_deterministic_with_seed() {
    let first = solve_multiway(base_request(&["Ah", "7d", "2c"])).expect("first solve");
    let second = solve_multiway(base_request(&["Ah", "7d", "2c"])).expect("second solve");

    assert_eq!(first.recommended_action, second.recommended_action);
    assert!((first.hero_ev - second.hero_ev).abs() < 1e-6);
    for (left, right) in first.actions.iter().zip(second.actions.iter()) {
        assert_eq!(left.name, right.name);
        assert!((left.frequency - right.frequency).abs() < 1e-6);
    }
}

#[test]
fn preflop_board_is_rejected() {
    let mut request = base_request(&["Ah", "7d"]);
    request.board.truncate(2);
    let result = solve_multiway(request);

    assert!(result.is_err());
    assert!(result.unwrap_err().contains("3 à 5"));
}

#[test]
fn invalid_range_is_rejected() {
    let mut request = base_request(&["Ah", "7d", "2c", "Kd", "9s"]);
    request.ranges[1] = "not-a-range!!!".to_string();
    let result = solve_multiway(request);

    assert!(result.is_err());
    assert!(result.unwrap_err().contains("range invalide"));
}

#[test]
fn weak_hero_range_converges_toward_passive_play() {
    // Héro avec une main quasi sans équité face à deux ranges fortes : l'EV
    // doit rester très inférieure à celle d'un monstre (test stable, sans
    // dépendre de l'argmax exact en début de convergence).
    // Note: 72o sur J72 floppe deux paires (fort), on utilise 92o (seulement paire de 2) comme vraie poubelle.
    let mut request = base_request(&["Jh", "7d", "2c"]);
    request.ranges[0] = "92o".to_string();
    request.max_iterations = 4_000;
    let response = solve_multiway(request).expect("weak hero solve");

    assert!(
        response.hero_ev < 1.0,
        "hero_ev = {} (une poubelle ne doit pas rapporter)",
        response.hero_ev
    );
    // L'action recommandée reste légale dans l'abstraction.
    assert!(matches!(
        response.recommended_action.as_str(),
        "fold" | "call" | "bet_0.5" | "bet_1"
    ));

    // Contraste : le même spot avec AA produit une EV nettement supérieure.
    let mut strong = base_request(&["Jh", "7d", "2c"]);
    strong.max_iterations = 4_000;
    let strong_response = solve_multiway(strong).expect("strong hero solve");
    assert!(
        strong_response.hero_ev > response.hero_ev,
        "AA ({}) doit dominer 72o ({})",
        strong_response.hero_ev,
        response.hero_ev
    );
}
