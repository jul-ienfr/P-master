"""Supported poker room metadata used by the desktop help and docs."""

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class SupportedSite:
    """Describe how a poker room is supported by the application."""

    key: str
    display_name: str
    support_mode: str
    aliases: tuple[str, ...]
    notes: str


SUPPORT_MODE_LABELS = {
    "official_preset": "Official preset included",
    "custom_mapping": "Supported through custom table mapping",
}


SUPPORTED_SITES = (
    SupportedSite(
        key="ggpoker",
        display_name="GGPoker",
        support_mode="official_preset",
        aliases=("ggpoker", "gg poker", "natural8"),
        notes="Bundled table profiles already exist in the current project/database.",
    ),
    SupportedSite(
        key="pokerstars",
        display_name="PokerStars",
        support_mode="official_preset",
        aliases=("pokerstars", "poker stars"),
        notes="Bundled table profiles already exist in the current project/database.",
    ),
    SupportedSite(
        key="partypoker",
        display_name="PartyPoker",
        support_mode="official_preset",
        aliases=("partypoker", "party poker"),
        notes="Bundled table profiles already exist in the current project/database.",
    ),
    SupportedSite(
        key="winamax",
        display_name="Winamax",
        support_mode="custom_mapping",
        aliases=("winamax",),
        notes="Create and save a table profile in Table Setup before using it in the bot.",
    ),
    SupportedSite(
        key="wpt_global",
        display_name="WPT Global",
        support_mode="custom_mapping",
        aliases=("wpt global", "wptglobal"),
        notes="Create and save a table profile in Table Setup before using it in the bot.",
    ),
    SupportedSite(
        key="ipoker",
        display_name="iPoker Network",
        support_mode="custom_mapping",
        aliases=("ipoker", "i poker"),
        notes="Create and save a table profile for the exact skin/layout you play before using it in the bot.",
    ),
    SupportedSite(
        key="coinpoker",
        display_name="CoinPoker",
        support_mode="custom_mapping",
        aliases=("coinpoker", "coin poker"),
        notes="Create and save a table profile in Table Setup before using it in the bot.",
    ),
)


def _normalize_alias_text(value):
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return " ".join(normalized.split())


def infer_supported_site(table_name):
    """Best-effort inference of a room family from a table/profile name."""

    if not table_name:
        return None

    normalized_table_name = _normalize_alias_text(str(table_name))
    compact_table_name = normalized_table_name.replace(" ", "")

    for site in SUPPORTED_SITES:
        for alias in site.aliases:
            normalized_alias = _normalize_alias_text(alias)
            if (
                normalized_alias in normalized_table_name
                or normalized_alias.replace(" ", "") in compact_table_name
            ):
                return site

    return None


def _build_site_items(support_mode):
    items = []
    for site in SUPPORTED_SITES:
        if site.support_mode != support_mode:
            continue

        label = SUPPORT_MODE_LABELS.get(site.support_mode, site.support_mode)
        items.append(
            (
                f"<li><b>{escape(site.display_name)}</b> - "
                f"{escape(label)}<br/>{escape(site.notes)}</li>"
            )
        )
    return "".join(items)


def build_supported_sites_help_html():
    """Return a short HTML summary for the Help dialog."""

    official_items = _build_site_items("official_preset")
    custom_items = _build_site_items("custom_mapping")

    return (
        "<p><b>Supported poker rooms</b></p>"
        "<p>The desktop bot supports two kinds of room integrations:</p>"
        "<p><b>Official presets</b></p>"
        f"<ul>{official_items}</ul>"
        "<p><b>Custom-mapped rooms</b></p>"
        f"<ul>{custom_items}</ul>"
        "<p>"
        "For custom-mapped rooms, create a saved table profile with "
        "<b>Table Setup</b> first. The fastest path is usually <b>Blank new</b> "
        "for a new layout or <b>Copy to new</b> when you already have a similar table profile."
        "</p>"
    )
