//! Convergence des schedules CFR sur Kuhn et Leduc (spec `012`, T006/T007/T008).
//!
//! Ce test mesure l'exploitabilité et la valeur de jeu atteintes à itérations
//! fixées, pour le défaut (DCFR) et pour HS-DCFR(30)/HS-DCFR(15), sur les deux
//! jeux tabulaires du dépôt. Les valeurs de référence (Kuhn `−1/18`, Leduc
//! `−0,0856`) sont celles déjà vérifiées contre OpenSpiel dans `tests/kuhn.rs`
//! et `tests/leduc.rs`.
//!
//! La mesure est **déterministe** (aucune graine, aucun service externe) et
//! **reproductible** : les paliers sont rejoués depuis un jeu neuf à chaque fois.

extern crate postflop_solver;
use postflop_solver::{solve_step_with_schedule, DiscountSchedule, Game, GameNode};

mod common;
use common::kuhn::{KuhnGame, NUM_PRIVATE_HANDS as KUHN_HANDS};
use common::leduc::{LeducGame, NUM_PRIVATE_HANDS as LEDUC_HANDS};
use common::schedule_bench::{
    measure_schedule, today_utc, verdict, DEFAULT_TIERS, EXISTING_TOLERANCE, REFERENCE_KUHN,
    REFERENCE_LEDUC,
};

/// Tous les schedules mesurés, dans un ordre stable (le rapport suit cet ordre).
const SCHEDULES: [DiscountSchedule; 3] = [
    DiscountSchedule::Dcfr,
    DiscountSchedule::HsDcfr30,
    DiscountSchedule::HsDcfr15,
];

/// Valeur de jeu du joueur suivi à la racine, pour Kuhn.
///
/// La stratégie stockée est normalisée par main (deux actions par main), comme
/// dans `tests/kuhn.rs` : c'est la fréquence de la première action.
fn kuhn_root_ev(game: &KuhnGame) -> f32 {
    let root = game.root();
    let mut strategy = root.strategy().to_vec();
    for i in 0..KUHN_HANDS {
        let j = i + KUHN_HANDS;
        let sum = strategy[i] + strategy[j];
        strategy[i] /= sum;
        strategy[j] /= sum;
    }
    root.cfvalues()
        .iter()
        .zip(strategy.iter())
        .fold(0.0, |acc, (&cfv, &s)| acc + cfv * s)
}

/// Valeur de jeu du joueur suivi à la racine, pour Leduc (chemin non compressé).
fn leduc_root_ev(game: &LeducGame) -> f32 {
    let root = game.root();
    let mut strategy = root.strategy().to_vec();
    for i in 0..LEDUC_HANDS {
        let j = i + LEDUC_HANDS;
        let sum = strategy[i] + strategy[j];
        strategy[i] /= sum;
        strategy[j] /= sum;
    }
    root.cfvalues()
        .iter()
        .zip(strategy.iter())
        .fold(0.0, |acc, (&ev, &s)| acc + ev * s)
}

/// T006 — Kuhn : chaque schedule atteint `−1/18` à la tolérance du test existant.
#[test]
fn kuhn_converges_under_every_schedule() {
    for schedule in SCHEDULES {
        let samples = measure_schedule(KuhnGame::new, schedule, &DEFAULT_TIERS, kuhn_root_ev);
        let (reaches, summary) = verdict(&samples, REFERENCE_KUHN, EXISTING_TOLERANCE);
        println!("[kuhn] {schedule}: {summary}");
        assert!(
            reaches,
            "Kuhn sous {schedule} n'atteint pas la référence : {summary}"
        );
    }
}

/// T007 — Leduc : chaque schedule atteint `−0,0856` à la tolérance du test existant.
#[test]
fn leduc_converges_under_every_schedule() {
    for schedule in SCHEDULES {
        let samples = measure_schedule(
            || LeducGame::new(false),
            schedule,
            &DEFAULT_TIERS,
            leduc_root_ev,
        );
        let (reaches, summary) = verdict(&samples, REFERENCE_LEDUC, EXISTING_TOLERANCE);
        println!("[leduc] {schedule}: {summary}");
        assert!(
            reaches,
            "Leduc sous {schedule} n'atteint pas la référence : {summary}"
        );
    }
}

/// T005/FR-007 — parité compressé / non compressé sous un schedule HS.
///
/// Les deux chemins lisent les mêmes `params` ; le schedule ne doit donc pas
/// les faire diverger. La tolérance est celle du test `leduc_compressed`
/// existant (1e-3), plus lâche parce que la compression quantifie en i16.
///
/// T005 demande la **même stratégie**, pas seulement la même valeur de jeu :
/// deux stratégies différentes peuvent partager une valeur de jeu à la racine.
/// La comparaison porte donc aussi sur la stratégie normalisée par main, à une
/// tolérance qui tient compte de la quantification u16.
#[test]
fn leduc_compressed_and_uncompressed_agree_under_hs_schedule() {
    let tiers = [1_000u32, 10_000];
    let schedule = DiscountSchedule::HsDcfr30;

    let plain = measure_schedule(|| LeducGame::new(false), schedule, &tiers, leduc_root_ev);
    let compressed = measure_schedule(
        || LeducGame::new(true),
        schedule,
        &tiers,
        leduc_compressed_root_ev,
    );

    for (a, b) in plain.iter().zip(compressed.iter()) {
        assert_eq!(a.iterations, b.iterations);
        let delta = (a.game_value - b.game_value).abs();
        println!(
            "[parity] {} itérations : non compressé {:.6}, compressé {:.6}, écart {:.2e}",
            a.iterations, a.game_value, b.game_value, delta
        );
        assert!(
            delta < 1e-3,
            "les chemins compressé et non compressé divergent sous {schedule} \
             à {} itérations : écart {delta:.2e}",
            a.iterations
        );
    }

    // La stratégie elle-même, à chaque palier : c'est la parité que T005 exige.
    for &tier in &tiers {
        let plain_strategy =
            normalized_root_strategy(&LeducGame::new(false), schedule, tier, false);
        let compressed_strategy =
            normalized_root_strategy(&LeducGame::new(true), schedule, tier, true);

        let max_delta = plain_strategy
            .iter()
            .zip(compressed_strategy.iter())
            .map(|(a, b)| (a - b).abs())
            .fold(0.0f32, f32::max);
        println!("[parity-strategy] {tier} itérations : écart max de fréquence {max_delta:.2e}");
        // La quantification u16 borne la précision de la stratégie compressée :
        // on exige la même stratégie à cette résolution près, pas au bit près.
        assert!(
            max_delta < 2e-3,
            "la stratégie diverge entre les chemins compressé et non compressé \
             sous {schedule} à {tier} itérations : écart max {max_delta:.2e}"
        );
    }
}

