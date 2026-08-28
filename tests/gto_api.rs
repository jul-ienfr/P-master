use postflop_solver::{ev, solve_spot, SolveRequest};

fn river_request(effective_stack: f32) -> SolveRequest {
    SolveRequest {
        oop_range: "AA,KK,QQ".to_string(),
        ip_range: "JJ,TT,AKs".to_string(),
        board: vec![
            "Ah".to_string(),
            "7d".to_string(),
            "2c".to_string(),
            "Kd".to_string(),
            "9s".to_string(),
        ],
        starting_pot: 8.0,
        effective_stack,
        hero_is_oop: true,
        max_iterations: 200,
        target_exploitability: 0.5,
        use_cache: false,
        ..SolveRequest::default()
    }
}

#[test]
fn gto_ev_bb_matches_ev_chips_over_bb() {
    let req = river_request(20.0);
    let bb = req.effective_stack / 100.0;
    let resp = solve_spot(req).expect("solve_spot river");
    assert!(resp.hero_ev.is_finite(), "hero_ev not finite: {}", resp.hero_ev);
    let ev_bb = resp.ev_bb.expect("ev_bb should be Some with positive stack");
    // § D : ev_bb ≈ ev_chips / bb
    assert!(
        (ev_bb - resp.hero_ev / bb).abs() < 1e-4,
        "ev_bb {} != hero_ev {} / bb {} (diff {})",
        ev_bb,
        resp.hero_ev,
        bb,
        (ev_bb - resp.hero_ev / bb).abs()
    );
    // Direct helper consistency
    assert!(
        (ev::ev_chips_to_bb(resp.hero_ev, bb).unwrap() - ev_bb).abs() < 1e-6,
        "ev_chips_to_bb mismatch"
    );
}

#[test]
fn gto_ev_bb_per_100_is_ev_bb_times_100() {
    let req = river_request(20.0);
    let resp = solve_spot(req).expect("solve_spot river");
    let ev_bb = resp.ev_bb.expect("ev_bb");
    let ev_bb_per_100 = resp.ev_bb_per_100.expect("ev_bb_per_100");
    // § D : ev_bb_per_100 = ev_bb * 100
    assert!(
        (ev_bb_per_100 - ev_bb * 100.0).abs() < 1e-4,
        "ev_bb_per_100 {} != ev_bb {} * 100 (diff {})",
        ev_bb_per_100,
        ev_bb,
        (ev_bb_per_100 - ev_bb * 100.0).abs()
    );
    assert!(
        (ev::ev_bb_per_100(ev_bb) - ev_bb_per_100).abs() < 1e-6,
        "ev_bb_per_100 helper mismatch"
    );
}

#[test]
fn gto_action_ev_bb_consistent_with_ev_chips_and_combo() {
    let req = river_request(100.0);
    let bb = req.effective_stack / 100.0;
    let resp = solve_spot(req).expect("solve_spot deep");
    assert!(!resp.actions.is_empty(), "no actions");
    // Each action ev_bb ~ ev / bb and ev_bb_per_100 = ev_bb*100
    for action in &resp.actions {
        if let Some(ev_bb) = action.ev_bb {
            assert!(
                (ev_bb - action.ev / bb).abs() < 1e-4,
                "action {} ev_bb {} != ev {} / bb {}",
                action.name,
                ev_bb,
                action.ev,
                bb
            );
            let ev_bb_per_100 = action.ev_bb_per_100.expect("action ev_bb_per_100");
            assert!(
                (ev_bb_per_100 - ev_bb * 100.0).abs() < 1e-4,
                "action {} ev_bb_per_100 {} != {}*100",
                action.name,
                ev_bb_per_100,
                ev_bb
            );
        } else {
            panic!("action {} ev_bb is None with bb={}", action.name, bb);
        }
        assert!(action.ev.is_finite());
    }
    // combo_ev_bb ≈ hero_combo_ev / bb
    if let Some(combo_bb) = resp.combo_ev_bb {
        assert!(
            (combo_bb - resp.hero_combo_ev / bb).abs() < 1e-4,
            "combo_ev_bb {} != hero_combo_ev {} / bb {}",
            combo_bb,
            resp.hero_combo_ev,
            bb
        );
    }
}

#[test]
fn gto_ev_chips_bb_roundtrip_via_effective_stack() {
    // Cheap pure-helper check without a solve: ev_bb_per_100_from_chips
    let ev_chips = 10.0f32;
    let bb = 2.0f32; // e.g. NL2
    let via_helper = ev::ev_bb_per_100_from_chips(ev_chips, bb).unwrap();
    let via_steps = ev::ev_chips_to_bb(ev_chips, bb).unwrap() * 100.0;
    assert!((via_helper - via_steps).abs() < 1e-6);
    assert!((via_helper - 500.0).abs() < 1e-6); // 10/2=5 bb → 500 bb/100
}
