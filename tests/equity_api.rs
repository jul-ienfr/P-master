use postflop_solver::{evaluate_equity, ev, EquityMode, EquityRequest};

#[test]
fn equity_ev_equals_equity_times_pot() {
    // § D : equity*pot - cost  (cost=0 here) via ev_chips_given_pot
    let pot = 8.0f32;
    let resp = evaluate_equity(EquityRequest {
        hero_hand: vec!["Ah".into(), "Ad".into()],
        villain_ranges: vec!["KcKd".into()],
        board: vec!["2c".into(), "7d".into(), "9h".into(), "Js".into(), "Qd".into()],
        mode: EquityMode::Exact,
        pot: Some(pot),
        use_cache: false,
        ..Default::default()
    })
    .expect("exact equity");

    let ev_chips = resp.ev_chips_given_pot.expect("ev_chips_given_pot with pot");
    // ev should be equity * pot  (cost=0)
    let expected = ev::equity_ev(pot, resp.equity, 0.0);
    assert!(
        (ev_chips - expected).abs() < 1e-4,
        "ev_chips_given_pot {} != equity {} * pot {} = {} (diff {})",
        ev_chips,
        resp.equity,
        pot,
        expected,
        (ev_chips - expected).abs()
    );
    // Direct identity
    assert!(
        (ev_chips - resp.equity * pot).abs() < 1e-4,
        "ev_chips_given_pot {} != equity*pot {}",
        ev_chips,
        resp.equity * pot
    );
}

#[test]
fn equity_ev_with_cost_is_equity_times_pot_minus_cost() {
    // Pure helper § D : EV = equity*pot - cost
    let pot = 100.0f32;
    let equity = 0.55f32;
    let cost = 50.0f32;
    let ev = ev::equity_ev(pot, equity, cost);
    assert!((ev - 5.0).abs() < 1e-6, "equity_ev(100,0.55,50) should be 5, got {}", ev);
    // Rake-aware variant sanity: with no rake should equal plain equity_ev
    let ev_rake = ev::equity_ev_rake_aware(pot, equity, cost, 0.0, 0.0);
    assert!(
        (ev - ev_rake).abs() < 1e-6,
        "rake_aware with 0 rake should match plain, {} vs {}",
        ev_rake,
        ev
    );
}

#[test]
fn equity_ev_chips_bb_and_per100_roundtrip() {
    // ev_chips_given_pot → ev_bb → ev_bb_per_100  (§ D conversions)
    let pot = 20.0f32;
    let bb = 2.0f32;
    let resp = evaluate_equity(EquityRequest {
        hero_hand: vec!["As".into(), "Ks".into()],
        villain_ranges: vec!["QQ+".into()],
        board: vec!["Ah".into(), "7d".into(), "2c".into()],
        mode: EquityMode::Exact,
        pot: Some(pot),
        use_cache: false,
        ..Default::default()
    })
    .expect("equity for bb roundtrip");

    let ev_chips = resp.ev_chips_given_pot.expect("ev_chips_given_pot");
    let ev_bb = ev::ev_chips_to_bb(ev_chips, bb).expect("ev_bb");
    let ev_bb_per_100 = ev::ev_bb_per_100(ev_bb);
    let via_helper = ev::ev_bb_per_100_from_chips(ev_chips, bb).expect("via helper");

    assert!(
        (ev_bb - ev_chips / bb).abs() < 1e-6,
        "ev_bb {} != ev_chips {} / bb {}",
        ev_bb,
        ev_chips,
        bb
    );
    assert!(
        (ev_bb_per_100 - ev_bb * 100.0).abs() < 1e-6,
        "ev_bb_per_100 {} != ev_bb {} *100",
        ev_bb_per_100,
        ev_bb
    );
    assert!(
        (via_helper - ev_bb_per_100).abs() < 1e-6,
        "helper {} != manual {}",
        via_helper,
        ev_bb_per_100
    );
}

#[test]
fn equity_ev_none_pot_gives_none_and_cache_recalc() {
    // No pot → None; cache is pot-agnostic and recalculates on hit
    let base = EquityRequest {
        hero_hand: vec!["Ah".into(), "Kd".into()],
        villain_ranges: vec!["QQ,JJ,TT,AKs".into()],
        board: vec!["2c".into(), "7d".into(), "9h".into()],
        pot: None,
        use_cache: true,
        ..Default::default()
    };
    let r1 = evaluate_equity(base.clone()).expect("equity no pot");
    assert!(r1.ev_chips_given_pot.is_none(), "no pot should give None");
    // Same spot with pot → ev populated; second call with same pot should still match equity*pot via cache recalc
    let with_pot = EquityRequest {
        pot: Some(12.0),
        ..base.clone()
    };
    let r2 = evaluate_equity(with_pot.clone()).expect("with pot");
    let expected = r2.equity * 12.0;
    assert!(
        (r2.ev_chips_given_pot.unwrap() - expected).abs() < 1e-4,
        "ev_chips_given_pot {} != equity {} * 12 {}",
        r2.ev_chips_given_pot.unwrap(),
        r2.equity,
        expected
    );
    let r3 = evaluate_equity(with_pot).expect("with pot cached");
    assert!(r3.cache_hit, "should be cache hit");
    assert!(
        (r3.ev_chips_given_pot.unwrap() - r3.equity * 12.0).abs() < 1e-4,
        "cached recalc mismatch"
    );
}
