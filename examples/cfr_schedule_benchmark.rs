//! Point d'entrée opérateur : mesure de convergence des schedules CFR (spec `012`).
//!
//! Écrit `research/results/cfr_schedule_benchmark.json` — un artefact **daté et
//! versionné** portant, pour chaque schedule et chaque jeu (Kuhn, Leduc) :
//! itérations, tolérance, valeur de référence, exploitabilité et valeur de jeu
//! par palier, et un verdict qui ne dépasse pas ce qui a été mesuré (FR-011,
//! FR-012).
//!
//! ```text
//! cargo run --release --example cfr_schedule_benchmark
//! ```
//!
//! La mesure est déterministe et hors ligne : aucun service externe, aucune
//! graine. Elle ne rejoue pas le postflop HU à range complète (~800 ms/spot) et
//! ne prétend donc rien sur le chemin de production — elle tranche la question
//! préalable « le schedule change-t-il la convergence dans ce codebase ».

extern crate postflop_solver;
use postflop_solver::{DiscountSchedule, Game, GameNode};

#[path = "../tests/common/kuhn.rs"]
mod kuhn;
#[path = "../tests/common/leduc.rs"]
mod leduc;
#[path = "../tests/common/schedule_bench.rs"]
mod schedule_bench;

use kuhn::{KuhnGame, NUM_PRIVATE_HANDS as KUHN_HANDS};
use leduc::{LeducGame, NUM_PRIVATE_HANDS as LEDUC_HANDS};
use schedule_bench::{
    measure_schedule, report_json, today_utc, verdict, ConvergenceSample, DEFAULT_TIERS,
    EXISTING_TOLERANCE, REFERENCE_KUHN, REFERENCE_LEDUC,
};

/// Résultat de mesure d'un couple (jeu, schedule).
struct Measurement {
    game: &'static str,
    schedule: DiscountSchedule,
    reference: f32,
    samples: Vec<ConvergenceSample>,
    reaches: bool,
    summary: String,
}

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

/// Comparaison mesurée de chaque schedule HS au défaut, par jeu et par palier.
struct Comparison {
    json: String,
    /// Nombre de couples (schedule, palier) où HS est strictement moins exploitable.
    hs_wins: usize,
    /// Nombre total de couples comparés.
    total: usize,
    /// Phrase factuelle dérivée des mesures, jamais écrite à la main.
    summary: String,
}

/// Construit la comparaison HS vs DCFR à partir des mesures déjà prises.
///
/// Pour chaque jeu et chaque palier, on rapporte l'exploitabilité des deux
/// variantes HS et celle du défaut ; « bat » signifie strictement inférieure
/// (moins exploitable). Aucun seuil n'est inventé : on rapporte la différence
/// brute et un décompte factuel, pour que le verdict global soit **dérivé des
/// mesures** et non rédigé à la main.
fn comparison_json(measurements: &[Measurement]) -> Comparison {
    let mut rows = Vec::new();
    let mut hs_wins = 0usize;
    let mut total = 0usize;
    // Décompte par jeu : (victoires, total) pour HS-DCFR(30) et HS-DCFR(15).
    let mut per_game: Vec<(&str, &str, usize, usize)> = Vec::new();

    for game in ["kuhn", "leduc"] {
        let base = measurements
            .iter()
            .find(|m| m.game == game && m.schedule == DiscountSchedule::Dcfr)
            .expect("le défaut est toujours mesuré");
        for schedule in [DiscountSchedule::HsDcfr30, DiscountSchedule::HsDcfr15] {
            let hs = measurements
                .iter()
                .find(|m| m.game == game && m.schedule == schedule)
                .expect("chaque schedule est mesuré");
            let mut wins = 0usize;
            for (b, h) in base.samples.iter().zip(hs.samples.iter()) {
                debug_assert_eq!(b.iterations, h.iterations);
                let beats = h.exploitability < b.exploitability;
                if beats {
                    hs_wins += 1;
                    wins += 1;
                }
                total += 1;
                rows.push(format!(
                    "{{\"game\":\"{game}\",\"schedule\":\"{}\",\"iterations\":{},\
\"dcfr_exploitability\":{},\"hs_exploitability\":{},\
\"hs_better\":{beats}}}",
                    schedule.as_str(),
                    b.iterations,
                    schedule_bench::fmt_f32(b.exploitability),
                    schedule_bench::fmt_f32(h.exploitability),
                ));
            }
            per_game.push((game, schedule.as_str(), wins, hs.samples.len()));
        }
    }

    let detail = per_game
        .iter()
        .map(|(g, s, w, n)| format!("{s} sur {g} : {w}/{n} paliers"))
        .collect::<Vec<_>>()
        .join(", ");

    let summary = if hs_wins == 0 {
        format!(
            "HS-DCFR n'est strictement moins exploitable que le DCFR du crate sur \
             AUCUN des {total} couples (schedule, jeu, palier) mesurés ({detail})."
        )
    } else if hs_wins == total {
        format!(
            "HS-DCFR est strictement moins exploitable que le DCFR du crate sur \
             les {total} couples mesurés ({detail})."
        )
    } else {
        format!(
            "HS-DCFR est strictement moins exploitable que le DCFR du crate sur \
             {hs_wins} des {total} couples (schedule, jeu, palier) mesurés \
             ({detail}) : le résultat est mitigé, pas un gain net."
        )
    };

    Comparison {
        json: format!("[\n    {}\n  ]", rows.join(",\n    ")),
        hs_wins,
        total,
        summary,
    }
}

