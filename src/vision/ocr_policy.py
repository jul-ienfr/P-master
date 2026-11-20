"""Politique OCR par site (spec 010, constat F-08).

La cible de l'audit §3.1 est « un moteur OCR principal + un fallback maximum ».
Le runtime supportait quatre moteurs sans politique : rien ne reliait le choix
du moteur au site ni à une mesure, et rien n'empêchait d'en charger quatre.

Ce module porte la règle, hors du moteur OCR lui-même : une politique nomme un
principal et au plus un fallback, tous deux du catalogue supporté. Une politique
invalide (plus de deux moteurs, moteur inconnu) est rejetée à la construction,
jamais chargée en silence.
"""

from __future__ import annotations

from dataclasses import dataclass

# Catalogue supporté — doit rester aligné sur ``src.vision.ocr.SUPPORTED_OCR_ENGINES``.
SUPPORTED_ENGINES: tuple[str, ...] = ("rapidocr", "tesseract", "surya", "doctr")

# Politique par défaut : un principal rapide et sans dépendance système, un
# fallback optionnel. Aucun site ne charge plus de deux moteurs.
DEFAULT_PRIMARY = "rapidocr"
DEFAULT_FALLBACK = "tesseract"

MAX_ENGINES = 2

# Politiques livrées par site. Un site absent retombe sur la politique par
# défaut ; aucune politique ne charge le catalogue entier.
SITE_OCR_POLICIES: dict[str, tuple[str, str | None]] = {
    "pokerstars": (DEFAULT_PRIMARY, DEFAULT_FALLBACK),
    "winamax": (DEFAULT_PRIMARY, DEFAULT_FALLBACK),
    "partypoker": (DEFAULT_PRIMARY, DEFAULT_FALLBACK),
}


@dataclass(frozen=True)
class OCREnginePolicy:
    """Politique OCR d'un site : un principal, au plus un fallback."""

    site_key: str
    primary: str = DEFAULT_PRIMARY
    fallback: str | None = DEFAULT_FALLBACK
    mode: str = "fallback"

    def __post_init__(self) -> None:
        primary = str(self.primary or "").strip().lower()
        if primary not in SUPPORTED_ENGINES:
            raise ValueError(
                f"moteur OCR principal inconnu: {self.primary!r} "
                f"(supportés : {', '.join(SUPPORTED_ENGINES)})"
            )
        fallback = str(self.fallback).strip().lower() if self.fallback else None
        if fallback is not None:
            if fallback not in SUPPORTED_ENGINES:
                raise ValueError(
                    f"moteur OCR de repli inconnu: {self.fallback!r} "
                    f"(supportés : {', '.join(SUPPORTED_ENGINES)})"
                )
            if fallback == primary:
                # Un fallback identique au principal n'est pas un fallback.
                fallback = None
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "fallback", fallback)

    def engines(self) -> list[str]:
        """Moteurs à charger, dans l'ordre : principal puis fallback."""
        ordered = [self.primary]
        if self.fallback:
            ordered.append(self.fallback)
        return ordered

    def with_unavailable(self, unavailable: set[str]) -> list[str]:
        """Moteurs réellement chargeables, une fois retirés les indisponibles.

        Si le principal manque, le fallback prend la main ; si les deux manquent,
        la liste est vide et l'appelant traite l'absence de moteur explicitement
        (jamais un moteur inconnu chargé en silence).
        """
        return [engine for engine in self.engines() if engine not in unavailable]

    def as_dict(self) -> dict[str, object]:
        return {
            "site_key": self.site_key,
            "primary": self.primary,
            "fallback": self.fallback,
            "mode": self.mode,
        }


def policy_for_site(
    site_key: str,
    *,
    primary: str | None = None,
    fallback: str | None = None,
) -> OCREnginePolicy:
    """Politique OCR d'un site, avec la politique par défaut si non déclarée.

    ``primary``/``fallback`` surchargent explicitement la politique du site ;
    omis, c'est la politique déclarée du site qui s'applique.
    """
    key = str(site_key or "default").strip().lower()
    declared_primary, declared_fallback = SITE_OCR_POLICIES.get(
        key, (DEFAULT_PRIMARY, DEFAULT_FALLBACK)
    )
    return OCREnginePolicy(
        site_key=key,
        primary=primary or declared_primary,
        fallback=declared_fallback if fallback is None else fallback,
    )


def validate_engine_selection(engines: list[str] | tuple[str, ...]) -> list[str]:
    """Valide une sélection de moteurs : au plus deux, tous supportés.

    Lève sur un moteur inconnu ou au-delà de ``MAX_ENGINES`` ; ne tronque jamais
    silencieusement (tronquer masquerait une politique mal écrite).
    """
    normalized: list[str] = []
    for engine in engines:
        key = str(engine or "").strip().lower()
        if not key:
            continue
        if key not in SUPPORTED_ENGINES:
            raise ValueError(
                f"moteur OCR inconnu: {engine!r} (supportés : {', '.join(SUPPORTED_ENGINES)})"
            )
        if key not in normalized:
            normalized.append(key)
    if len(normalized) > MAX_ENGINES:
        raise ValueError(
            f"politique OCR invalide: {len(normalized)} moteurs "
            f"(maximum {MAX_ENGINES} : un principal + un fallback)"
        )
    return normalized


def clamp_to_policy(engines: list[str] | tuple[str, ...], policy: OCREnginePolicy) -> list[str]:
    """Restreint une sélection aux moteurs de la politique, au plus ``MAX_ENGINES``.

    Un moteur hors politique est écarté (le runtime ne charge que la politique
    active) ; l'ordre de la politique est conservé, jamais l'ordre d'entrée.
    """
    selected = {str(engine or "").strip().lower() for engine in engines}
    return [engine for engine in policy.engines() if engine in selected]
