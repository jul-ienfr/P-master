//! Harnais de mesure de convergence des schedules CFR (spec `012`).
//!
//! Ce module est partagé par le test d'intégration
//! `tests/cfr_schedule_convergence.rs` et le point d'entrée opérateur
//! `examples/cfr_schedule_benchmark.rs` : les deux mesurent la **même** chose,
//! de la même façon, sur les mêmes jeux. Il est générique sur `T: Game` et
//! n'importe aucun jeu — chaque appelant fournit sa fabrique et sa lecture de
//! valeur de jeu, ce qui évite d'imposer une abstraction de jeu au crate.
//!
//! **Ce que ce harnais mesure.** L'exploitabilité atteinte à un nombre
//! d'itérations fixé, pour un schedule donné, dans *ce* codebase. Il ne rejoue
//! pas le postflop HU à range complète (~800 ms/spot) et ne prétend donc rien
//! sur le chemin de production : il tranche la question préalable « le schedule
//! change-t-il la convergence ici ».

use postflop_solver::{
    compute_exploitability, finalize, solve_step_with_schedule, DiscountSchedule, Game,
};

/// Valeur de jeu de Kuhn, vérifiée contre OpenSpiel (`tests/kuhn.rs`).
pub const REFERENCE_KUHN: f32 = -1.0 / 18.0;

/// Valeur de jeu de Leduc, vérifiée contre OpenSpiel (`tests/leduc.rs`).
pub const REFERENCE_LEDUC: f32 = -0.0856;

/// Tolérance des tests de convergence existants (`tests/kuhn.rs`, `tests/leduc.rs`).
pub const EXISTING_TOLERANCE: f32 = 1e-4;

/// Paliers d'itérations mesurés. Le palier haut correspond aux 10 000 itérations
/// des tests de convergence existants, pour que la valeur de jeu y soit
/// comparable à la référence déjà vérifiée.
pub const DEFAULT_TIERS: [u32; 4] = [10, 100, 1_000, 10_000];

/// Un point de mesure : itérations écoulées, exploitabilité, valeur de jeu.
#[derive(Debug, Clone, Copy)]
pub struct ConvergenceSample {
    pub iterations: u32,
    pub exploitability: f32,
    pub game_value: f32,
}

/// Mesure l'exploitabilité et la valeur de jeu à chaque palier, pour un schedule.
///
/// `make` construit un jeu **neuf** : `finalize` marque un jeu comme résolu et
/// interdit toute itération ultérieure, donc chaque palier repart d'un jeu
/// vierge et rejoue les itérations depuis zéro (les paliers sont cumulatifs).
///
/// `total_iterations` du schedule vaut le palier courant : c'est la lecture
/// naturelle de l'article (« exécuter `n` itérations avec le schedule pour ce
/// `n` »). `n` n'est donc pas constant entre paliers, et chaque ligne du rapport
/// est une exécution complète et reproductible en elle-même.
pub fn measure_schedule<T, F, G>(
    make: F,
    schedule: DiscountSchedule,
    tiers: &[u32],
    root_ev: G,
) -> Vec<ConvergenceSample>
where
    T: Game,
    F: Fn() -> T,
    G: Fn(&T) -> f32,
{
    let mut samples = Vec::with_capacity(tiers.len());
    for &tier in tiers {
        let mut game = make();
        for t in 0..tier {
            solve_step_with_schedule(&game, t, schedule, tier);
        }
        // L'exploitabilité se lit avant `finalize` (elle ne dépend pas des
        // valeurs stockées) ; la valeur de jeu exige la finalisation.
        let exploitability = compute_exploitability(&game);
        finalize(&mut game);
        samples.push(ConvergenceSample {
            iterations: tier,
            exploitability,
            game_value: root_ev(&game),
        });
    }
    samples
}

/// Date UTC du jour, au format `YYYY-MM-DD`, sans dépendance de calendrier.
///
/// Conversion jours-depuis-époque → date civile (algorithme de Howard Hinnant,
/// domaine public) : un artefact daté ne justifie pas une dépendance nouvelle.
pub fn today_utc() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let days = secs.div_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}")
}

/// Jours depuis l'époque → `(année, mois, jour)`. Hinnant, `civil_from_days`.
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Sérialise un flottant de façon lisible et stable (`-0.055556`, `1.23e-7`).
pub fn fmt_f32(value: f32) -> String {
    if value.is_finite() && (value == 0.0 || (value.abs() >= 1e-4 && value.abs() < 1e6)) {
        format!("{value:.6}")
    } else {
        format!("{value:.6e}")
    }
}

/// Sérialise un palier de mesure en objet JSON.
pub fn sample_json(sample: &ConvergenceSample) -> String {
    format!(
        "{{\"iterations\":{},\"exploitability\":{},\"game_value\":{}}}",
        sample.iterations,
        fmt_f32(sample.exploitability),
        fmt_f32(sample.game_value)
    )
}

/// Verdict honnête sur un schedule : ne dépasse jamais ce qui a été mesuré.
///
/// Renvoie `(reaches_reference, summary)` — le booléen alimente le test, le
/// texte alimente le rapport. La conclusion porte **uniquement** sur la
/// convergence observée dans ce codebase, jamais sur un gain transposé de
/// l'article (FR-012).
pub fn verdict(samples: &[ConvergenceSample], reference: f32, tolerance: f32) -> (bool, String) {
    let Some(last) = samples.last() else {
        return (false, "aucun échantillon mesuré".to_string());
    };
    let delta = (last.game_value - reference).abs();
    let reaches = delta < tolerance;
    let summary = format!(
        "à {} itérations, valeur de jeu {:.6} (référence {:.6}, écart {:.2e}, tolérance {:.0e}) — {}",
        last.iterations,
        last.game_value,
        reference,
        delta,
        tolerance,
        if reaches {
            "atteint la référence"
        } else {
            "N'ATTEINT PAS la référence"
        }
    );
    (reaches, summary)
}

/// Sérialise un rapport de mesure complet (artefact daté et versionné).
///
/// `claim` est le texte du verdict global ; il est **fourni par l'appelant** et
/// recopié tel quel, pour que l'artefact ne puisse pas affirmer plus que ce qui
/// a été mesuré.
#[allow(clippy::too_many_arguments)]
pub fn report_json(
    kind: &str,
    date: &str,
    game: &str,
    schedule: DiscountSchedule,
    tolerance: f32,
    reference: f32,
    tiers: &[u32],
    samples: &[ConvergenceSample],
    reaches_reference: bool,
    claim: &str,
) -> String {
    let samples_json = samples
        .iter()
        .map(sample_json)
        .collect::<Vec<_>>()
        .join(",");
    let tiers_json = tiers
        .iter()
        .map(|t| t.to_string())
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "{{\"kind\":\"{kind}\",\"date\":\"{date}\",\"game\":\"{game}\",\
\"schedule\":\"{}\",\"tolerance\":{},\"reference_value\":{},\
\"tiers\":[{tiers_json}],\"samples\":[{samples_json}],\
\"reaches_reference\":{reaches_reference},\"claim\":\"{claim}\"}}",
        schedule.as_str(),
        fmt_f32(tolerance),
        fmt_f32(reference),
    )
}
