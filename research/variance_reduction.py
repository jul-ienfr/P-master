"""Estimateurs de winrate à variance réduite (AIVAT C11, MIVAT C27).

Le résultat d'une main de NLHE a une variance énorme (σ ≈ 90 bb/100 en 6-max) :
la moyenne brute exige un volume irréaliste pour un intervalle de confiance
étroit. Une **variable de contrôle** corrélée au résultat permet de réduire la
variance **sans introduire de biais**, à condition que sa moyenne soit connue.

Pour un résultat par main ``u`` et un contrôle ``C`` de moyenne connue ``E[C]`` :

    X = u − β · (C − E[C])

``E[X] = E[u]`` pour tout ``β`` et tout ``E[C]`` exact : l'estimateur est sans
biais **par construction**. Le ``β`` optimal ``Cov(u,C)/Var(C)`` minimise la
variance résiduelle, qui vaut ``Var(u)·(1 − ρ²)``.

AIVAT (C11) est le cas ``E[C] = 0`` et ``β = 1`` : le contrôle est construit
centré. MIVAT (C27) applique le même principe joueur par joueur.

Ce module ne calcule rien de « chaud » : il consomme des résultats et des
contrôles déjà collectés, hors de la boucle de décision (constitution §II).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

BIG_BLIND = 2.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: Sequence[float], mean: float | None = None) -> float:
    """Variance de population ; ``0.0`` pour un échantillon de moins de 2 points."""
    n = len(values)
    if n < 2:
        return 0.0
    center = _mean(values) if mean is None else mean
    return sum((value - center) ** 2 for value in values) / n


def _covariance(
    first: Sequence[float],
    second: Sequence[float],
    *,
    mean_first: float,
    mean_second: float,
) -> float:
    n = len(first)
    if n < 2:
        return 0.0
    return sum((a - mean_first) * (b - mean_second) for a, b in zip(first, second, strict=True)) / n


@dataclass(frozen=True)
class VarianceReducedEstimate:
    """Estimation d'un winrate, brute et à variance réduite.

    ``variance_reduction`` est le taux **mesuré** ``1 − Var(X)/Var(u)``, jamais un
    taux supposé : il vaut ``0.0`` quand le contrôle est constant (aucune
    réduction) et peut être négatif si le contrôle est anti-corrélé au résultat.
    """

    n: int
    raw_bb100: float
    reduced_bb100: float
    raw_ci95_bb100: float
    reduced_ci95_bb100: float
    raw_std_bb: float
    reduced_std_bb: float
    variance_reduction: float
    beta: float
    mean_control: float
    unbiased_inputs: bool

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "n": self.n,
            "raw_bb100": self.raw_bb100,
            "reduced_bb100": self.reduced_bb100,
            "raw_ci95_bb100": self.raw_ci95_bb100,
            "reduced_ci95_bb100": self.reduced_ci95_bb100,
            "raw_std_bb": self.raw_std_bb,
            "reduced_std_bb": self.reduced_std_bb,
            "variance_reduction": self.variance_reduction,
            "beta": self.beta,
            "mean_control": self.mean_control,
            "unbiased_inputs": self.unbiased_inputs,
        }


def control_variate_estimate(
    payoffs: Sequence[float],
    controls: Sequence[float],
    *,
    mean_control: float | None = None,
    beta: float | str = "optimal",
    z: float = 1.96,
    big_blind: float = BIG_BLIND,
) -> VarianceReducedEstimate:
    """Estime le winrate bb/100 par variable de contrôle.

    ``payoffs`` sont les résultats par main (en unités de mise, ex. bb) et
    ``controls`` la variable de contrôle alignée. ``mean_control`` est la moyenne
    **connue** du contrôle : la fournir garantit l'absence de biais. Quand elle
    est omise, elle est estimée sur l'échantillon et ``unbiased_inputs`` passe à
    ``False`` — la moyenne doit alors venir d'un échantillon de calibration
    distinct pour que l'estimateur reste sans biais.

    ``beta`` vaut ``"optimal"`` (``Cov(u,C)/Var(C)``) ou un flottant explicite.
    """
    if len(payoffs) != len(controls):
        raise ValueError(
            f"payoffs ({len(payoffs)}) et controls ({len(controls)}) de tailles différentes"
        )

    n = len(payoffs)
    if n == 0:
        return VarianceReducedEstimate(
            n=0,
            raw_bb100=0.0,
            reduced_bb100=0.0,
            raw_ci95_bb100=0.0,
            reduced_ci95_bb100=0.0,
            raw_std_bb=0.0,
            reduced_std_bb=0.0,
            variance_reduction=0.0,
            beta=0.0,
            mean_control=float(mean_control or 0.0),
            unbiased_inputs=mean_control is not None,
        )

    raw_mean = _mean(payoffs)
    raw_var = _variance(payoffs, raw_mean)
    raw_std = math.sqrt(raw_var)

    unbiased_inputs = mean_control is not None
    control_mean = float(mean_control) if mean_control is not None else _mean(controls)
    control_sample_mean = _mean(controls)
    control_var = _variance(controls, control_sample_mean)

    if isinstance(beta, str):
        if beta != "optimal":
            raise ValueError(f"beta inconnu : {beta!r} (attendu 'optimal' ou un flottant)")
        if control_var > 0.0:
            beta_used = (
                _covariance(
                    payoffs,
                    controls,
                    mean_first=raw_mean,
                    mean_second=control_sample_mean,
                )
                / control_var
            )
        else:
            beta_used = 0.0
    else:
        beta_used = float(beta)

    residuals = [
        payoff - beta_used * (control - control_mean)
        for payoff, control in zip(payoffs, controls, strict=True)
    ]
    reduced_mean = _mean(residuals)
    reduced_var = _variance(residuals, reduced_mean)
    reduced_std = math.sqrt(reduced_var)

    scale = 100.0 / big_blind if big_blind else 0.0
    sqrt_n = math.sqrt(n)
    return VarianceReducedEstimate(
        n=n,
        raw_bb100=raw_mean * scale,
        reduced_bb100=reduced_mean * scale,
        raw_ci95_bb100=z * raw_std / sqrt_n * scale,
        reduced_ci95_bb100=z * reduced_std / sqrt_n * scale,
        raw_std_bb=raw_std,
        reduced_std_bb=reduced_std,
        variance_reduction=(1.0 - reduced_var / raw_var) if raw_var > 0.0 else 0.0,
        beta=beta_used,
        mean_control=control_mean,
        unbiased_inputs=unbiased_inputs,
    )


def aivat_estimate(
    payoffs: Sequence[float],
    controls: Sequence[float],
    *,
    z: float = 1.96,
    big_blind: float = BIG_BLIND,
) -> VarianceReducedEstimate:
    """Cas AIVAT : contrôle centré par construction (``E[C] = 0``), ``β = 1``."""
    return control_variate_estimate(
        payoffs,
        controls,
        mean_control=0.0,
        beta=1.0,
        z=z,
        big_blind=big_blind,
    )


def mivat_estimate(
    per_player_payoffs: Mapping[int, Sequence[float]],
    per_player_controls: Mapping[int, Sequence[float]],
    *,
    mean_controls: Mapping[int, float] | None = None,
    beta: float | str = "optimal",
    z: float = 1.96,
    big_blind: float = BIG_BLIND,
) -> dict[int, VarianceReducedEstimate]:
    """MIVAT : un estimateur par joueur, chacun sur sa propre variable de contrôle.

    Chaque joueur est estimé indépendamment à partir de ses résultats et de son
    contrôle : aucune information d'un joueur ne fuit dans l'estimation d'un
    autre. ``mean_controls`` porte la moyenne connue du contrôle de chaque
    joueur ; un joueur absent de la table voit sa moyenne estimée sur
    l'échantillon (``unbiased_inputs=False``).
    """
    known = dict(mean_controls or {})
    estimates: dict[int, VarianceReducedEstimate] = {}
    for player, payoffs in per_player_payoffs.items():
        controls = per_player_controls.get(player)
        if controls is None:
            raise ValueError(f"aucun contrôle fourni pour le joueur {player!r}")
        estimates[player] = control_variate_estimate(
            payoffs,
            controls,
            mean_control=known.get(player),
            beta=beta,
            z=z,
            big_blind=big_blind,
        )
    return estimates
