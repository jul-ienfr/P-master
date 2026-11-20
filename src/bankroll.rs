//! Moteur de bankroll et de risque — fonctions pures, déterministes (spec 004).
//!
//! Source de vérité des formules : `docs/probabilites.md` §6 (RoR) et §2–§3
//! (P(profit)), `docs/ordre-conseille.md` (seuils 40 BI cash / 100–200 BI MTT).
//!
//! **Unités cohérentes obligatoires** (l'erreur historique du §6 venait d'un
//! mélange bb ↔ buy-ins) :
//!
//! - cash : `win_rate_bb_per_100` en bb/100, `sigma_bb_per_100` en bb/100,
//!   `roll_buyins` en buy-ins (1 BI = 100 bb) ;
//! - MTT : `roi` en fraction de BI par tournoi, `sigma_bi` en BI.
//!
//! `RoR = exp(−2·edge·roll / variance)` : `edge` et `roll` en buy-ins,
//! `variance` en BI² par 100 mains (cash) ou BI² par tournoi (MTT). La
//! conversion cash se fait ici (`edge_BI = WR/100`, `var_BI = (σ/100)²`), donc
//! l'appelant reste en unités naturelles bb/100.
//!
//! Aucune dépendance CFR, aucun état : chaque fonction est testable contre la
//! forme fermée.

/// Format de jeu — détermine la conversion d'unités edge/variance.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GameFormat {
    /// Cash game : edge en bb/100, variance en (bb/100)².
    Cash,
    /// Tournoi : edge = ROI (fraction de BI), variance en BI².
    Tournament,
}

/// Formule gambler's ruin / Kelly : `exp(−2·edge·roll / variance)`.
///
/// Renvoie `None` si les entrées sont dégénérées (variance ≤ 0, roll < 0,
/// valeurs non finies) : un RoR sans edge positif ni variance n'a pas de sens
/// et doit être signalé, jamais inventé.
#[inline]
pub fn risk_of_ruin(edge_bi: f32, variance_bi2: f32, roll_buyins: f32) -> Option<f32> {
    if !edge_bi.is_finite() || !variance_bi2.is_finite() || !roll_buyins.is_finite() {
        return None;
    }
    if variance_bi2 <= 0.0 || roll_buyins < 0.0 {
        return None;
    }
    if edge_bi <= 0.0 {
        // Edge nul ou négatif : la ruine est certaine à horizon infini.
        return Some(1.0);
    }
    let exponent = -2.0 * edge_bi * roll_buyins / variance_bi2;
    // exp d'un très grand négatif → 0 ; on borne pour éviter l'underflow silencieux.
    Some(exponent.exp().clamp(0.0, 1.0))
}

/// RoR cash depuis les unités naturelles bb/100.
///
/// `edge_BI = WR/100`, `var_BI = (σ/100)²` (§6).
#[inline]
pub fn risk_of_ruin_cash(
    win_rate_bb_per_100: f32,
    sigma_bb_per_100: f32,
    roll_buyins: f32,
) -> Option<f32> {
    if sigma_bb_per_100 <= 0.0 {
        return None;
    }
    let edge_bi = win_rate_bb_per_100 / 100.0;
    let variance_bi2 = (sigma_bb_per_100 / 100.0).powi(2);
    risk_of_ruin(edge_bi, variance_bi2, roll_buyins)
}

/// RoR tournoi : `roi` en fraction de BI, `sigma_bi` en BI.
#[inline]
pub fn risk_of_ruin_mtt(roi: f32, sigma_bi: f32, roll_buyins: f32) -> Option<f32> {
    if sigma_bi <= 0.0 {
        return None;
    }
    risk_of_ruin(roi, sigma_bi * sigma_bi, roll_buyins)
}

/// Bankroll minimale (en buy-ins) pour un RoR cible — inverse de [`risk_of_ruin`].
///
/// `roll = −ln(RoR)·variance / (2·edge)`. Sert à justifier un seuil (ex.
/// « 40 BI » pour RoR < 0,1 %) plutôt qu'à le poser arbitrairement.
#[inline]
pub fn bankroll_for_target_ror(edge_bi: f32, variance_bi2: f32, target_ror: f32) -> Option<f32> {
    if !edge_bi.is_finite()
        || !variance_bi2.is_finite()
        || !target_ror.is_finite()
        || edge_bi <= 0.0
        || variance_bi2 <= 0.0
        || target_ror <= 0.0
        || target_ror >= 1.0
    {
        return None;
    }
    Some(-target_ror.ln() * variance_bi2 / (2.0 * edge_bi))
}