/// Stratégie de la racine, normalisée par main, après `tier` itérations.
///
/// `compressed` sélectionne la lecture : `strategy()` (f32) ou
/// `strategy_compressed()` (u16 mis à l'échelle), chacune normalisée par main
/// pour que les deux lectures soient comparables.
fn normalized_root_strategy(
    game: &LeducGame,
    schedule: DiscountSchedule,
    tier: u32,
    compressed: bool,
) -> Vec<f32> {
    for t in 0..tier {
        solve_step_with_schedule(game, t, schedule, tier);
    }
    let root = game.root();
    let mut strategy = vec![0.0f32; LEDUC_HANDS * 2];
    if compressed {
        let raw = root.strategy_compressed();
        for i in 0..LEDUC_HANDS {
            let j = i + LEDUC_HANDS;
            let sum = (raw[i] as u32 + raw[j] as u32) as f32;
            strategy[i] = raw[i] as f32 / sum;
            strategy[j] = raw[j] as f32 / sum;
        }
    } else {
        let raw = root.strategy();
        for i in 0..LEDUC_HANDS {
            let j = i + LEDUC_HANDS;
            let sum = raw[i] + raw[j];
            strategy[i] = raw[i] / sum;
            strategy[j] = raw[j] / sum;
        }
    }
    strategy
}

/// Valeur de jeu lue sur le chemin compressé (i16 + échelle), comme
/// `tests/leduc.rs::leduc_compressed`.
fn leduc_compressed_root_ev(game: &LeducGame) -> f32 {
    let root = game.root();
    let mut strategy = [0.0; LEDUC_HANDS * 2];
    let raw_strategy = root.strategy_compressed();
    for i in 0..LEDUC_HANDS {
        let j = i + LEDUC_HANDS;
        let sum = (raw_strategy[i] as u32 + raw_strategy[j] as u32) as f32;
        strategy[i] = raw_strategy[i] as f32 / sum;
        strategy[j] = raw_strategy[j] as f32 / sum;
    }
    let ev_decoder = root.cfvalue_scale() / i16::MAX as f32;
    root.cfvalues_compressed()
        .iter()
        .zip(strategy.iter())
        .fold(0.0, |acc, (&raw_ev, &s)| {
            acc + ev_decoder * raw_ev as f32 * s
        })
}

/// T008/FR-011 — le rapport porte tout ce qui est requis, et son verdict ne
/// dépasse pas ce qui a été mesuré.
#[test]
fn convergence_report_carries_protocol_and_honest_verdict() {
    let samples = measure_schedule(
        KuhnGame::new,
        DiscountSchedule::HsDcfr30,
        &DEFAULT_TIERS,
        kuhn_root_ev,
    );
    let date = today_utc();
    let (reaches, summary) = verdict(&samples, REFERENCE_KUHN, EXISTING_TOLERANCE);

    let report = common::schedule_bench::report_json(
        "cfr_schedule_convergence",
        &date,
        "kuhn",
        DiscountSchedule::HsDcfr30,
        EXISTING_TOLERANCE,
        REFERENCE_KUHN,
        &DEFAULT_TIERS,
        &samples,
        reaches,
        &summary,
    );

    // Le rapport doit être un objet JSON non vide et porter chaque champ requis.
    assert!(report.starts_with('{') && report.ends_with('}'));
    for required in [
        "\"date\"",
        "\"iterations\"",
        "\"tolerance\"",
        "\"reference_value\"",
        "\"samples\"",
        "\"reaches_reference\"",
        "\"claim\"",
    ] {
        assert!(
            report.contains(required),
            "champ manquant : {required}\n{report}"
        );
    }

    // La date est au format YYYY-MM-DD et n'est pas une valeur inventée.
    assert_eq!(date.len(), 10, "date mal formée : {date}");
    assert!(
        date.starts_with("20"),
        "date hors du siècle attendu : {date}"
    );

    // Le verdict recopié dit ce qui a été mesuré, sans le dépasser : il nomme
    // la valeur obtenue et la référence.
    assert!(
        summary.contains("référence"),
        "le verdict doit citer la référence : {summary}"
    );
    assert!(
        summary.contains(&format!("{}", samples.last().unwrap().iterations)),
        "le verdict doit citer les itérations mesurées : {summary}"
    );
}
