from src.runtime.player_name_resolver import (
    is_probable_ui_name,
    is_placeholder_player_name,
    resolve_player_name,
    sanitize_player_name,
)


def test_ui_labels_are_rejected():
    assert is_probable_ui_name("Passer") is True
    assert is_probable_ui_name("Parier") is True
    assert is_probable_ui_name("Suivre") is True
    assert is_probable_ui_name("Suivr") is True
    assert is_probable_ui_name("M") is True
    assert is_probable_ui_name("ah uffi au 26") is True
    assert is_probable_ui_name("l auton M") is True
    assert is_probable_ui_name("CI I") is True
    assert is_probable_ui_name("150.4") is True
    assert is_probable_ui_name("��*�") is True


def test_valid_screen_names_are_kept():
    assert is_probable_ui_name("Nick Deb01") is False
    assert is_probable_ui_name("monica_ghi") is False


def test_html_noise_is_sanitized_before_name_resolution():
    cache = {}

    assert sanitize_player_name(".<br>NTFmango") == "NTFmango"
    resolved, source = resolve_player_name("seat_7", ".<br>NTFmango", cache)

    assert resolved == "NTFmango"
    assert source == "live_ocr"
    assert cache["seat_7"] == "NTFmango"


def test_placeholder_names_are_rejected():
    assert is_placeholder_player_name("seat_5") is True
    assert is_placeholder_player_name("Joueur 8") is True


def test_cached_name_is_reused_when_ui_label_overrides_seat():
    cache = {"seat_4": "maxy117"}
    resolved, source = resolve_player_name("seat_4", "Passer", cache)

    assert resolved == "maxy117"
    assert source == "seat_cache"


def test_live_name_updates_cache():
    cache = {}
    resolved, source = resolve_player_name("seat_2", "Brucy20", cache)

    assert resolved == "Brucy20"
    assert source == "live_ocr"
    assert cache["seat_2"] == "Brucy20"


def test_placeholder_name_reuses_cached_name():
    cache = {"seat_3": "Nick Deb01"}
    resolved, source = resolve_player_name("seat_3", "Joueur 3", cache)

    assert resolved == "Nick Deb01"
    assert source == "seat_cache"


def test_trailing_stack_amount_is_stripped_from_player_name():
    cache = {}

    resolved, source = resolve_player_name("seat_5", "curintia2 14 800", cache)

    assert resolved == "curintia2"
    assert source == "live_ocr"
    assert cache["seat_5"] == "curintia2"


def test_french_ui_label_with_trailing_amount_is_rejected():
    cache = {"seat_6": "Villain42"}

    resolved, source = resolve_player_name("seat_6", "Mettre la 10 494", cache)

    assert resolved == "Villain42"
    assert source == "seat_cache"
