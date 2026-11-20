"""Puissance statistique et verdict de winrate (déclaration *avant* la mesure).

Un winrate nu n'est pas une preuve : un résultat de +0,1 bb/100 avec un IC95 de
[−50 ; +50] est indistinguable de zéro. Ce module impose deux choses que l'audit
exige explicitement :

1. **le nombre de mains requis est calculé à l'avance**, à partir de l'écart-type
   observé et d'une demi-largeur d'IC visée ;
2. **un verdict explicite** est retourné, et le protocole n'est déclaré complet
   que si l'effectif atteint le requis et que l'IC est fourni.

Rappel de la formule : la demi-largeur d'un IC95 vaut ``z·σ/√n``, donc
``n = ⌈(z·σ/demi-largeur)²⌉``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

DEFAULT_Z = 1.96

VERDICT_SIGNIFICANT_POSITIVE = "significant_positive"
VERDICT_SIGNIFICANT_NEGATIVE = "significant_negative"
VERDICT_NOT_SIGNIFICANT = "not_significant"
VERDICT_UNDERPOWERED = "underpowered"
VERDICT_UNMEASURED = "unmeasured"

VALID_VERDICTS = (
    VERDICT_SIGNIFICANT_POSITIVE,
    VERDICT_SIGNIFICANT_NEGATIVE,
    VERDICT_NOT_SIGNIFICANT,
    VERDICT_UNDERPOWERED,
    VERDICT_UNMEASURED,
)


def required_hands(
    sigma_bb100: float,
    target_half_width_bb100: float,
    *,
    z: float = DEFAULT_Z,
) -> int:
    """Nombre de mains nécessaire pour un IC95 de demi-largeur visée.

    ``⌈(z·σ/demi-largeur)²⌉``. Un écart-type non positif retourne ``0`` (aucune
    main nécessaire pour un résultat certain) ; une demi-largeur non positive est
    une demande impossible et lève une erreur plutôt que de diviser par zéro.
    """
    if target_half_width_bb100 <= 0.0:
        raise ValueError(
            f"demi-largeur visée invalide : {target_half_width_bb100!r} (doit être > 0)"
        )
    if sigma_bb100 <= 0.0:
        return 0
    return int(math.ceil((z * sigma_bb100 / target_half_width_bb100) ** 2))


@dataclass(frozen=True)
class WinrateVerdict:
    """Verdict d'un résultat de winrate, avec la raison de sa complétude."""

    verdict: str
    significant: bool
    protocol_complete: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "significant": self.significant,
            "protocol_complete": self.protocol_complete,
            "reasons": list(self.reasons),
        }


def classify_winrate(
    winrate_bb100: float | None,
    ci95_bb100: tuple[float, float] | None,
    evaluated_hands: int,
    required: int,
    *,
    is_production_policy: bool = True,
) -> WinrateVerdict:
    """Classe un résultat mesuré et dit si le protocole est complet.

    - ``unmeasured`` : aucune main évaluable ou aucun IC — jamais un chiffre
      inventé à la place du vide ;
    - ``underpowered`` : l'effectif n'atteint pas le requis, aucun verdict de
      significativité n'est prononcé ;
    - ``significant_positive`` / ``significant_negative`` : l'IC95 exclut zéro ;
    - ``not_significant`` : l'IC95 contient zéro — un résultat honnête, mais qui
      **n'est pas une preuve** de performance.

    ``protocol_complete`` exige : au moins une main évaluée, un IC fourni, un
    effectif ≥ requis, et une politique de production. Un artefact mesuré sur
    l'heuristique ne satisfait donc jamais le protocole.
    """
    reasons: list[str] = []

    if evaluated_hands <= 0 or ci95_bb100 is None or winrate_bb100 is None:
        return WinrateVerdict(
            verdict=VERDICT_UNMEASURED,
            significant=False,
            protocol_complete=False,
            reasons=("no_evaluable_hands",),
        )

    low, high = float(ci95_bb100[0]), float(ci95_bb100[1])
    if low > high:
        low, high = high, low

    if not is_production_policy:
        reasons.append("policy_not_production")
    if required > 0 and evaluated_hands < required:
        reasons.append("sample_below_required")

    if low > 0.0:
        verdict = VERDICT_SIGNIFICANT_POSITIVE
        significant = True
    elif high < 0.0:
        verdict = VERDICT_SIGNIFICANT_NEGATIVE
        significant = True
    else:
        verdict = VERDICT_NOT_SIGNIFICANT
        significant = False

    if evaluated_hands < required:
        # Effectif insuffisant : le classement de significativité reste
        # indicatif, le verdict explicite est « sous-dimensionné ».
        verdict = VERDICT_UNDERPOWERED
        significant = False
        reasons.append("insufficient_power")

    protocol_complete = not reasons and evaluated_hands >= required and required >= 0
    if not reasons and not protocol_complete:
        reasons.append("protocol_incomplete")

    return WinrateVerdict(
        verdict=verdict,
        significant=significant,
        protocol_complete=protocol_complete,
        reasons=tuple(reasons),
    )
