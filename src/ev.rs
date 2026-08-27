//! Helper pur EV — conversions d'unités et rake-aware share.
//!
//! Source unique pour `ev_chips ↔ ev_bb ↔ ev_bb_per_100 ↔ $` et
//! `share = (pot - rake)/winners`. Factorise `multiway::payoffs`,
//! `multiway::static_payoffs` et `TreeConfig.rake_*` (C20).
//! Aucune dépendance CFR ; fonctions pures, testables unitairement.

/// Résumé EV d'un spot — une instance par `hero_ev` (range ou combo).
#[derive(Debug, Clone, PartialEq)]
pub struct EvSummary {
    pub ev_chips: f32,
    /// `ev_chips / bb` — `None` si `bb <= 0`.
    pub ev_bb: Option<f32>,
    /// WR instantané du spot : `ev_bb * 100` — `None` si `ev_bb` est `None`.
    pub ev_bb_per_100: Option<f32>,
    /// `ev_chips * (bb_dollars / bb)` si stake connu.
    pub ev_dollars: Option<f32>,
    /// Note quand `ev_bb`/`ev_dollars` est absent (fallback, stake inconnu).
    pub dollar_ev_note: Option<String>,
}

/// `ev_chips / bb` — `None` si `bb <= 0`.
#[inline]
pub fn ev_chips_to_bb(ev_chips: f32, bb: f32) -> Option<f32> {
    if bb > 0.0 && bb.is_finite() && ev_chips.is_finite() {
        Some(ev_chips / bb)
    } else {
        None
    }
}

/// `ev_bb * 100` — WR instantané du spot.
#[inline]
pub fn ev_bb_per_100(ev_bb: f32) -> f32 {
    ev_bb * 100.0
}

/// `ev_chips / bb * 100` — `None` si `bb <= 0`.
#[inline]
pub fn ev_bb_per_100_from_chips(ev_chips: f32, bb: f32) -> Option<f32> {
    ev_chips_to_bb(ev_chips, bb).map(ev_bb_per_100)
}

/// `equity * pot - cost` — EV showdown sans mise future (avant rake).
#[inline]
pub fn equity_ev(pot: f32, equity: f32, cost: f32) -> f32 {
    equity * pot - cost
}

/// `equity * (pot - rake) - cost` avec `rake = min(pot*rate, cap)`.
///
/// `winners` n'intervient pas ici (pot net) ; voir `rake_adjusted_share` pour le split.
#[inline]
pub fn equity_ev_rake_aware(pot: f32, equity: f32, cost: f32, rake_rate: f32, rake_cap: f32) -> f32 {
    let rake = compute_rake(pot as f64, rake_rate as f64, rake_cap as f64) as f32;
    equity * (pot - rake).max(0.0) - cost
}

/// Rake en chips : `min(pot*rate, cap)` avec garde `rate/cap <= 0`.
#[inline]
pub fn compute_rake(pot: f64, rake_rate: f64, rake_cap: f64) -> f64 {
    if rake_rate <= 0.0 {
        return 0.0;
    }
    let r = pot * rake_rate;
    if rake_cap > 0.0 { r.min(rake_cap) } else { r }
}

/// Pot net après rake : `(pot - rake).max(0)`.
#[inline]
pub fn pot_after_rake(pot: f64, rake_rate: f64, rake_cap: f64) -> f64 {
    (pot - compute_rake(pot, rake_rate, rake_cap)).max(0.0)
}

/// Share par winner : `(pot - rake) / winners` — factorise `multiway::payoffs` et `static_payoffs`.
///
/// `winners` doit être `>= 1` ; retourne 0 si `winners == 0`.
// TODO factorisation: factorise `multiway::Solver::payoffs` (~l615) + `multiway::static_payoffs` (~l1021)
//   et `TreeConfig.rake_*` (`action_tree.rs:95` + `game/evaluation.rs:24` `min(pot*rate,cap)`) via `ev::compute_rake` /
//   `ev::rake_adjusted_share` — ne refactor pas encore si hors scope (garder 2 call sites actuels en place).
#[inline]
pub fn rake_adjusted_share(pot: f64, rake_rate: f64, rake_cap: f64, winners: usize) -> f64 {
    if winners == 0 {
        return 0.0;
    }
    pot_after_rake(pot, rake_rate, rake_cap) / winners as f64
}

/// `$EV` optionnel — `ev_chips * (bb_dollars / bb)` si les deux sont finis et `bb > 0`.
#[inline]
pub fn dollar_ev(ev_chips: f32, bb: f32, bb_dollars: f32) -> Option<f32> {
    if bb > 0.0 && bb.is_finite() && bb_dollars.is_finite() && ev_chips.is_finite() {
        Some(ev_chips * (bb_dollars / bb))
    } else {
        None
    }
}

