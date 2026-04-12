from poker.tools.supported_sites import (
    SUPPORTED_SITES,
    build_supported_sites_help_html,
    infer_supported_site,
)


def test_expected_supported_sites_are_listed():
    names = {site.display_name for site in SUPPORTED_SITES}
    assert {
        "GGPoker",
        "PokerStars",
        "PartyPoker",
        "Winamax",
        "WPT Global",
        "iPoker Network",
        "CoinPoker",
    } <= names


def test_infer_supported_site_from_common_table_names():
    assert infer_supported_site("Official Poker Stars").display_name == "PokerStars"
    assert infer_supported_site("GG Poker 6-max").display_name == "GGPoker"
    assert infer_supported_site("Winamax Expresso").display_name == "Winamax"
    assert infer_supported_site("WPTGlobal turbo").display_name == "WPT Global"
    assert infer_supported_site("iPoker cash").display_name == "iPoker Network"
    assert infer_supported_site("Coin Poker cash").display_name == "CoinPoker"
    assert infer_supported_site("Mystery Room") is None


def test_help_html_mentions_mapping_guidance():
    html = build_supported_sites_help_html()
    assert "Supported poker rooms" in html
    assert "Blank new" in html
    assert "Copy to new" in html
    assert "Custom-mapped rooms" in html
