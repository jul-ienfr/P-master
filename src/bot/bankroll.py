"""Enveloppe runtime du moteur de bankroll Rust (spec 004).

Le calcul (risque de ruine, probabilité de profit, Kelly, bankroll cible,
move-up/down, limites de session) vit dans ``src/bankroll.rs`` et n'est **pas**
dupliqué ici. Ce module ne fait que trois choses :

1. appeler les fonctions natives avec des unités naturelles (bb/100, BI) ;
2. traduire le verdict de session en décision d'arrêt exploitable ;
3. écrire une ligne d'audit par évaluation.

Si l'extension native n'est pas disponible, toutes les fonctions de calcul
retournent ``None`` et l'appelant garde un comportement sûr (aucun conseil de
bankroll inventé). Les limites dures de session restent, elles, garanties par
``SessionManager``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - dépend du build maturin
    import postflop_solver_py as _native

    NATIVE_BANKROLL_AVAILABLE = True
except ImportError:  # pragma: no cover - chemin de repli
    _native = None
    NATIVE_BANKROLL_AVAILABLE = False
    logging.warning(
        "Le module Rust 'postflop_solver_py' n'est pas disponible : "
        "le conseil de bankroll est désactivé (les limites de session restent actives)."
    )


def _require_native() -> Any | None:
    """Retourne l'extension native si elle expose le moteur de bankroll."""
    if _native is None:
        return None
    if not hasattr(_native, "assess_cash"):
        return None
    return _native


# --------------------------------------------------------------------------- #
# Calculs (délégation pure au Rust)
# --------------------------------------------------------------------------- #


def risk_of_ruin_cash(
    win_rate_bb_per_100: float, sigma_bb_per_100: float, roll_buyins: float
) -> float | None:
    """Risque de ruine cash, ou ``None`` si le calcul n'est pas défini."""
    native = _require_native()
    if native is None:
        return None
    return native.risk_of_ruin_cash(win_rate_bb_per_100, sigma_bb_per_100, roll_buyins)


def risk_of_ruin_mtt(roi: float, sigma_bi: float, roll_buyins: float) -> float | None:
    """Risque de ruine tournoi (ROI en fraction de BI, σ en BI)."""
    native = _require_native()
    if native is None:
        return None
    return native.risk_of_ruin_mtt(roi, sigma_bi, roll_buyins)


def bankroll_for_target_ror(edge_bi: float, variance_bi2: float, target_ror: float) -> float | None:
    """Bankroll minimale (en BI) pour un RoR cible — inverse du RoR."""
    native = _require_native()
    if native is None:
        return None
    return native.bankroll_for_target_ror(edge_bi, variance_bi2, target_ror)


def probability_of_profit_cash(
    win_rate_bb_per_100: float, sigma_bb_per_100: float, hands: int
) -> float | None:
    """P(profit) après ``hands`` mains, ou ``None`` si σ ≤ 0."""
    native = _require_native()
    if native is None:
        return None
    return native.probability_of_profit_cash(win_rate_bb_per_100, sigma_bb_per_100, hands)


def probability_of_profit_mtt(roi: float, sigma_bi: float, n_tournaments: int) -> float | None:
    """P(profit) après ``n_tournaments`` tournois."""
    native = _require_native()
    if native is None:
        return None
    return native.probability_of_profit_mtt(roi, sigma_bi, n_tournaments)


def kelly_fraction(edge_bi: float, variance_bi2: float) -> float | None:
    """Fraction de Kelly optimale ``edge/variance``, bornée à 1."""
    native = _require_native()
    if native is None:
        return None
    return native.kelly_fraction(edge_bi, variance_bi2)


def risk_band(ror: float) -> str | None:
    """Bande de risque : ``safe``, ``acceptable``, ``elevated`` ou ``excessive``."""
    native = _require_native()
    if native is None:
        return None
    return native.risk_band(ror)


def assess_cash(
    win_rate_bb_per_100: float, sigma_bb_per_100: float, roll_buyins: float
) -> dict[str, Any] | None:
    """Évaluation complète d'un plan cash (dict journalisable)."""
    native = _require_native()
    if native is None:
        return None
    return native.assess_cash(win_rate_bb_per_100, sigma_bb_per_100, roll_buyins)


# --------------------------------------------------------------------------- #
# Limites dures de session
# --------------------------------------------------------------------------- #

# Seuils par défaut, identiques à ``SessionManager`` (comportement inchangé).
DEFAULT_MAX_HOURS = 4.0
DEFAULT_STOP_LOSS_BUYINS = 3.0
DEFAULT_STOP_WIN_BUYINS = 10.0
DEFAULT_MAX_HANDS_PER_DAY = 0  # 0 = pas de plafond