/// Erreur maximale de l'approximation `erf` utilisée ici.
const ERF_ABS_ERROR: f64 = 1.5e-7;

/// `erf` — approximation Abramowitz & Stegun 7.1.26 (|erreur| ≤ 1,5·10⁻⁷).
#[inline]
fn erf(x: f64) -> f64 {
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let x = x.abs();
    let t = 1.0 / (1.0 + 0.3275911 * x);
    let poly =
        ((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592;
    sign * (1.0 - poly * t * (-x * x).exp())
}

/// CDF de la loi normale centrée réduite `Φ`.
#[inline]
pub fn norm_cdf(x: f64) -> f64 {
    0.5 * (1.0 + erf(x / std::f64::consts::SQRT_2))
}

/// P(profit) après `hands` mains — `Φ(WR·√(N/100) / σ)` (§2).
///
/// Renvoie `None` si `σ ≤ 0` ou `hands < 0` (pas de probabilité définie).
#[inline]
pub fn probability_of_profit_cash(
    win_rate_bb_per_100: f32,
    sigma_bb_per_100: f32,
    hands: u64,
) -> Option<f64> {
    if sigma_bb_per_100 <= 0.0 || !win_rate_bb_per_100.is_finite() {
        return None;
    }
    let blocks = (hands as f64 / 100.0).sqrt();
    let z = win_rate_bb_per_100 as f64 * blocks / sigma_bb_per_100 as f64;
    Some(norm_cdf(z))
}

/// P(profit) tournoi après `n_tournaments` — `Φ(ROI·√n / σ_BI)`.
#[inline]
pub fn probability_of_profit_mtt(roi: f32, sigma_bi: f32, n_tournaments: u64) -> Option<f64> {
    if sigma_bi <= 0.0 || !roi.is_finite() {
        return None;
    }
    let z = roi as f64 * (n_tournaments as f64).sqrt() / sigma_bi as f64;
    Some(norm_cdf(z))
}

/// Fraction de Kelly optimale : `edge / variance` (croissance logarithmique
/// maximale). Bornée à 1 (jamais plus que la bankroll entière).
#[inline]
pub fn kelly_fraction(edge_bi: f32, variance_bi2: f32) -> Option<f32> {
    if !edge_bi.is_finite() || !variance_bi2.is_finite() || variance_bi2 <= 0.0 || edge_bi <= 0.0 {
        return None;
    }
    Some((edge_bi / variance_bi2).clamp(0.0, 1.0))
}

/// Règle de move-up/move-down pour un format.
///
/// `up_buyins` : bankroll (en BI) au-dessus de laquelle on monte de limite ;
/// `down_buyins` : en-dessous de laquelle on redescend. `down < up` pour
/// éviter l'oscillation sur le seuil (hystérésis).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct MoveRule {
    pub up_buyins: f32,
    pub down_buyins: f32,
}

impl MoveRule {
    /// Règle valide : `down_buyins < up_buyins`, valeurs finies et positives.
    pub fn is_valid(&self) -> bool {
        self.down_buyins.is_finite()
            && self.up_buyins.is_finite()
            && self.down_buyins > 0.0
            && self.up_buyins > self.down_buyins
    }
}

/// Décision de changement de limite — journalisable telle quelle.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MoveDecision {
    /// Rester à la limite courante.
    Stay,
    /// Monter d'un cran (bankroll au-dessus du seuil haut).
    MoveUp,
    /// Redescendre d'un cran (bankroll sous le seuil bas).
    MoveDown,
}

/// Applique la règle d'hystérésis : `MoveUp` seulement si `roll ≥ up_buyins`,
/// `MoveDown` seulement si `roll < down_buyins`, sinon `Stay`.
///
/// `at_top_limit` / `at_bottom_limit` empêchent de sortir de l'échelle de
/// limites : au sommet on ne monte plus, au plancher on ne descend plus.
pub fn decide_move(
    roll_buyins: f32,
    rule: &MoveRule,
    at_top_limit: bool,
    at_bottom_limit: bool,
) -> MoveDecision {
    if !rule.is_valid() || !roll_buyins.is_finite() {
        return MoveDecision::Stay;
    }
    if roll_buyins >= rule.up_buyins && !at_top_limit {
        MoveDecision::MoveUp
    } else if roll_buyins < rule.down_buyins && !at_bottom_limit {
        MoveDecision::MoveDown
    } else {
        MoveDecision::Stay
    }
}

