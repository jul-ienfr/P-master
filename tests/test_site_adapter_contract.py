from src.vision.site_adapter import FormatProfile, PokerStarsAdapter, ThemeProfile, get_active_adapter


def test_pokerstars_adapter_filters_preset_manifests_to_pokerstars_only():
    adapter = PokerStarsAdapter()
    manifests = adapter.preset_manifests()

    assert manifests
    assert all("pokerstars" in str(path).lower() for path in manifests)


def test_pokerstars_adapter_exposes_play_money_amount_format_by_default():
    adapter = PokerStarsAdapter()
    amount_format = adapter.amount_format

    assert isinstance(adapter.theme, ThemeProfile)
    assert isinstance(amount_format, FormatProfile)
    assert amount_format.allow_decimals is False
    assert amount_format.thousands_separators == (" ",)


def test_get_active_adapter_returns_pokerstars_adapter():
    adapter = get_active_adapter("pokerstars", theme_key="dark-fr", real_money=True)

    assert isinstance(adapter, PokerStarsAdapter)
    assert adapter.amount_format.allow_decimals is True