fn main() {
    let schedules = [
        DiscountSchedule::Dcfr,
        DiscountSchedule::HsDcfr30,
        DiscountSchedule::HsDcfr15,
    ];
    let mut measurements = Vec::new();
    for schedule in schedules {
        let samples = measure_schedule(KuhnGame::new, schedule, &DEFAULT_TIERS, kuhn_root_ev);
        let (reaches, summary) = verdict(&samples, REFERENCE_KUHN, EXISTING_TOLERANCE);
        measurements.push(Measurement {
            game: "kuhn",
            schedule,
            reference: REFERENCE_KUHN,
            samples,
            reaches,
            summary,
        });
    }
    for schedule in schedules {
        let samples = measure_schedule(
            || LeducGame::new(false),
            schedule,
            &DEFAULT_TIERS,
            leduc_root_ev,
        );
        let (reaches, summary) = verdict(&samples, REFERENCE_LEDUC, EXISTING_TOLERANCE);
        measurements.push(Measurement {
            game: "leduc",
            schedule,
            reference: REFERENCE_LEDUC,
            samples,
            reaches,
            summary,
        });
    }

    let date = today_utc();
    let entries = measurements
        .iter()
        .map(|m| {
            report_json(
                "cfr_schedule_measurement",
                &date,
                m.game,
                m.schedule,
                EXISTING_TOLERANCE,
                m.reference,
                &DEFAULT_TIERS,
                &m.samples,
                m.reaches,
                &m.summary,
            )
        })
        .collect::<Vec<_>>()
        .join(",\n  ");

    let tiers_json = DEFAULT_TIERS
        .iter()
        .map(|t| t.to_string())
        .collect::<Vec<_>>()
        .join(",");

    let all_reach = measurements.iter().all(|m| m.reaches);

    // Comparaison mesurée au défaut, palier par palier (FR-012). C'est le cœur
    // scientifique de la spec : le gain annoncé par l'article ne se transpose
    // pas nécessairement à la variante DCFR propre à ce crate, et le rapport
    // doit le dire au lieu de le supposer.
    let comparison = comparison_json(&measurements);

    let claim = if !all_reach {
        "Au moins un schedule n'atteint pas la valeur de jeu de référence : voir \
         les verdicts par entrée. Aucun gain n'est affirmé au-delà de ce qui a \
         été mesuré."
    } else {
        "Les trois schedules atteignent la valeur de jeu de référence à 10 000 \
         itérations sur Kuhn et Leduc. Sur la VITESSE de convergence, le résultat \
         est mesuré et rapporté ci-dessous sans arrondi favorable ; le gain de \
         2–3 ordres de magnitude annoncé par l'article (arXiv 2404.09097) n'est \
         pas reproduit ici. Deux explications possibles, non départagées par \
         cette mesure : le crate implémente une variante DCFR qui n'est pas le \
         DCFR canonique de l'article (β = 0,5 constant, reset de la stratégie à \
         chaque puissance de 4), et l'article avertit lui-même que l'avantage des \
         schedules diminue quand la taille du jeu augmente. Aucun gain n'est \
         affirmé au-delà de ce qui a été mesuré."
    };

    let artifact = format!(
        "{{\n  \"kind\": \"cfr_schedule_benchmark\",\n  \"date\": \"{date}\",\n  \
\"produced_by\": \"cargo run --release --example cfr_schedule_benchmark\",\n  \
\"deterministic\": true,\n  \"tiers\": [{tiers_json}],\n  \
\"tolerance\": {tol},\n  \"reference_values\": {{\"kuhn\": {rk}, \"leduc\": {rl}}},\n  \
\"scope\": \"Jeux tabulaires Kuhn et Leduc de tests/common ; le postflop HU a \
range complete n'est pas mesure.\",\n  \"all_reach_reference\": {all_reach},\n  \
\"comparison_summary\": \"{comparison_summary}\",\n  \
\"hs_wins_over_dcfr\": {hs_wins},\n  \"comparison_pairs\": {total_pairs},\n  \
\"claim\": \"{claim}\",\n  \"comparison\": {comparison},\n  \
\"measurements\": [\n  {entries}\n  ]\n}}\n",
        tol = schedule_bench::fmt_f32(EXISTING_TOLERANCE),
        rk = schedule_bench::fmt_f32(REFERENCE_KUHN),
        rl = schedule_bench::fmt_f32(REFERENCE_LEDUC),
        comparison_summary = comparison.summary,
        hs_wins = comparison.hs_wins,
        total_pairs = comparison.total,
        comparison = comparison.json,
    );

    let out_dir = std::path::Path::new("research/results");
    std::fs::create_dir_all(out_dir).expect("créer research/results");
    let out_path = out_dir.join("cfr_schedule_benchmark.json");
    std::fs::write(&out_path, &artifact).expect("écrire l'artefact");
    println!("artefact écrit : {}", out_path.display());

    for m in &measurements {
        println!("[{}/{}] {}", m.game, m.schedule, m.summary);
    }
}