/// Limites dures d'une session — reproduit et étend `SessionManager` (F-07).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SessionLimits {
    pub max_hours: f32,
    pub stop_loss_buyins: f32,
    pub stop_win_buyins: f32,
    /// Plafond de mains par jour (0 = pas de plafond).
    pub max_hands_per_day: u64,
}

impl Default for SessionLimits {
    fn default() -> Self {
        // Valeurs historiques de `session_manager.py` (4 h, −3 BI, +10 BI).
        Self {
            max_hours: 4.0,
            stop_loss_buyins: 3.0,
            stop_win_buyins: 10.0,
            max_hands_per_day: 0,
        }
    }
}

/// Motif d'arrêt d'une session — `None` quand la session peut continuer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StopReason {
    MaxDuration,
    StopLoss,
    StopWin,
    DailyHands,
}

/// Verdict de session : soit on continue, soit on s'arrête avec un motif.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SessionVerdict {
    Continue,
    Stop(StopReason),
}

/// Évalue les limites dures d'une session. Ordre déterministe :
/// durée → plafond journalier → stop-loss → stop-win.
pub fn session_verdict(
    limits: &SessionLimits,
    hours_played: f32,
    hands_today: u64,
    profit_loss_buyins: f32,
) -> SessionVerdict {
    if limits.max_hours > 0.0 && hours_played >= limits.max_hours {
        return SessionVerdict::Stop(StopReason::MaxDuration);
    }
    if limits.max_hands_per_day > 0 && hands_today >= limits.max_hands_per_day {
        return SessionVerdict::Stop(StopReason::DailyHands);
    }
    if limits.stop_loss_buyins > 0.0 && profit_loss_buyins <= -limits.stop_loss_buyins {
        return SessionVerdict::Stop(StopReason::StopLoss);
    }
    if limits.stop_win_buyins > 0.0 && profit_loss_buyins >= limits.stop_win_buyins {
        return SessionVerdict::Stop(StopReason::StopWin);
    }
    SessionVerdict::Continue
}

/// Avertissement de risque dérivé d'un RoR : seuils documentés
/// (`docs/probabilites.md` §6 — viser < 1 % MTT, < 5 % cash).
pub fn risk_band(ror: f32) -> RiskBand {
    if ror < 0.001 {
        RiskBand::Safe
    } else if ror < 0.05 {
        RiskBand::Acceptable
    } else if ror < 0.20 {
        RiskBand::Elevated
    } else {
        RiskBand::Excessive
    }
}

/// Bande de risque qualitative.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RiskBand {
    /// < 0,1 %.
    Safe,
    /// < 5 % — cible cash.
    Acceptable,
    /// < 20 %.
    Elevated,
    /// ≥ 20 %.
    Excessive,
}

/// Résumé d'un plan de bankroll pour un format — un enregistrement par limite,
/// journalisable pour l'audit.
#[derive(Debug, Clone, PartialEq)]
pub struct BankrollAssessment {
    pub format: GameFormat,
    pub roll_buyins: f32,
    pub ror: Option<f32>,
    pub risk_band: Option<RiskBand>,
    pub kelly: Option<f32>,
    /// Bankroll minimale pour ramener le RoR sous 1 %.
    pub bankroll_for_1pct_ror: Option<f32>,
}

/// Évalue un plan : RoR, bande, Kelly et bankroll cible pour RoR < 1 %.
///
/// `edge`/`variance` sont attendus dans les unités du format (voir
/// [`GameFormat`]) ; pour le cash, utiliser [`assess_cash`].
pub fn assess(
    format: GameFormat,
    edge_bi: f32,
    variance_bi2: f32,
    roll_buyins: f32,
) -> BankrollAssessment {
    let ror = risk_of_ruin(edge_bi, variance_bi2, roll_buyins);
    BankrollAssessment {
        format,
        roll_buyins,
        ror,
        risk_band: ror.map(risk_band),
        kelly: kelly_fraction(edge_bi, variance_bi2),
        bankroll_for_1pct_ror: bankroll_for_target_ror(edge_bi, variance_bi2, 0.01),
    }
}

/// Évalue un plan cash depuis les unités naturelles bb/100.
pub fn assess_cash(
    win_rate_bb_per_100: f32,
    sigma_bb_per_100: f32,
    roll_buyins: f32,
) -> BankrollAssessment {
    let edge_bi = win_rate_bb_per_100 / 100.0;
    let variance_bi2 = (sigma_bb_per_100 / 100.0).powi(2);
    assess(GameFormat::Cash, edge_bi, variance_bi2, roll_buyins)
}

