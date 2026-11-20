extern crate postflop_solver;
use postflop_solver::*;

mod common;
use common::kuhn::{KuhnGame, NUM_PRIVATE_HANDS};
#[test]
fn kuhn() {
    let target = 1e-4;
    let mut game = KuhnGame::new();
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
        .fold(0.0, |acc, (&cfv, &strategy)| acc + cfv * strategy);

    let expected_ev = -1.0 / 18.0;
    assert!((root_ev - expected_ev).abs() < 2.0 * target);
}
