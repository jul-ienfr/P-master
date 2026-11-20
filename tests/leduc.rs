extern crate postflop_solver;
use postflop_solver::*;

mod common;
use common::leduc::{LeducGame, NUM_PRIVATE_HANDS};
#[test]
fn leduc() {
    let target = 1e-4;
    let mut game = LeducGame::new(false);
    solve(&mut game, 10000, target, false);

    let root = game.root();

    let mut strategy = root.strategy().to_vec();
    for i in 0..NUM_PRIVATE_HANDS {
        let j = i + NUM_PRIVATE_HANDS;
        let sum = strategy[i] + strategy[j];
        strategy[i] /= sum;
        strategy[j] /= sum;
    }

    let root_ev = root
        .cfvalues()
        .iter()
        .zip(strategy.iter())
        .fold(0.0, |acc, (&ev, &strategy)| acc + ev * strategy);

    let expected_ev = -0.0856; // verified by OpenSpiel
    assert!((root_ev - expected_ev).abs() < 2.0 * target);
}

#[test]
fn leduc_compressed() {
    let target = 1e-3;
    let mut game = LeducGame::new(true);
    solve(&mut game, 10000, target, false);

    let root = game.root();

    let mut strategy = [0.0; NUM_PRIVATE_HANDS * 2];
    let raw_strategy = root.strategy_compressed();
    for i in 0..NUM_PRIVATE_HANDS {
        let j = i + NUM_PRIVATE_HANDS;
        let sum = (raw_strategy[i] as u32 + raw_strategy[j] as u32) as f32;
        strategy[i] = raw_strategy[i] as f32 / sum;
        strategy[j] = raw_strategy[j] as f32 / sum;
    }

    let ev_decoder = root.cfvalue_scale() / i16::MAX as f32;
    let root_ev = root
        .cfvalues_compressed()
        .iter()
        .zip(strategy.iter())
        .fold(0.0, |acc, (&raw_ev, &strategy)| {
            acc + ev_decoder * raw_ev as f32 * strategy
        });

    let expected_ev = -0.0856; // verified by OpenSpiel
    assert!((root_ev - expected_ev).abs() < 2.0 * target);
}
