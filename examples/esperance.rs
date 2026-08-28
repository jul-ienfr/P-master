//! esperance — 3 spots chiffres ev_chips->ev_bb->bb/100->$EV via postflop_solver::ev. + reference docs/esperance.md §7
//! Conversions docs/esperance.md §3-5 + README § solver EV ; rake C20, PKO C23 ; regimes §7 volume->€/mois.
//! cargo run --example esperance
//! cargo run --example esperance -- --regime 6h6j
use postflop_solver::ev::{compute_rake, equity_ev, ev_summary, pot_after_rake};

fn main() {
    // ── Spot 1 — cash NL2 : pot 100 eq 0.55 cost 50 → EV +5 chips ──
    // EV = equity*pot - cost (esperance.md Ex.1) puis ev_summary décline
    // ev_chips → ev_bb (/bb) → ev_bb_per_100 (×100) → ev_dollars (×$/bb).
    let ev = equity_ev(100.0, 0.55, 50.0); // +5 chips
    let bb = 2.0; // NL2 1bb = 2 chips
    let bb_dollars = 0.02; // 1bb = $0.02  (config ev_bb_dollars)
    let s = ev_summary(ev, Some(bb), Some(bb_dollars), None);
    println!(
        "S1 ev_chips={:.1} ev_bb={:.1} bb/100={:.0} $EV={:.2}",
        s.ev_chips, s.ev_bb.unwrap(), s.ev_bb_per_100.unwrap(), s.ev_dollars.unwrap()
    );
    // ── Spot 2 — rake 5% cap $3 + PKO $EV=ChipEV+BountyEV ──
    // rake=min(pot*rate,cap) net=pot-rake (C20) ; bounty 0.3 BI P(elim)=0.2 (C23).
    let pot = 100.0;
    let rake = compute_rake(pot, 0.05, 3.0); // 3.0 cap touché
    let net = pot_after_rake(pot, 0.05, 3.0); // 97.0
    let ev_rake = 0.6 * net as f32 - 20.0; // eq 0.6 cost 20 → 38.2 net
    let t = ev_summary(ev_rake, Some(bb), Some(bb_dollars), None);
    let bounty_ev_bi = 0.2 * 0.3; // 0.06 BI
    println!(
        "S2 rake={:.0} net={:.0} ev_chips={:.1} ev_bb={:.1} $EV={:.2} (+BountyEV={:.2} BI)",
        rake, net, t.ev_chips, t.ev_bb.unwrap(), t.ev_dollars.unwrap(), bounty_ev_bi
    );
    println!("units: ev_chips → ev_bb → ev_bb_per_100 → ev_dollars → $EV (docs/esperance.md §3)");

    // ── Spot 3 — Regimes de volume -> €/mois — NL10 ref bb=0.10€ WR7 median ──
    // Formule: gain = WR * (N/100) * $/bb  ;  P(profit)=Φ(WR·√(N/100)/σ) probabilites.md §2
    // NL10: bb=0.10€, $/bb=0.10, WR 7 bb/100 median micro (σ~90). Heures = h/j * j/sem * 4 sem.
    let args: Vec<String> = std::env::args().collect();
    let mut regime_filter: Option<String> = None;
    for (i, a) in args.iter().enumerate() {
        if a == "--regime" {
            if let Some(v) = args.get(i + 1) {
                regime_filter = Some(v.clone());
            }
        } else if let Some(v) = a.strip_prefix("--regime=") {
            regime_filter = Some(v.to_string());
        }
    }
    let filter_norm = regime_filter.as_deref().map(|s| {
        s.to_lowercase()
            .replace('×', "x")
            .replace(' ', "")
            .replace('-', "")
    });

    let should_show = |tag: &str| -> bool {
        match &filter_norm {
            None => true,
            Some(f) => {
                // f attendu: "4h5j" / "4hx5j" / "6h6j" / "12h6j" etc.
                // Normalise tag de la même façon pour comparaison contient.
                let t = tag.to_lowercase().replace('×', "x").replace(' ', "");
                // match exact ou contient le marqueur court
                f == &t || t.contains(f.as_str()) || f.contains(t.as_str())
                    // fallback heuristique sur sous-chaîne discriminante
                    || (f.contains("12h") && tag.contains("12h"))
                    || (f.contains("6h") && !f.contains("12h") && tag.contains("6h") && !tag.contains("12h"))
                    || (f.contains("4h") && tag.contains("4h"))
            }
        }
    };

    // Constantes NL10 référence
    let wr_med: f32 = 7.0; // bb/100 median micro
    let wr_tilt: f32 = 5.0; // degrade -30% §5 (tilt / fatigue volume)
    let euro_per_bb: f32 = 0.10; // NL10 bb=0.10€

    println!("S3 Regimes de volume -> €/mois — NL10 ref bb=0.10€ WR7 median ($/bb=0.10) gain=WR*(N/100)*€/bb");

    // Regime A: 4h×5j → 48k mains/mois, 80h/mois, P95%
    if should_show("4hx5j") {
        let hands: f32 = 48_000.0;
        let hours: f32 = 80.0; // 4h*5j*4sem
        let units = hands / 100.0; // 480
        let gain = wr_med * units * euro_per_bb; // 7*480*0.10 = 336
        let eur_h = gain / hours; // 4.20
        println!(
            "  4h×5j  48k mains ( {:>3.0}h/mois) -> gain = {:.0}* {:.0}* {:.2} = {:.0}€ (P95%)  {:.2}€/h",
            hours, wr_med, units, euro_per_bb, gain, eur_h
        );
    }
    // Regime B: 6h×6j → 86k mains/mois, 144h/mois, P99%
    if should_show("6hx6j") {
        let hands: f32 = 86_000.0;
        let hours: f32 = 144.0; // 6h*6j*4sem
        let units = hands / 100.0; // 860
        let gain = wr_med * units * euro_per_bb; // 7*860*0.10 = 602
        let eur_h = gain / hours; // 4.18
        println!(
            "  6h×6j  86k mains ({:>3.0}h/mois) -> gain = {:.0}* {:.0}* {:.2} = {:.0}€ (P99%)  {:.2}€/h",
            hours, wr_med, units, euro_per_bb, gain, eur_h
        );
    }
    // Regime C: 12h×6j → 173k mains/mois, 288h/mois, theorique WR7 puis degrade WR5 (-30% §5)
    if should_show("12hx6j") {
        let hands: f32 = 173_000.0;
        let hours: f32 = 288.0; // 12h*6j*4sem
        let units = hands / 100.0; // 1730
        let gain_theorique = wr_med * units * euro_per_bb; // 7*1730*0.10 = 1211
        let gain_degrade = wr_tilt * units * euro_per_bb; // 5*1730*0.10 = 865
        let eur_h_theorique = gain_theorique / hours; // 4.20
        let eur_h_degrade = gain_degrade / hours; // 3.00
        println!(
            "  12h×6j 173k mains ({:>3.0}h/mois) -> theorique WR7: {:.0}* {:.0}* {:.2} = {:.0}€ ({:.2}€/h) mais degrade WR5 -> {:.0}* {:.0}* {:.2} = {:.0}€ si tilt -30% §5 ({:.2}€/h) chute {:.2}->{:.2}€/h",
            hours, wr_med, units, euro_per_bb, gain_theorique, eur_h_theorique, wr_tilt, units, euro_per_bb, gain_degrade, eur_h_degrade, eur_h_theorique, eur_h_degrade
        );
    }

    if let Some(f) = &filter_norm {
        // si filtre inconnu, lister les valeurs valides
        let known = ["4hx5j", "6hx6j", "12hx6j"];
        let matched = known.iter().any(|k| should_show(k));
        if !matched {
            eprintln!("--regime inconnu \"{}\" — valeurs: 4h5j, 6h6j, 12h6j (defaut: affiche les 3)", f);
        }
    }
}
