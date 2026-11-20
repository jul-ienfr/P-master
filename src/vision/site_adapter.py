"""Contrat de plateforme multi-site (spec 005, constat F-06).

Un adaptateur de site regroupe ce qui varie d'une plateforme à l'autre :

- **identité** : clé de site, nom affiché, thème ;
- **format des montants** : décimales autorisées, séparateurs de milliers et
  décimaux, symboles monétaires — et le parseur qui en découle (source unique) ;
- **profil de fenêtre** : motifs de reconnaissance (titre, classe, process),
  blinde par défaut, motif de limite ;
- **limites d'action** : mise minimale, incrément minimal de relance, tapis ;
- **manifestes de preset** : géométrie et assets du site, s'ils existent.

Le registre ``SITE_ADAPTERS`` associe une clé à une fabrique. ``get_active_adapter``
le consulte et lève une erreur explicite pour une clé inconnue : un adaptateur par
défaut silencieux ferait jouer l'opérateur sur le mauvais site.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.vision.action_limits import ActionLimits
from src.vision.models import BUILTIN_PRESET_MANIFESTS
from src.vision.numeric_parser import NumericParser

DEFAULT_SITE_KEY = "pokerstars"

DEFAULT_POKERSTARS_PRESET_MANIFESTS = tuple(
    path for path in BUILTIN_PRESET_MANIFESTS if "pokerstars" in path.lower()
)
DEFAULT_WINAMAX_PRESET_MANIFESTS = tuple(
    path for path in BUILTIN_PRESET_MANIFESTS if "winamax" in path.lower()
)


@dataclass(frozen=True)
class ThemeProfile:
    site_key: str
    theme_key: str
    display_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FormatProfile:
    allow_decimals: bool = False
    thousands_separators: tuple[str, ...] = (" ",)
    decimal_separators: tuple[str, ...] = ()
    currency_symbols: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WindowProfile:
    """Motifs de reconnaissance d'une fenêtre de table pour un site.

    Les champs non observés (classe de fenêtre, nom de process d'un site non
    encore instrumenté) restent ``None`` : une valeur inventée ferait échouer la
    reconnaissance en silence plutôt que de laisser le titre décider.
    """

    title_aliases: tuple[str, ...] = ()
    title_regex: str | None = None
    window_class: str | None = None
    process_name: str | None = None
    default_bb: int = 100
    stake_regex: str = r"\d+[/,](\d+)\b"
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches_title(self, title: str) -> bool:
        normalized = str(title or "")
        if not normalized:
            return False
        if self.title_regex:
            try:
                if re.search(self.title_regex, normalized, re.IGNORECASE):
                    return True
            except re.error:
                pass
        lowered = normalized.lower()
        return any(alias.lower() in lowered for alias in self.title_aliases if alias)


class SiteAdapterProtocol(Protocol):
    site_key: str
    display_name: str
    theme: ThemeProfile
    amount_format: FormatProfile
    window_profile: WindowProfile
    action_limits: ActionLimits

    def preset_manifests(self) -> Sequence[Path]: ...

    def amount_parser(self) -> NumericParser: ...


def _parser_from_format(amount_format: FormatProfile) -> NumericParser:
    """Construit le parseur de montants depuis le format déclaré du site.

    Source unique : le format n'est plus déclaré deux fois (adaptateur *et*
    configuration OCR).
    """
    return NumericParser(
        allow_decimal_amounts=bool(amount_format.allow_decimals),
        thousands_separators=tuple(amount_format.thousands_separators or (" ",)),
        decimal_separators=tuple(amount_format.decimal_separators),
    )


def _site_manifests(relative_paths: Sequence[str], site_token: str) -> tuple[Path, ...]:
    """Résout les manifestes du site, en ne gardant que ceux présents sur le disque."""
    repo_root = Path(__file__).resolve().parents[2]
    manifests: list[Path] = []
    for relative_path in relative_paths:
        normalized = relative_path.replace("\\", "/").lower()
        if site_token not in normalized:
            continue
        candidate = (repo_root / relative_path).resolve()
        if candidate.is_file():
            manifests.append(candidate)
    return tuple(manifests)


@dataclass(frozen=True)
class PokerStarsAdapter:
    theme_key: str = "dark-fr"
    real_money: bool = False

    @property
    def site_key(self) -> str:
        return "pokerstars"

    @property
    def display_name(self) -> str:
        return "PokerStars"

    @property
    def theme(self) -> ThemeProfile:
        return ThemeProfile(
            site_key=self.site_key,
            theme_key=self.theme_key,
            display_name="PokerStars Dark",
            metadata={"network": "PokerStars"},
        )

    @property
    def amount_format(self) -> FormatProfile:
        return FormatProfile(
            allow_decimals=bool(self.real_money),
            thousands_separators=(" ",),
            decimal_separators=(",", ".") if self.real_money else (),
            currency_symbols=("$", "€"),
            metadata={"real_money": bool(self.real_money)},
        )

    @property
    def window_profile(self) -> WindowProfile:
        return WindowProfile(
            title_aliases=("PokerStars",),
            title_regex=r"PokerStars|Hold'em No Limit|NLHE",
            window_class="PokerStarsTableFrameClass",
            process_name="PokerStars.exe",
            default_bb=200,
            metadata={"real_money": bool(self.real_money)},
        )

    @property
    def action_limits(self) -> ActionLimits:
        return ActionLimits(
            min_bet_bb=1.0,
            min_raise_increment_bb=1.0,
            allow_decimals=bool(self.real_money),
            all_in_supported=True,
        )

    def preset_manifests(self) -> Sequence[Path]:
        return _site_manifests(DEFAULT_POKERSTARS_PRESET_MANIFESTS, "pokerstars")

    def amount_parser(self) -> NumericParser:
        return _parser_from_format(self.amount_format)


@dataclass(frozen=True)
class WinamaxAdapter:
    theme_key: str = "default"
    real_money: bool = True

    @property
    def site_key(self) -> str:
        return "winamax"

    @property
    def display_name(self) -> str:
        return "Winamax"

    @property
    def theme(self) -> ThemeProfile:
        return ThemeProfile(
            site_key=self.site_key,
            theme_key=self.theme_key,
            display_name="Winamax",
            metadata={"network": "Winamax"},
        )

    @property
    def amount_format(self) -> FormatProfile:
        # Convention européenne : séparateur de milliers espace, décimale virgule.
        return FormatProfile(
            allow_decimals=bool(self.real_money),
            thousands_separators=(" ",),
            decimal_separators=(",",) if self.real_money else (),
            currency_symbols=("€",),
            metadata={"real_money": bool(self.real_money)},
        )

    @property
    def window_profile(self) -> WindowProfile:
        # Classe et process Winamax non observés : laissés None (jamais inventés).
        # La reconnaissance par titre suffit tant que la fenêtre n'est pas instrumentée.
        return WindowProfile(
            title_aliases=("Winamax",),
            title_regex=r"Winamax",
            window_class=None,
            process_name=None,
            default_bb=100,
            metadata={"calibrated": False},
        )

    @property
    def action_limits(self) -> ActionLimits:
        return ActionLimits(
            min_bet_bb=1.0,
            min_raise_increment_bb=1.0,
            allow_decimals=bool(self.real_money),
            all_in_supported=True,
        )

    def preset_manifests(self) -> Sequence[Path]:
        return _site_manifests(DEFAULT_WINAMAX_PRESET_MANIFESTS, "winamax")

    def amount_parser(self) -> NumericParser:
        return _parser_from_format(self.amount_format)


# Registre des sites livrés. Une nouvelle plateforme s'ajoute ici, sans modifier
# le code d'appel (constat F-06 : le site ne doit plus être codé en dur).
SITE_ADAPTERS: dict[str, type] = {
    "pokerstars": PokerStarsAdapter,
    "winamax": WinamaxAdapter,
}


def available_site_keys() -> tuple[str, ...]:
    """Clés de site livrées, triées (ordre déterministe)."""
    return tuple(sorted(SITE_ADAPTERS))


def get_active_adapter(
    site_key: str = DEFAULT_SITE_KEY,
    *,
    theme_key: str | None = None,
    real_money: bool | None = None,
) -> SiteAdapterProtocol:
    """Retourne l'adaptateur du site demandé.

    Une clé vide ou ``None`` retombe sur le site par défaut ; une clé inconnue
    lève une erreur explicite (jamais de repli silencieux sur un autre site).
    """
    normalized = str(site_key or DEFAULT_SITE_KEY).strip().lower()
    factory = SITE_ADAPTERS.get(normalized)
    if factory is None:
        raise ValueError(
            f"Unsupported site adapter: {site_key!r} "
            f"(sites livrés : {', '.join(available_site_keys())})"
        )
    kwargs: dict[str, Any] = {}
    if theme_key is not None:
        kwargs["theme_key"] = theme_key
    if real_money is not None:
        kwargs["real_money"] = real_money
    return factory(**kwargs)


def resolve_site_from_title(
    title: str,
    *,
    adapters: dict[str, type] | None = None,
    default: str | None = None,
) -> str | None:
    """Identifie le site depuis un titre de fenêtre, de façon déterministe.

    Parcourt le registre dans l'ordre trié des clés — pas l'ordre d'insertion du
    dictionnaire, qui rendait la résolution dépendante de la déclaration. Retourne
    la clé du premier adaptateur dont le profil correspond, sinon ``default``.
    """
    registry = adapters if adapters is not None else SITE_ADAPTERS
    for key in sorted(registry):
        try:
            adapter = registry[key]()
        except Exception:
            continue
        if adapter.window_profile.matches_title(title):
            return key
    return default
