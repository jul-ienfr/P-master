from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence


DEFAULT_POKERSTARS_PRESET_MANIFESTS = (
    "poker/pokerstars-7-fr-6-max/draft/manifest.json",
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


class SiteAdapterProtocol(Protocol):
    site_key: str
    display_name: str
    theme: ThemeProfile
    amount_format: FormatProfile

    def preset_manifests(self) -> Sequence[Path]:
        ...


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

    def preset_manifests(self) -> Sequence[Path]:
        repo_root = Path(__file__).resolve().parents[2]
        manifests = []
        for relative_path in DEFAULT_POKERSTARS_PRESET_MANIFESTS:
            normalized = relative_path.replace("\\", "/").lower()
            if "pokerstars" not in normalized:
                continue
            manifests.append((repo_root / relative_path).resolve())
        return tuple(manifests)


def get_active_adapter(site_key: str = "pokerstars", *, theme_key: str = "dark-fr", real_money: bool = False) -> SiteAdapterProtocol:
    normalized = str(site_key or "pokerstars").strip().lower()
    if normalized == "pokerstars":
        return PokerStarsAdapter(theme_key=theme_key, real_money=real_money)
    raise ValueError(f"Unsupported site adapter: {site_key}")
