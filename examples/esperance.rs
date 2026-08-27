//! Exemple `esperance` — hero_ev, ev_bb, rake, equity EV.
//!
//! Démonstration standalone des conversions `ev_chips ↔ ev_bb ↔ ev_bb_per_100`
//! et du helper `rake` documenté dans `docs/esperance.md`.
//!
//! ```bash
//! cargo run --example esperance
//! ```

use postflop_solver::ev::{
    compute_rake, equity_ev, equity_ev_rake_aware, ev_chips_to_bb, ev_summary, pot_after_rake,
    rake_adjusted_share,
};

fn main() {
    // ── Ex.1 EV de base (équité·pot − cost) — esperance.md §5 ──
    let pot = 100.0f32;
    let equity = 0.55f32;
    let cost = 50.0f32;
    let ev = equity_ev(pot, equity, cost);
    println!("Ex.1  EV de base : equity {equity:.2} × pot {pot:.0} − cost {cost:.0} = {ev:.2} chips");
    let bb = 2.0f32; // NL2: bb = 2 chips
    println!("      ev_bb = {ev:.2}/{bb:.0} = {:.2} bb", ev_chips_to_bb(ev, bb).unwrap());
    let s = ev_summary(ev, Some(bb), Some(0.02), None);
    println!("      ev_bb_per_100 = {:.1}  ev_dollars = {:?}", s.ev_bb_per_100.unwrap(), s.ev_dollars);

    // ── Ex.2 Rake 5% cap $3 — esperance.md §5 + C20 ──
    let pot_f64 = 100.0f64;
    let rake = compute_rake(pot_f64, 0.05, 3.0);
    let net = pot_after_rake(pot_f64, 0.05, 3.0);
    println!("\nEx.2a Rake 5% cap $3 sur pot {pot_f64:.0} : rake={rake:.1}  net={net:.1}  share={:.1}", rake_adjusted_share(pot_f64, 0.05, 3.0, 1));
    // EV rake-aware vs brut
    let ev_rake = equity_ev_rake_aware(100.0, 0.6, 20.0, 0.05, 3.0);
    println!("      equity 0.6  pot 100  cost 20  rake cap 3 → EV rake-aware = {ev_rake:.1} (= 0.6×97−20)");
    // Pot 30 : cap non touché
    let pot30 = 30.0f64;
    println!("Ex.2b Pot {pot30:.0} : rake={:.1}  net={:.1}  share 3-way={:.1}", compute_rake(pot30, 0.05, 3.0), pot_after_rake(pot30, 0.05, 3.0), rake_adjusted_share(pot30, 0.05, 3.0, 3));

    // ── Ex.3 PKO bounty 0.3 BI — esperance.md §5 + C23 ──
    let bounty_bi = 0.3f32;
    let p_elim = 0.2f32;
    let bounty_ev_bi = p_elim * bounty_bi;
    let chip_ev_bb = 4.0f32;
    let dollar_ev_bi = chip_ev_bb / 100.0 + bounty_ev_bi; // 1 BI = 100bb
    println!("\nEx.3  PKO : ChipEV {chip_ev_bb:.0}bb (= {:.2} BI) + BountyEV {p_elim:.1}×{bounty_bi:.1}={bounty_ev_bi:.2} BI → $EV ≈ {dollar_ev_bi:.2} BI ({:.0}bb equiv.)", chip_ev_bb / 100.0, dollar_ev_bi * 100.0);

    // ── Résumé unités — esperance.md §3 ──
    println!("\nUnités : ev_chips (solver) → ev_bb (= /bb) → ev_bb_per_100 (= ×100) → ev_dollars (= ×$/bb) → $EV (= ChipEV+BountyEV)");
}
