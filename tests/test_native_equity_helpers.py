"""Tests des helpers purs de l'adaptateur equity natif (ratchet coverage)."""

from types import SimpleNamespace

import pytest

from poker.decisionmaker.native_equity import (
    _is_exact_combo,
    active_villain_utg,
    board_len_is_closed,
    derive_assumed_players,
    normalize_card,
    normalize_cards,
    normalize_range_percent,
    normalize_range_token,
    normalize_winner_types,
    percent_to_range_string,
    range_set_to_string,
    rank_index,
    sort_ranks_desc,
    stage_max_samples,
    villain_ranges_are_exact,
)


def test_board_len_is_closed():
    assert board_len_is_closed(["2C", "7D", "JH", "KS", "AD"]) is True
    assert board_len_is_closed(["2C", "7D", "JH"]) is False


def test_is_exact_combo_validates_suits_and_ranks():
    assert _is_exact_combo("AhKd") is True
    assert _is_exact_combo("ah kd".replace(" ", "")) is True
    assert _is_exact_combo("AKQJ") is False
    assert _is_exact_combo("AhXx") is False
    assert _is_exact_combo("AK") is False
    assert _is_exact_combo("") is False


def test_villain_ranges_are_exact_requires_all_combos():
    assert villain_ranges_are_exact(["AhKd", "QcQs"]) is True
    assert villain_ranges_are_exact(["AhKd", "QQ"]) is False
    assert villain_ranges_are_exact(["  "]) is False
    assert villain_ranges_are_exact([]) is False


def test_normalize_card_handles_ten_and_case():
    assert normalize_card("10h") == "Th"
    assert normalize_card("aH") == "Ah"
    assert normalize_card(" kd ") == "Kd"
    assert normalize_card("") == ""


def test_normalize_cards_filters_falsy():
    assert normalize_cards(["10s", None, "", "qc"]) == ["Ts", "Qc"]


def test_normalize_range_token_sorts_ranks():
    assert normalize_range_token("qk") == "KQ"
    assert normalize_range_token("9t s") == "T9s"
    assert normalize_range_token("kh as") == "AsKh"
    assert normalize_range_token("") == ""


def test_range_set_to_string_dedupes_and_sorts():
    hands = ["qs js", "AhKd", "QsJs"]
    result = range_set_to_string(hands)
    # Les combos gardent l'ordre de couleur d'origine ; seuls les rangs
    # sont triés (KQ -> QsJs inchangé).
    tokens = set(result.split(","))
    assert tokens == {"AhKd", "QsJs"}


def test_normalize_range_percent_clamps_and_divides():
    assert normalize_range_percent(50) == pytest.approx(0.5)
    assert normalize_range_percent(0.3) == pytest.approx(0.3)
    assert normalize_range_percent(200) == 1.0
    assert normalize_range_percent(-5) == 0.0


def test_percent_to_range_string_returns_top_slice():
    top = percent_to_range_string(0.01)
    assert top and "," in top or top
    # ~1% : doit contenir les paires hautes.
    tokens = set(top.split(","))
    assert "AA" in tokens or "Aks".upper() in {token.upper() for token in tokens}


def test_stage_max_samples_grows_with_street():
    samples = [stage_max_samples(stage) for stage in ("PreFlop", "Flop", "Turn", "River")]
    # Pic au flop (5000), repli turn/river : budget borné par la complexité.
    assert samples == [3000, 5000, 4000, 3000]


def test_active_villain_utg_first_alive_player():
    table = SimpleNamespace(
        other_players=[
            {"status": 0, "utg_position": 1},
            {"status": 1, "utg_position": 3},
        ]
    )
    assert active_villain_utg(table) == 3


def test_derive_assumed_players_bounds():
    strategy = {"range_multiple_players": 0.4}
    table = SimpleNamespace(
        gameStage="Turn",
        isHeadsUp=False,
        total_players=6,
        other_active_players=3,
        playersAhead=2,
        selected_strategy=strategy,
    )
    assumed = derive_assumed_players({"selected_strategy": strategy}, table)
    assert 2 <= assumed <= max(2, table.total_players - 1)

    preflop_table = SimpleNamespace(gameStage="PreFlop", total_players=6)
    assert derive_assumed_players({"selected_strategy": {}}, preflop_table) == 2


def test_sort_ranks_and_rank_index():
    assert sort_ranks_desc("K", "A") == ("A", "K")
    assert sort_ranks_desc("A", "K") == ("A", "K")
    assert rank_index("2") == 0
    assert rank_index("A") == 12


def test_normalize_winner_types_maps_counts():
    normalized = normalize_winner_types({"Flush": 12, "High Card": 30})
    assert normalized["Flush"] == 12
    assert sum(normalized.values()) == 42