/// Construit un `EvSummary` depuis `ev_chips` + `bb` + stake optionnel.
///
/// `bb_fallback_note` est recopiée dans `dollar_ev_note` quand `bb` vient du fallback
/// `effective_stack/100` (pour traçabilité).
pub fn ev_summary(
    ev_chips: f32,
    bb: Option<f32>,
    bb_dollars: Option<f32>,
    bb_fallback_note: Option<String>,
) -> EvSummary {
    let ev_bb = bb.and_then(|b| ev_chips_to_bb(ev_chips, b));
    let ev_bb_per_100 = ev_bb.map(ev_bb_per_100);
    let ev_dollars = match (bb, bb_dollars) {
        (Some(b), Some(d)) => dollar_ev(ev_chips, b, d),
        _ => None,
    };
    let dollar_ev_note = bb_fallback_note.or_else(|| {
        if ev_bb.is_none() {
            Some("bb inconnu — ev_bb/ev_dollars indisponibles".to_string())
        } else if ev_dollars.is_none() && bb_dollars.is_none() {
            None
        } else {
            None
        }
    });
    // Ne pas polluer la note si tout est renseigné
    let dollar_ev_note = if ev_bb.is_some() && dollar_ev_note.as_deref() == Some("bb inconnu — ev_bb/ev_dollars indisponibles") {
        None
    } else {
        dollar_ev_note
    };
    EvSummary { ev_chips, ev_bb, ev_bb_per_100, ev_dollars, dollar_ev_note }
}

/// Dérive `bb` depuis `effective_stack` (chips) — convention 100bb deep.
/// Retourne `(bb, is_fallback)` pour `tracing::warn` côté appelant.
#[inline]
pub fn bb_from_effective_stack(effective_stack: f32) -> (f32, bool) {
    if effective_stack.is_finite() && effective_stack > 0.0 {
        (effective_stack / 100.0, true)
    } else {
        (0.0, true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chips_to_bb_basic() {
        assert!((ev_chips_to_bb(100.0, 2.0).unwrap() - 50.0).abs() < 1e-6);
        assert!(ev_chips_to_bb(10.0, 0.0).is_none());
        assert!(ev_chips_to_bb(10.0, -1.0).is_none());
    }

    #[test]
    fn bb_per_100_basic() {
        assert!((ev_bb_per_100(0.05) - 5.0).abs() < 1e-6);
        assert!((ev_bb_per_100_from_chips(10.0, 2.0).unwrap() - 500.0).abs() < 1e-6);
    }

    #[test]
    fn equity_ev_basic() {
        // pot 100bb, equity 0.55, cost 50bb → +5bb (esperance.md Ex.1)
        assert!((equity_ev(100.0, 0.55, 50.0) - 5.0).abs() < 1e-6);
    }

    #[test]
    fn rake_cap_not_hit() {
        // pot 30, rate 5%, cap 3 → rake 1.5, pot_after 28.5
        assert!((compute_rake(30.0, 0.05, 3.0) - 1.5).abs() < 1e-9);
        assert!((pot_after_rake(30.0, 0.05, 3.0) - 28.5).abs() < 1e-9);
        assert!((rake_adjusted_share(30.0, 0.05, 3.0, 1) - 28.5).abs() < 1e-9);
        // 3-way split
        assert!((rake_adjusted_share(30.0, 0.05, 3.0, 3) - 9.5).abs() < 1e-9);
    }

    #[test]
    fn rake_cap_hit() {
        // pot 100, rate 5%, cap 3 → rake 3 (cap touché), pot_after 97 (esperance.md Ex.2)
        assert!((compute_rake(100.0, 0.05, 3.0) - 3.0).abs() < 1e-9);
        assert!((pot_after_rake(100.0, 0.05, 3.0) - 97.0).abs() < 1e-9);
        assert!((rake_adjusted_share(100.0, 0.05, 3.0, 1) - 97.0).abs() < 1e-9);
        // pot 200 cap toujours 3
        assert!((compute_rake(200.0, 0.05, 3.0) - 3.0).abs() < 1e-9);
    }

    #[test]
    fn rake_zero_cases() {
        assert_eq!(compute_rake(100.0, 0.0, 3.0), 0.0);
        assert_eq!(compute_rake(100.0, 0.05, 0.0), 5.0); // cap 0 = pas de cap
        assert_eq!(rake_adjusted_share(100.0, 0.05, 3.0, 0), 0.0);
    }

    #[test]
    fn equity_ev_rake_aware_matches_manual() {
        // pot 100, equity 0.6, cost 20, rake 5% cap 3 → net 97 → EV 0.6*97-20=38.2
        let ev = equity_ev_rake_aware(100.0, 0.6, 20.0, 0.05, 3.0);
        assert!((ev - 38.2).abs() < 1e-4);
    }

    #[test]
    fn ev_summary_with_and_without_bb() {
        let s = ev_summary(10.0, Some(2.0), None, None);
        assert!((s.ev_bb.unwrap() - 5.0).abs() < 1e-6);
        assert!((s.ev_bb_per_100.unwrap() - 500.0).abs() < 1e-6);
        assert!(s.ev_dollars.is_none());

        let s2 = ev_summary(10.0, None, None, None);
        assert!(s2.ev_bb.is_none());
        assert!(s2.ev_bb_per_100.is_none());
    }

    #[test]
    fn dollar_ev_basic() {
        // ev 10 chips, bb 2 chips, bb_dollars 0.02$ (NL2) → 0.10$
        assert!((dollar_ev(10.0, 2.0, 0.02).unwrap() - 0.10).abs() < 1e-6);
        assert!(dollar_ev(10.0, 0.0, 0.02).is_none());
    }
}