@dataclass(frozen=True)
class SessionLimits:
    """Limites dures d'une session — miroir de ``bankroll::SessionLimits``."""

    max_hours: float = DEFAULT_MAX_HOURS
    stop_loss_buyins: float = DEFAULT_STOP_LOSS_BUYINS
    stop_win_buyins: float = DEFAULT_STOP_WIN_BUYINS
    max_hands_per_day: int = DEFAULT_MAX_HANDS_PER_DAY


def session_verdict(
    limits: SessionLimits,
    hours_played: float,
    profit_loss_buyins: float,
    hands_today: int = 0,
) -> str | None:
    """Motif d'arrêt (``max_duration``, ``daily_hands``, ``stop_loss``,
    ``stop_win``) ou ``None`` si la session peut continuer.

    Repli Python si l'extension native est absente : mêmes seuils, même ordre de
    priorité, pour que la protection de capital ne dépende jamais du build.
    """
    native = _require_native()
    if native is not None:
        return native.session_verdict(
            hours_played,
            profit_loss_buyins,
            limits.max_hours,
            limits.stop_loss_buyins,
            limits.stop_win_buyins,
            hands_today,
            limits.max_hands_per_day,
        )

    if limits.max_hours > 0.0 and hours_played >= limits.max_hours:
        return "max_duration"
    if limits.max_hands_per_day > 0 and hands_today >= limits.max_hands_per_day:
        return "daily_hands"
    if limits.stop_loss_buyins > 0.0 and profit_loss_buyins <= -limits.stop_loss_buyins:
        return "stop_loss"
    if limits.stop_win_buyins > 0.0 and profit_loss_buyins >= limits.stop_win_buyins:
        return "stop_win"
    return None


# --------------------------------------------------------------------------- #
# Journal d'audit
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BankrollAuditEntry:
    """Une évaluation de bankroll, journalisable telle quelle (spec 004, FR-012)."""

    timestamp: str
    format: str
    roll_buyins: float
    win_rate_bb_per_100: float
    sigma_bb_per_100: float
    ror: float | None
    risk_band: str | None
    kelly: float | None
    bankroll_for_1pct_ror: float | None
    decision: str
    stop_reason: str | None
    limits: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


class BankrollAuditLog:
    """Journal JSONL append-only des évaluations de bankroll.

    Le schéma est stable et testé : un changement de limite doit être
    reconstructible après coup (audit §3.5).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, entry: BankrollAuditEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.to_json() + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries


# --------------------------------------------------------------------------- #
# Évaluation de plan
# --------------------------------------------------------------------------- #

#: Champs attendus dans une évaluation — utilisé par le test de schéma.
ASSESSMENT_FIELDS = (
    "format",
    "roll_buyins",
    "ror",
    "risk_band",
    "kelly",
    "bankroll_for_1pct_ror",
)


def evaluate_plan_cash(
    win_rate_bb_per_100: float,
    sigma_bb_per_100: float,
    roll_buyins: float,
    *,
    hours_played: float = 0.0,
    profit_loss_buyins: float = 0.0,
    hands_today: int = 0,
    limits: SessionLimits | None = None,
    audit_log: BankrollAuditLog | None = None,
    now: str | None = None,
) -> BankrollAuditEntry:
    """Évalue un plan cash et, si un journal est fourni, l'y enregistre.

    Retourne une entrée complète même quand le calcul n'est pas disponible
    (champs à ``None``), pour que l'audit reste traçable en mode dégradé.
    """
    limits = limits or SessionLimits()
    assessment = assess_cash(win_rate_bb_per_100, sigma_bb_per_100, roll_buyins) or {}
    stop_reason = session_verdict(limits, hours_played, profit_loss_buyins, hands_today)
    decision = "stop" if stop_reason else "continue"

    entry = BankrollAuditEntry(
        timestamp=now or datetime.now(UTC).isoformat(),
        format="cash",
        roll_buyins=roll_buyins,
        win_rate_bb_per_100=win_rate_bb_per_100,
        sigma_bb_per_100=sigma_bb_per_100,
        ror=assessment.get("ror"),
        risk_band=assessment.get("risk_band"),
        kelly=assessment.get("kelly"),
        bankroll_for_1pct_ror=assessment.get("bankroll_for_1pct_ror"),
        decision=decision,
        stop_reason=stop_reason,
        limits=asdict(limits),
    )
    if audit_log is not None:
        audit_log.record(entry)
    return entry
