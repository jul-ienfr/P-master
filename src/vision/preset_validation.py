"""Statut de validation d'un preset — un vert exige une mesure (spec 010, F-08).

Constat mesuré : les deux manifestes livrés (`pokerstars-7-fr-6-max`,
`official-party-poker`) portaient ``validation.status = "green"`` avec
``evaluated_samples = 0`` et des taux à ``1.0``. La cause est une règle qui
traitait l'absence de mesure comme une réussite parfaite
(``min(scores) if scores else 1.0``). Un vert vide donne confiance sans preuve
et masque l'absence de mesure.

Ce module est la **source unique** du calcul de statut :

- ``unmeasured`` quand rien n'a été évalué, avec des taux ``None`` (jamais
  ``0.0``, qui signifierait « tout faux », ni ``1.0``, qui signifierait « tout
  juste ») ;
- ``green``/``yellow``/``red`` dès qu'un échantillon a été évalué.

Il vit dans ``src/`` (production) et est consommé par le laboratoire
``poker/tools/room_manager.py``, jamais l'inverse (ADR-001).
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNMEASURED = "unmeasured"
GREEN = "green"
YELLOW = "yellow"
RED = "red"

# Seuils de statut, en taux de réussite live.
GREEN_MIN_LIVE_PASS_RATE = 0.95
YELLOW_MIN_LIVE_PASS_RATE = 0.80


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


@dataclass(frozen=True)
class ValidationOutcome:
    """Résultat d'une validation de preset, avec effectif évalué explicite.

    Les trois taux valent ``None`` quand la grandeur n'a pas été mesurée : un
    preset non mesuré n'a pas de taux de réussite, ni bon ni mauvais.
    """

    status: str
    golden_pass_rate: float | None
    live_pass_rate: float | None
    critical_anchor_score: float | None
    evaluated_samples: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def measured(self) -> bool:
        return self.evaluated_samples > 0 and self.status != UNMEASURED

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "golden_pass_rate": _round_or_none(self.golden_pass_rate),
            "live_pass_rate": _round_or_none(self.live_pass_rate),
            "critical_anchor_score": _round_or_none(self.critical_anchor_score),
            "issues": list(self.issues),
            "evaluated_samples": int(self.evaluated_samples),
        }


def compute_validation_status(
    *,
    golden_scores: list[float] | None = None,
    live_scores: list[float] | None = None,
    critical_anchor_score: float | None = 1.0,
    issues: list[str] | None = None,
) -> ValidationOutcome:
    """Calcule le statut d'un preset **à partir de mesures réelles**.

    - aucun échantillon évalué (ni golden ni live) → ``unmeasured`` : les taux
      valent ``None`` et l'effectif ``0``, jamais un taux de réussite inventé ;
    - au moins un échantillon et tout réussit → ``green`` ;
    - sinon ``yellow``/``red`` selon le seuil, ou ``red`` dès qu'un problème est
      signalé.
    """
    issues = list(issues or [])
    golden = list(golden_scores or [])
    live = list(live_scores or [])
    evaluated = len(golden) + len(live)

    if evaluated == 0:
        # Un preset non mesuré n'est ni vert ni rouge : il est non mesuré, et
        # aucun taux n'est inventé (ni 0.0 ni 1.0).
        return ValidationOutcome(
            status=UNMEASURED,
            golden_pass_rate=None,
            live_pass_rate=None,
            critical_anchor_score=None,
            evaluated_samples=0,
            issues=issues,
        )

    golden_pass_rate = min(golden) if golden else None
    live_pass_rate = (sum(live) / len(live)) if live else None

    # Taux live effectif : la mesure live si elle existe, sinon la mesure
    # golden (une validation golden-only n'est pas un « non mesuré »).
    effective_live = live_pass_rate if live_pass_rate is not None else (golden_pass_rate or 0.0)
    anchors_ok = critical_anchor_score is None or critical_anchor_score == 1.0

    if issues:
        status = RED
    elif (
        anchors_ok
        and (golden_pass_rate is None or golden_pass_rate == 1.0)
        and effective_live >= GREEN_MIN_LIVE_PASS_RATE
    ):
        status = GREEN
    elif anchors_ok and YELLOW_MIN_LIVE_PASS_RATE <= effective_live < GREEN_MIN_LIVE_PASS_RATE:
        status = YELLOW
    else:
        status = RED

    return ValidationOutcome(
        status=status,
        golden_pass_rate=golden_pass_rate,
        live_pass_rate=live_pass_rate,
        critical_anchor_score=critical_anchor_score,
        evaluated_samples=evaluated,
        issues=issues,
    )