/// Erreur d'approximation documentée de [`norm_cdf`], pour les tests.
pub const NORM_CDF_ABS_ERROR: f64 = ERF_ABS_ERROR / 2.0;

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f32, b: f32, tol: f32) -> bool {
        (a - b).abs() <= tol
    }

    #[test]
    fn norm_cdf_matches_known_points() {
        assert!(close(norm_cdf(0.0) as f32, 0.5, 1e-6));
        assert!(close(norm_cdf(1.0) as f32, 0.841_344_7, 1e-5));
        assert!(close(norm_cdf(-1.0) as f32, 0.158_655_3, 1e-5));
        assert!(close(norm_cdf(1.96) as f32, 0.975_002, 1e-5));
        assert!(close(norm_cdf(-1.96) as f32, 0.024_998, 1e-5));
        assert!((norm_cdf(-8.0)) < 1e-6);
        assert!((norm_cdf(8.0) - 1.0).abs() < 1e-6);
    }

    #[test]
    fn norm_cdf_symmetric() {
        for x in [0.1f64, 0.5, 1.0, 2.0, 3.5] {
            let sum = norm_cdf(x) + norm_cdf(-x);
            assert!((sum - 1.0).abs() < 1e-7, "x={x} sum={sum}");
        }
    }

    #[test]
    fn ror_cash_matches_doc_table_6max_wr7_40bi() {
        // docs/probabilites.md §6.2 : 6-max WR 7, σ 90, roll 40 BI → 0,10 %.
        let ror = risk_of_ruin_cash(7.0, 90.0, 40.0).unwrap();
        assert!(close(ror, 0.001, 5e-5), "ror={ror}");
        assert_eq!(risk_band(ror), RiskBand::Safe);
    }

    #[test]
    fn ror_cash_matches_doc_table_6max_wr5_20bi() {
        // §6.2 : WR 5, σ 90, roll 20 BI → 8,49 %.
        let ror = risk_of_ruin_cash(5.0, 90.0, 20.0).unwrap();
        assert!(close(ror, 0.0849, 1e-3), "ror={ror}");
    }

    #[test]
    fn ror_cash_matches_doc_table_hu_wr5_20bi() {
        // §6.1 : HU WR 5, σ 70, roll 20 BI → 1,69 %.
        let ror = risk_of_ruin_cash(5.0, 70.0, 20.0).unwrap();
        assert!(close(ror, 0.0169, 1e-3), "ror={ror}");
    }

    #[test]
    fn ror_mtt_matches_doc_table_roi15_sigma19_50bi() {
        // §6.3 : MTT ROI 15 %, σ 1,9 BI, roll 50 BI → 1,57 %.
        let ror = risk_of_ruin_mtt(0.15, 1.9, 50.0).unwrap();
        assert!(close(ror, 0.0157, 1e-3), "ror={ror}");
    }

    #[test]
    fn ror_degenerate_inputs_return_none() {
        assert_eq!(risk_of_ruin_cash(7.0, 0.0, 40.0), None);
        assert_eq!(risk_of_ruin(0.07, 0.0, 40.0), None);
        assert_eq!(risk_of_ruin(0.07, 0.81, -1.0), None);
        assert_eq!(risk_of_ruin(f32::NAN, 0.81, 40.0), None);
        // Edge nul/negatif : ruine certaine, pas None.
        assert_eq!(risk_of_ruin(0.0, 0.81, 40.0), Some(1.0));
        assert_eq!(risk_of_ruin(-0.05, 0.81, 40.0), Some(1.0));
    }

    #[test]
    fn ror_is_monotone_in_roll_and_edge() {
        let a = risk_of_ruin_cash(7.0, 90.0, 20.0).unwrap();
        let b = risk_of_ruin_cash(7.0, 90.0, 40.0).unwrap();
        let c = risk_of_ruin_cash(7.0, 90.0, 100.0).unwrap();
        assert!(a > b && b > c, "roll ↑ doit réduire le RoR : {a} {b} {c}");
        let lo = risk_of_ruin_cash(3.0, 90.0, 40.0).unwrap();
        let hi = risk_of_ruin_cash(7.0, 90.0, 40.0).unwrap();
        assert!(lo > hi, "edge ↑ doit réduire le RoR : {lo} {hi}");
    }

    #[test]
    fn bankroll_for_target_ror_is_inverse_of_risk_of_ruin() {
        let target = 0.01f32;
        let roll = bankroll_for_target_ror(0.07, 0.81, target).unwrap();
        let back = risk_of_ruin(0.07, 0.81, roll).unwrap();
        assert!(close(back, target, 1e-5), "aller-retour {back} != {target}");
        // Le seuil 40 BI documenté doit ramener le RoR 6-max sous 1 %.
        assert!(roll < 40.0, "roll cible 1% = {roll} BI");
    }

    #[test]
    fn probability_of_profit_matches_doc_table_50k() {
        // §2.2 : 6-max WR 7, σ 90, 50k mains → 96 %.
        let p = probability_of_profit_cash(7.0, 90.0, 50_000).unwrap();
        assert!((p - 0.96).abs() < 0.01, "p={p}");
        // §2.2 : 10k mains → 78 %.
        let p10k = probability_of_profit_cash(7.0, 90.0, 10_000).unwrap();
        assert!((p10k - 0.78).abs() < 0.02, "p10k={p10k}");
        // HU §2.1 : WR 5, σ 70, 10k → 76 %.
        let phu = probability_of_profit_cash(5.0, 70.0, 10_000).unwrap();
        assert!((phu - 0.76).abs() < 0.02, "phu={phu}");
    }

    #[test]
    fn probability_of_profit_grows_with_hands() {
        let p1 = probability_of_profit_cash(7.0, 90.0, 1_000).unwrap();
        let p2 = probability_of_profit_cash(7.0, 90.0, 50_000).unwrap();
        assert!(p2 > p1, "{p1} -> {p2}");
        assert_eq!(probability_of_profit_cash(7.0, 0.0, 100), None);
    }

    #[test]
    fn kelly_fraction_basic() {
        let f = kelly_fraction(0.07, 0.81).unwrap();
        assert!(close(f, 0.0864, 1e-3), "f={f}");
        assert_eq!(kelly_fraction(0.0, 0.81), None);
        assert_eq!(kelly_fraction(0.07, 0.0), None);
        // Jamais > 1 même avec une variance minuscule.
        assert_eq!(kelly_fraction(10.0, 0.01), Some(1.0));
    }

    #[test]
    fn move_rule_hysteresis() {
        let rule = MoveRule {
            up_buyins: 50.0,
            down_buyins: 30.0,
        };
        assert!(rule.is_valid());
        assert_eq!(decide_move(60.0, &rule, false, false), MoveDecision::MoveUp);
        assert_eq!(
            decide_move(25.0, &rule, false, false),
            MoveDecision::MoveDown
        );
        // Zone morte : entre down et up → Stay (pas d'oscillation).
        assert_eq!(decide_move(40.0, &rule, false, false), MoveDecision::Stay);
        // Bornes de l'échelle.
        assert_eq!(decide_move(60.0, &rule, true, false), MoveDecision::Stay);
        assert_eq!(decide_move(25.0, &rule, false, true), MoveDecision::Stay);
    }

    #[test]
    fn move_rule_invalid_is_stay() {
        let bad = MoveRule {
            up_buyins: 30.0,
            down_buyins: 50.0,
        };
        assert!(!bad.is_valid());
        assert_eq!(decide_move(100.0, &bad, false, false), MoveDecision::Stay);
    }

    #[test]
    fn session_limits_priority_and_triggers() {
        let limits = SessionLimits::default();
        assert_eq!(
            session_verdict(&limits, 1.0, 0, 0.0),
            SessionVerdict::Continue
        );
        assert_eq!(
            session_verdict(&limits, 4.5, 0, 0.0),
            SessionVerdict::Stop(StopReason::MaxDuration)
        );
        assert_eq!(
            session_verdict(&limits, 1.0, 0, -3.5),
            SessionVerdict::Stop(StopReason::StopLoss)
        );
        assert_eq!(
            session_verdict(&limits, 1.0, 0, 12.0),
            SessionVerdict::Stop(StopReason::StopWin)
        );
        // La durée prime sur le stop-loss.
        assert_eq!(
            session_verdict(&limits, 5.0, 0, -5.0),
            SessionVerdict::Stop(StopReason::MaxDuration)
        );
        let with_hands = SessionLimits {
            max_hands_per_day: 500,
            ..limits
        };
        assert_eq!(
            session_verdict(&with_hands, 1.0, 500, 0.0),
            SessionVerdict::Stop(StopReason::DailyHands)
        );
    }

    #[test]
    fn assess_cash_reports_band_and_target() {
        let a = assess_cash(7.0, 90.0, 40.0);
        assert_eq!(a.format, GameFormat::Cash);
        assert_eq!(a.risk_band, Some(RiskBand::Safe));
        assert!(a.bankroll_for_1pct_ror.unwrap() < 40.0);
        // Roll trop faible : bande Excessive.
        let bad = assess_cash(7.0, 90.0, 5.0);
        assert_eq!(bad.risk_band, Some(RiskBand::Excessive));
    }
}
